"""桥段 API（工程化桥段流水线）。

端点：
- GET    /api/projects/{project_id}/bridges/plan-preview  槽位表预览（纯计算，不写库）
- POST   /api/projects/{project_id}/bridges/plan          建骨架：N 个 draft 桥段（无 LLM）
- DELETE /api/projects/{project_id}/bridges               重置骨架（已展开 → 409）
- POST   /api/projects/{project_id}/bridges/fill-stream   SSE：启动后台填充任务并从头续尾（重连 / 停止走 /api/ai-jobs/*）
- GET    /api/projects/{project_id}/bridges               列表
- GET    /api/bridges/{bridge_id}                         详情
- PATCH  /api/bridges/{bridge_id}                         更新（修改 4 章卡片内容）
- DELETE /api/bridges/{bridge_id}                         删除
- POST   /api/bridges/{bridge_id}/expand                  展开为第 4(n-1)+1…4n 章
- POST   /api/projects/{project_id}/bridges/expand-all    按序批量展开 ready 桥段

前置不满足 → 400；状态冲突 → 409。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.models.project import Project
from app.services.ai_jobs import job_session_factory
from app.services.ai_service import AIService
from app.services.bridge_fill_jobs import start_bridge_fill
from app.services.bridge_planning_service import BridgePlanningService, bridge_to_dict
from app.services.bridge_slot_planner import (
    BridgePlanningConflictError,
    BridgePlanningPreconditionError,
)


def _raise_http(exc: Exception) -> None:
    """服务层异常 → HTTP：前置条件 400，状态冲突 409，其余原样抛出。"""
    if isinstance(exc, BridgePlanningPreconditionError):
        raise HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, BridgePlanningConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise exc


async def verify_project_access(
    project_id: str, user_id: str | None, db: AsyncSession
) -> Project:
    """统一的项目访问验证（参考其他 api 模块的同名函数）。"""
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问此项目")
    return project

logger = logging.getLogger(__name__)

router = APIRouter(tags=["桥段四章 K2"])


# ============================================================
# Schemas
# ============================================================

class FillBridgesRequest(BaseModel):
    """填充桥段内容请求。"""
    model: Optional[str] = Field(default=None, description="覆盖默认模型")
    beat_index: Optional[int] = Field(default=None, ge=1, description="只填充该主线节点的 draft 桥段")


class ExpandBridgeRequest(BaseModel):
    """展开桥段请求。章号由桥段序号决定（第 4(n-1)+1…4n 章），不接受外部指定。"""
    model: Optional[str] = Field(default=None, description="覆盖默认模型")


class ExpandAllRequest(BaseModel):
    """批量展开项目下所有 ready 桥段为章纲（按 bridge_number 顺序，首个失败即停止）。"""
    model: Optional[str] = Field(default=None, description="覆盖默认模型")


class UpdateBridgeRequest(BaseModel):
    title: Optional[str] = None
    goal: Optional[str] = None
    showoff_point: Optional[str] = None
    golden_finger_usage: Optional[str] = None
    c1_intro: Optional[str] = None
    c2_build: Optional[str] = None
    c3_payoff: Optional[str] = None
    c4_aftermath: Optional[str] = None
    next_bridge_hook: Optional[str] = None
    status: Optional[str] = None


class BridgeResponse(BaseModel):
    id: str
    project_id: str
    bridge_number: int
    title: str
    goal: str
    showoff_point: str
    golden_finger_usage: Optional[str]
    c1_intro: Optional[str]
    c2_build: Optional[str]
    c3_payoff: Optional[str]
    c4_aftermath: Optional[str]
    next_bridge_hook: Optional[str]
    status: str
    order_index: Optional[int]
    # 桥段 ↔ 主线节点绑定字段（由 bridge_slot_planner 写入）
    plot_line_id: Optional[str] = None
    beat_index: Optional[int] = None
    beat_coverage_start: Optional[float] = None
    beat_coverage_end: Optional[float] = None
    # 副线任务（bridge_to_dict 解析 JSON）+ 确定性章号范围
    secondary_beats: list[dict] = []
    chapter_start: int
    chapter_end: int
    # 生成溯源（填充时写入；draft / 旧数据为 None）
    generation_meta: Optional[dict[str, Any]] = None
    template: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 依赖
# ============================================================

def get_bridge_service(
    user_ai: AIService = Depends(get_user_ai_service),
) -> BridgePlanningService:
    """复用全局 `get_user_ai_service`：按当前登录用户的 Settings.api_provider /
    api_key / api_base_url / llm_model 创建 AIService，与 wizard_stream /
    chapter_outline 等其他生成入口的依赖注入方式保持一致。

    历史 bug：旧实现从 `request.state.user_ai_service` 取（中间件并未注入此字段），
    永远走 `AIService()` fallback → 用环境变量默认 provider/key 创建 → 用户在
    弹窗里选 Anthropic 模型时撞 "OpenAI 客户端未初始化"。
    """
    return BridgePlanningService(ai_service=user_ai)


# ============================================================
# Routes
# ============================================================

@router.get("/projects/{project_id}/bridges/plan-preview")
async def preview_bridge_plan_endpoint(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """纯计算：返回主线节点 → 桥段槽位表，不写库。"""
    await verify_project_access(project_id, getattr(request.state, "user_id", None), db)
    try:
        plan = await service.preview_plan(db, project_id)
    except (BridgePlanningPreconditionError, BridgePlanningConflictError) as exc:
        _raise_http(exc)
    return plan.to_dict()


@router.post("/projects/{project_id}/bridges/plan", response_model=list[BridgeResponse])
async def plan_bridges_endpoint(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """建骨架：创建 N 个 draft 桥段（无 LLM）。已存在 → 409。"""
    await verify_project_access(project_id, getattr(request.state, "user_id", None), db)
    try:
        bridges = await service.plan_bridges(db, project_id)
    except (BridgePlanningPreconditionError, BridgePlanningConflictError) as exc:
        _raise_http(exc)
    return [BridgeResponse(**bridge_to_dict(b)) for b in bridges]


@router.delete("/projects/{project_id}/bridges")
async def reset_bridges_endpoint(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """重置骨架：删除全部桥段。已展开 → 409。"""
    await verify_project_access(project_id, getattr(request.state, "user_id", None), db)
    try:
        deleted = await service.reset_bridges(db, project_id)
    except BridgePlanningConflictError as exc:
        _raise_http(exc)
    return {"deleted": deleted}


@router.post("/projects/{project_id}/bridges/fill-stream")
async def fill_bridges_stream_endpoint(
    project_id: str,
    payload: FillBridgesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """SSE：启动后台填充任务并从头流式输出其事件。

    任务寿命独立于本连接：关弹窗 / 刷新 / 断网不会终止填充；重连与停止走通用
    GET /api/ai-jobs、POST /api/ai-jobs/{id}/events、DELETE /api/ai-jobs/{id}。已有任务在跑 → 409。
    事件翻译（服务层 → progress/stage/meta/bridges/reference/partial/thinking/result/done/error）在
    bridge_fill_jobs 的 runner 里完成。
    """
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)
    try:
        job = await start_bridge_fill(
            project_id=project_id,
            user_id=user_id,
            ai_service=service.ai_service,
            model=payload.model,
            beat_index=payload.beat_index,
            session_factory=job_session_factory(user_id),
        )
    except BridgePlanningConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.get("/projects/{project_id}/bridges", response_model=list[BridgeResponse])
async def list_bridges_endpoint(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """列出项目下所有桥段（按 order_index）。"""
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)

    bridges = await service.list_bridges(db, project_id)
    return [BridgeResponse(**bridge_to_dict(b)) for b in bridges]


@router.get("/bridges/{bridge_id}", response_model=BridgeResponse)
async def get_bridge_endpoint(
    bridge_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    bridge = await service.get_bridge(db, bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail="桥段不存在")

    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(bridge.project_id, user_id, db)
    return BridgeResponse(**bridge_to_dict(bridge))


@router.patch("/bridges/{bridge_id}", response_model=BridgeResponse)
async def update_bridge_endpoint(
    bridge_id: str,
    payload: UpdateBridgeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """用户手工编辑桥段卡片内容。"""
    bridge = await service.get_bridge(db, bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail="桥段不存在")

    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(bridge.project_id, user_id, db)

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            setattr(bridge, key, value)
    await db.commit()
    await db.refresh(bridge)
    return BridgeResponse(**bridge_to_dict(bridge))


@router.delete("/bridges/{bridge_id}")
async def delete_bridge_endpoint(
    bridge_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    bridge = await service.get_bridge(db, bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail="桥段不存在")

    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(bridge.project_id, user_id, db)

    ok = await service.delete_bridge(db, bridge_id)
    return {"success": ok}


@router.post("/bridges/{bridge_id}/expand")
async def expand_bridge_endpoint(
    bridge_id: str,
    payload: ExpandBridgeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """把一个 ready 桥段展开为第 4(n-1)+1…4n 章（自动赋 bridge_id + bridge_position，回写节点覆盖账本）。"""
    bridge = await service.get_bridge(db, bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail="桥段不存在")

    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(bridge.project_id, user_id, db)

    # payload.model 为 None 时，由 service 内部回退到 user_ai_service.default_model
    try:
        chapters = await service.expand_bridge_to_chapters(db, bridge_id=bridge_id, model_name=payload.model)
    except (BridgePlanningPreconditionError, BridgePlanningConflictError) as exc:
        _raise_http(exc)
    except Exception as exc:
        logger.error("[plot_bridges] 展开失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"桥段展开失败: {exc}")

    return {
        "success": True,
        "bridge_id": bridge_id,
        "chapter_count": len(chapters),
        "chapter_ids": [c.id for c in chapters],
    }


@router.post("/projects/{project_id}/bridges/expand-all")
async def expand_all_bridges_endpoint(
    project_id: str,
    payload: ExpandAllRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: BridgePlanningService = Depends(get_bridge_service),
):
    """批量展开项目下所有 status='ready' 的桥段（按 bridge_number 顺序）。

    首个失败即停止：后续桥段依赖前序 completed。返回成功/失败明细。
    """
    user_id = getattr(request.state, "user_id", None)
    await verify_project_access(project_id, user_id, db)

    try:
        result = await service.expand_all_ready_bridges(db, project_id=project_id, model_name=payload.model)
    except Exception as exc:
        logger.error("[plot_bridges] 批量展开失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量展开失败: {exc}")

    return {"success": True, **result}
