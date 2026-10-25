"""拆书编排器：切章 → 拆书卡（≈章纲）→ 剧情单元 → 分卷 / 全书骨架（≈卷纲 / 总纲）→ 文风指纹 → 参考包。

运行方式（mode）：
- full：删掉本书全部拆书卡从头抽
- resume：保留已成功的拆书卡，只抽失败 / 没抽过的章（断点续抽、重试失败章节、扩大范围都走它），再重建后面的产物；
  缩小范围时范围外的拆书卡删掉
- rebuild_post：拆书卡一张不动，只重跑剧情单元及之后（某个维度生成失败时）
resume / rebuild_post 要求这次切出的章节和上次一样（chapters_meta 的章数与标题），否则章号对不上已有的拆书卡，
直接失败让作者选全部重抽；需要 AI 兜底切章的书靠全文旁的 .split.json 固化决策（llm_chapter_splitter）。

拆书卡阶段的失败处理（_CardRunner，分类见 failure_policy）：致命错误（鉴权 / 余额 / 模型不存在）立即中止整个任务；
429 原批等待重试、不拆半；多章批整批失败拆半；截断只补抽没拿到完整卡的章，并把后面的批次缩到实际能输出的大小；
单章失败再试两次（截断改精简要求）；主循环跑完后冷却一会儿把失败的章再补抽一轮；连续 BREAKER_STREAK 次调用失败
先停一分钟，再失败就中止。中止时已抽的拆书卡都在，作者处理好后「继续抽取」接着跑。

每批 commit 一次；写库走独立连接（见 _create_task_session）。
进度切片：splitting 0-3 / cards 3-70 / arcs 70-84 / skeleton 84-93 / style 93-97 / pack 97-100。
失败以异常抛出（ExtractionAborted / ExtractionFatal / 原异常），ai_jobs 据此标 error；用户取消 → cancelled。
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from bisect import bisect_left, insort
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_engine
from app.models.book_dissect_chapter_fact import BookDissectChapterFact
from app.models.book_dissect_story_arc import BookDissectStoryArc
from app.models.book_dissect_task import BookDissectTask
from app.models.reference_pack import ReferencePack
from app.services.ai_service import AIService
from app.services.book_dissect import failure_policy
from app.services.book_dissect.batch_planner import (
    BatchPlan, plan_arc_window, plan_batches, select_target_indices, split_batch, take_batch,
)
from app.services.book_dissect.chapter_card_extractor import ChapterCardExtractionError, ChapterCardExtractor
from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.dissect_stats import build_structure_stats, build_units_payload
from app.services.book_dissect.failure_policy import (
    NETWORK_RETRY_DELAYS, RATE_LIMIT_DELAYS, ExtractionAborted, ExtractionFatal,
)
from app.services.book_dissect.skeleton_builder import SkeletonBuilder, fallback_volumes
from app.services.book_dissect.story_arc_builder import StoryArcBuilder
from app.services.book_dissect.style_fingerprint import StyleFingerprintBuilder
from app.services.book_dissect.style_stats import compute_style_metrics, pick_even_indices
from app.services.book_dissect.v5_types import ChapterCard, StoryArc
from app.services.generation_trace import begin_stage, trace_progress

logger = logging.getLogger(__name__)

PIPELINE_VERSION = 5
RUN_MODES = ("full", "resume", "rebuild_post")
CANCELLED_MESSAGE = "已手动停止抽取；已抽出的拆书卡都保留着，可「继续抽取」接着跑"
CORE_DIMS = ("bridges", "synopsis", "style")
STYLE_SAMPLE_CHAPTERS = 120

# 单章失败后的重试间隔（秒）：主循环里再试两次；阶段末补抽时只再给一次
LEAF_RETRY_DELAYS = NETWORK_RETRY_DELAYS
SWEEP_LEAF_RETRIES = 1
SWEEP_COOLDOWN = 30.0
# 连续这么多次调用都失败：网络类先停 BREAKER_COOLDOWN 秒再试，仍失败就中止；其余类（坏输出 / 被拒 / 意外异常）直接中止
BREAKER_STREAK = 8
BREAKER_COOLDOWN = 60.0

_P_SPLIT_END, _P_SWEEP_START, _P_CARDS_END, _P_ARCS_END, _P_SKELETON_END, _P_STYLE_END = 3, 68, 70, 84, 93, 97


def _set_progress(task: BookDissectTask, progress: int, message: str) -> None:
    """DB 进度与 AI 任务弹窗进度同步推进（trace 未绑定时后者 no-op）。"""
    task.progress = progress
    trace_progress(message, progress)


def _without_reasoning(ai_service: Any) -> Any:
    """拆书是结构化抽取：关掉思考，把 Max Tokens 留给输出（推理模型常把预算耗在思考上 → 截断 → 拆半）。不改外面共用的实例。"""
    if isinstance(ai_service, AIService) and getattr(ai_service, "reasoning_enabled", False):
        ai_service = copy.copy(ai_service)
        ai_service.reasoning_enabled = False
    return ai_service


# ---------------------------------------------------------------------------
# 会话与任务行
# ---------------------------------------------------------------------------

def _isolated_engine(main_engine: Any) -> Any:
    from app.services.chapter_batch_service import isolated_sqlite_engine

    try:
        return isolated_sqlite_engine(main_engine.url.render_as_string(hide_password=False))
    except Exception:  # noqa: BLE001 - 拿不到独立连接就用主引擎
        return None


async def _create_task_session(user_id: str) -> AsyncSession:
    """流水线的会话尽量走独立连接（NullPool）：主引擎是 StaticPool 单连接、所有会话共用一个事务，别的请求收尾时的
    ROLLBACK 会把这里已写未提交的拆书卡一起冲掉，commit 也不报错（压测：流水线以为写了 1200 张卡，库里 0 行）。
    内存库等拿不到独立连接时退回主引擎。"""
    main = await get_engine(user_id)
    owned = _isolated_engine(main)
    session = async_sessionmaker(owned or main, class_=AsyncSession, expire_on_commit=False)()
    if owned is not None:
        session.info["owned_engine"] = owned
    return session


async def _close_session(db: AsyncSession) -> None:
    owned = db.info.pop("owned_engine", None)
    await db.close()
    if owned is not None:
        await owned.dispose()


async def _fetch_task(db: AsyncSession, task_id: str) -> Optional[BookDissectTask]:
    return (await db.execute(select(BookDissectTask).where(BookDissectTask.id == task_id))).scalar_one_or_none()


async def _mark_failed(db: AsyncSession, task: BookDissectTask, msg: str) -> NoReturn:
    task.status, task.error_message, task.completed_at = "failed", msg, datetime.now()
    await db.commit()
    raise ExtractionAborted(msg)


async def _mark_terminal(db: AsyncSession, task_id: str, *, status: str, message: str) -> None:
    task = await _fetch_task(db, task_id)
    if task is not None:
        task.status, task.error_message, task.completed_at = status, message, datetime.now()
        await db.commit()


async def _mark_fatal(db: AsyncSession, task_id: str, reason: str) -> None:
    """重试也没用的失败：按库里的拆书卡重算计数，落 failed 并告诉作者已抽的都在、处理好后继续抽取。"""
    task = await _fetch_task(db, task_id)
    if task is None:
        return
    statuses = (await db.execute(
        select(BookDissectChapterFact.extraction_status).where(BookDissectChapterFact.task_id == task_id)
    )).scalars().all()
    ok = sum(1 for s in statuses if s == "success")
    task.chapters_extracted, task.chapters_failed = ok, len(statuses) - ok
    if ok:
        tail = f"已抽出的 {ok} 章拆书卡都保留着，处理好后点「继续抽取」接着跑"
    elif statuses:
        tail = "处理好后点「继续抽取」接着跑"
    else:
        tail = "处理好后点「开始抽取」重新跑"
    task.status, task.completed_at = "failed", datetime.now()
    task.error_message = f"{reason}；{tail}"[:500]
    await db.commit()


# ---------------------------------------------------------------------------
# 切章
# ---------------------------------------------------------------------------

async def _load_chapters(storage_path: str, ai_service: AIService) -> list[Chapter]:
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(storage_path)
    raw = path.read_bytes()
    from app.services.book_dissect.llm_chapter_splitter import decision_cache_path, split_bytes_with_llm_fallback
    chapters, _ = await split_bytes_with_llm_fallback(raw, ai_service=ai_service, decision_path=decision_cache_path(path))
    return chapters


def _stored_titles(task: BookDissectTask) -> Optional[list[str]]:
    try:
        metas = json.loads(task.chapters_meta) if task.chapters_meta else None
    except (TypeError, ValueError):
        return None
    if not isinstance(metas, list):
        return None
    return [str(m.get("title") or "") if isinstance(m, dict) else "" for m in metas]


def _same_split(task: BookDissectTask, chapters: Sequence[Chapter]) -> bool:
    """继续 / 重建要求这次切出的章节和上次记录的一样，章号才对得上已有的拆书卡。没有记录可比时按一样处理。"""
    titles = _stored_titles(task)
    return titles is None or titles == [ch.title or "" for ch in chapters]


def _sync_chapter_meta(task: BookDissectTask, chapters: list[Chapter]) -> None:
    """运行时重切结果与记录不一致（章数或标题）→ 以运行时为准更新任务元信息（格式与 api.book_dissect._meta_from_chapter 一致）。"""
    if len(chapters) == (task.chapter_count or 0) and _stored_titles(task) == [ch.title or "" for ch in chapters]:
        return
    if len(chapters) != (task.chapter_count or 0):
        logger.warning("[拆书V5] task=%s 运行时切分 %d 章 ≠ 记录的 %d 章，按运行时更新", task.id, len(chapters), task.chapter_count or 0)
    task.chapter_count = len(chapters)
    task.total_words = sum(ch.word_count for ch in chapters)
    task.chapters_meta = json.dumps([
        {"number": ch.chapter_number, "title": ch.title, "raw_title": ch.raw_title, "word_count": ch.word_count, "kind": ch.kind}
        for ch in chapters
    ], ensure_ascii=False)


def _range_label(batch: Sequence[Chapter]) -> str:
    a, b = batch[0].chapter_number, batch[-1].chapter_number
    return f"第 {a} 章" if a == b else f"第 {a}-{b} 章"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_extraction_v5_background(task_id: str, user_id: str, ai_service: AIService, mode: str = "full") -> None:
    mode = mode if mode in RUN_MODES else "full"
    ai_service = _without_reasoning(ai_service)
    db: Optional[AsyncSession] = None
    try:
        db = await _create_task_session(user_id)
        task = await _fetch_task(db, task_id)
        if task is None or task.user_id != user_id:
            logger.error("[拆书V5] 任务不存在或无权 task=%s", task_id)
            return
        task.status, task.stage, task.extraction_phase = "running", "splitting", "splitting"
        task.progress, task.started_at, task.error_message, task.version = 0, datetime.now(), None, PIPELINE_VERSION
        task.completed_at = None
        await db.commit()
        trace_progress(f"正在切分章节（约 {task.total_words or 0:,} 字）…", 0)
        split_stage = begin_stage("splitting", "章节切分")

        try:
            chapters = await _load_chapters(task.storage_path or "", ai_service)
        except FileNotFoundError:
            await _mark_failed(db, task, "全文文件丢失，请重新上传")
        if not chapters:
            await _mark_failed(db, task, "重新切分得到 0 章")
        if mode != "full" and not _same_split(task, chapters):
            await _mark_failed(db, task, (
                f"这次切出 {len(chapters)} 章，和上次记录的 {task.chapter_count or 0} 章对不上，已有拆书卡的章号不可信，"
                "没法接着抽；请选「全部重抽」"
            ))
        _sync_chapter_meta(task, chapters)
        indices = select_target_indices(
            len(chapters), task.sampling_mode or "all", task.sampling_param or 1, chapter_limit=task.chapter_limit or 0,
        )
        target = [chapters[i] for i in indices]
        if not target:
            await _mark_failed(db, task, "按当前范围 / 采样设置未选出任何章节")
        task.chapters_total = len(target)
        plan = plan_batches(
            [len(ch.content or "") for ch in target],
            model=getattr(ai_service, "default_model", None), max_tokens=getattr(ai_service, "default_max_tokens", None),
            extraction_engine=(task.extraction_engine or "auto").lower(), chapters_per_request=task.chapters_per_request or 0,
        )
        split_stage.done(章节=len(chapters), 目标章节=len(target), 方式=mode)
        _set_progress(task, _P_SPLIT_END, f"开始抽取拆书卡：目标 {len(target)} 章")
        await db.commit()

        if mode == "rebuild_post":
            cards = await _reuse_cards(db, task, target)
            if not cards:
                await _mark_failed(db, task, "没有可用的拆书卡，请先「继续抽取」或「全部重抽」")
        else:
            cards = await _run_card_extraction(db, task, target, plan, ai_service, mode=mode)
            if not cards:
                await _mark_failed(db, task, "没有任何章节抽出拆书卡")

        arcs = await _run_arc_building(db, task, cards, ai_service)

        task.stage = task.extraction_phase = "skeleton"
        await db.commit()
        stats = build_structure_stats(cards, arcs)
        units_payload = build_units_payload(arcs, cards)
        skeleton, characters, methodology = await _run_skeleton(task, cards, arcs, stats, ai_service)

        task.stage = task.extraction_phase = "style"
        await db.commit()
        style = await _run_style(task, target, cards, ai_service)

        payload: dict[str, Optional[dict]] = {
            "bridges": units_payload if arcs else None, "synopsis": skeleton, "style": style,
            "character_archive": characters, "methodology": methodology, "structure": stats,
        }
        generated = [k for k, v in payload.items() if isinstance(v, dict)]

        task.stage = task.extraction_phase = "pack"
        _set_progress(task, _P_STYLE_END, "写入拆书结果…")
        await db.commit()
        pack_stage = begin_stage("pack", "写入拆书结果")
        pack_id = await _write_reference_pack_v5(db, task, payload, generated)

        task.result_json = json.dumps({
            "version": PIPELINE_VERSION, "pack_id": pack_id, "generated_dimensions": generated,
            "stats": {"chapters_total": task.chapters_total, "chapters_extracted": task.chapters_extracted,
                      "chapters_failed": task.chapters_failed, "arc_count": len(arcs),
                      "volume_count": len((skeleton or {}).get("volumes") or [])},
        }, ensure_ascii=False)
        task.status, task.progress, task.stage, task.extraction_phase, task.completed_at = "completed", 100, "done", "done", datetime.now()
        await db.commit()
        pack_stage.done(章节=f"{task.chapters_extracted}/{task.chapters_total}", 单元=len(arcs), 维度=len(generated))
        logger.info("[拆书V5] 完成 task=%s mode=%s cards=%d/%d arcs=%d pack=%s dims=%s",
                    task_id, mode, task.chapters_extracted, task.chapters_total, len(arcs), pack_id, generated)

    except asyncio.CancelledError:
        # 用户手动停止（AIJobManager.cancel）：先 rollback（取消可能打在 flush / commit 中途），再落库 cancelled
        logger.info("[拆书V5] 任务被手动停止 task=%s", task_id)
        if db is not None:
            try:
                await db.rollback()
                await _mark_terminal(db, task_id, status="cancelled", message=CANCELLED_MESSAGE)
            except Exception as inner:
                logger.error("[拆书V5] 写停止状态出错 task=%s err=%s", task_id, inner)
        raise
    except ExtractionFatal as exc:
        # 重试也没用的失败（鉴权 / 余额 / 模型 / 持续限流 / 连续失败熔断）：已抽的拆书卡都在，落 failed 等作者继续
        logger.warning("[拆书V5] 中止 task=%s：%s", task_id, exc)
        if db is not None:
            try:
                await db.rollback()
                await _mark_fatal(db, task_id, str(exc))
            except Exception as inner:
                logger.error("[拆书V5] 写中止状态出错 task=%s err=%s", task_id, inner)
        raise
    except ExtractionAborted:
        # 前置校验失败：_mark_failed 已落库，原样抛给 ai_jobs 标 error
        raise
    except Exception as exc:
        # 异常可能出在 flush / commit 中途（如 IntegrityError），session 处于 pending-rollback 状态，
        # 不先 rollback 就写不进 failed，任务会卡在 running
        logger.error("[拆书V5] 未预期异常 task=%s err=%s", task_id, exc, exc_info=True)
        if db is not None:
            try:
                await db.rollback()
                await _mark_terminal(db, task_id, status="failed", message=f"{type(exc).__name__}: {exc}"[:500])
            except Exception as inner:
                logger.error("[拆书V5] 写失败状态再次出错 %s", inner)
        raise
    finally:
        if db is not None:
            await _close_session(db)
    await _import_to_knowledge(task_id, user_id)


# ---------------------------------------------------------------------------
# S1 拆书卡
# ---------------------------------------------------------------------------

CardResult = tuple[Chapter, Optional[ChapterCard], Optional[str]]


def _halves(chs: Sequence[Chapter]) -> list[list[Chapter]]:
    return [[chs[i] for i in half] for half in split_batch(list(range(len(chs))))]


def _chunks(chs: Sequence[Chapter], size: int) -> list[list[Chapter]]:
    size = max(1, size)
    return [list(chs[i: i + size]) for i in range(0, len(chs), size)]


class _CardRunner:
    """拆书卡阶段的一次次模型调用：限流原批等待、致命错误中止、连续失败熔断、整批失败拆半、截断补抽 + 批次自适应、单章重试。"""

    def __init__(self, task: BookDissectTask, extractor: ChapterCardExtractor, *, cap: int, pack_budget: Optional[int]):
        self.task = task
        self.extractor = extractor
        self.cap = max(1, cap)                      # 每批章数上限；截断后缩到实际能输出的张数
        self.pack_budget = pack_budget
        self.leaf_retries = len(LEAF_RETRY_DELAYS)
        self.known: Counter[str] = Counter()
        self.done: dict[int, ChapterCard] = {}
        self._order: list[int] = []
        self.fail_streak = 0
        self.cooled = False

    # ---------- 跨批上下文：累计出场最多的角色 + 本批之前最近几张卡的章纲 ----------

    def remember(self, card: ChapterCard) -> None:
        if card.chapter_number not in self.done:
            insort(self._order, card.chapter_number)
            self.known.update(name for name in card.characters if name)
        self.done[card.chapter_number] = card

    def _context(self, batch: Sequence[Chapter]) -> tuple[list[str], list[ChapterCard]]:
        known = [name for name, _ in self.known.most_common(ChapterCardExtractor.KNOWN_CHAR_TOP_N)]
        i = bisect_left(self._order, batch[0].chapter_number)
        prior = [self.done[n] for n in self._order[max(0, i - ChapterCardExtractor.PRIOR_OUTLINE_COUNT): i]]
        return known, prior

    def _note(self, message: str) -> None:
        trace_progress(message, self.task.progress or 0)

    # ---------- 单次调用 ----------

    async def _call(self, batch: Sequence[Chapter], *, compact: bool = False) -> list[ChapterCard]:
        known, prior = self._context(batch)
        rate_tries = 0
        while True:
            try:
                cards = await self.extractor.extract_batch(batch, known_characters=known, prior_cards=prior, compact=compact)
            except ChapterCardExtractionError as exc:
                if exc.kind == "fatal":
                    raise ExtractionFatal(exc.reason) from exc
                if exc.kind == "rate_limited":
                    if rate_tries >= len(RATE_LIMIT_DELAYS):
                        raise ExtractionFatal(f"AI 接口一直在限流，已暂停抽取（{exc.reason}）") from exc
                    delay = exc.retry_after if exc.retry_after is not None else RATE_LIMIT_DELAYS[rate_tries]
                    rate_tries += 1
                    self._note(f"{_range_label(batch)} 被接口限流，{delay:.0f} 秒后原样重试…")
                    await failure_policy.pause(delay)
                    continue
                if exc.kind == "truncated" and exc.partial:
                    self._succeeded()                 # 截断但拿到了完整的卡：有进展，不算连续失败
                else:
                    await self._failed(exc.kind, str(exc))
                raise
            self._succeeded()
            return cards

    def _succeeded(self) -> None:
        self.fail_streak, self.cooled = 0, False

    async def _failed(self, kind: str, message: str) -> None:
        self.fail_streak += 1
        if self.fail_streak < BREAKER_STREAK:
            return
        if kind == "network" and not self.cooled:
            self.cooled, self.fail_streak = True, BREAKER_STREAK - 3
            self._note(f"连续 {BREAKER_STREAK} 次调用失败（{message[:60]}），先停 {BREAKER_COOLDOWN:.0f} 秒再试…")
            await failure_policy.pause(BREAKER_COOLDOWN)
            return
        raise ExtractionFatal(f"连续 {BREAKER_STREAK} 次调用模型都失败（最近一次：{message[:120]}），已暂停抽取")

    # ---------- 一批 ----------

    async def extract(self, batch: Sequence[Chapter]) -> list[CardResult]:
        """整批失败拆半；截断保留完整的卡、剩下的按缩小后的批补抽；漏章组子批；单章交给 extract_leaf。"""
        if len(batch) == 1:
            return [await self.extract_leaf(batch[0])]
        try:
            cards = await self._call(batch)
        except ChapterCardExtractionError as exc:
            if exc.kind != "truncated":
                self._note(f"{_range_label(batch)} 整批抽取失败（{str(exc)[:60]}），拆成两半重试…")
                return await self._extract_each(_halves(batch))
            cards = [c for c in exc.partial if c.has_content()]
            self.cap = max(1, min(self.cap, len(cards) or len(batch) // 2))
            self._note(f"{_range_label(batch)} 输出被截断，完整拿到 {len(cards)} 张；剩下的补抽，之后每批最多 {self.cap} 章")
        except ExtractionAborted:
            raise
        except Exception as exc:  # noqa: BLE001 - 意外异常按整批失败处理
            logger.error("[拆书V5] task=%s 批次 %s 意外异常 %s", self.task.id, _range_label(batch), exc, exc_info=True)
            await self._failed("unknown", f"{type(exc).__name__}: {exc}")
            return await self._extract_each(_halves(batch))

        by_num = {c.chapter_number: c for c in cards if c.has_content()}
        results: list[CardResult] = []
        for ch in batch:
            card = by_num.get(ch.chapter_number)
            if card is not None:
                self.remember(card)
                results.append((ch, card, None))
        missed = [ch for ch in batch if ch.chapter_number not in by_num]
        if missed:
            self._note(f"{_range_label(batch)} 还差 {len(missed)} 章没拿到，组成子批补抽…")
            subs = _halves(missed) if len(missed) == len(batch) else _chunks(missed, self.cap)
            results.extend(await self._extract_each(subs))
            order = {ch.chapter_number: i for i, ch in enumerate(batch)}
            results.sort(key=lambda r: order[r[0].chapter_number])
        return results

    async def _extract_each(self, subs: Sequence[Sequence[Chapter]]) -> list[CardResult]:
        out: list[CardResult] = []
        for sub in subs:
            out.extend(await self.extract(sub))
        return out

    # ---------- 单章 ----------

    async def extract_leaf(self, ch: Chapter) -> CardResult:
        """单章：网络 / 坏输出 / 漏给 再试 leaf_retries 次；截断改精简要求再试一次；输入超长、被接口拒绝不重试。"""
        compact, retries = False, 0
        while True:
            try:
                cards = await self._call([ch], compact=compact)
                card = next((c for c in cards if c.has_content()), None)
                if card is not None:
                    self.remember(card)
                    return ch, card, None
                kind, err = "bad_output", "模型没有给出这一章的拆书卡"
                await self._failed(kind, err)
            except ChapterCardExtractionError as exc:
                kind, err = exc.kind, str(exc)
            except ExtractionAborted:
                raise
            except Exception as exc:  # noqa: BLE001 - 意外异常也按失败重试
                logger.error("[拆书V5] task=%s 第 %d 章意外异常 %s", self.task.id, ch.chapter_number, exc, exc_info=True)
                kind, err = "unknown", f"{type(exc).__name__}: {exc}"
                await self._failed(kind, err)
            if kind in ("context_overflow", "rejected"):
                return ch, None, err[:500]
            if kind == "truncated" and not compact:
                compact = True
                self._note(f"第 {ch.chapter_number} 章输出被截断，改用精简要求重试…")
                continue
            if kind == "truncated" or retries >= self.leaf_retries:
                return ch, None, err[:500]
            delay = LEAF_RETRY_DELAYS[min(retries, len(LEAF_RETRY_DELAYS) - 1)]
            retries += 1
            self._note(f"第 {ch.chapter_number} 章抽取失败（{err[:40]}），{delay:.0f} 秒后第 {retries} 次重试…")
            await failure_policy.pause(delay)


def _row_ok(row: Optional[BookDissectChapterFact]) -> bool:
    return row is not None and row.extraction_status == "success"


def _card_from_row(row: BookDissectChapterFact) -> Optional[ChapterCard]:
    try:
        data = json.loads(row.fact_json or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    card = ChapterCard.from_dict({**data, "chapter_number": row.chapter_number})
    return card if card.has_content() else None


async def _fact_rows(
    db: AsyncSession, task_id: str, keep: Optional[dict[int, BookDissectChapterFact]] = None,
) -> dict[int, BookDissectChapterFact]:
    """读库里本任务的拆书卡行。keep 里有、库里却没有的（写入被别的会话回滚冲掉了）从会话里摘掉，之后按待抽重新插入。"""
    rows = {r.chapter_number: r for r in (await db.execute(
        select(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task_id)
    )).scalars().all()}
    for num, obj in (keep or {}).items():
        if num not in rows and obj in db:
            db.expunge(obj)
    return rows


async def _trim_to_target(db: AsyncSession, task_id: str, target_nums: set[int]) -> None:
    """继续 / 重建时范围缩小了：范围外的拆书卡删掉（知识库导入、剧情单元都按表里的卡走）。"""
    await db.execute(delete(BookDissectChapterFact).where(
        BookDissectChapterFact.task_id == task_id, BookDissectChapterFact.chapter_number.notin_(target_nums),
    ))


async def _load_cards(db: AsyncSession, task_id: str, target_nums: set[int]) -> list[ChapterCard]:
    """以库为准取本次范围内成功的拆书卡（后面的阶段、知识库导入都读同一份）。"""
    rows = await _fact_rows(db, task_id)
    cards = [card for num, row in rows.items() if num in target_nums and _row_ok(row) and (card := _card_from_row(row))]
    return sorted(cards, key=lambda c: c.chapter_number)


def _refresh_counts(task: BookDissectTask, rows: dict[int, BookDissectChapterFact], target_nums: set[int]) -> None:
    present = [rows[n] for n in target_nums if n in rows]
    task.chapters_extracted = sum(1 for r in present if _row_ok(r))
    task.chapters_failed = len(present) - task.chapters_extracted


async def _recount(db: AsyncSession, task: BookDissectTask, target_nums: set[int]) -> None:
    """以库为准重算计数：范围内没写进库的章也算失败（继续抽取时会补）。"""
    statuses = dict((await db.execute(
        select(BookDissectChapterFact.chapter_number, BookDissectChapterFact.extraction_status)
        .where(BookDissectChapterFact.task_id == task.id)
    )).all())
    ok = sum(1 for n in target_nums if statuses.get(n) == "success")
    task.chapters_extracted, task.chapters_failed = ok, len(target_nums) - ok


def _write_card(
    db: AsyncSession, task: BookDissectTask, rows: dict[int, BookDissectChapterFact],
    ch: Chapter, card: Optional[ChapterCard], err: Optional[str],
) -> None:
    row = rows.get(ch.chapter_number)
    if row is None:
        row = BookDissectChapterFact(task_id=task.id, chapter_number=ch.chapter_number)
        db.add(row)
        rows[ch.chapter_number] = row
    if card is None:
        card = ChapterCard(chapter_number=ch.chapter_number, title=ch.title or "", word_count=ch.word_count)
    row.chapter_title = ch.title or ""
    row.fact_json = json.dumps(card.to_dict(), ensure_ascii=False)
    row.summary = card.outline or None
    row.extraction_status = "success" if err is None else "failed"
    row.extraction_error = err
    row.is_truncated = int(card.truncated_input)
    row.segment_count = 1
    row.extracted_at = datetime.now()


async def _card_pass(
    db: AsyncSession, task: BookDissectTask, runner: _CardRunner, rows: dict[int, BookDissectChapterFact],
    target_nums: set[int], chapters: Sequence[Chapter], *, span: tuple[int, int], verb: str = "抽取",
) -> None:
    """按 runner 当前的批大小现切批次跑一遍；每批写库 + commit（中途停掉 / 中止时已完成的批都在）。"""
    start_p, end_p = span
    sizes = [len(ch.content or "") for ch in chapters]
    i = 0
    while i < len(chapters):
        size = take_batch(sizes, i, input_budget=runner.pack_budget, cap=runner.cap)
        batch = chapters[i: i + size]
        trace_progress(f"正在{verb}{_range_label(batch)} · 拆书卡 {task.chapters_extracted}/{task.chapters_total} 章", task.progress or 0)
        for ch, card, err in await runner.extract(batch):
            _write_card(db, task, rows, ch, card, err)
        i += size
        _refresh_counts(task, rows, target_nums)
        failed_note = f"，{task.chapters_failed} 章失败" if task.chapters_failed else ""
        _set_progress(task, int(start_p + i / len(chapters) * (end_p - start_p)),
                      f"拆书卡 {task.chapters_extracted}/{task.chapters_total} 章{failed_note}")
        await db.commit()


async def _run_card_extraction(
    db: AsyncSession, task: BookDissectTask, target: list[Chapter], plan: BatchPlan, ai_service: AIService,
    *, mode: str = "full",
) -> list[ChapterCard]:
    target_nums = {ch.chapter_number for ch in target}
    if mode == "full":
        await db.execute(delete(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task.id))
    else:
        await _trim_to_target(db, task.id, target_nums)
    task.stage = task.extraction_phase = "cards"
    await db.commit()

    rows = await _fact_rows(db, task.id)
    runner = _CardRunner(task, ChapterCardExtractor(ai_service=ai_service),
                         cap=plan.chapters_per_request or len(target), pack_budget=plan.pack_budget)
    for num in sorted(rows):
        card = _card_from_row(rows[num]) if _row_ok(rows[num]) else None
        if card is not None:
            runner.remember(card)
    pending = [ch for ch in target if not _row_ok(rows.get(ch.chapter_number))]
    _refresh_counts(task, rows, target_nums)
    kept = len(target) - len(pending)
    stage = begin_stage("cards", f"拆书卡（{len(pending)} 章待抽" + (f"，沿用 {kept} 章）" if kept else "）"))
    if pending:
        await _card_pass(db, task, runner, rows, target_nums, pending, span=(_P_SPLIT_END, _P_SWEEP_START))
        rows = await _fact_rows(db, task.id, keep=rows)
        retry = [ch for ch in target if not _row_ok(rows.get(ch.chapter_number))]
        if retry:
            trace_progress(f"{len(retry)} 章没抽出来，{SWEEP_COOLDOWN:.0f} 秒后逐章再补抽一轮…", task.progress or 0)
            await failure_policy.pause(SWEEP_COOLDOWN)
            runner.cap, runner.leaf_retries = 1, SWEEP_LEAF_RETRIES
            await _card_pass(db, task, runner, rows, target_nums, retry, span=(_P_SWEEP_START, _P_CARDS_END), verb="补抽")
    await _recount(db, task, target_nums)
    failed_note = f"，{task.chapters_failed} 章失败（可「继续抽取」补抽）" if task.chapters_failed else ""
    _set_progress(task, _P_CARDS_END, f"拆书卡完成：{task.chapters_extracted}/{task.chapters_total} 章{failed_note}")
    await db.commit()
    stage.done(成功=task.chapters_extracted, 失败=task.chapters_failed, 本次抽取=len(pending))
    return await _load_cards(db, task.id, target_nums)


async def _reuse_cards(db: AsyncSession, task: BookDissectTask, target: list[Chapter]) -> list[ChapterCard]:
    """只重建后续产物：拆书卡一张不动（范围缩小时删掉范围外的），按库里的成功卡往下跑。"""
    target_nums = {ch.chapter_number for ch in target}
    await _trim_to_target(db, task.id, target_nums)
    await _recount(db, task, target_nums)
    cards = await _load_cards(db, task.id, target_nums)
    _set_progress(task, _P_CARDS_END, f"沿用已有的 {len(cards)} 张拆书卡，重建剧情单元及之后的结果…")
    await db.commit()
    return cards


# ---------------------------------------------------------------------------
# S2 剧情单元
# ---------------------------------------------------------------------------

async def _run_arc_building(db: AsyncSession, task: BookDissectTask, cards: list[ChapterCard], ai_service: AIService) -> list[StoryArc]:
    await db.execute(delete(BookDissectStoryArc).where(BookDissectStoryArc.task_id == task.id))
    task.stage = task.extraction_phase = "arcs"
    await db.commit()
    arc_plan = plan_arc_window(
        len(cards), model=getattr(ai_service, "default_model", None), max_tokens=getattr(ai_service, "default_max_tokens", None),
    )
    stage = begin_stage("arcs", f"剧情单元识别（每轮 {arc_plan.window_new} 章，约 {arc_plan.window_count(len(cards))} 轮）")
    trace_progress(f"识别剧情单元：每轮喂 {arc_plan.window_new} 张拆书卡，约 {arc_plan.window_count(len(cards))} 轮", task.progress)
    last_chapter = cards[-1].chapter_number

    def _on_window(n_arcs: int, s: int, e: int) -> None:
        ratio = min(1.0, e / max(1, last_chapter))
        _set_progress(task, int(_P_CARDS_END + ratio * (_P_ARCS_END - _P_CARDS_END)),
                      f"识别剧情单元：已到第 {e} 章，累计 {n_arcs} 个单元")

    arcs = await StoryArcBuilder(ai_service, window_new=arc_plan.window_new).build(cards, on_window=_on_window)
    for a in arcs:
        db.add(BookDissectStoryArc(
            task_id=task.id, arc_index=a.arc_index, start_chapter=a.start_chapter, end_chapter=a.end_chapter,
            title=a.title[:120], payoff_type=a.payoff_type, origin=a.origin,
            arc_json=json.dumps(a.to_dict(), ensure_ascii=False),
        ))
    _set_progress(task, _P_ARCS_END, f"剧情单元识别完成：{len(arcs)} 个（{len(cards)} 章）")
    await db.commit()
    stage.done(单元=len(arcs), 兜底=sum(1 for a in arcs if a.origin == "fallback"))
    return arcs


# ---------------------------------------------------------------------------
# S3 骨架 / S4 文风
# ---------------------------------------------------------------------------

async def _run_skeleton(
    task: BookDissectTask, cards: list[ChapterCard], arcs: list[StoryArc], stats: dict[str, Any], ai_service: AIService,
) -> tuple[dict[str, Any], Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    stage = begin_stage("skeleton", "全书骨架")
    builder = SkeletonBuilder(ai_service=ai_service)
    trace_progress("全书骨架：按剧情单元分卷…", task.progress)
    volumes = await builder.build_volumes(arcs) or fallback_volumes(arcs)
    _set_progress(task, _P_ARCS_END + 3, f"分卷完成：{len(volumes)} 卷，归纳全书骨架 / 人物功能谱…")
    skeleton, characters = await asyncio.gather(
        builder.build_skeleton(volumes, cards, stats), builder.build_character_functions(volumes, arcs, cards),
    )
    if skeleton is None:
        skeleton = {"volumes": volumes, "pipeline_version": PIPELINE_VERSION, "genre_tag": "", "premise": "", "main_conflict": ""}
        stage.note(骨架="LLM 失败，仅保留分卷")
    methodology = await builder.build_methodology(skeleton, stats, cards)
    _set_progress(task, _P_SKELETON_END, "全书骨架完成，开始文风指纹…")
    stage.done(卷=len(volumes), 人物谱=characters is not None, 手册=methodology is not None)
    return skeleton, characters, methodology


async def _run_style(task: BookDissectTask, target: list[Chapter], cards: list[ChapterCard], ai_service: AIService) -> Optional[dict[str, Any]]:
    stage = begin_stage("style", "文风指纹")
    sample = [target[i] for i in pick_even_indices(len(target), STYLE_SAMPLE_CHAPTERS)]
    metrics = await asyncio.to_thread(compute_style_metrics, [ch.content or "" for ch in sample])
    trace_progress(f"文风指纹：已统计 {metrics.get('sample_chars', 0):,} 字，模型定性 + 摘例句…", task.progress)
    style = await StyleFingerprintBuilder(ai_service=ai_service).build(target, cards, metrics)
    _set_progress(task, _P_STYLE_END, "文风指纹完成" if style else "文风定性失败（已跳过）")
    if style is None:
        stage.skip("LLM 定性失败")
    else:
        stage.done(例句=len(style.get("examples") or []))
    return style


# ---------------------------------------------------------------------------
# 参考包
# ---------------------------------------------------------------------------

async def _write_reference_pack_v5(db: AsyncSession, task: BookDissectTask, payload: dict[str, Optional[dict]], generated: list[str]) -> str:
    """upsert：同 task 已有则更新（重抽），否则创建。状态看核心三维 + 章节覆盖率闸门。"""
    pack = (await db.execute(select(ReferencePack).where(ReferencePack.task_id == task.id))).scalar_one_or_none()
    core_done = [d for d in generated if d in CORE_DIMS]
    if len(core_done) == len(CORE_DIMS):
        status, error = "ready", None
    elif core_done:
        status, error = "partial", f"部分维度生成失败：{', '.join(sorted(set(CORE_DIMS) - set(core_done)))}"
    else:
        status, error = "failed", "全部核心维度生成失败"
    total = task.chapters_total or 0
    if total > 0:
        coverage = (task.chapters_extracted or 0) / total
        if coverage < 0.3 and status != "failed":
            status, error = "failed", f"章节抽取覆盖率过低（{task.chapters_extracted}/{total}={coverage:.0%}），参考包不可靠；请重新抽取"
        elif coverage < 0.8 and status == "ready":
            status, error = "partial", f"章节抽取覆盖率 {coverage:.0%}（{task.chapters_extracted}/{total}），部分拆书卡缺失"

    def _dump(key: str) -> Optional[str]:
        v = payload.get(key)
        return json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else None

    values = dict(
        source_book_title=task.file_name or "未命名拆书",
        methodology_json=_dump("methodology"), style_json=_dump("style"), structure_json=_dump("structure"),
        synopsis_json=_dump("synopsis"), bridges_json=_dump("bridges"), character_archive_json=_dump("character_archive"),
        pipeline_version=PIPELINE_VERSION, status=status, error_message=error,
        generated_dimensions=json.dumps(generated, ensure_ascii=False),
    )
    if pack is None:
        pack = ReferencePack(user_id=task.user_id, task_id=task.id, **values)
        db.add(pack)
    else:
        for k, v in values.items():
            setattr(pack, k, v)
        for dim in ReferencePack.DIMENSIONS_WITH_PRECOMPRESSION:      # 老预压缩清掉，避免新旧混用
            for level in ReferencePack.STRENGTH_LEVELS:
                setattr(pack, f"{dim}_{level}", None)
    await db.flush()
    return pack.id


async def _import_to_knowledge(task_id: str, user_id: str) -> None:
    """拆书产物写入知识库（确定性转换，不调模型）。失败只记 warning：打开知识库书架时会自动补导。"""
    try:
        from app.services.knowledge import kb_import
        db = await _create_task_session(user_id)
        try:
            await kb_import.import_dissect_task(db, task_id, user_id)
        finally:
            await _close_session(db)
    except Exception as exc:
        logger.warning("[拆书V5] task=%s 写入知识库失败（打开知识库时会自动补导）：%s", task_id, exc)
