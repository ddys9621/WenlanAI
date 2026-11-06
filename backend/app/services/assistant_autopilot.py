"""共创室 · 自动执行（工具直接写书，一轮从架构一路做到正文）。

作者在输入框打开「自动执行」才生效，默认关，关着时一切照旧（候选要作者在卡片上点了才写入）。打开后：
- 工具产出的修改卡直接应用、新建卡直接建档、卷纲 / 章纲草案直接确认（apply_cards）；生成总入口遇到「等作者确认」
  或先补了上游，也当场写入再接着做（assistant_generators.run_target）
- write_chapter 等后台正文写完，候选稿直接采用（finish_chapter），并排上章节分析
- 系统提问卡（作品信息 / 章数视角字数）与成员自己的提问按推荐项作答（assistant_agent_service）

和作者在卡片上点按钮走同一套服务函数、同一把项目锁（decision_lock），提交后读回真东西核对（所有会话共用一个 SQLite
连接，别的请求收尾时的回滚可能冲掉刚写的）。改动照样记在卡片上：修改可以撤销，正文能在历史版本里恢复，
新建的资料到对应页面删。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.assistant import AssistantEntityCandidate, AssistantFieldCandidate
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_outline import ChapterOutline
from app.models.volume import Volume
from app.services import assistant_candidate_service as cands
from app.services import assistant_entity_candidate_service as entity_cands
from app.services import assistant_fields as fields
from app.services import outline_review_service as outline_review
from app.services import volume_service as volumes
from app.services.assistant_persistence import WRITE_ATTEMPTS, decision_lock

logger = get_logger(__name__)

# 创作顺序（与前端 utils/cocreation.ts 的 LAYER 一致）：关系 / 成员排在人物与组织之后，两头先建好
LAYER = {"project": 0, "world_rule": 1, "setting_entry": 2, "location": 3, "character": 4, "organization": 4,
         "relationship": 5, "membership": 5, "story_outline": 6, "volume": 7, "volume_unit": 8, "chapter_outline": 9}
LIST_LIMIT = 12
CHAPTER_WAIT_SECONDS = 15 * 60  # 等后台正文写完的上限：超了这一章就留成候选稿，作者自己采用
NOTE = ("（自动执行：上面这些已经直接写进书里了——修改已应用、新建已建档、草案已确认，作者在卡片上看得到、能撤销；"
        "不用再请作者确认，接着往下做。）")


@dataclass
class AutoResult:
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def extend(self, other: "AutoResult") -> None:
        self.done += other.done
        self.failed += other.failed

    @property
    def empty(self) -> bool:
        return not (self.done or self.failed)

    def text(self) -> str:
        parts = []
        if self.done:
            shown = "、".join(self.done[:LIST_LIMIT]) + ("……" if len(self.done) > LIST_LIMIT else "")
            parts.append(f"已直接写入 {len(self.done)} 项：{shown}")
        if self.failed:
            parts.append(f"没写成 {len(self.failed)} 项（卡片还在待确认栏，作者可以自己处理）：{'；'.join(self.failed[:6])}")
        return "；".join(parts)

    def outcome_note(self) -> str:
        return f"{self.text()}\n{NOTE}" if self.done else self.text()


def _layer_of_field(field_id: str) -> int:
    return LAYER.get(fields.entity_of(field_id) or "", len(LAYER))


async def _fresh(db: AsyncSession, model: Any, row_id: str) -> Any:
    return (await db.execute(
        select(model).where(model.id == row_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def _apply_field(db: AsyncSession, project_id: str, candidate_id: str) -> tuple[bool, str]:
    """同 api/assistant._decide（应用）：记成已应用、内容却被冲掉了就退回一步重做。"""
    label = "修改"
    for _attempt in range(WRITE_ATTEMPTS):
        cand = await _fresh(db, AssistantFieldCandidate, candidate_id)
        if cand is None or cand.project_id != project_id:
            return False, "修改卡不见了"
        label = f"修改{cand.target_label}"
        field_id, target_id, expected = cand.field_id, cand.target_id, cand.after_json
        if cand.status == "applied":
            if await cands.value_is(db, project_id, field_id, target_id, expected):
                return True, label
            cand.status = "candidate"
        elif cand.status != "candidate":
            return False, f"{label}：作者已经处理过了"
        try:
            await cands.apply_candidate(db, cand)
        except fields.FieldError as exc:
            await db.rollback()
            return False, f"{label}：{exc}"
        await db.commit()
        status = await db.scalar(select(AssistantFieldCandidate.status).where(AssistantFieldCandidate.id == candidate_id))
        if status == "applied" and await cands.value_is(db, project_id, field_id, target_id, expected):
            return True, label
        db.expire_all()
    return False, f"{label}：没能写进数据库（被同时进行的其他操作打断）"


async def _apply_entity(db: AsyncSession, project_id: str, candidate_id: str) -> tuple[bool, str]:
    """同 api/assistant._decide_entity（建档）：记成已建档、建出来的那一行却不在了就重建。"""
    label = "新建"
    for _attempt in range(WRITE_ATTEMPTS):
        cand = await _fresh(db, AssistantEntityCandidate, candidate_id)
        if cand is None or cand.project_id != project_id:
            return False, "新建卡不见了"
        label, entity_type = cand.label, cand.entity_type
        if cand.status == "applied":
            if await entity_cands.created_entity_exists(db, entity_type, cand.created_entity_id):
                return True, label
            entity_cands.reopen_entity_candidate(cand)
        elif cand.status != "candidate":
            return False, f"{label}：作者已经处理过了"
        try:
            entity_id = await entity_cands.apply_entity_candidate(db, cand)
        except entity_cands.EntityError as exc:
            await db.rollback()
            return False, f"{label}：{exc}"
        await db.commit()
        status = await db.scalar(select(AssistantEntityCandidate.status).where(AssistantEntityCandidate.id == candidate_id))
        if status == "applied" and await entity_cands.created_entity_exists(db, entity_type, entity_id):
            return True, label
        db.expire_all()
    return False, f"{label}：没能写进数据库（被同时进行的其他操作打断）"


async def _confirm_plan(db: AsyncSession, project_id: str, model: Any, row_id: str) -> tuple[bool, str]:
    """同谋篇页 / 草案卡片上的「确认」：卷纲 volume_service.confirm_volume，章纲 outline_review.confirm。"""
    label = "草案"
    for _attempt in range(WRITE_ATTEMPTS):
        row = await _fresh(db, model, row_id)
        if row is None or row.project_id != project_id:
            return False, f"{label}已经不在了（被重新生成替换或删掉）"
        label = f"第{row.volume_number}卷卷纲" if model is Volume else f"第{row.chapter_number}章章纲"
        if (row.review_status or volumes.CONFIRMED) == volumes.CONFIRMED and not row.upstream_stale:
            return True, label
        (volumes.confirm_volume if model is Volume else outline_review.confirm)(row)
        await db.commit()
        status = await db.scalar(select(model.review_status).where(model.id == row_id))
        if status == volumes.CONFIRMED:
            return True, label
        db.expire_all()
    return False, f"{label}：没能写进数据库（被同时进行的其他操作打断）"


async def _drafts(db: AsyncSession, model: Any, ids: list[str]) -> list[str]:
    """还没确认（草拟 / 上游已改）的卷纲或章纲，保持原来的先后。"""
    if not ids:
        return []
    rows = (await db.execute(select(model.id, model.review_status, model.upstream_stale).where(model.id.in_(ids)))).all()
    pending = {r.id for r in rows if (r.review_status or volumes.CONFIRMED) != volumes.CONFIRMED or r.upstream_stale}
    return [i for i in ids if i in pending]


def _emit_updates(ctx: Any, field_ids: list[str], entity_ids: list[str], plans: dict, entities: list[str]) -> None:
    """告诉前端这些卡已经处理了（卡片上的状态跟着变，跑完读回对话时以库里为准；entities = 要刷新的页面数据类型）。"""
    if field_ids or entity_ids:
        ctx.emit({"type": "card_update", "candidates": field_ids, "entity_candidates": entity_ids,
                  "entities": list(dict.fromkeys(entities))})
    if plans.get("volume_ids") or plans.get("outline_ids"):
        ctx.emit({"type": "plans_confirmed", "volume_ids": plans.get("volume_ids") or [],
                  "outline_ids": plans.get("outline_ids") or []})


async def apply_cards(ctx: Any, waiting: dict) -> AutoResult:
    """把一批卡直接写进书里（waiting：{"candidates", "entity_candidates", "volume_ids", "outline_ids"}，键都可以没有）。
    按创作顺序：修改卡、新建卡（人物 / 组织在关系之前）、卷纲、章纲。"""
    db, project_id, result = ctx.db, ctx.project_id, AutoResult()
    field_ids = list(dict.fromkeys(waiting.get("candidates") or []))
    entity_ids = list(dict.fromkeys(waiting.get("entity_candidates") or []))
    volume_ids = list(dict.fromkeys(waiting.get("volume_ids") or []))
    outline_ids = list(dict.fromkeys(waiting.get("outline_ids") or []))
    if not (field_ids or entity_ids or volume_ids or outline_ids):
        return result
    # 只处理还待确认的（同一步里生成总入口已经写过的上游卡、作者刚在卡片上点过的都跳过，不重复算）
    field_rows = {i: f for i, f, s in (await db.execute(select(
        AssistantFieldCandidate.id, AssistantFieldCandidate.field_id, AssistantFieldCandidate.status,
    ).where(AssistantFieldCandidate.id.in_(field_ids)))).all() if s == "candidate"} if field_ids else {}
    entity_rows = {i: t for i, t, s in (await db.execute(select(
        AssistantEntityCandidate.id, AssistantEntityCandidate.entity_type, AssistantEntityCandidate.status,
    ).where(AssistantEntityCandidate.id.in_(entity_ids)))).all() if s == "candidate"} if entity_ids else {}
    field_ids = sorted((i for i in field_ids if i in field_rows), key=lambda i: _layer_of_field(field_rows[i]))
    entity_ids = sorted((i for i in entity_ids if i in entity_rows), key=lambda i: LAYER.get(entity_rows[i], len(LAYER)))
    volume_ids = await _drafts(db, Volume, volume_ids)
    outline_ids = await _drafts(db, ChapterOutline, outline_ids)
    done_fields, done_entities, done_plans = [], [], {"volume_ids": [], "outline_ids": []}
    touched: list[str] = []
    async with decision_lock(project_id):
        for cid in field_ids:
            ok, label = await _apply_field(db, project_id, cid)
            (result.done if ok else result.failed).append(label)
            if ok:
                done_fields.append(cid)
                touched.append(fields.entity_of(field_rows[cid]) or "")
        for eid in entity_ids:
            ok, label = await _apply_entity(db, project_id, eid)
            (result.done if ok else result.failed).append(label)
            if ok:
                done_entities.append(eid)
                touched.append(entity_rows[eid])
        for key, model, ids in (("volume_ids", Volume, volume_ids), ("outline_ids", ChapterOutline, outline_ids)):
            for row_id in ids:
                ok, label = await _confirm_plan(db, project_id, model, row_id)
                (result.done if ok else result.failed).append(label)
                if ok:
                    done_plans[key].append(row_id)
    _emit_updates(ctx, done_fields, done_entities, done_plans, [e for e in touched if e])
    return result


def marks(ctx: Any) -> tuple[int, int, int]:
    return len(ctx.candidates), len(ctx.entity_candidates), len(ctx.plans)


def new_cards(ctx: Any, since: tuple[int, int, int]) -> dict:
    from app.services.assistant_generators import _new_cards  # 延迟导入：生成器模块导入本模块

    return _new_cards(ctx, since)


async def apply_new(ctx: Any, since: tuple[int, int, int]) -> AutoResult:
    """一步工具做完：这一步新出的卡全部直接写入。"""
    return await apply_cards(ctx, new_cards(ctx, since))


async def finish_chapter(ctx: Any, chapter_id: str, number: int, job: Any, *, ai_service: Any,
                         write: Optional[dict] = None) -> tuple[bool, str, str]:
    """自动执行时 write_chapter 等后台正文写完，直接采用候选稿（正文旧稿先进历史版本），再排上章节分析。
    采用了就在 write（对话里那张写作卡）上记 adopted：候选稿、采用前那一版（空稿为空）、采用后的正文指纹——撤销本轮按它恢复。
    返回 (成功, 摘要, 给模型的说明)。"""
    from app.services.chapter_candidate_service import CandidateError, adopt_candidate
    from app.services.chapter_version_service import content_hash

    try:
        await asyncio.wait_for(asyncio.shield(job.task), timeout=CHAPTER_WAIT_SECONDS)
    except asyncio.TimeoutError:
        return True, f"第 {number} 章还在后台写", (
            f"等了 {CHAPTER_WAIT_SECONDS // 60} 分钟第 {number} 章还没写完：写完会存成候选稿，请作者在章节写作页采用；"
            "这一章没采用之前，后面的章先不要写。")
    except asyncio.CancelledError:
        raise  # 停止的是这一轮；shield 让后台正文接着写完，存成候选稿
    except Exception:  # noqa: BLE001 - 正文任务自己失败：下面按任务状态如实说
        pass
    result = job.result if isinstance(job.result, dict) else {}
    candidate_id = result.get("candidate_id")
    if job.status != "done" or not candidate_id:
        return False, f"第 {number} 章没写成", f"后台正文任务结束了，但没有存下候选稿（{job.error or job.status}）。"
    db = ctx.db
    adopted, mode, before_empty, before_hash = None, "", None, ""
    async with decision_lock(ctx.project_id):
        for _attempt in range(WRITE_ATTEMPTS):
            db.expire_all()
            candidate = await _fresh(db, ChapterCandidate, candidate_id)
            chapter = await _fresh(db, Chapter, chapter_id)
            if candidate is None or chapter is None:
                return False, f"第 {number} 章没采用上", "候选稿或章节不见了（可能被作者删了）。"
            if candidate.status == "adopted" and (chapter.content or "").strip():
                break
            mode = candidate.mode
            if before_empty is None:  # 只认第一次看到的样子（重试时正文可能已经是一半写进去的）
                before_empty, before_hash = not (chapter.content or "").strip(), content_hash(chapter.content)
            try:
                adopted = await adopt_candidate(db, candidate, chapter)
            except CandidateError as exc:
                await db.rollback()
                return False, f"第 {number} 章没采用上：{exc}", (
                    f"候选稿已存好，但没能自动采用：{exc}。请作者到章节写作页的候选稿里看。")
            await db.commit()
            status = await db.scalar(select(ChapterCandidate.status).where(ChapterCandidate.id == candidate_id))
            content = await db.scalar(select(Chapter.content).where(Chapter.id == chapter_id))
            if status == "adopted" and (content or "").strip():
                break
        else:
            return False, f"第 {number} 章没采用上", "候选稿已存好，但没能写进正文（被同时进行的其他操作打断），请作者到章节写作页采用。"
    chapter = await _fresh(db, Chapter, chapter_id)
    words = chapter.word_count or len(chapter.content or "")
    if write is not None and before_empty is not None:
        write["adopted"] = {"candidate_id": candidate_id, "after_hash": content_hash(chapter.content),
                            "before_empty": before_empty, "before_hash": before_hash}
    await _after_adopt(ctx, chapter, adopted if mode == "replace_all" else None, ai_service)
    ctx.emit({"type": "chapter_adopted", "chapter_id": chapter_id, "chapter_number": number, "word_count": words})
    return True, f"第 {number} 章写好并采用了（{words} 字）", (
        f"第 {number} 章已经写完并直接采用进正文（{words} 字；正文原来的内容先存进了历史版本，作者能在章节写作页恢复），"
        "章节分析已排上。要接着写下一章就再调用 write_chapter。")


async def _after_adopt(ctx: Any, chapter: Chapter, whole: Any, ai_service: Any) -> None:
    """同章节页「采用」之后（api/chapter_candidates）：整章替换（whole = 那次采用的结果）且正文变了就清掉这章的向量记忆，
    再排一次章节分析（故事账本、后面章节的前情靠它）。"""
    from app.api.chapter_candidates import _queue_analysis
    from app.services.chapter_purge_service import purge_chapter_vector_memory

    if not ctx.user_id:
        return
    try:
        if whole is not None and whole.changed:
            await purge_chapter_vector_memory(ctx.user_id, chapter.project_id, chapter.id, whole.purged_memories)
        await _queue_analysis(ctx.db, chapter, ctx.user_id, ai_service)
    except Exception as exc:  # noqa: BLE001 - 分析只是后续增强，正文已经采用了
        logger.warning(f"[智能助笔] 自动执行采用第 {chapter.chapter_number} 章后排分析失败：{exc}")


def auto_answers(question: dict) -> list[dict]:
    """自动执行替作者作答：有推荐项选推荐项，否则选第一项；只能填字的问题跳过（交给成员按自己的判断推进）。"""
    answers = []
    for q in question.get("questions") or []:
        options = q.get("options") or []
        picked = [o["id"] for o in options if o.get("recommended")] or ([options[0]["id"]] if options else [])
        if q.get("mode") == "single":
            picked = picked[:1]
        if q.get("mode") == "text" or not picked:
            answers.append({"id": q["id"], "choices": [], "text": "", "skipped": True})
        else:
            answers.append({"id": q["id"], "choices": picked, "text": "", "skipped": False})
    return answers
