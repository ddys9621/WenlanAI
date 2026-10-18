"""章节候选稿：列表 / 全文 / 采用（可编辑后采用、确认覆盖、采用后自动分析）/ 丢弃。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chapter_versions import load_owned_chapter
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.schemas.chapter_candidate import CandidateAdoptRequest
from app.services.ai_jobs import AIJobConflictError, ai_jobs
from app.services.ai_service import AIService
from app.services.chapter_analysis_jobs import analysis_scope, create_analysis_task, start_chapter_analysis
from app.services.chapter_candidate_service import (
    CandidateError,
    adopt_candidate,
    candidate_detail,
    candidate_summary,
    discard_candidate,
    list_candidates,
)
from app.services.chapter_purge_service import purge_chapter_vector_memory
from app.services.chapter_version_service import content_hash

router = APIRouter(prefix="/chapters", tags=["章节候选稿"])
logger = get_logger(__name__)


async def _load_candidate(db: AsyncSession, chapter: Chapter, candidate_id: str) -> ChapterCandidate:
    candidate = (await db.execute(
        select(ChapterCandidate).where(ChapterCandidate.id == candidate_id, ChapterCandidate.chapter_id == chapter.id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选稿不存在")
    return candidate


async def _queue_analysis(db: AsyncSession, chapter: Chapter, user_id: str, ai_service: AIService) -> dict:
    # 同章还在跑的分析读的是采用前的旧稿，结果对不上新正文：停掉它再排新的（否则新分析排不上，作者什么也看不到）
    running = ai_jobs.current(analysis_scope(chapter.id))
    if running is not None:
        await ai_jobs.cancel(running.id)
    task_id = await create_analysis_task(db, chapter_id=chapter.id, user_id=user_id, project_id=chapter.project_id)
    try:
        job = await start_chapter_analysis(
            chapter_id=chapter.id, chapter_number=chapter.chapter_number, chapter_title=chapter.title,
            user_id=user_id, project_id=chapter.project_id, task_id=task_id, ai_service=ai_service, manager=ai_jobs,
        )
    except AIJobConflictError as conflict:
        logger.warning(f"⚠️ 采用候选稿后的分析没排上（刚有同章分析发起，跟着它走）: {conflict}")
        job = ai_jobs.current(analysis_scope(chapter.id))
    return {"analysis_task_id": task_id, "analysis_job_id": job.id if job else None}


def _chapter_payload(chapter: Chapter) -> dict:
    return {
        "id": chapter.id,
        "project_id": chapter.project_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "content": chapter.content,
        "word_count": chapter.word_count or 0,
        "status": chapter.status,
    }


@router.get("/{chapter_id}/candidates", summary="章节候选稿列表（不含全文）")
async def list_chapter_candidates(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query("pending", description="pending / adopted / discarded / superseded / all"),
):
    chapter = await load_owned_chapter(db, chapter_id, request)
    rows = await list_candidates(db, chapter.id, status=None if status in (None, "all") else status)
    current = content_hash(chapter.content)
    return {"total": len(rows), "items": [candidate_summary(c, current) for c in rows]}


@router.get("/{chapter_id}/candidates/{candidate_id}", summary="候选稿全文与审校报告")
async def get_chapter_candidate(chapter_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await load_owned_chapter(db, chapter_id, request)
    candidate = await _load_candidate(db, chapter, candidate_id)
    return candidate_detail(candidate, content_hash(chapter.content))


@router.post("/{chapter_id}/candidates/{candidate_id}/adopt", summary="采用候选稿写入正文")
async def adopt_chapter_candidate(
    chapter_id: str,
    candidate_id: str,
    body: CandidateAdoptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    chapter = await load_owned_chapter(db, chapter_id, request)
    candidate = await _load_candidate(db, chapter, candidate_id)
    user_id = getattr(request.state, "user_id", None)
    try:
        result = await adopt_candidate(db, candidate, chapter, content_override=body.content, force=body.force)
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(chapter)
    if result.changed and candidate.mode == "replace_all":
        await purge_chapter_vector_memory(user_id, chapter.project_id, chapter.id, result.purged_memories)

    response = {
        "chapter": _chapter_payload(chapter),
        "candidate_id": candidate.id,
        "changed": result.changed,
        "purged_memories": result.purged_memories,
        "snapshot_version_id": result.version.id if result.version else None,
        "analysis_task_id": None,
        "analysis_job_id": None,
    }
    if body.auto_analyze and (chapter.content or "").strip() and user_id:
        response.update(await _queue_analysis(db, chapter, user_id, user_ai_service))
    return response


@router.post("/{chapter_id}/candidates/{candidate_id}/discard", summary="丢弃候选稿")
async def discard_chapter_candidate(chapter_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await load_owned_chapter(db, chapter_id, request)
    candidate = await _load_candidate(db, chapter, candidate_id)
    try:
        await discard_candidate(db, candidate)
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"id": candidate.id, "status": candidate.status}
