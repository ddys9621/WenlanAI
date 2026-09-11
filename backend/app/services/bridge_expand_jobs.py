"""桥段展开后台任务（单个 / 批量），跑在 ai_jobs 通用管理器上。

- 单个：一个 stage（"展开桥段 n《title》→ 第 a-b 章"）+ 一条 bridges 事件（页面翻卡）+ result
- 批量：复用 BridgePlanningService.expand_all_ready_bridges（每桥段 stage 在服务层），on_bridge_done 回调里发
  progress + bridges 事件；首个失败即停止，result 是服务层的汇总字典
同一项目单个与批量共用互斥键（章号连续分配，不能并行展开）。中断 = 已展开的桥段已 completed，其余保持 ready。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.services.ai_jobs import AIJob, AIJobConflictError, AIJobManager, Runner, ai_jobs
from app.services.bridge_planning_service import BridgePlanningService, bridge_to_dict
from app.services.bridge_slot_planner import BridgePlanningConflictError, chapter_range
from app.services.generation_trace import stage_scope

logger = logging.getLogger(__name__)

KIND_EXPAND = "bridge_expand"
CANCELLED_MESSAGE = "已停止展开；已展开的桥段已保存，未展开的保持 ready"

ServiceFactory = Callable[[Any], Any]


def expand_scope(project_id: str) -> str:
    return f"{KIND_EXPAND}:{project_id}"


def _default_service(ai: Any) -> BridgePlanningService:
    return BridgePlanningService(ai_service=ai)


def _label(bridge: Any) -> str:
    c_start, c_end = chapter_range(bridge.bridge_number)
    return f"展开桥段 {bridge.bridge_number}《{bridge.title or ''}》→ 第 {c_start}-{c_end} 章"


def make_expand_one_runner(
    *,
    ai_service: Any,
    session_factory: Callable[[], Any],
    bridge_id: str,
    model: Optional[str],
    service_factory: Optional[ServiceFactory] = None,
) -> Runner:
    make_service = service_factory or _default_service

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            service = make_service(ai_service)
            bridge = await service.get_bridge(db, bridge_id)
            if bridge is None:
                raise ValueError("桥段不存在")
            job.progress(_label(bridge), 5)
            async with stage_scope(f"bridge-{bridge.bridge_number}", _label(bridge)) as st:
                chapters = await service.expand_bridge_to_chapters(db, bridge_id=bridge_id, model_name=model)
                st.note(chapters=len(chapters))
            job.publish({"type": "bridges", "bridges": [bridge_to_dict(await service.get_bridge(db, bridge_id))]})
            return {
                "success": True,
                "bridge_id": bridge_id,
                "chapter_count": len(chapters),
                "chapter_ids": [c.id for c in chapters],
            }

    return runner


def make_expand_all_runner(
    *,
    ai_service: Any,
    session_factory: Callable[[], Any],
    model: Optional[str],
    service_factory: Optional[ServiceFactory] = None,
) -> Runner:
    make_service = service_factory or _default_service

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            service = make_service(ai_service)
            ready = [b for b in await service.list_bridges(db, job.project_id) if b.status == "ready"]
            total = len(ready)
            done = 0
            job.progress(f"共 {total} 个就绪桥段待展开", 1)

            async def on_bridge_done(bridge: Any, chapters: list[Any]) -> None:
                nonlocal done
                done += 1
                job.publish({"type": "bridges", "bridges": [bridge_to_dict(bridge)]})
                job.progress(
                    f"桥段 {bridge.bridge_number} 已展开为 {len(chapters)} 章（{done}/{total}）",
                    int(done / total * 100) if total else 100,
                )

            return await service.expand_all_ready_bridges(
                db, project_id=job.project_id, model_name=model, on_bridge_done=on_bridge_done
            )

    return runner


async def start_bridge_expand(
    *,
    project_id: str,
    user_id: str,
    ai_service: Any,
    session_factory: Callable[[], Any],
    model: Optional[str],
    bridge_id: Optional[str] = None,
    service_factory: Optional[ServiceFactory] = None,
    manager: AIJobManager = ai_jobs,
) -> AIJob:
    """bridge_id 给定 → 单个展开；None → 批量展开全部 ready。同项目只允许一个展开任务。"""
    if bridge_id is not None:
        async with session_factory() as db:
            bridge = await (service_factory or _default_service)(ai_service).get_bridge(db, bridge_id)
        if bridge is None:
            raise ValueError("桥段不存在")
        title = f"展开桥段 {bridge.bridge_number}《{bridge.title or ''}》"
        runner = make_expand_one_runner(
            ai_service=ai_service, session_factory=session_factory, bridge_id=bridge_id, model=model,
            service_factory=service_factory,
        )
    else:
        title = "展开全部就绪桥段为章纲"
        runner = make_expand_all_runner(
            ai_service=ai_service, session_factory=session_factory, model=model, service_factory=service_factory,
        )
    try:
        return await manager.start(
            kind=KIND_EXPAND, title=title, user_id=user_id, project_id=project_id, scope=expand_scope(project_id),
            runner=runner, cancel_message=CANCELLED_MESSAGE, meta={"model": model, "bridge_id": bridge_id},
        )
    except AIJobConflictError as exc:
        raise BridgePlanningConflictError("该项目已有桥段展开任务在运行，请等待完成或先停止") from exc
