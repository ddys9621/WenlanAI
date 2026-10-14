"""智能助笔接口：当前章的对话式写作助手（后台任务 + SSE）。修改类结果是候选稿，采用走 /chapters/{id}/candidates。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.chapter_versions import load_owned_chapter
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.schemas.writing_assistant import AssistantRequest
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.writing_assistant_service import SKILL_LABELS, resolve_skill, run_assistant, selection_matches

router = APIRouter(prefix="/chapters", tags=["智能助笔"])


@router.post("/{chapter_id}/assistant-stream", summary="智能助笔：续写 / 改写 / 润色 / 核对 / 提问（SSE）")
async def assistant_stream(
    chapter_id: str,
    body: AssistantRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    chapter = await load_owned_chapter(db, chapter_id, request)
    user_id = getattr(request.state, "user_id", None)
    selection = body.selection.model_dump() if body.selection else None
    if selection and not selection_matches(chapter.content or "", selection):
        raise HTTPException(status_code=400, detail="选区与正文对不上（正文可能刚被改过），请重新选中")
    skill = resolve_skill(body.message, has_selection=selection is not None, preferred=body.skill)
    factory = job_session_factory(user_id)

    async def runner(job):
        return await run_assistant(
            job, session_factory=factory, chapter_id=chapter_id, ai_service=user_ai_service,
            message=body.message, skill=skill, selection=selection,
        )

    try:
        job = await ai_jobs.start(
            kind="chapter_assistant",
            title=f"智能助笔·{SKILL_LABELS[skill]}：第 {chapter.chapter_number} 章《{chapter.title}》",
            user_id=user_id,
            project_id=chapter.project_id,
            runner=runner,
            scope=f"assistant:{chapter_id}",
            cancel_message="已停止；没有产生候选稿，正文未改动",
            meta={"chapter_id": chapter_id, "skill": skill},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)
