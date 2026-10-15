"""卷纲规划后台任务（分卷 / 细化卷纲 / 单元章纲），跑在 ai_jobs 通用管理器上：关掉页面也不停，刷新可接管。

同一项目共用一个互斥键：章号连续分配，规划任务不能并行。中断 = 已完成的批次已落库（单元章纲按批提交）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.services import volume_service as vs
from app.services.ai_jobs import AIJob, AIJobConflictError, AIJobManager, ai_jobs

KIND = "volume_plan"
CANCELLED_MESSAGE = "已停止规划；已生成的卷纲 / 章纲已保存"
TITLES = {"skeleton": "按总纲分卷", "detail": "细化卷纲", "outlines": "生成单元章纲"}


def plan_scope(project_id: str) -> str:
    return f"{KIND}:{project_id}"


async def start_volume_job(
    *,
    action: str,
    project_id: str,
    user_id: str,
    ai_service: Any,
    session_factory: Callable[[], Any],
    volume_id: Optional[str] = None,
    unit_index: Optional[int] = None,
    total_chapters: Optional[int] = None,
    volume_count: Optional[int] = None,
    instruction: str = "",
    model: Optional[str] = None,
    title_suffix: str = "",
    manager: AIJobManager = ai_jobs,
) -> AIJob:
    if action not in TITLES:
        raise ValueError(f"未知的规划动作：{action}")

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            if action == "skeleton":
                job.progress("正在按总纲分卷…", 10)
                created = await vs.generate_skeleton(db, project_id, ai_service, total_chapters=total_chapters,
                                                     volume_count=volume_count, instruction=instruction, model=model)
                return {"action": action, "volumes": [vs.volume_to_dict(v) for v in created]}
            if action == "detail":
                job.progress("正在把本卷拆成剧情单元…", 10)
                volume = await vs.detail_volume(db, volume_id, ai_service, instruction=instruction, model=model)
                return {"action": action, "volume": vs.volume_to_dict(volume)}

            async def on_batch(start: int, end: int) -> None:
                job.progress(f"已生成第 {start}-{end} 章章纲", 60)

            job.progress("正在展开剧情单元为章纲…", 10)
            created = await vs.generate_unit_outlines(db, volume_id, int(unit_index or 0), ai_service,
                                                      instruction=instruction, model=model, on_batch=on_batch)
            return {"action": action, "volume_id": volume_id, "unit_index": unit_index,
                    "chapter_numbers": [o.chapter_number for o in created], "outline_ids": [o.id for o in created]}

    try:
        return await manager.start(
            kind=KIND, title=TITLES[action] + title_suffix, user_id=user_id, project_id=project_id,
            scope=plan_scope(project_id), runner=runner, cancel_message=CANCELLED_MESSAGE,
            meta={"action": action, "volume_id": volume_id, "unit_index": unit_index},
        )
    except AIJobConflictError as exc:
        raise vs.VolumeConflictError("该项目已有卷纲规划任务在运行，请等待完成或先停止") from exc
