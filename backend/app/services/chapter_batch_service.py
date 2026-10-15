"""服务端批量写作队列（跑在 ai_jobs 上：关掉浏览器也不停，刷新可接管）。

每章：[缺章纲 → 自动规划（细化覆盖本章的卷纲 / 展开覆盖本章的剧情单元）] → 生成候选稿（带截断续写，失败自动重试）→
质量闸门（AI 味分过高 / 字数严重不足 → 重写一次）→ 自动采用最后一稿写入正文 → 分析（记忆 / 状态卡 / 伏笔结算）→
一致性闸门（严重问题暂停）。

- 续跑：已有正文的章节直接跳过；中断后用同样的范围重新发起即可接着写
- 流水线：pipeline=True 时第 N 章分析与第 N+1 章生成重叠（第 N+1 章本来就带着第 N 章全文，不依赖其分析结果；
  分析仍严格按章顺序）。代价：严重问题要晚一章才能发现——这一章会照常写完再暂停。
  注意：应用的 SQLite 引擎是 StaticPool（所有会话共用一条连接），两个会话并发时一方 close / rollback 会把另一方
  未提交的写入一起回滚。所以流水线模式下分析必须走独立连接（analysis_session_factory + analyze_kwargs 里的
  engine，见 isolated_sqlite_engine），拿不到独立连接时调用方应退回顺序模式
- 单章正文的 content 事件不进批量任务日志（几百章全文会撑爆内存），只发每章状态事件 batch_chapter
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_outline import ChapterOutline
from app.services.adherence_review_service import failure_reason as adherence_failure_reason

logger = logging.getLogger(__name__)

KIND = "chapter_batch"
CANCELLED_MESSAGE = "已停止批量生成；已写完的章节已保存，重新发起同样的范围会接着写"

Generate = Callable[..., Awaitable[dict[str, Any]]]
Analyze = Callable[..., Awaitable[None]]
Expand = Callable[..., Awaitable[bool]]
Adopt = Callable[[str], Awaitable[None]]


@dataclass
class BatchOptions:
    from_chapter: int
    to_chapter: int
    pause_on_critical: bool = True
    quality_gate: bool = True
    ai_flavor_threshold: int = 60
    min_word_ratio: float = 0.6
    max_retries: int = 2
    retry_backoff: float = 3.0
    pipeline: bool = False
    auto_expand: bool = True
    style_id: Optional[int] = None
    enable_mcp: bool = False
    target_word_count: Optional[int] = None
    require_confirmed_outline: bool = False  # 只写作者确认过的章纲：遇到 AI 草拟 / 上游已改的章纲就停
    adherence_gate: bool = True  # 章纲遵循度审校不通过（漏写关键事件 / 抢跑 / 新增设定…）时重写一次


@dataclass
class _State:
    completed: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paused_at: Optional[int] = None
    message: str = ""


class _ChapterJobView:
    """单章生成看到的 job：吞掉 content 事件，进度换算到批量进度并加章号前缀，其余事件原样转发。"""

    def __init__(self, job: Any, chapter_number: int, base: float, span: float):
        self._job, self._number, self._base, self._span = job, chapter_number, base, span
        self.chars = 0

    def publish(self, event: dict[str, Any]) -> None:
        if event.get("type") == "content":
            self.chars += len(event.get("content") or "")
            return
        if event.get("type") == "progress":
            pct = float(event.get("progress") or 0)
            event = {**event, "progress": int(self._base + self._span * min(pct, 100) / 100),
                     "message": f"第 {self._number} 章：{event.get('message', '')}"}
        self._job.publish(event)

    def progress(self, message: str, progress: int, status: str = "processing") -> None:
        self.publish({"type": "progress", "message": message, "progress": progress, "status": status})


def _default_generate() -> Generate:
    from app.api.chapters import run_chapter_generation  # 延迟导入：api 层依赖本模块

    return run_chapter_generation


def _default_adopt(session_factory: Callable[[], Any]) -> Adopt:
    """批量：过了闸门的候选稿直接采用（批量只写没有正文的章，不存在覆盖作者修改的问题）。"""
    from app.services.chapter_candidate_service import adopt_candidate_by_id

    async def adopt(candidate_id: str) -> None:
        async with session_factory() as db:
            await adopt_candidate_by_id(db, candidate_id, force=True)

    return adopt


def _default_analyze() -> Analyze:
    from app.api.chapters import analyze_chapter_background

    return analyze_chapter_background


async def default_expand(db: Any, project_id: str, chapter_number: int, ai_service: Any) -> bool:
    """自动规划：找覆盖本章的卷纲；没细化就先拆剧情单元，再把覆盖本章的单元展开成章纲。成功返回 True。"""
    from app.services.volume_service import ensure_outline_for_chapter

    return await ensure_outline_for_chapter(db, project_id, chapter_number, ai_service)


def isolated_sqlite_engine(database_url: str) -> Any:
    """流水线模式给分析用的独立连接引擎（NullPool + 忙等超时）；内存库 / 非 SQLite 返回 None（调用方退回顺序模式）。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    if not database_url.startswith("sqlite") or ":memory:" in database_url or database_url.rstrip("/").endswith("sqlite+aiosqlite:"):
        return None
    return create_async_engine(
        database_url, poolclass=NullPool, connect_args={"check_same_thread": False, "timeout": 30},
    )


