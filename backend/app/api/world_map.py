"""世界地图接口：读取 / 布局保存（版本号防覆盖）/ 地点增删改与档案 / 登记为世界规则 / AI 布局候选（生成、采用、丢弃）/ 底图设置。"""
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_request_project
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.models.world_rule import WorldRule
from app.schemas.world_map import (
    CandidateAdoptRequest, LayoutSaveRequest, LocationCreate, LocationUpdate, MapSettingsUpdate, RegisterRulesRequest,
)
from app.services import world_map_service as wms
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService

router = APIRouter(prefix="/projects/{project_id}/world-map", tags=["世界地图"])


def _http(exc: wms.WorldMapError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _vectorize(rules: Iterable[Optional[WorldRule]]) -> None:
    """规则改名 / 新登记后更新向量（用时才导入，免得加载本模块就拉起向量模型）。"""
    from app.services.world_rule_service import world_rule_service

    for rule in rules:
        if rule is not None:
            await world_rule_service.upsert_rule_to_vector_db(rule)


@router.get("", summary="地图（底图参数 + 地点 + 故事地点原文）")
async def get_world_map(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        if await wms.sync_rule_locations(db, project_id):  # 世界规则「地图位置」兜底补齐
            await db.commit()
    except IntegrityError:
        await db.rollback()  # 同时打开的另一个请求已经补齐了
    return await wms.build_view(db, project_id)


@router.put("/layout", summary="保存地点坐标（带版本号，过期 409）")
async def save_world_map_layout(project_id: str, body: LayoutSaveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        await wms.save_layout(db, project_id, body.expected_revision, body.markers)
    except wms.WorldMapError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    return await wms.build_view(db, project_id)


@router.post("/locations", summary="新建地点")
async def create_world_map_location(project_id: str, body: LocationCreate, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        loc = await wms.create_location(db, project_id, body)
    except wms.WorldMapError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    await db.refresh(loc)
    return wms.location_view(loc)


@router.post("/locations/register-rules", summary="把未登记的地点登记为世界规则「地图位置」（不传 ID = 全部未登记的）")
async def register_world_map_rules(
    project_id: str, body: RegisterRulesRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    await verify_request_project(request, project_id, db)
    rules = await wms.register_rules(db, project_id, body.location_ids)
    await db.commit()
    await _vectorize(rules)
    return await wms.build_view(db, project_id)


@router.get("/locations/{location_id}", summary="地点档案（按原文地点精确匹配的出处，按章节顺序）")
async def get_world_map_location(project_id: str, location_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        loc = await wms.get_location(db, project_id, location_id)
    except wms.WorldMapError as exc:
        raise _http(exc) from exc
    return await wms.dossier(db, loc)


@router.patch("/locations/{location_id}", summary="修改地点（名称 / 坐标 / 类型 / 区域 / 档案 / 绑定的原文地点）")
async def update_world_map_location(
    project_id: str, location_id: str, body: LocationUpdate, request: Request, db: AsyncSession = Depends(get_db),
):
    await verify_request_project(request, project_id, db)
    try:
        loc = await wms.update_location(db, await wms.get_location(db, project_id, location_id), body)
    except wms.WorldMapError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    await db.refresh(loc)
    if body.name is not None and loc.rule_id:  # 规则地点改名：世界规则已跟着改名，重新向量化
        await _vectorize([await db.get(WorldRule, loc.rule_id)])
    return wms.location_view(loc)


@router.delete("/locations/{location_id}", summary="删除地点（只删地图标注，不动故事内容；世界规则里的地点要到规则页删）")
async def delete_world_map_location(project_id: str, location_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    try:
        await wms.delete_location(db, await wms.get_location(db, project_id, location_id))
    except wms.WorldMapError as exc:
        raise _http(exc) from exc
    await db.commit()
    return {"deleted": location_id}


@router.put("/settings", summary="换底图种子 / 风格")
async def update_world_map_settings(project_id: str, body: MapSettingsUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    await wms.update_settings(db, project_id, body.seed, body.style)
    await db.commit()
    return await wms.build_view(db, project_id)


@router.post("/generate-stream", summary="AI 生成布局候选（后台任务 + SSE；采用前不写入地图）")
async def generate_world_map_stream(
    project_id: str, request: Request, db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    await verify_request_project(request, project_id, db)
    user_id = getattr(request.state, "user_id", None)
    factory = job_session_factory(user_id)

    async def runner(job):
        return await wms.generate_candidate(job, session_factory=factory, project_id=project_id, ai_service=user_ai_service)

    try:
        job = await ai_jobs.start(
            kind="world_map_generate",
            title="AI 设计世界地图布局",
            user_id=user_id,
            project_id=project_id,
            runner=runner,
            cancel_message="已停止；没有生成地图候选",
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.get("/candidate", summary="查看待采用的布局候选")
async def get_world_map_candidate(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    return {"candidate": wms.candidate_of(await wms.load_map(db, project_id))}


@router.post("/candidate/adopt", summary="采用布局候选（默认不挪动已放好的地点）")
async def adopt_world_map_candidate(
    project_id: str, body: CandidateAdoptRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    await verify_request_project(request, project_id, db)
    try:
        await wms.adopt_candidate(db, project_id, body.replace_positions)
    except wms.WorldMapError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await wms.build_view(db, project_id)


@router.post("/candidate/discard", summary="丢弃布局候选")
async def discard_world_map_candidate(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    await wms.discard_candidate(db, project_id)
    await db.commit()
    return await wms.build_view(db, project_id)
