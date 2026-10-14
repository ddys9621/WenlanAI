"""整章正文被替换后，清理本章全部分析产物（不标过期，直接删，回到「未分析」）。

采用整章候选稿、恢复历史版本都走这里；局部修改（手改几句、助笔润色一段）不清，靠正文指纹判过期。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis, StoryMemory
from app.services import arc_summary_service
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service

logger = get_logger(__name__)


async def purge_chapter_analysis(db: AsyncSession, chapter_id: str) -> int:
    """删除该章全部分析产物：PlotAnalysis + AnalysisTask + StoryMemory（DB 行）+ 叙事状态（伏笔 / 承诺、因果、时间轴、
    关系事件、已知信息）+ 一致性信号与问题 + 覆盖本章的层级摘要。

    仅删关系库行，不提交、不清向量；返回删除的记忆条数供调用方做向量清理。
    """
    for row in (await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id))).scalars().all():
        await db.delete(row)
    for row in (await db.execute(select(AnalysisTask).where(AnalysisTask.chapter_id == chapter_id))).scalars().all():
        await db.delete(row)
    mem_rows = (await db.execute(select(StoryMemory).where(StoryMemory.chapter_id == chapter_id))).scalars().all()
    for row in mem_rows:
        await db.delete(row)
    await narrative_state_service.clear_chapter_state(db, chapter_id)
    await chapter_consistency_service.clear_chapter_records(db, chapter_id)
    located = (await db.execute(
        select(Chapter.project_id, Chapter.chapter_number).where(Chapter.id == chapter_id)
    )).first()
    if located:
        # 覆盖本章的单元 / 阶段 / 卷摘要已过期：删掉，等本章重新分析后自然重算
        await arc_summary_service.invalidate_covering(db, located[0], located[1])
    return len(mem_rows)


async def purge_chapter_vector_memory(user_id: str | None, project_id: str, chapter_id: str, mem_count: int) -> None:
    """向量库记忆清理（best-effort；须在 DB 删除已提交后调用）。"""
    if not mem_count or not user_id:
        return
    try:
        await memory_service.delete_chapter_memories(user_id=user_id, project_id=project_id, chapter_id=chapter_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ 向量记忆清理失败（不影响正文替换）: {e}")
