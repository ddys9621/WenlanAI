"""卷纲接口：总纲 → 卷纲（剧情单元 + 线索编排）→ 章纲。

- GET    /api/projects/{project_id}/volumes                 列表（含每卷章纲数）
- POST   /api/projects/{project_id}/volumes                 手建一卷
- POST   /api/projects/{project_id}/volumes/plan-stream     SSE：按总纲分卷（已有章纲的卷保留）
- POST   /api/projects/{project_id}/volumes/confirm-all     一键确认全部草拟 / 上游已改的卷纲
- PUT    /api/volumes/{volume_id}                           修改（内容变了 → 本卷章纲标上游已改）
- POST   /api/volumes/{volume_id}/confirm                   确认
- DELETE /api/volumes/{volume_id}                           删除（已有章纲 → 409）
- POST   /api/volumes/{volume_id}/detail-stream             SSE：细化为剧情单元
- POST   /api/volumes/{volume_id}/units/{unit_index}/outlines-stream  SSE：剧情单元展开为章纲
重连 / 停止走 /api/ai-jobs/*。前置不满足 → 400，冲突 → 409。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.deps import load_owned, request_user_id, verify_request_project
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.models.volume import Volume
from app.schemas.volume import VolumeFields, VolumeGenerateRequest, VolumePlanRequest
from app.services import volume_service as vs
from app.services.ai_jobs import job_session_factory
from app.services.ai_service import AIService
from app.services.volume_jobs import start_volume_job

router = APIRouter(tags=["卷纲"])


def _http(exc: Exception) -> HTTPException:
    status = 409 if isinstance(exc, vs.VolumeConflictError) else 400
    return HTTPException(status_code=status, detail=str(exc))


def _dump(body: VolumeFields) -> dict:
    data = body.model_dump(exclude_unset=True)
    if body.units is not None:
        data["units"] = [u.model_dump() for u in body.units]
    return data


async def _volume_view(db: AsyncSession, volume: Volume) -> dict:
    return vs.volume_to_dict(volume, (await vs.outline_counts(db, volume.project_id)).get(volume.id, 0))


@router.get("/projects/{project_id}/volumes", summary="卷纲列表")
async def list_volumes(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    project = await verify_request_project(request, project_id, db)
    counts = await vs.outline_counts(db, project_id)
    return {
        "items": [vs.volume_to_dict(v, counts.get(v.id, 0)) for v in await vs.list_volumes(db, project_id)],
        "chapter_count": project.chapter_count,
    }


@router.post("/projects/{project_id}/volumes", summary="手建一卷（默认接在最后一卷之后）")
async def create_volume(project_id: str, body: VolumeFields, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        volume = await vs.create_volume(db, project_id, _dump(body))
    except (vs.VolumePlanningError, vs.VolumeConflictError) as exc:
        raise _http(exc)
    await db.commit()
    await db.refresh(volume)
    return await _volume_view(db, volume)


@router.post("/projects/{project_id}/volumes/plan-stream", summary="按总纲分卷（后台任务 + SSE）")
async def plan_volumes(
    project_id: str, body: VolumePlanRequest, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    await verify_request_project(request, project_id, db)
    user_id = request_user_id(request)
    try:
        job = await start_volume_job(
            action="skeleton", project_id=project_id, user_id=user_id, ai_service=user_ai_service,
            session_factory=job_session_factory(user_id), total_chapters=body.total_chapters,
            volume_count=body.volume_count, instruction=body.instruction, model=body.model,
        )
    except vs.VolumeConflictError as exc:
        raise _http(exc)
    return job_sse_response(job)


@router.post("/projects/{project_id}/volumes/confirm-all", summary="一键确认全部草拟 / 上游已改的卷纲")
async def confirm_all(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    rows = (await db.execute(select(Volume).where(
        Volume.project_id == project_id, or_(Volume.review_status == vs.DRAFT, Volume.upstream_stale.is_(True)),
    ))).scalars().all()
    for volume in rows:
        vs.confirm_volume(volume)
    await db.commit()
    return {"confirmed": len(rows)}


@router.put("/volumes/{volume_id}", summary="修改卷纲（保存 ≠ 确认；内容变了 → 本卷章纲标上游已改）")
async def update_volume(volume_id: str, body: VolumeFields, request: Request, db: AsyncSession = Depends(get_db)):
    volume = await load_owned(db, request, Volume, volume_id, "卷纲不存在")
    try:
        await vs.update_volume(db, volume, _dump(body))
    except vs.VolumePlanningError as exc:
        raise _http(exc)
    await db.commit()
    await db.refresh(volume)
    return await _volume_view(db, volume)


@router.post("/volumes/{volume_id}/confirm", summary="确认卷纲")
async def confirm_volume(volume_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    volume = await load_owned(db, request, Volume, volume_id, "卷纲不存在")
    vs.confirm_volume(volume)
    await db.commit()
    await db.refresh(volume)
    return await _volume_view(db, volume)


@router.delete("/volumes/{volume_id}", summary="删除卷纲（本卷已有章纲 → 409）")
async def delete_volume(volume_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    volume = await load_owned(db, request, Volume, volume_id, "卷纲不存在")
    try:
        await vs.delete_volume(db, volume)
    except vs.VolumeConflictError as exc:
        raise _http(exc)
    await db.commit()
    return {"success": True}


async def _start_for_volume(request: Request, db: AsyncSession, volume_id: str, ai: AIService, body: VolumeGenerateRequest,
                            action: str, unit_index: int | None = None):
    volume = await load_owned(db, request, Volume, volume_id, "卷纲不存在")
    user_id = request_user_id(request)
    suffix = f"：第{volume.volume_number}卷《{volume.title}》" + (f" 单元 {unit_index}" if unit_index else "")
    try:
        job = await start_volume_job(
            action=action, project_id=volume.project_id, user_id=user_id, ai_service=ai,
            session_factory=job_session_factory(user_id), volume_id=volume.id, unit_index=unit_index,
            instruction=body.instruction, model=body.model, title_suffix=suffix,
        )
    except vs.VolumeConflictError as exc:
        raise _http(exc)
    return job_sse_response(job)


@router.post("/volumes/{volume_id}/detail-stream", summary="细化卷纲为剧情单元（后台任务 + SSE）")
async def detail_volume(
    volume_id: str, body: VolumeGenerateRequest, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    return await _start_for_volume(request, db, volume_id, user_ai_service, body, "detail")


@router.post("/volumes/{volume_id}/units/{unit_index}/outlines-stream", summary="剧情单元展开为章纲（后台任务 + SSE）")
async def unit_outlines(
    volume_id: str, unit_index: int, body: VolumeGenerateRequest, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    return await _start_for_volume(request, db, volume_id, user_ai_service, body, "outlines", unit_index)
