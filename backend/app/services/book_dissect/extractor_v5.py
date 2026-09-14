"""拆书 V5 编排器：切章 → 拆书卡 → 情节单元 → 全书骨架 → 文风指纹 → 参考包。

进度切片：splitting 0-3 / cards 3-70 / arcs 70-84 / skeleton 84-93 / style 93-97 / pack 97-100。
每批 / 每步 commit 一次，前端轮询能看细粒度进度；同时经 generation_trace 上报 progress / stage。
失败以异常抛出（ExtractionAborted / 原异常），ai_jobs 据此标 error；用户取消 → cancelled。
设计：agent-docs/features/book_dissect_v5_design.md §3
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_engine
from app.models.book_dissect_chapter_fact import BookDissectChapterFact
from app.models.book_dissect_story_arc import BookDissectStoryArc
from app.models.book_dissect_task import BookDissectTask
from app.models.reference_pack import ReferencePack
from app.services.ai_service import AIService
from app.services.book_dissect.batch_planner import BatchPlan, plan_batches, select_target_indices, split_batch
from app.services.book_dissect.chapter_card_extractor import ChapterCardExtractionError, ChapterCardExtractor
from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.dissect_stats import build_bridges_payload, build_structure_stats
from app.services.book_dissect.skeleton_builder import SkeletonBuilder, fallback_stages
from app.services.book_dissect.story_arc_builder import StoryArcBuilder
from app.services.book_dissect.style_fingerprint import StyleFingerprintBuilder
from app.services.book_dissect.style_stats import compute_style_metrics, pick_even_indices
from app.services.book_dissect.v5_types import ChapterCard, StoryArc
from app.services.generation_trace import begin_stage, trace_progress

logger = logging.getLogger(__name__)

PIPELINE_VERSION = 5
CANCELLED_MESSAGE = "已手动停止抽取；已完成批次的拆书卡已保留，可重新抽取"
CORE_DIMS = ("bridges", "synopsis", "style")
STYLE_SAMPLE_CHAPTERS = 120

_P_SPLIT_END, _P_CARDS_END, _P_ARCS_END, _P_SKELETON_END, _P_STYLE_END = 3, 70, 84, 93, 97


class ExtractionAborted(RuntimeError):
    """前置校验不过（全文丢失 / 0 章 / 未选出章节）：DB 已落 failed，抛出让 ai_jobs 标失败。"""


def _set_progress(task: BookDissectTask, progress: int, message: str) -> None:
    """DB 进度与 AI 任务弹窗进度同步推进（trace 未绑定时后者 no-op）。"""
    task.progress = progress
    trace_progress(message, progress)


async def _create_task_session(user_id: str) -> AsyncSession:
    engine = await get_engine(user_id)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


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


async def _load_chapters(storage_path: str, ai_service: AIService) -> list[Chapter]:
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(storage_path)
    raw = path.read_bytes()
    from app.services.book_dissect.llm_chapter_splitter import split_bytes_with_llm_fallback
    chapters, _ = await split_bytes_with_llm_fallback(raw, ai_service=ai_service)
    return chapters


def _sync_chapter_meta(task: BookDissectTask, chapters: list[Chapter]) -> None:
    """运行时重切结果与上传时不一致 → 以运行时为准更新任务元信息（格式与 api.book_dissect._meta_from_chapter 一致）。"""
    if len(chapters) == (task.chapter_count or 0):
        return
    logger.warning("[拆书V5] task=%s 运行时切分 %d 章 ≠ 上传时 %d 章，按运行时更新", task.id, len(chapters), task.chapter_count or 0)
    task.chapter_count = len(chapters)
    task.total_words = sum(ch.word_count for ch in chapters)
    task.chapters_meta = json.dumps([
        {"number": ch.chapter_number, "title": ch.title, "raw_title": ch.raw_title, "word_count": ch.word_count, "kind": ch.kind}
        for ch in chapters
    ], ensure_ascii=False)


def _range_label(batch: list[Chapter]) -> str:
    a, b = batch[0].chapter_number, batch[-1].chapter_number
    return f"第 {a} 章" if a == b else f"第 {a}-{b} 章"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_extraction_v5_background(task_id: str, user_id: str, ai_service: AIService) -> None:
    db: Optional[AsyncSession] = None
    try:
        db = await _create_task_session(user_id)
        task = await _fetch_task(db, task_id)
        if task is None or task.user_id != user_id:
            logger.error("[拆书V5] 任务不存在或无权 task=%s", task_id)
            return
        task.status, task.stage, task.extraction_phase = "running", "splitting", "splitting"
        task.progress, task.started_at, task.error_message, task.version = 0, datetime.now(), None, PIPELINE_VERSION
        await db.commit()
        trace_progress(f"正在切分章节（约 {task.total_words or 0:,} 字）…", 0)
        split_stage = begin_stage("splitting", "章节切分")

        try:
            chapters = await _load_chapters(task.storage_path or "", ai_service)
        except FileNotFoundError:
            await _mark_failed(db, task, "全文文件丢失，请重新上传")
        if not chapters:
            await _mark_failed(db, task, "重新切分得到 0 章")
        _sync_chapter_meta(task, chapters)
        indices = select_target_indices(
            len(chapters), task.sampling_mode or "all", task.sampling_param or 1, chapter_limit=task.chapter_limit or 0,
        )
        target = [chapters[i] for i in indices]
        if not target:
            await _mark_failed(db, task, "按当前范围 / 采样设置未选出任何章节")
        task.chapters_total, task.chapters_extracted, task.chapters_failed = len(target), 0, 0
        plan = plan_batches(
            [len(ch.content or "") for ch in target],
            model=getattr(ai_service, "default_model", None), max_tokens=getattr(ai_service, "default_max_tokens", None),
            extraction_engine=(task.extraction_engine or "auto").lower(), chapters_per_request=task.chapters_per_request or 0,
        )
        split_stage.done(章节=len(chapters), 目标章节=len(target), 批次=plan.batch_count)
        _set_progress(task, _P_SPLIT_END, f"开始抽取拆书卡：{len(target)} 章分 {plan.batch_count} 批")
        await db.commit()

        cards = await _run_card_extraction(db, task, target, plan, ai_service)
        if not cards:
            await _mark_failed(db, task, "没有任何章节抽出拆书卡")

        arcs = await _run_arc_building(db, task, cards, ai_service)

        task.stage = task.extraction_phase = "skeleton"
        await db.commit()
        stats = build_structure_stats(cards, arcs)
        bridges_payload = build_bridges_payload(arcs, cards)
        skeleton, characters, methodology = await _run_skeleton(task, cards, arcs, stats, ai_service)

        task.stage = task.extraction_phase = "style"
        await db.commit()
        style = await _run_style(task, target, cards, ai_service)

        payload: dict[str, Optional[dict]] = {
            "bridges": bridges_payload if arcs else None, "synopsis": skeleton, "style": style,
            "character_archive": characters, "methodology": methodology, "structure": stats,
        }
        generated = [k for k, v in payload.items() if isinstance(v, dict)]

        task.stage = task.extraction_phase = "pack"
        _set_progress(task, _P_STYLE_END, "写入参考包并预压缩各维度…")
        await db.commit()
        pack_stage = begin_stage("pack", "写入参考包")
        pack_id = await _write_reference_pack_v5(db, task, payload, generated)
        await _precompress(db, pack_id, task_id)

        task.result_json = json.dumps({
            "version": PIPELINE_VERSION, "pack_id": pack_id, "generated_dimensions": generated,
            "stats": {"chapters_total": task.chapters_total, "chapters_extracted": task.chapters_extracted,
                      "chapters_failed": task.chapters_failed, "arc_count": len(arcs),
                      "stage_count": len((skeleton or {}).get("stages") or [])},
        }, ensure_ascii=False)
        task.status, task.progress, task.stage, task.extraction_phase, task.completed_at = "completed", 100, "done", "done", datetime.now()
        await db.commit()
        pack_stage.done(章节=f"{task.chapters_extracted}/{task.chapters_total}", 单元=len(arcs), 维度=len(generated))
        logger.info("[拆书V5] 完成 task=%s cards=%d/%d arcs=%d pack=%s dims=%s",
                    task_id, task.chapters_extracted, task.chapters_total, len(arcs), pack_id, generated)

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
    except ExtractionAborted:
        # 前置校验失败：_mark_failed 已落库，原样抛给 ai_jobs 标 error
        raise
    except Exception as exc:
        logger.error("[拆书V5] 未预期异常 task=%s err=%s", task_id, exc, exc_info=True)
        if db is not None:
            try:
                await _mark_terminal(db, task_id, status="failed", message=f"{type(exc).__name__}: {exc}"[:500])
            except Exception as inner:
                logger.error("[拆书V5] 写失败状态再次出错 %s", inner)
        raise
    finally:
        if db is not None:
            await db.close()


# ---------------------------------------------------------------------------
# S1 拆书卡
# ---------------------------------------------------------------------------

CardResult = tuple[Chapter, Optional[ChapterCard], Optional[str]]


async def _extract_cards_with_fallback(
    batch: list[Chapter], *, extractor: ChapterCardExtractor, known: list[str], prior: list[ChapterCard],
    task_id: str, progress: int,
) -> list[CardResult]:
    """整批失败 → 对半拆分递归；漏章 → 漏的组子批（全漏按整批失败）；单章失败即该章失败。"""
    async def _recurse(subs: list[list[Chapter]]) -> list[CardResult]:
        out: list[CardResult] = []
        for sub in subs:
            out.extend(await _extract_cards_with_fallback(
                sub, extractor=extractor, known=known, prior=prior, task_id=task_id, progress=progress,
            ))
        return out

    def _halves(chs: list[Chapter]) -> list[list[Chapter]]:
        return [[chs[i] for i in half] for half in split_batch(list(range(len(chs))))]

    try:
        cards = await extractor.extract_batch(batch, known_characters=known, prior_cards=prior)
    except ChapterCardExtractionError as exc:
        if len(batch) == 1:
            return [(batch[0], None, str(exc)[:500])]
        logger.warning("[拆书V5] task=%s 批次 %s 失败：%s → 对半拆分重试", task_id, _range_label(batch), exc)
        trace_progress(f"{_range_label(batch)} 整批抽取失败（{str(exc)[:60]}），拆成两半重试…", progress)
        return await _recurse(_halves(batch))
    except Exception as exc:
        logger.error("[拆书V5] task=%s 批次 %s 意外异常 %s", task_id, _range_label(batch), exc, exc_info=True)
        if len(batch) == 1:
            return [(batch[0], None, f"{type(exc).__name__}: {exc}"[:500])]
        return await _recurse(_halves(batch))

    by_num = {c.chapter_number: c for c in cards if c.has_content()}
    results: list[CardResult] = [(ch, by_num[ch.chapter_number], None) for ch in batch if ch.chapter_number in by_num]
    missed = [ch for ch in batch if ch.chapter_number not in by_num]
    if missed:
        if len(batch) == 1:
            return [(batch[0], None, "模型未返回本章拆书卡")]
        trace_progress(f"{_range_label(batch)} 模型漏给了 {len(missed)} 章，组成子批补抽…", progress)
        results.extend(await _recurse(_halves(missed) if len(missed) == len(batch) else [missed]))
        order = {ch.chapter_number: i for i, ch in enumerate(batch)}
        results.sort(key=lambda r: order[r[0].chapter_number])
    return results


async def _run_card_extraction(
    db: AsyncSession, task: BookDissectTask, target: list[Chapter], plan: BatchPlan, ai_service: AIService,
) -> list[ChapterCard]:
    await db.execute(delete(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task.id))
    await db.execute(delete(BookDissectStoryArc).where(BookDissectStoryArc.task_id == task.id))
    task.stage = task.extraction_phase = "cards"
    await db.commit()
    stage = begin_stage("cards", f"拆书卡（{plan.batch_count} 批）")
    extractor = ChapterCardExtractor(ai_service=ai_service)
    cards: list[ChapterCard] = []
    total = plan.batch_count
    for b_idx, idxs in enumerate(plan.batches):
        batch = [target[i] for i in idxs]
        trace_progress(
            f"正在抽取第 {b_idx + 1}/{total} 批拆书卡（{_range_label(batch)}）· 已完成 {task.chapters_extracted}/{task.chapters_total} 章",
            task.progress,
        )
        results = await _extract_cards_with_fallback(
            batch, extractor=extractor, known=ChapterCardExtractor.build_known_characters(cards), prior=cards[-3:],
            task_id=task.id, progress=task.progress or 0,
        )
        for ch, card, err in results:
            if card is not None:
                cards.append(card)
                task.chapters_extracted += 1
            else:
                task.chapters_failed += 1
                card = ChapterCard(chapter_number=ch.chapter_number, title=ch.title or "", word_count=ch.word_count)
            db.add(BookDissectChapterFact(
                task_id=task.id, chapter_number=ch.chapter_number, chapter_title=ch.title or "",
                fact_json=json.dumps(card.to_dict(), ensure_ascii=False), summary=card.outline or None,
                extraction_status="success" if err is None else "failed", extraction_error=err,
                is_truncated=int(card.truncated_input), segment_count=1, extracted_at=datetime.now(),
            ))
        ratio = (b_idx + 1) / max(1, total)
        failed_note = f"，{task.chapters_failed} 章失败" if task.chapters_failed else ""
        _set_progress(task, int(_P_SPLIT_END + ratio * (_P_CARDS_END - _P_SPLIT_END)),
                      f"已完成 {b_idx + 1}/{total} 批 · {task.chapters_extracted}/{task.chapters_total} 章{failed_note}")
        # 多章批每批 commit；逐章模式每 5 章 commit 一次（避免每章都 commit 影响 IO）
        if len(idxs) > 1 or (b_idx + 1) % 5 == 0 or b_idx + 1 == total:
            await db.commit()
    stage.done(成功=task.chapters_extracted, 失败=task.chapters_failed)
    return cards


# ---------------------------------------------------------------------------
# S2 情节单元
# ---------------------------------------------------------------------------

async def _run_arc_building(db: AsyncSession, task: BookDissectTask, cards: list[ChapterCard], ai_service: AIService) -> list[StoryArc]:
    task.stage = task.extraction_phase = "arcs"
    await db.commit()
    stage = begin_stage("arcs", "情节单元识别")
    last_chapter = cards[-1].chapter_number

    def _on_window(n_arcs: int, s: int, e: int) -> None:
        ratio = min(1.0, e / max(1, last_chapter))
        _set_progress(task, int(_P_CARDS_END + ratio * (_P_ARCS_END - _P_CARDS_END)),
                      f"识别情节单元：已到第 {e} 章，累计 {n_arcs} 个单元")

    arcs = await StoryArcBuilder(ai_service).build(cards, on_window=_on_window)
    for a in arcs:
        db.add(BookDissectStoryArc(
            task_id=task.id, arc_index=a.arc_index, start_chapter=a.start_chapter, end_chapter=a.end_chapter,
            title=a.title[:120], payoff_type=a.payoff_type, origin=a.origin,
            arc_json=json.dumps(a.to_dict(), ensure_ascii=False),
        ))
    _set_progress(task, _P_ARCS_END, f"情节单元识别完成：{len(arcs)} 个（{len(cards)} 章）")
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
    trace_progress("全书骨架：按情节单元划分阶段…", task.progress)
    stages = await builder.build_stages(arcs) or fallback_stages(arcs)
    _set_progress(task, _P_ARCS_END + 3, f"阶段划分完成：{len(stages)} 个阶段，归纳全书骨架 / 人物功能谱…")
    skeleton, characters = await asyncio.gather(
        builder.build_skeleton(stages, cards, stats), builder.build_character_functions(stages, arcs, cards),
    )
    if skeleton is None:
        skeleton = {"stages": stages, "pipeline_version": PIPELINE_VERSION, "genre_tag": "", "one_line_premise": "", "main_conflict": ""}
        stage.note(骨架="LLM 失败，仅保留阶段划分")
    methodology = await builder.build_methodology(skeleton, stats, cards)
    _set_progress(task, _P_SKELETON_END, "全书骨架完成，开始文风指纹…")
    stage.done(阶段=len(stages), 人物谱=characters is not None, 手册=methodology is not None)
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
        archetypes_json=None, worldbuilding_json=None, entities_json=None, relations_json=None, events_json=None,
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


async def _precompress(db: AsyncSession, pack_id: str, task_id: str) -> None:
    try:
        pack = (await db.execute(select(ReferencePack).where(ReferencePack.id == pack_id))).scalar_one_or_none()
        if pack is None:
            return
        from app.services.reference_pack.dimension_compressor import compress_pack_to_db
        for field_name, text in compress_pack_to_db(pack).items():
            setattr(pack, field_name, text)
        await db.flush()
    except Exception as exc:  # pragma: no cover - 预压缩失败运行时 fallback
        logger.warning("[拆书V5] task=%s 预压缩失败（已跳过，运行时实时压缩）：%s", task_id, exc)
