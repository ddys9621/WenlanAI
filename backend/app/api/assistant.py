"""全局智能助笔接口（参考岚笺 GlobalAssistantHost）：对话 / 发送前核对 / 作者回答 / 任务记录 / 字段候选 / 核对清单 /
团队与上下文设置。

一个项目一段可续接的对话；每条要求在后台任务里运行（SSE 推进度、处理记录、流式回复、上下文用量）；修改只产生候选。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_request_project
from app.api.settings import get_user_ai_service, load_or_create_settings
from app.database import get_db
from app.models.assistant import (
    AssistantEntityCandidate, AssistantFieldCandidate, AssistantMessage, AssistantRun, AssistantSession,
    AssistantTeamSetting,
)
from app.schemas.assistant import (
    AssistantAnswerRequest, AssistantContextRequest, AssistantPage, AssistantSendRequest, AssistantTeamModelRequest,
)
from app.services import assistant_agent_service as agent
from app.services import assistant_candidate_service as cands
from app.services import assistant_entity_candidate_service as entity_cands
from app.services import assistant_context as budgeting
from app.services import cocreation_team as team
from app.services.project_ai_preference import load_project_ai_preference, resolve_override_values
from app.services.story_progress import progress_snapshot
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.assistant_checks_service import project_checks as compute_checks
from app.services.assistant_fields import FieldError
from app.services.assistant_entity_candidate_service import EntityError
from app.services.assistant_persistence import WRITE_ATTEMPTS

router = APIRouter(prefix="/projects/{project_id}/assistant", tags=["智能助笔"])

BUSY_MESSAGE = "智能助笔正在处理上一条要求，等它完成或先停止再发"


def _scope(project_id: str) -> str:
    return f"assistant-run:{project_id}"


INTERRUPTED_MESSAGE = "上次处理被中断（服务重启或任务异常），没有写入回复；可以重新发送"


def _project_interrupted(project_id: str, runs: list[dict]) -> list[dict]:
    """库里还是 running、但本项目没有在跑的助笔任务：只在读取时显示为「已中断」，不在读路径写库、也不自动重跑。"""
    if ai_jobs.current(_scope(project_id)) is not None:
        return runs
    return [{**r, "status": "interrupted", "message": INTERRUPTED_MESSAGE} if r.get("status") == "running" else r for r in runs]


def _session_payload(project_id: str, view: dict) -> dict:
    active = view.get("active_run")
    if active:
        [projected] = _project_interrupted(project_id, [active])
        view = {**view, "active_run": None if projected["status"] == "interrupted" else projected}
    return view


def _start_job(*, project_id: str, user_id: str, run: AssistantRun, ai: AIService, title: str):
    factory = job_session_factory(user_id)

    async def runner(job):
        return await agent.run_agent(job, session_factory=factory, run_id=run.id, ai_service=ai)

    return ai_jobs.start(
        kind="assistant_run", title=title, user_id=user_id, project_id=project_id, runner=runner,
        scope=_scope(project_id), cancel_message="已停止；本轮没有写入任何内容",
        meta={"run_id": run.id, "session_id": run.session_id},
    )


@router.get("/session", summary="当前对话（消息、进行中的运行、修改候选）")
async def get_session(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return _session_payload(project_id, await agent.build_session_view(db, await agent.current_session(db, project_id)))


@router.post("/sessions", summary="开始新对话（当前对话归档，可在任务记录里回看）")
async def new_session(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    if ai_jobs.current(_scope(project_id)) is not None:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE)
    session = await agent.new_session(db, project_id, getattr(request.state, "user_id", None))
    await db.commit()
    return await agent.build_session_view(db, session)


@router.get("/sessions", summary="对话记录")
async def list_sessions(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    counts = dict((await db.execute(
        select(AssistantMessage.session_id, func.count(AssistantMessage.id))
        .where(AssistantMessage.project_id == project_id).group_by(AssistantMessage.session_id)
    )).all())
    rows = (await db.execute(
        select(AssistantSession).where(AssistantSession.project_id == project_id)
        .order_by(AssistantSession.updated_at.desc()).limit(100)
    )).scalars().all()
    return {"items": [{**agent.session_view(s), "message_count": counts.get(s.id, 0)} for s in rows]}


@router.get("/sessions/{session_id}", summary="回看某段对话（只读）")
async def get_session_by_id(project_id: str, session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    session = await db.get(AssistantSession, session_id)
    if session is None or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="对话不存在")
    return _session_payload(project_id, await agent.build_session_view(db, session))


@router.post("/messages/stream", summary="发一条要求给智能助笔（后台任务 + SSE）")
async def send_message_stream(
    project_id: str, body: AssistantSendRequest, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    await verify_request_project(request, project_id, db)
    if ai_jobs.current(_scope(project_id)) is not None:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE)
    user_id = getattr(request.state, "user_id", None)
    run = await agent.start_run(db, project_id=project_id, user_id=user_id, message=body.message,
                                page=body.page.model_dump())
    try:
        job = await _start_job(project_id=project_id, user_id=user_id, run=run, ai=user_ai_service,
                               title=f"智能助笔：{body.message.strip()[:24]}")
    except AIJobConflictError as exc:
        await db.execute(update(AssistantRun).where(AssistantRun.id == run.id).values(status="failed", message=str(exc)[:500]))
        await db.commit()
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.post("/runs/{run_id}/answer/stream", summary="回答助笔的提问并继续（后台任务 + SSE）")
async def answer_stream(
    project_id: str, run_id: str, body: AssistantAnswerRequest, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    await verify_request_project(request, project_id, db)
    run = await db.get(AssistantRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="这轮处理不存在")
    if ai_jobs.current(_scope(project_id)) is not None:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE)
    try:
        await agent.submit_answers(db, run, [a.model_dump() for a in body.answers])
    except agent.AssistantStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user_id = getattr(request.state, "user_id", None)
    try:
        job = await _start_job(project_id=project_id, user_id=user_id, run=run, ai=user_ai_service,
                               title=f"智能助笔：{run.goal.strip()[:24]}（继续）")
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


async def _project_defaults(db: AsyncSession, project_id: str, request: Request) -> tuple[Optional[str], Optional[int]]:
    """项目实际用的模型与 max_tokens（全局设置 + 本项目 AI 偏好，与 get_user_ai_service 同一来源，但不建 AI 客户端）。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None, None
    values = resolve_override_values(await load_or_create_settings(db, user_id),
                                     await load_project_ai_preference(db, project_id, user_id))
    return values.get("llm_model"), values.get("max_tokens")