async def sync_chapters_from_outlines(db: Any, project_id: str) -> int:
    """为还没有章节行的章纲建章节（与「从章纲同步章节」端点同一逻辑）。返回新建数。"""
    outlines = (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id).order_by(ChapterOutline.chapter_number)
    )).scalars().all()
    existing = set((await db.execute(
        select(Chapter.chapter_outline_id).where(Chapter.project_id == project_id, Chapter.chapter_outline_id.isnot(None))
    )).scalars().all())
    taken_numbers = set((await db.execute(
        select(Chapter.chapter_number).where(Chapter.project_id == project_id)
    )).scalars().all())
    created = 0
    for outline in outlines:
        if outline.id in existing or outline.chapter_number in taken_numbers:
            continue
        db.add(Chapter(project_id=project_id, chapter_outline_id=outline.id, chapter_number=outline.chapter_number,
                       title=outline.title, summary=outline.summary, status="draft", word_count=0))
        created += 1
    if created:
        await db.commit()
    return created


async def _chapter_row(db: Any, project_id: str, number: int) -> Optional[Chapter]:
    return (await db.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_number == number)
    )).scalar_one_or_none()


async def _critical_count(db: Any, chapter_id: str) -> int:
    return int((await db.execute(
        select(func.count()).select_from(ChapterConsistencyIssue).where(
            ChapterConsistencyIssue.chapter_id == chapter_id, ChapterConsistencyIssue.severity == "critical",
        )
    )).scalar_one() or 0)


def _quality_failed(result: dict[str, Any], options: BatchOptions) -> Optional[str]:
    quality = (result or {}).get("quality") or {}
    score = quality.get("score")
    ratio = quality.get("word_count_ratio")
    if isinstance(score, (int, float)) and score >= options.ai_flavor_threshold:
        return f"AI 味分 {score}（阈值 {options.ai_flavor_threshold}）"
    if isinstance(ratio, (int, float)) and ratio < options.min_word_ratio:
        return f"字数只有目标的 {ratio:.0%}"
    if options.adherence_gate:
        return adherence_failure_reason((result or {}).get("adherence"))
    return None


