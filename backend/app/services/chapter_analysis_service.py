"""章节分析流水线：两段式抽取 → 校验 → 一次性落库 → 刷新检索索引 → 汇总层级摘要。

- 分析 A「叙事事实」失败（截断 / 空返回 / 缺摘要 / 调用失败）：任务记失败，原因写人话；本章旧的档案 / 账本 /
  标注原样保留。旧版先清后写，截断的结果会把上一次正确的结算冲掉。
- 分析 B「人物与标注」失败只降级：人物档案不补、标注沿用上一次，任务照样完成并附说明。
- 写库在一个事务里完成，且尽量走独立连接：主库是 StaticPool 单连接、所有会话共用一个事务，别的请求收尾时
  rollback 会把这里没提交的写入一起冲掉（内存库等拿不到独立连接时退回主引擎）。
- AnalysisTask 行仍是任务状态的唯一真相（/analysis 状态、批量分析、过期判断都靠它）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from app.logger import get_logger
from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.memory import PlotAnalysis
from app.services import arc_summary_service, chapter_digest_service, story_index_items
from app.services import chapter_analysis_schema as schema
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.chapter_entity_service import auto_create_entities
from app.services.chapter_version_service import content_hash
from app.services.generation_trace import stage_scope, trace_progress
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service
from app.services.narrative_tasks import render_narrative_tasks, task_promise_ids
from app.services.plot_analyzer import AnalysisError, PlotAnalyzer

logger = get_logger(__name__)

KNOWN_CHARACTER_LIMIT = 60
_ROLE_ORDER = {"protagonist": 0, "antagonist": 1, "major": 2, "supporting": 3}
_write_locks: dict[str, asyncio.Lock] = {}


def get_db_write_lock(user_id: str) -> asyncio.Lock:
    """同一用户的分析写库串行（批量流水线 + 手动分析同时跑时不互相抢锁）。"""
    lock = _write_locks.get(user_id)
    if lock is None:
        lock = _write_locks[user_id] = asyncio.Lock()
    return lock


async def load_analysis_inputs(db: AsyncSession, project_id: str, chapter: Chapter) -> dict[str, Any]:
    """分析 A 的额外输入：未回收承诺（本章计划处理的排前面）、本章计划叙事任务、已登记角色正式名。"""
    planned_raw = None
    if chapter.chapter_outline_id:
        planned_raw = (await db.execute(
            select(ChapterOutline.narrative_tasks).where(ChapterOutline.id == chapter.chapter_outline_id)
        )).scalar_one_or_none()
    open_promises = await narrative_state_service._get_active_promises(
        db, project_id, chapter.chapter_number,
        focus_ids=task_promise_ids(planned_raw), limit=PlotAnalyzer.OPEN_PROMISE_LIMIT,
    )
    rows = (await db.execute(
        select(Character.name, Character.role_type, Character.is_organization).where(Character.project_id == project_id)
    )).all()
    ordered = sorted(rows, key=lambda r: _ROLE_ORDER.get((r[1] or "").lower(), 9))
    people = [name for name, _role, is_org in ordered if name and not is_org]
    return {
        "open_promises": open_promises,
        "planned_tasks": render_narrative_tasks(planned_raw, chapter.chapter_number, for_analysis=True),
        "known_characters": people[:KNOWN_CHARACTER_LIMIT],
        "known_entities": [name for name, _role, _org in ordered if name][:KNOWN_CHARACTER_LIMIT * 2],
    }


def _annotation_groups(cast: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {kind: [] for kind in schema.ANNOTATION_TYPES}
    for item in cast.get("annotations") or []:
        groups.setdefault(item["type"], []).append(
            {"title": item["title"], "note": item["note"], "quote": item["quote"], "importance": item["importance"]}
        )
    return groups


async def _upsert_analysis_record(
    db: AsyncSession, chapter: Chapter, settlement: dict, cast: Optional[dict], analyzed_hash: str, analyzed_at: Any,
) -> None:
    row = (await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter.id))).scalar_one_or_none()
    if row is None:
        row = PlotAnalysis(project_id=chapter.project_id, chapter_id=chapter.id, hooks=[], foreshadows=[], plot_points=[])
        db.add(row)
    if cast is not None:
        groups = _annotation_groups(cast)
        row.hooks, row.foreshadows, row.plot_points = groups["hook"], groups["foreshadow"], groups["plot_point"]
    row.character_states = settlement.get("character_states") or []
    row.scenes = settlement.get("scenes") or []
    row.content_hash = analyzed_hash
    # 记「读取正文的时刻」（与 chapter.updated_at 同一时钟：SQLite CURRENT_TIMESTAMP，UTC）：分析期间作者又改了正文，
    # updated_at 晚于它，章节目录据此只给这些章重算指纹（记落库时刻会把分析中途的修改漏掉）
    row.created_at = analyzed_at


def _isolated_engine(main_engine: Any) -> Any:
    from app.services.chapter_batch_service import isolated_sqlite_engine

    try:
        return isolated_sqlite_engine(main_engine.url.render_as_string(hide_password=False))
    except Exception:  # noqa: BLE001 - 拿不到独立连接就用主引擎
        return None


async def _set_task(db: AsyncSession, lock: asyncio.Lock, task_id: str, **values: Any) -> None:
    async with lock:
        task = await db.get(AnalysisTask, task_id)
        if task is None:
            return
        for key, value in values.items():
            setattr(task, key, value)
        await db.commit()


async def _fail(db: AsyncSession, lock: asyncio.Lock, task_id: str, message: str) -> None:
    logger.error(f"❌ 章节分析失败（任务 {task_id}）：{message}")
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass
    await _set_task(db, lock, task_id, status="failed", error_message=message[:500], completed_at=datetime.now(), progress=0)


async def analyze_chapter_background(
    chapter_id: str,
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: Any,
    engine: Any = None,
) -> None:
    """后台分析一章（单章分析、采用候选稿后、批量写作 / 批量分析共用）。engine：调用方给的独立连接（批量流水线）。"""
    from app.database import get_engine

    owned = None
    if engine is None:
        main = await get_engine(user_id)
        owned = _isolated_engine(main)
        engine = owned or main
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    lock = get_db_write_lock(user_id)
    try:
        async with maker() as db:
            try:
                await _analyze(db, lock, chapter_id=chapter_id, user_id=user_id, project_id=project_id,
                               task_id=task_id, ai_service=ai_service)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(_fail(db, lock, task_id, "分析已停止；本章原有的分析结果未改动，可重新分析"))
                except BaseException:  # noqa: BLE001 - 取消路径上记不下状态也要把取消抛出去
                    pass
                raise
            except Exception as exc:  # noqa: BLE001 - 统一记成任务失败
                logger.error(f"❌ 后台分析异常: {exc}", exc_info=True)
                await _fail(db, lock, task_id, f"分析失败：{exc}")
    finally:
        if owned is not None:
            await owned.dispose()


async def _analyze(
    db: AsyncSession, lock: asyncio.Lock, *, chapter_id: str, user_id: str, project_id: str, task_id: str, ai_service: Any,
) -> None:
    task = await db.get(AnalysisTask, task_id)
    if task is None:
        logger.error(f"❌ 分析任务不存在: {task_id}")
        return
    await _set_task(db, lock, task_id, status="running", started_at=datetime.now(), progress=10, error_message=None)
    trace_progress("读取章节…", 10)

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None or not (chapter.content or "").strip():
        await _fail(db, lock, task_id, "章节不存在或内容为空")
        return
    analyzed_hash = content_hash(chapter.content)
    analyzed_at = (await db.execute(select(func.now()))).scalar()
    inputs = await load_analysis_inputs(db, project_id, chapter)

    await _set_task(db, lock, task_id, progress=20)
    trace_progress("模型分析章节中…", 20)
    analyzer = PlotAnalyzer(ai_service)
    async with stage_scope("analyze", "分析叙事事实 + 人物与标注") as st:
        facts, cast = await asyncio.gather(
            analyzer.analyze_facts(
                chapter_number=chapter.chapter_number, title=chapter.title or "", content=chapter.content,
                open_promises=inputs["open_promises"], planned_tasks=inputs["planned_tasks"],
                known_characters=inputs["known_characters"],
            ),
            analyzer.extract_cast(
                chapter_number=chapter.chapter_number, title=chapter.title or "", content=chapter.content,
                known_characters=inputs["known_entities"],
            ),
            return_exceptions=True,
        )
        st.note(facts_ok=not isinstance(facts, BaseException), cast_ok=not isinstance(cast, BaseException))
    for result in (facts, cast):
        if isinstance(result, asyncio.CancelledError):
            raise result
    if isinstance(facts, BaseException):
        reason = str(facts) if isinstance(facts, AnalysisError) else f"分析失败：{facts}"
        await _fail(db, lock, task_id, f"{reason}（本章原有的分析结果未改动）")
        return
    warning = None
    if isinstance(cast, BaseException):
        warning = f"人物与标注没抽出来（{cast}），本章人物档案与正文标注未更新，可重新分析"
        logger.warning(f"⚠️ 第{chapter.chapter_number}章{warning}")
        cast = None

    settlement = schema.facts_to_settlement(facts)
    trace_progress("写入档案与账本…", 60)
    async with stage_scope("persist", "一次性写入档案 / 账本 / 标注") as st:
        async with lock:
            try:
                if cast is not None:
                    await auto_create_entities(db, project_id, chapter.chapter_number, cast)
                await _upsert_analysis_record(db, chapter, settlement, cast, analyzed_hash, analyzed_at)
                await chapter_digest_service.upsert_from_analysis(
                    db, chapter, summary=facts["summary"], end_state=facts.get("end_state") or "",
                    analyzed_hash=analyzed_hash,
                )
                settle_stats = await narrative_state_service.settle_chapter_state(
                    db=db, project_id=project_id, chapter=chapter, analysis=settlement,
                )
                audit_stats = await chapter_consistency_service.settle_signals_and_audit(
                    db=db, project_id=project_id, chapter=chapter, analysis=settlement,
                )
                task = await db.get(AnalysisTask, task_id)
                if task is not None:
                    task.progress = 85
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        st.note(**settle_stats, **audit_stats)
    logger.info(f"✅ 第{chapter.chapter_number}章分析已落库: {settle_stats} / {audit_stats}")

    trace_progress("刷新检索索引…", 90)
    async with stage_scope("index", "刷新检索索引") as st:
        try:
            items = await story_index_items.chapter_items(db, project_id, chapter.id)
            st.note(items=await memory_service.refresh_chapter(user_id, project_id, chapter.id, items))
        except Exception as exc:  # noqa: BLE001 - 索引可重建，不影响分析结果
            logger.warning(f"⚠️ 刷新检索索引失败（可在故事账本里重建）: {exc}")
            st.note(error=str(exc)[:200])

    async with stage_scope("arc_rollup", "汇总剧情单元 / 卷摘要") as st:
        try:
            async with lock:
                st.note(llm_calls=await arc_summary_service.maybe_rollup(db, project_id, chapter.chapter_number, ai_service))
        except Exception as exc:  # noqa: BLE001 - 汇总失败不影响本章分析
            await db.rollback()
            logger.warning(f"⚠️ 层级摘要汇总失败（不影响本章分析）: {exc}")
            st.note(error=str(exc)[:200])

    await _set_task(db, lock, task_id, status="completed", progress=100, completed_at=datetime.now(),
                    error_message=warning)
    logger.info(f"✅ 章节分析完成: 第{chapter.chapter_number}章 {chapter_id}")
