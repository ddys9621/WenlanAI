"""章节分析后台任务：把 api.chapters.analyze_chapter_background（DB 持久的 AnalysisTask 工作流）包成 ai_jobs 任务。

AnalysisTask 行仍是真相（/analysis/status 端点、"分析过期"判断都靠它）；本模块只让分析在托盘 / 弹窗里可见：
worker 内部的 stage_scope / trace_progress 自动进任务日志，runner 结束后读任务行判定成败。
同一章同时只允许一个分析任务。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.services.ai_jobs import AIJob, AIJobManager, ai_jobs, job_session_factory

KIND = "chapter_analyze"
CANCELLED_MESSAGE = "已停止分析；本章记忆未更新，可在章节列表重新分析"
Worker = Callable[..., Awaitable[None]]


def analysis_scope(chapter_id: str) -> str:
    return f"{KIND}:{chapter_id}"


async def create_analysis_task(db: AsyncSession, *, chapter_id: str, user_id: str, project_id: str) -> str:
    """建 pending 的 AnalysisTask 行并提交，返回 task_id（发起端点与正文任务共用）。"""
    task = AnalysisTask(chapter_id=chapter_id, user_id=user_id, project_id=project_id, status="pending", progress=0)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task.id


def _default_worker() -> Worker:
    from app.api.chapters import analyze_chapter_background  # 延迟导入：api 层反过来依赖本模块

    return analyze_chapter_background


async def start_chapter_analysis(
    *,
    chapter_id: str,
    chapter_number: int,
    chapter_title: Optional[str],
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: Any,
    worker: Optional[Worker] = None,
    manager: AIJobManager = ai_jobs,
) -> AIJob:
    """启动分析任务；同章已有任务在跑 → AIJobConflictError（调用方转 409 或忽略）。"""
    run_worker = worker or _default_worker()

    async def runner(job: AIJob) -> dict[str, Any]:
        job.progress("准备分析章节…", 2)
        await run_worker(chapter_id=chapter_id, user_id=user_id, project_id=project_id, task_id=task_id, ai_service=ai_service)
        async with job_session_factory(user_id)() as db:
            task = (await db.execute(select(AnalysisTask).where(AnalysisTask.id == task_id))).scalar_one_or_none()
        if task is None or task.status != "completed":
            raise RuntimeError((task.error_message if task is not None else None) or "章节分析未完成")
        return {"task_id": task_id, "chapter_id": chapter_id, "status": "completed"}

    return await manager.start(
        kind=KIND,
        title=f"分析第 {chapter_number} 章《{chapter_title or ''}》",
        user_id=user_id,
        project_id=project_id,
        scope=analysis_scope(chapter_id),
        runner=runner,
        cancel_message=CANCELLED_MESSAGE,
        meta={"chapter_id": chapter_id, "task_id": task_id},
    )