async def run_batch(
    job: Any,
    *,
    project_id: str,
    user_id: str,
    ai_service: Any,
    options: BatchOptions,
    session_factory: Callable[[], Any],
    generate: Optional[Generate] = None,
    analyze: Optional[Analyze] = None,
    expand: Optional[Expand] = None,
    adopt: Optional[Adopt] = None,
    analysis_session_factory: Optional[Callable[[], Any]] = None,
    analyze_kwargs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """analysis_session_factory / analyze_kwargs：分析用的独立连接（流水线模式必需，见模块说明）。

    generate 返回 candidate_id 时，过闸门的那一稿由 adopt 写入正文（重写前的那稿随之作废）。
    """
    from app.api.chapters import ChapterGenerateOptions

    generate = generate or _default_generate()
    analyze = analyze or _default_analyze()
    expand = expand or default_expand
    adopt = adopt or _default_adopt(session_factory)
    analysis_sessions = analysis_session_factory or session_factory
    extra_analyze = dict(analyze_kwargs or {})
    gen_options = ChapterGenerateOptions(
        style_id=options.style_id, target_word_count=options.target_word_count, enable_mcp=options.enable_mcp,
        adherence_review=options.adherence_gate,
    )
    state = _State()
    numbers = list(range(options.from_chapter, options.to_chapter + 1))
    total = max(len(numbers), 1)
    pending_analysis: Optional[asyncio.Task] = None
    pending_meta: Optional[tuple[int, str]] = None

    def emit(number: int, chapter_id: Optional[str], status: str, **extra: Any) -> None:
        job.publish({"type": "batch_chapter", "chapter_number": number, "chapter_id": chapter_id, "status": status, **extra})

    async def run_analysis(number: int, chapter_id: str) -> None:
        from app.services.chapter_analysis_jobs import create_analysis_task

        for attempt in range(2):
            async with analysis_sessions() as db:
                task_id = await create_analysis_task(db, chapter_id=chapter_id, user_id=user_id, project_id=project_id)
            await analyze(chapter_id=chapter_id, user_id=user_id, project_id=project_id, task_id=task_id,
                          ai_service=ai_service, **extra_analyze)
            async with analysis_sessions() as db:
                task = await db.get(AnalysisTask, task_id)
                if task is not None and task.status == "completed":
                    return
            logger.warning("[Batch] 第 %d 章分析未完成（第 %d 次）", number, attempt + 1)
        state.warnings.append(f"第 {number} 章分析失败，后续章节缺少这一章的记忆")
        emit(number, chapter_id, "analysis_failed")

    async def settle_analysis() -> bool:
        """等上一章分析结束并过一致性闸门；需要暂停时返回 False。"""
        nonlocal pending_analysis, pending_meta
        if pending_analysis is None or pending_meta is None:
            return True
        number, chapter_id = pending_meta
        try:
            await pending_analysis
        finally:
            pending_analysis, pending_meta = None, None
        if options.pause_on_critical:
            async with session_factory() as db:
                critical = await _critical_count(db, chapter_id)
            if critical:
                state.paused_at = number
                state.message = f"第 {number} 章检测到 {critical} 个严重一致性问题，批量已暂停：修复后用同样范围重新发起即可接着写"
                emit(number, chapter_id, "paused", critical=critical)
                return False
        emit(number, chapter_id, "done")
        return True

    try:
        for idx, number in enumerate(numbers):
            base = idx / total * 100
            async with session_factory() as db:
                chapter = await _chapter_row(db, project_id, number)
                if (chapter is None or not chapter.chapter_outline_id) and options.auto_expand:
                    job.progress(f"第 {number} 章缺少章纲，自动规划中…", int(base))
                    try:
                        if await expand(db, project_id, number, ai_service):
                            await sync_chapters_from_outlines(db, project_id)
                            chapter = await _chapter_row(db, project_id, number)
                    except Exception as exc:  # noqa: BLE001 - 规划失败当作缺章纲处理
                        logger.warning("[Batch] 第 %d 章自动规划失败: %s", number, exc)
                        state.warnings.append(f"第 {number} 章自动规划失败：{exc}")
                if chapter is None or not chapter.chapter_outline_id:
                    state.message = f"第 {number} 章没有章纲（请先在谋篇页规划卷纲 / 生成章纲），批量在此停止"
                    emit(number, None, "no_outline")
                    break
                chapter_id, has_content = chapter.id, bool((chapter.content or "").strip())
                outline_row = await db.get(ChapterOutline, chapter.chapter_outline_id)
                outline_unconfirmed = outline_row is not None and (
                    outline_row.review_status == "draft" or bool(outline_row.upstream_stale)
                )
            if has_content:
                state.skipped.append(number)
                emit(number, chapter_id, "skipped")
                continue
            if options.require_confirmed_outline and outline_unconfirmed:
                state.message = (
                    f"第 {number} 章章纲未确认（AI 草拟或上游已改），批量在此停止：确认章纲后用同样范围重新发起即可接着写"
                )
                emit(number, chapter_id, "outline_unconfirmed")
                break

            view = _ChapterJobView(job, number, base, 100 / total)
            result: dict[str, Any] = {}
            quality_retry_used = False
            attempt = 0
            while True:
                attempt += 1
                emit(number, chapter_id, "generating", attempt=attempt)
                try:
                    result = await generate(view, chapter_id=chapter_id, user_id=user_id, ai_service=ai_service,
                                            options=gen_options)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 重试
                    if attempt > options.max_retries:
                        state.failed.append({"chapter_number": number, "error": str(exc)})
                        state.message = f"第 {number} 章连续 {attempt} 次生成失败：{exc}"
                        emit(number, chapter_id, "failed", error=str(exc))
                        break
                    emit(number, chapter_id, "retrying", attempt=attempt, error=str(exc))
                    await asyncio.sleep(options.retry_backoff * attempt)
                    continue
                reason = _quality_failed(result, options) if options.quality_gate else None
                if reason and not quality_retry_used:
                    quality_retry_used = True
                    emit(number, chapter_id, "quality_retry", reason=reason)
                    continue
                if reason:
                    state.warnings.append(f"第 {number} 章质检未过（{reason}），已保留")
                break
            if state.failed and state.failed[-1]["chapter_number"] == number:
                break
            candidate_id = (result or {}).get("candidate_id")
            if candidate_id:
                try:
                    await adopt(candidate_id)
                except Exception as exc:  # noqa: BLE001 - 采用失败按生成失败处理，批量停在这一章
                    state.failed.append({"chapter_number": number, "error": f"采用候选稿失败：{exc}"})
                    state.message = f"第 {number} 章候选稿采用失败：{exc}"
                    emit(number, chapter_id, "failed", error=str(exc))
                    break

            quality = (result or {}).get("quality") or {}
            emit(number, chapter_id, "generated", word_count=result.get("word_count"), quality_score=quality.get("score"))
            state.completed.append(number)
            if not await settle_analysis():
                break
            emit(number, chapter_id, "analyzing")
            pending_analysis = asyncio.create_task(run_analysis(number, chapter_id))
            pending_meta = (number, chapter_id)
            if not options.pipeline and not await settle_analysis():
                break
        if state.paused_at is None:
            await settle_analysis()
    except asyncio.CancelledError:
        if pending_analysis is not None and not pending_analysis.done():
            pending_analysis.cancel()
        raise

    status = "paused" if state.paused_at is not None else ("stopped" if state.failed or state.message else "completed")
    if status == "completed":
        state.message = f"批量完成：写了 {len(state.completed)} 章，跳过 {len(state.skipped)} 章"
    return {
        "status": status,
        "completed": state.completed,
        "skipped": state.skipped,
        "failed": state.failed,
        "paused_at": state.paused_at,
        "warnings": state.warnings,
        "message": state.message,
    }