@router.post("/preview", summary="发送前核对：本次会发给模型的内容与上下文用量（不调用模型）")
async def preview_context(project_id: str, body: AssistantSendRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    model, max_tokens = await _project_defaults(db, project_id, request)
    return await agent.preview(db, project_id, body.message, body.page.model_dump(), default_model=model,
                               max_tokens=max_tokens)


@router.post("/context/usage", summary="上下文用量：下一条要求开跑时大约占多少（估算，不调用模型）")
async def context_usage(project_id: str, body: AssistantPage, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    model, max_tokens = await _project_defaults(db, project_id, request)
    return await agent.estimate_usage(db, project_id, body.model_dump(), default_model=model, max_tokens=max_tokens)


@router.get("/runs", summary="任务记录（进行中 / 等待回答的排在前面）")
async def list_runs(project_id: str, request: Request, db: AsyncSession = Depends(get_db), limit: int = 50):
    await verify_request_project(request, project_id, db)
    limit = max(1, min(int(limit or 50), 200))
    rows = (await db.execute(
        select(AssistantRun).where(AssistantRun.project_id == project_id)
        .order_by(AssistantRun.updated_at.desc()).limit(limit)
    )).scalars().all()
    items = _project_interrupted(project_id, [agent.run_view(r) for r in rows])
    return {"items": sorted(items, key=lambda r: 0 if r["status"] in agent.ACTIVE else 1)}


async def _candidate(db: AsyncSession, project_id: str, candidate_id: str) -> AssistantFieldCandidate:
    candidate = (await db.execute(
        select(AssistantFieldCandidate).where(AssistantFieldCandidate.id == candidate_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if candidate is None or candidate.project_id != project_id:
        raise HTTPException(status_code=404, detail="修改候选不存在")
    return candidate


async def _decide(project_id: str, candidate_id: str, request: Request, db: AsyncSession, action, done: str) -> dict:
    """应用 / 撤销 / 放弃：提交后读回核对（所有会话共用一个 SQLite 连接，别的请求收尾时的回滚可能冲掉这次写入）。"""
    await verify_request_project(request, project_id, db)
    for attempt in range(WRITE_ATTEMPTS):
        candidate = await _candidate(db, project_id, candidate_id)
        try:
            await action(db, candidate)
        except FieldError as exc:
            await db.rollback()
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        await db.commit()
        if await db.scalar(select(AssistantFieldCandidate.status).where(AssistantFieldCandidate.id == candidate_id)) == done:
            return cands.candidate_view(candidate)
        db.expire_all()
    raise HTTPException(status_code=503, detail="这次修改没能写进数据库（被同时进行的其他操作打断），请重试")


@router.get("/candidates/{candidate_id}", summary="查看修改候选")
async def get_field_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return cands.candidate_view(await _candidate(db, project_id, candidate_id))


@router.post("/candidates/{candidate_id}/apply", summary="应用修改候选（这项内容在生成后被改过则拒绝）")
async def apply_field_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _decide(project_id, candidate_id, request, db, cands.apply_candidate, "applied")


@router.post("/candidates/{candidate_id}/undo", summary="撤销已应用的修改（应用后又被改过则拒绝）")
async def undo_field_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _decide(project_id, candidate_id, request, db, cands.undo_candidate, "undone")


@router.post("/candidates/{candidate_id}/reject", summary="不用这份候选")
async def reject_field_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _decide(project_id, candidate_id, request, db, cands.reject_candidate, "rejected")


async def _entity_candidate(db: AsyncSession, project_id: str, candidate_id: str) -> AssistantEntityCandidate:
    candidate = (await db.execute(
        select(AssistantEntityCandidate).where(AssistantEntityCandidate.id == candidate_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if candidate is None or candidate.project_id != project_id:
        raise HTTPException(status_code=404, detail="新建候选不存在")
    return candidate


async def _decide_entity(project_id: str, candidate_id: str, request: Request, db: AsyncSession, action, done: str) -> dict:
    """应用 / 放弃新建候选：提交后读回核对（同一 SQLite 连接，别的请求收尾时的回滚可能冲掉这次写入）。"""
    await verify_request_project(request, project_id, db)
    for _attempt in range(WRITE_ATTEMPTS):
        candidate = await _entity_candidate(db, project_id, candidate_id)
        try:
            await action(db, candidate)
        except EntityError as exc:
            await db.rollback()
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        view = entity_cands.entity_candidate_view(candidate)
        await db.commit()
        if await db.scalar(select(AssistantEntityCandidate.status).where(AssistantEntityCandidate.id == candidate_id)) == done:
            return view
        db.expire_all()
    raise HTTPException(status_code=503, detail="这次操作没能写进数据库（被同时进行的其他操作打断），请重试")


@router.get("/entity-candidates/{candidate_id}", summary="查看新建候选")
async def get_entity_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return entity_cands.entity_candidate_view(await _entity_candidate(db, project_id, candidate_id))


@router.post("/entity-candidates/{candidate_id}/apply", summary="应用新建候选（真正建档）")
async def apply_entity_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _decide_entity(project_id, candidate_id, request, db, entity_cands.apply_entity_candidate, "applied")


@router.post("/entity-candidates/{candidate_id}/reject", summary="不用这份新建候选")
async def reject_entity_candidate(project_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _decide_entity(project_id, candidate_id, request, db, entity_cands.reject_entity_candidate, "rejected")


@router.get("/checks", summary="核对清单：本书现在需要注意的事项")
async def project_checks(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return await compute_checks(db, project_id)


async def _team_payload(db: AsyncSession, project_id: str, request: Request) -> dict:
    models = await agent.team_models(db, project_id)
    setting = await agent.context_setting(db, project_id)
    default_model, _max_tokens = await _project_defaults(db, project_id, request)

    def window(member_id: str, value: Optional[int] = setting) -> budgeting.Window:
        return budgeting.resolve_window(value, models.get(member_id) or default_model)

    editor, auto = window(team.DEFAULT_MEMBER), window(team.DEFAULT_MEMBER, None)
    return {
        "members": [{**team.member_view(m, models.get(m.id)), "context_window": window(m.id).tokens} for m in team.MEMBERS],
        "starters": list(team.STARTERS),
        "context": {
            "setting": setting, "window": editor.tokens, "source": editor.source, "model": editor.model,
            "auto": auto.tokens, "auto_source": auto.source, "presets": list(budgeting.PRESETS),
            "min": budgeting.MIN_WINDOW, "max": budgeting.MAX_WINDOW,
        },
    }


@router.get("/team", summary="共创室：成员（职责 / 模型 / 上下文上限）、上下文设置与开场引导")
async def get_team(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return await _team_payload(db, project_id, request)


@router.put("/context", summary="共创室：设置上下文上限（token；空 = 自动按成员用的模型查窗口）")
async def set_context_window(project_id: str, body: AssistantContextRequest, request: Request,
                             db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    await agent.save_context_setting(db, project_id, body.context_window)
    return await _team_payload(db, project_id, request)


@router.put("/team/{member_id}", summary="共创室：设置某位成员用的模型（空 = 跟随项目模型）")
async def set_member_model(project_id: str, member_id: str, body: AssistantTeamModelRequest, request: Request,
                           db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    if member_id not in {m.id for m in team.MEMBERS}:
        raise HTTPException(status_code=404, detail="没有这位成员")
    row = (await db.execute(select(AssistantTeamSetting).where(
        AssistantTeamSetting.project_id == project_id, AssistantTeamSetting.member_id == member_id,
    ))).scalars().first()
    model = (body.model or "").strip() or None
    if row is None:
        db.add(AssistantTeamSetting(project_id=project_id, member_id=member_id, model=model))
    else:
        row.model = model
    await db.commit()
    return await _team_payload(db, project_id, request)


@router.get("/progress", summary="创作进度：总纲 / 卷纲 / 章纲 / 正文各到哪一步与建议的下一步")
async def story_progress(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return await progress_snapshot(db, project_id)
