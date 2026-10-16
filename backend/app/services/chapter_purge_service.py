"""章节正文被整章替换 / 章节被删除 / 项目被删除时，清理对应的分析产物与账本。

- purge_chapter_analysis：采用整章候选稿、恢复历史版本走这里（回到「未分析」）。AI 档案删掉、作者改过的档案留着；
  本章埋的伏笔标记待对账（重新分析时按标题复用原 ID）；局部修改（手改几句、助笔润色一段）不清，靠正文指纹判过期
- purge_deleted_chapter：删章节时连同本章埋设且后面没用过的伏笔、本章的档案一起删（SQLite 没开外键级联）
- purge_project_ledger：删项目时清掉全部账本表
都只改关系库、不提交；检索索引由调用方在提交后清（purge_chapter_vector_memory / memory_service.delete_project_memories）。
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.analysis_task import AnalysisTask
from app.models.arc_summary import ArcSummary
from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_digest import ChapterDigest
from app.models.character_known_info import CharacterKnownInfo
from app.models.ledger_override import AuthorStateSignal, PromiseAuthorLock
from app.models.memory import PlotAnalysis
from app.models.narrative_promise import NarrativePromise
from app.models.relationship_event import RelationshipEvent
from app.models.timeline_event import TimelineEvent
from app.services import arc_summary_service, chapter_digest_service
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.chapter_entity_service import strip_chapter_entity_notes
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service

logger = get_logger(__name__)


async def _clear_chapter(db: AsyncSession, chapter_id: str) -> int:
    analyses = (await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id))).scalars().all()
    for row in analyses:
        await db.delete(row)
    for row in (await db.execute(select(AnalysisTask).where(AnalysisTask.chapter_id == chapter_id))).scalars().all():
        await db.delete(row)
    await narrative_state_service.clear_chapter_state(db, chapter_id)
    await chapter_consistency_service.clear_chapter_records(db, chapter_id)
    return len(analyses)


async def purge_chapter_analysis(db: AsyncSession, chapter_id: str) -> int:
    """整章替换后清掉本章分析产物；返回清掉的分析记录 + 档案条数（>0 时调用方再清检索索引）。"""
    purged = await _clear_chapter(db, chapter_id)
    digest = await chapter_digest_service.get_digest(db, chapter_id)
    if digest is not None:
        purged += 1
        await chapter_digest_service.purge_for_replacement(db, chapter_id)
    located = (await db.execute(
        select(Chapter.project_id, Chapter.chapter_number).where(Chapter.id == chapter_id)
    )).first()
    if located:
        # 覆盖本章的单元 / 阶段 / 卷摘要已过期：删掉，等本章重新分析后自然重算
        await arc_summary_service.invalidate_covering(db, located[0], located[1])
        await strip_chapter_entity_notes(db, located[0], located[1])
    return purged


async def purge_deleted_chapter(db: AsyncSession, chapter: Chapter) -> int:
    """删除章节前调用：清分析产物、档案（含作者的）、本章埋设且没被后文用过 / 作者没改过的伏笔、本章写进人物档案的行。"""
    purged = await _clear_chapter(db, chapter.id)
    await narrative_state_service._finish_promise_reconcile(db, chapter)
    await chapter_digest_service.delete_for_chapter(db, chapter.id)
    await arc_summary_service.invalidate_covering(db, chapter.project_id, chapter.chapter_number)
    await strip_chapter_entity_notes(db, chapter.project_id, chapter.chapter_number)
    return purged


async def purge_project_ledger(db: AsyncSession, project_id: str) -> None:
    """删除项目时清掉全部账本表（SQLite 没开外键级联，不清会留下孤儿行）。"""
    promise_ids = select(NarrativePromise.id).where(NarrativePromise.project_id == project_id)
    await db.execute(delete(PromiseAuthorLock).where(PromiseAuthorLock.promise_id.in_(promise_ids)))
    for model in (
        PlotAnalysis, AnalysisTask, ChapterDigest, NarrativePromise, ChapterCausalLink, TimelineEvent, RelationshipEvent,
        CharacterKnownInfo, ChapterContinuitySignal, ChapterConsistencyIssue, AuthorStateSignal, ArcSummary,
    ):
        await db.execute(delete(model).where(model.project_id == project_id))


async def purge_chapter_vector_memory(user_id: str | None, project_id: str, chapter_id: str, mem_count: int) -> None:
    """检索索引清理（best-effort；须在关系库删除已提交后调用）。"""
    if not mem_count or not user_id:
        return
    try:
        await memory_service.delete_chapter_memories(user_id=user_id, project_id=project_id, chapter_id=chapter_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ 检索索引清理失败（不影响正文替换）: {e}")
