"""桥段填充后台任务：跑在 ai_jobs 通用管理器上的 runner（服务层事件 → 前端事件翻译）。

历史：2026-09-09 这里是独立的 BridgeFillJobManager（agent-docs/plans/2026-09-09-bridge-fill-ux.md）；
2026-09-11 泛化为 ai_jobs.AIJobManager 后，本模块只剩桥段特有的部分：
- 进度文案 / 百分比（按 draft 总数）
- partial / thinking 打字机快照原样透传（最新态）
- phase_plan → 进度文案 + 一条 reference（长节点拆成了哪些阶段）
- batch_done → meta + bridges + 一条 reference（本批参考了什么，给通用弹窗的参考面板）
- 每个主线节点一个 stage（通用弹窗的过程时间线）
桥段表 status 仍是唯一持久状态：任务中断 = 当前子批保持 draft，下次点填充即续跑。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlalchemy import select

from app.models.plot_bridge import PlotBridge
from app.services.ai_jobs import AIJob, AIJobConflictError, AIJobManager, Runner, ai_jobs
from app.services.bridge_planning_service import BridgePlanningService
from app.services.bridge_slot_planner import BridgePlanningConflictError
from app.services.generation_trace import trace_reference, trace_stage

logger = logging.getLogger(__name__)

KIND = "bridge_fill"
TITLE = "AI 填充桥段内容"
CANCELLED_MESSAGE = "已停止填充；已完成的桥段已保存，再次点击填充可续跑"
LIVE_PASSTHROUGH = ("partial", "thinking")


def fill_scope(project_id: str) -> str:
    return f"{KIND}:{project_id}"


def _provenance_items(prov: dict[str, Any]) -> list[dict[str, str]]:
    """把 build_fill_provenance 产出的溯源压成通用 reference 条目。"""
    pack = prov.get("reference_pack") or {}
    inputs = prov.get("inputs") or {}
    ledger = inputs.get("ledger_bridge_numbers") or []
    return [
        {"title": "题材模板", "detail": str(prov.get("template") or "—")},
        {"title": "模型档位", "detail": str(prov.get("model_tier") or "—")},
        {"title": "参考包", "detail": str(pack.get("title") or "未挂载")},
        {"title": "已填桥段账本", "detail": f"{len(ledger)} 个桥段" if ledger else "无前文账本"},
    ]


def _phase_items(phases: list[dict[str, Any]]) -> list[dict[str, str]]:
    """把长节点阶段拆分结果压成通用 reference 条目。"""
    items = []
    for p in phases:
        detail = str(p.get("goal") or "")
        if p.get("antagonist"):
            detail += f"｜对手：{p['antagonist']}"
        items.append({
            "title": f"阶段 {p.get('index')}《{p.get('title')}》桥段 {p.get('bridge_start')}-{p.get('bridge_end')}",
            "detail": detail,
        })
    return items


def make_bridge_fill_runner(
    *,
    ai_service: Any,
    session_factory: Callable[[], Any],
    model: Optional[str],
    beat_index: Optional[int],
    service_factory: Optional[Callable[[Any], Any]] = None,
) -> Runner:
    make_service = service_factory or (lambda ai: BridgePlanningService(ai_service=ai))

    async def runner(job: AIJob) -> Optional[dict[str, Any]]:
        async with session_factory() as db:
            total = len((await db.execute(
                select(PlotBridge.id).where(PlotBridge.project_id == job.project_id, PlotBridge.status == "draft")
            )).scalars().all())
            done_count = 0

            def pct() -> int:
                return int(done_count / total * 100) if total else 100

            job.progress("开始填充桥段内容...", 1)
            service = make_service(ai_service)
            result: Optional[dict[str, Any]] = None
            async for evt in service.fill_bridges(db, job.project_id, model, beat_index):
                kind = evt["type"]
                if kind == "beat_start":
                    nums = evt["bridge_numbers"]
                    label = f"节点 {evt['beat_index']}：桥段 {nums[0]}-{nums[-1]}"
                    trace_stage(f"beat-{evt['beat_index']}", label, "running")
                    job.progress(label, pct())
                elif kind in LIVE_PASSTHROUGH:
                    job.publish(evt)
                elif kind == "phase_plan":
                    phases = evt.get("phases") or []
                    trace_reference("bridge_phases", f"节点 {evt['beat_index']} 阶段拆分", _phase_items(phases))
                    job.progress(f"节点 {evt['beat_index']} 拆成 {len(phases)} 个阶段，开始逐阶段填充", pct())
                elif kind == "batch_done":
                    done_count += len(evt["bridges"])
                    nums = evt["bridge_numbers"]
                    prov = evt.get("provenance") or {}
                    job.publish({"type": "meta", "beat_index": evt["beat_index"], "bridge_numbers": nums, "provenance": prov})
                    job.publish({"type": "bridges", "beat_index": evt["beat_index"], "bridges": evt["bridges"]})
                    trace_reference(
                        "bridge_provenance", f"本批参考（节点 {evt['beat_index']}）", _provenance_items(prov),
                        warnings=list(prov.get("warnings") or []),
                    )
                    job.progress(
                        f"节点 {evt['beat_index']}：桥段 {nums[0]}-{nums[-1]} 已填充（累计 {done_count}/{total}）", pct(),
                    )
                elif kind == "beat_done":
                    nums = evt.get("bridge_numbers") or []
                    label = f"节点 {evt['beat_index']}" + (f"：桥段 {nums[0]}-{nums[-1]}" if nums else "")
                    trace_stage(f"beat-{evt['beat_index']}", label, "done")
                    job.progress(f"节点 {evt['beat_index']} 完成（累计 {done_count}/{total}）", pct())
                elif kind == "done":
                    result = evt
            return result

    return runner


async def start_bridge_fill(
    *,
    project_id: str,
    user_id: str,
    ai_service: Any,
    model: Optional[str],
    beat_index: Optional[int],
    session_factory: Callable[[], Any],
    service_factory: Optional[Callable[[Any], Any]] = None,
    manager: AIJobManager = ai_jobs,
) -> AIJob:
    """启动填充任务；同项目已有任务在跑 → BridgePlanningConflictError（API 层转 409）。"""
    runner = make_bridge_fill_runner(
        ai_service=ai_service, session_factory=session_factory, model=model, beat_index=beat_index,
        service_factory=service_factory,
    )
    try:
        return await manager.start(
            kind=KIND, title=TITLE, user_id=user_id, project_id=project_id, scope=fill_scope(project_id),
            runner=runner, cancel_message=CANCELLED_MESSAGE, meta={"model": model, "beat_index": beat_index},
        )
    except AIJobConflictError as exc:
        raise BridgePlanningConflictError("该项目已有填充任务在运行，请等待完成或先停止") from exc
