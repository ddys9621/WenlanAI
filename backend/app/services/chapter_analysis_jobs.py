"""章节分析相关的后台任务（跑在 ai_jobs 上：托盘可见、关页面不停、可取消）。

- 单章分析（chapter_analyze）：AnalysisTask 行仍是真相（/analysis 状态、"分析过期"判断都靠它），本模块只让分析
  在托盘 / 弹窗里可见；同一章同时只允许一个分析任务
- 按章序批量分析（chapter_analyze_batch）：从小到大逐章分析（伏笔的推进 / 回收依赖前文已入账，乱序会留下
  孤立的回收和永远不回收的坑）；导入项目、手写的章节、过期分析都靠它补齐
- 重建检索索引（memory_index_rebuild）：从账本表重新编码写入向量库，不调用大模型
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis
from app.services.ai_jobs import AIJob, AIJobManager, ai_jobs, job_session_factory
from app.services.chapter_readiness_service import analysis_is_stale

KIND = "chapter_analyze"
BATCH_KIND = "chapter_analyze_batch"
REBUILD_KIND = "memory_index_rebuild"
CANCELLED_MESSAGE = "已停止分析；本章原有的分析结果未改动，可在章节列表重新分析"
BATCH_CANCELLED_MESSAGE = "已停止批量分析；已分析完的章节结果已保存，再次发起会接着补"
Worker = Callable[..., Awaitable[None]]
BATCH_MODES = ("missing", "stale", "all")


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
    from app.api.chapters import analyze_chapter_background  # 经 api 模块取（测试在那里打桩）

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
        return {"task_id": task_id, "chapter_id": chapter_id, "status": "completed", "warning": task.error_message}

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


async def select_batch_chapters(
    db: AsyncSession, project_id: str, *, from_chapter: int, to_chapter: int, mode: str,
) -> list[Chapter]:
    """范围内有正文、且按 mode 需要分析的章（按章号升序）：missing 只补没分析过的；stale 再加上分析后正文改过的；all 全部重来。"""
    chapters = list((await db.execute(
        select(Chapter).where(
            Chapter.project_id == project_id, Chapter.chapter_number >= from_chapter, Chapter.chapter_number <= to_chapter,
            Chapter.content.isnot(None), Chapter.content != "",
        ).order_by(Chapter.chapter_number)
    )).scalars().all())
    if mode == "all":
        return chapters
    analyses = {a.chapter_id: a for a in (await db.execute(
        select(PlotAnalysis).where(PlotAnalysis.chapter_id.in_([c.id for c in chapters]))
    )).scalars().all()} if chapters else {}
    picked = []
    for chapter in chapters:
        analysis = analyses.get(chapter.id)
        if analysis is None or (mode == "stale" and analysis_is_stale(analysis, chapter)):
            picked.append(chapter)
    return picked


async def start_batch_analysis(
    *,
    project_id: str,
    user_id: str,
    ai_service: Any,
    from_chapter: int,
    to_chapter: int,
    mode: str = "stale",
    worker: Optional[Worker] = None,
    manager: AIJobManager = ai_jobs,
    session_factory: Optional[Callable[[], Any]] = None,
) -> AIJob:
    """按章序批量分析；同项目已有批量分析在跑 → AIJobConflictError。"""
    run_worker = worker or _default_worker()
    sessions = session_factory or job_session_factory(user_id)
    mode = mode if mode in BATCH_MODES else "stale"

    async def runner(job: AIJob) -> dict[str, Any]:
        from app.services.chapter_analysis_service import _isolated_engine
        from app.database import get_engine

        async with sessions() as db:
            targets = [(c.id, c.chapter_number, c.title) for c in await select_batch_chapters(
                db, project_id, from_chapter=from_chapter, to_chapter=to_chapter, mode=mode,
            )]
        total = len(targets)
        if total == 0:
            return {"total": 0, "analyzed": [], "failed": [], "skipped": [], "message": "范围内没有需要分析的章节"}
        isolated = None
        try:
            isolated = _isolated_engine(await get_engine(user_id))
        except Exception:  # noqa: BLE001 - 拿不到独立连接就让单章分析自己处理
            isolated = None
        analyzed: list[int] = []
        failed: list[dict[str, Any]] = []
        skipped: list[int] = []
        try:
            for index, (chapter_id, number, title) in enumerate(targets):
                job.progress(f"第 {number} 章《{title or ''}》分析中（{index + 1}/{total}）…", int(index / total * 100))
                if manager.current(analysis_scope(chapter_id)) is not None:
                    skipped.append(number)  # 这一章正被单独分析：不抢
                    job.publish({"type": "batch_chapter", "chapter_number": number, "chapter_id": chapter_id, "status": "skipped"})
                    continue
                async with sessions() as db:
                    task_id = await create_analysis_task(db, chapter_id=chapter_id, user_id=user_id, project_id=project_id)
                job.publish({"type": "batch_chapter", "chapter_number": number, "chapter_id": chapter_id, "status": "analyzing"})
                kwargs = {"engine": isolated} if isolated is not None else {}
                await run_worker(chapter_id=chapter_id, user_id=user_id, project_id=project_id, task_id=task_id,
                                 ai_service=ai_service, **kwargs)
                async with sessions() as db:
                    task = await db.get(AnalysisTask, task_id)
                if task is not None and task.status == "completed":
                    analyzed.append(number)
                    job.publish({"type": "batch_chapter", "chapter_number": number, "chapter_id": chapter_id, "status": "done"})
                else:
                    reason = (task.error_message if task is not None else None) or "分析未完成"
                    failed.append({"chapter_number": number, "error": reason})
                    job.publish({"type": "batch_chapter", "chapter_number": number, "chapter_id": chapter_id,
                                 "status": "failed", "error": reason})
        finally:
            if isolated is not None:
                await isolated.dispose()
        message = f"分析完成 {len(analyzed)} 章" + (f"，失败 {len(failed)} 章" if failed else "") + (
            f"，跳过 {len(skipped)} 章（正在单独分析）" if skipped else "")
        return {"total": total, "analyzed": analyzed, "failed": failed, "skipped": skipped, "message": message}

    return await manager.start(
        kind=BATCH_KIND,
        title=f"按章序分析第 {from_chapter}-{to_chapter} 章",
        user_id=user_id,
        project_id=project_id,
        scope=f"{BATCH_KIND}:{project_id}",
        runner=runner,
        cancel_message=BATCH_CANCELLED_MESSAGE,
        meta={"from_chapter": from_chapter, "to_chapter": to_chapter, "mode": mode},
    )


async def start_index_rebuild(
    *, project_id: str, user_id: str, manager: AIJobManager = ai_jobs,
    session_factory: Optional[Callable[[], Any]] = None,
) -> AIJob:
    """从账本表重建本项目的检索索引（换向量模型 / 导入项目 / 索引损坏后）；同项目只跑一个。"""
    sessions = session_factory or job_session_factory(user_id)

    async def runner(job: AIJob) -> dict[str, Any]:
        from app.services import story_index_items
        from app.services.memory_service import memory_service

        if not memory_service.available:
            raise RuntimeError("向量模型没有加载，检索索引不可用（召回会只用人物 / 关键词匹配）")
        job.progress("读取账本…", 10)
        async with sessions() as db:
            items = await story_index_items.project_items(db, project_id)
        job.progress(f"重新编码 {len(items)} 条…", 30)
        count = await memory_service.rebuild(user_id, project_id, items)
        return {"count": count}

    return await manager.start(
        kind=REBUILD_KIND,
        title="重建检索索引",
        user_id=user_id,
        project_id=project_id,
        scope=f"{REBUILD_KIND}:{project_id}",
        runner=runner,
        cancel_message="已停止重建检索索引；可再次发起",
        meta={},
    )


async def schedule_index_rebuild_if_needed(
    *, project_id: str, user_id: str, index_count: int, ledger_count: int, manager: AIJobManager = ai_jobs,
) -> bool:
    """索引为空而账本里有档案（换了模型 / 刚导入 / 旧版升级）：后台起一次重建（不等它跑完）。已在跑就不重复起。"""
    from app.services.memory_service import memory_service

    if not memory_service.available or index_count > 0 or ledger_count <= 0:
        return False
    from app.services.embedding_settings_service import rebuild_all_scope

    # 本项目在重建，或刚换模型、正在逐个重建这个用户的全部项目：不再另起一份
    if manager.current(f"{REBUILD_KIND}:{project_id}") is not None or manager.current(rebuild_all_scope(user_id)) is not None:
        return False
    try:
        await start_index_rebuild(project_id=project_id, user_id=user_id, manager=manager)
    except Exception:  # noqa: BLE001 - 并发起了一份（AIJobConflictError）也无所谓
        return False
    return True
