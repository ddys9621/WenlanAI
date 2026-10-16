"""故事账本 API（原「记忆系统」）：章节分析沉淀下来、写正文时会召回的东西，作者都能看、能改。

- 概览：分析状态（未分析 / 过期 / 失败）、伏笔数、检索索引状态（为空而账本有内容时自动后台重建）
- 伏笔 / 承诺：列表、作者改 / 标回收 / 放弃 / 新建 / 合并重复（改过的字段重新分析不覆盖）
- 人物状态：按章回放、变化记录、作者修正（重新分析不清）
- 章节档案、时间线（事件 + 因果）、召回预览（写第 N 章时会注入什么、为什么）、检索（关键词 + 语义）
- 重建检索索引、按章序批量分析（后台任务，托盘可见）
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_project_access
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_digest import ChapterDigest
from app.models.narrative_promise import NarrativePromise
from app.models.timeline_event import TimelineEvent
from app.schemas.story_ledger import (
    BatchAnalyzeRequest, PromiseCreate, PromiseMerge, PromiseUpdate, StateCorrectionCreate,
)
from app.services import story_index_items
from app.services import story_ledger_service as ledger
from app.services.ai_jobs import AIJobConflictError, ai_jobs
from app.services.ai_service import AIService
from app.services.chapter_analysis_jobs import (
    REBUILD_KIND, analysis_scope, schedule_index_rebuild_if_needed, start_batch_analysis, start_index_rebuild,
)
from app.services.chapter_readiness_service import analysis_statuses
from app.services.memory_service import memory_service
from app.services.story_recall_service import recall_preview

logger = get_logger(__name__)
router = APIRouter(prefix="/api/memories", tags=["故事账本"])

KIND_LABELS = {"digest": "章节档案", "event": "事件", "causal": "因果", "promise": "伏笔"}


async def _owner(request: Request, project_id: str, db: AsyncSession) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)
    return user_id


async def _latest_written(db: AsyncSession, project_id: str) -> int:
    value = (await db.execute(
        select(func.max(Chapter.chapter_number)).where(
            Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "",
        )
    )).scalar_one_or_none()
    return int(value or 0)


def _running(chapter_id: str) -> bool:
    return ai_jobs.current(analysis_scope(chapter_id)) is not None


def _ledger_error(exc: ledger.LedgerError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _refresh_promises(user_id: str, db: AsyncSession, project_id: str, promise_ids: list[str],
                            removed: Optional[list[str]] = None) -> None:
    try:
        if removed:
            await memory_service.delete_items(user_id, project_id, [f"promise:{pid}" for pid in removed])
        await memory_service.upsert_items(user_id, project_id, await story_index_items.promise_items(db, project_id, promise_ids))
    except Exception as exc:  # noqa: BLE001 - 索引可重建
        logger.warning(f"⚠️ 刷新伏笔索引失败: {exc}")


# ---------------- 概览 ----------------

@router.get("/projects/{project_id}/overview", summary="故事账本概览")
async def get_overview(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    statuses = await analysis_statuses(db, project_id, is_running=_running)
    counts = Counter(s["status"] for s in statuses.values())
    promise_counts = dict((await db.execute(
        select(NarrativePromise.status, func.count(NarrativePromise.id))
        .where(NarrativePromise.project_id == project_id).group_by(NarrativePromise.status)
    )).all())
    latest = await _latest_written(db, project_id)
    active = await ledger.list_promises(db, project_id, status="active", as_of=latest + 1)
    index = await memory_service.index_status(user_id, project_id)
    ledger_items = await story_index_items.project_item_count(db, project_id)
    started = await schedule_index_rebuild_if_needed(
        project_id=project_id, user_id=user_id, index_count=index["count"], ledger_count=ledger_items,
    )
    return {
        "latest_chapter": latest,
        "chapters": {
            "written": len(statuses), "ok": counts.get("ok", 0), "stale": counts.get("stale", 0),
            "missing": counts.get("missing", 0), "failed": counts.get("failed", 0), "running": counts.get("running", 0),
        },
        "promises": {
            "active": sum(promise_counts.get(s, 0) for s in ledger.ACTIVE_STATUSES),
            "resolved": promise_counts.get("resolved", 0),
            "abandoned": promise_counts.get("abandoned", 0),
            "overdue": sum(1 for p in active if "超期" in p["flag"]),
            "dropout": sum(1 for p in active if "掉线" in p["flag"]),
        },
        "index": {
            **index, "ledger_items": ledger_items,
            "rebuilding": started or ai_jobs.current(f"{REBUILD_KIND}:{project_id}") is not None,
        },
    }


# ---------------- 伏笔 / 承诺 ----------------

@router.get("/projects/{project_id}/promises", summary="伏笔 / 承诺列表")
async def get_promises(project_id: str, request: Request, status: str = "active", q: str = "",
                       db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    as_of = await _latest_written(db, project_id) + 1
    items = await ledger.list_promises(db, project_id, status=status, as_of=as_of, query=q)
    return {"as_of": as_of, "total": len(items), "items": items}


@router.post("/projects/{project_id}/promises", summary="作者登记一条伏笔")
async def create_promise(project_id: str, body: PromiseCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    try:
        promise = await ledger.create_promise(db, project_id, body.model_dump())
    except ledger.LedgerError as exc:
        raise _ledger_error(exc)
    await db.commit()
    await _refresh_promises(user_id, db, project_id, [promise.id])
    as_of = await _latest_written(db, project_id) + 1
    return ledger.promise_view(promise, as_of, {"*"})


@router.patch("/projects/{project_id}/promises/{promise_id}", summary="作者修改伏笔（改过的字段重新分析不覆盖）")
async def update_promise(project_id: str, promise_id: str, body: PromiseUpdate, request: Request,
                         db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    try:
        promise = await ledger.update_promise(db, project_id, promise_id, body.model_dump(exclude_unset=True))
    except ledger.LedgerError as exc:
        raise _ledger_error(exc)
    await db.commit()
    await _refresh_promises(user_id, db, project_id, [promise.id])
    items = await ledger.list_promises(db, project_id, status="all", as_of=await _latest_written(db, project_id) + 1)
    return next((p for p in items if p["id"] == promise.id), None)


@router.post("/projects/{project_id}/promises/{promise_id}/merge", summary="把重复的伏笔并进这一条")
async def merge_promises(project_id: str, promise_id: str, body: PromiseMerge, request: Request,
                         db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    try:
        keep = await ledger.merge_promises(db, project_id, promise_id, body.merge_ids)
    except ledger.LedgerError as exc:
        raise _ledger_error(exc)
    await db.commit()
    await _refresh_promises(user_id, db, project_id, [keep.id], removed=body.merge_ids)
    return {"id": keep.id, "merged": len(body.merge_ids)}


# ---------------- 人物状态 ----------------

@router.get("/projects/{project_id}/characters", summary="写第 N 章时的人物状态")
async def get_character_states(project_id: str, request: Request, chapter: Optional[int] = None,
                               db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    as_of = chapter or (await _latest_written(db, project_id) + 1)
    return {"as_of": as_of, "items": await ledger.character_states(db, project_id, as_of)}


@router.get("/projects/{project_id}/characters/history", summary="某个人物的状态变化记录")
async def get_character_history(project_id: str, request: Request, name: str, before: Optional[int] = None,
                                db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    return {"name": name, "items": await ledger.character_history(db, project_id, name, before)}


@router.post("/projects/{project_id}/state-corrections", summary="作者修正人物状态（重新分析不清）")
async def add_state_correction(project_id: str, body: StateCorrectionCreate, request: Request,
                               db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    try:
        row = await ledger.add_state_correction(db, project_id, body.model_dump())
    except ledger.LedgerError as exc:
        raise _ledger_error(exc)
    await db.commit()
    return {"id": row.id}


@router.delete("/projects/{project_id}/state-corrections/{correction_id}", summary="撤销一条人物状态修正")
async def delete_state_correction(project_id: str, correction_id: str, request: Request,
                                  db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    try:
        await ledger.delete_state_correction(db, project_id, correction_id)
    except ledger.LedgerError as exc:
        raise _ledger_error(exc)
    await db.commit()
    return {"ok": True}


# ---------------- 章节档案 / 时间线 / 召回预览 / 检索 ----------------

@router.get("/projects/{project_id}/digests", summary="章节档案（摘要 + 章末状态 + 分析状态）")
async def get_digests(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    statuses = await analysis_statuses(db, project_id, is_running=_running)
    return {"items": await ledger.digest_rows(db, project_id, statuses)}


@router.get("/projects/{project_id}/timeline", summary="时间轴事件 + 因果链")
async def get_timeline(project_id: str, request: Request, character: Optional[str] = None,
                       from_chapter: Optional[int] = None, to_chapter: Optional[int] = None,
                       db: AsyncSession = Depends(get_db)):
    await _owner(request, project_id, db)
    items = await ledger.timeline(db, project_id, character=character or None, from_chapter=from_chapter,
                                  to_chapter=to_chapter)
    return {"items": items}


@router.get("/projects/{project_id}/recall-preview", summary="写第 N 章时会注入哪些记忆（不调用大模型）")
async def get_recall_preview(project_id: str, request: Request, chapter_number: Optional[int] = None,
                             db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    number = chapter_number or (await _latest_written(db, project_id) + 1)
    preview = await recall_preview(db, user_id=user_id, project_id=project_id, chapter_number=number)
    return {"chapter_number": preview.chapter_number, "sections": preview.sections,
            "relevant_items": preview.relevant_items, "stats": preview.stats}


@router.get("/projects/{project_id}/search", summary="在账本里找（关键词 + 语义）")
async def search_ledger(project_id: str, request: Request, q: str, limit: int = 30,
                        db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    query = (q or "").strip()
    if not query:
        return {"query": query, "items": []}
    found: dict[str, dict] = {}

    def add(item_id: str, kind: str, number: int, text: str, score: float, match: str) -> None:
        prev = found.get(item_id)
        if prev is None:
            found[item_id] = {"id": item_id, "kind": kind, "kind_label": KIND_LABELS.get(kind, kind),
                              "chapter_number": number, "text": text, "score": score, "match": match}
        else:
            prev["score"] = max(prev["score"], score)
            if prev["match"] != match:
                prev["match"] = "both"

    like = f"%{query}%"
    for chapter_id, number, summary, end_state in (await db.execute(
        select(Chapter.id, Chapter.chapter_number, ChapterDigest.summary, ChapterDigest.end_state)
        .join(ChapterDigest, ChapterDigest.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id, (ChapterDigest.summary.like(like)) | (ChapterDigest.end_state.like(like)))
        .limit(limit)
    )).all():
        add(f"digest:{chapter_id}", "digest", number, story_index_items.digest_text(summary, end_state), 1.0, "keyword")
    for row in (await db.execute(
        select(NarrativePromise).where(
            NarrativePromise.project_id == project_id,
            (NarrativePromise.title.like(like)) | (NarrativePromise.content.like(like)),
        ).limit(limit)
    )).scalars():
        add(f"promise:{row.id}", "promise", row.source_chapter_number, f"{row.title}：{row.content}", 1.0, "keyword")
    for row in (await db.execute(
        select(TimelineEvent).where(
            TimelineEvent.project_id == project_id,
            (TimelineEvent.title.like(like)) | (TimelineEvent.description.like(like)),
        ).limit(limit)
    )).scalars():
        add(f"event:{row.id}", "event", row.chapter_number,
            story_index_items.event_text(row.title, row.description, row.location, row.time_marker), 1.0, "keyword")
    for hit in await memory_service.search(user_id, project_id, query, kinds=story_index_items.KINDS, limit=20):
        add(hit.id, hit.kind, hit.chapter_number, hit.text, round(hit.similarity, 3), "semantic")
    items = sorted(found.values(), key=lambda r: (-r["score"], r["chapter_number"] or 0))[:limit]
    return {"query": query, "items": items, "semantic": memory_service.available}


# ---------------- 后台任务 ----------------

@router.post("/projects/{project_id}/index/rebuild", summary="重建检索索引（后台任务 + SSE，不调用大模型）")
async def rebuild_index(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _owner(request, project_id, db)
    if not memory_service.available:
        raise HTTPException(status_code=400, detail="向量模型没有加载，检索索引不可用（召回会只用人物 / 关键词匹配）")
    try:
        job = await start_index_rebuild(project_id=project_id, user_id=user_id)
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.post("/projects/{project_id}/analyze-batch", summary="按章序批量分析（后台任务 + SSE）")
async def analyze_batch(project_id: str, body: BatchAnalyzeRequest, request: Request,
                        db: AsyncSession = Depends(get_db), user_ai_service: AIService = Depends(get_user_ai_service)):
    user_id = await _owner(request, project_id, db)
    if body.to_chapter < body.from_chapter:
        raise HTTPException(status_code=400, detail="结束章号不能小于起始章号")
    try:
        job = await start_batch_analysis(
            project_id=project_id, user_id=user_id, ai_service=user_ai_service,
            from_chapter=body.from_chapter, to_chapter=body.to_chapter, mode=body.mode,
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)
