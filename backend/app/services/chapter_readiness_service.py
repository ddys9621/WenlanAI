"""生成前的就绪检查：前置章节的分析是否还对得上正文（从未分析 / 分析后正文又改过）。

都是提醒，不阻断生成。分析结果绑定分析时的正文指纹；旧记录没有指纹时按「正文修改时间晚于分析时间」判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis
from app.services.chapter_version_service import content_hash


def analysis_is_stale(analysis: Any, chapter: Any) -> bool:
    recorded = getattr(analysis, "content_hash", None)
    if recorded:
        return recorded != content_hash(getattr(chapter, "content", None))
    created, updated = getattr(analysis, "created_at", None), getattr(chapter, "updated_at", None)
    return bool(created and updated and updated > created)


@dataclass
class PreviousChapterIssues:
    unanalyzed: list[Chapter] = field(default_factory=list)
    stale: list[Chapter] = field(default_factory=list)


async def previous_chapter_issues(db: AsyncSession, chapter: Chapter) -> PreviousChapterIssues:
    """本章之前有正文的章节里：哪些从未分析、哪些分析已过期（按章号升序）。"""
    issues = PreviousChapterIssues()
    if chapter.chapter_number <= 1:
        return issues
    previous = list((await db.execute(
        select(Chapter)
        .where(
            Chapter.project_id == chapter.project_id,
            Chapter.chapter_number < chapter.chapter_number,
            Chapter.content.isnot(None),
            Chapter.content != "",
        )
        .order_by(Chapter.chapter_number)
    )).scalars().all())
    if not previous:
        return issues
    analyses = {
        a.chapter_id: a
        for a in (await db.execute(
            select(PlotAnalysis).where(PlotAnalysis.chapter_id.in_([c.id for c in previous]))
        )).scalars().all()
    }
    for c in previous:
        analysis = analyses.get(c.id)
        if analysis is None:
            issues.unanalyzed.append(c)
        elif analysis_is_stale(analysis, c):
            issues.stale.append(c)
    return issues


async def analysis_statuses(
    db: AsyncSession, project_id: str, is_running: Optional[Callable[[str], bool]] = None,
    chapters: Optional[list] = None,
) -> dict[str, dict[str, Any]]:
    """章节目录用：每章分析状态 missing / ok / stale / failed / running，附失败原因或降级说明。

    不拉全部正文：只有「分析之后又改过」（updated_at 晚于分析时间）的章才取正文算指纹。
    failed = 最近一次分析失败（之前的结果若有仍保留在用）。chapters：调用方已查好的章节行（有 id / word_count / updated_at）。
    """
    if chapters is None:
        chapters = (await db.execute(
            select(Chapter.id, Chapter.word_count, Chapter.updated_at).where(Chapter.project_id == project_id)
        )).all()
    analyses = {row.chapter_id: row for row in (await db.execute(
        select(PlotAnalysis.chapter_id, PlotAnalysis.content_hash, PlotAnalysis.created_at)
        .where(PlotAnalysis.project_id == project_id)
    )).all()}
    latest: dict[str, Any] = {}
    for row in (await db.execute(
        select(AnalysisTask.chapter_id, AnalysisTask.status, AnalysisTask.error_message, AnalysisTask.created_at)
        .where(AnalysisTask.project_id == project_id).order_by(AnalysisTask.created_at)
    )).all():
        latest[row.chapter_id] = row
    # 分析记录的时间 = 读取正文的时刻；同一秒内改过的也算可疑（CURRENT_TIMESTAMP 只到秒）
    suspects = [
        c.id for c in chapters
        if c.id in analyses and (
            not c.updated_at or not analyses[c.id].created_at or c.updated_at >= analyses[c.id].created_at
        )
    ]
    contents = dict((await db.execute(
        select(Chapter.id, Chapter.content).where(Chapter.id.in_(suspects))
    )).all()) if suspects else {}

    out: dict[str, dict[str, Any]] = {}
    for chapter in chapters:
        if not (chapter.word_count or 0):
            continue
        task, analysis = latest.get(chapter.id), analyses.get(chapter.id)
        if is_running is not None and is_running(chapter.id):
            out[chapter.id] = {"status": "running", "message": None}
            continue
        if analysis is None:
            failed = task is not None and task.status == "failed"
            out[chapter.id] = {"status": "failed" if failed else "missing", "message": task.error_message if failed else None}
            continue
        stale = False
        if chapter.id in contents:
            stale = (analysis.content_hash != content_hash(contents[chapter.id])) if analysis.content_hash else True
        status, message = ("stale" if stale else "ok"), None
        if task is not None and task.status == "failed" and task.created_at and analysis.created_at \
                and task.created_at >= analysis.created_at:
            status, message = "failed", task.error_message
        elif task is not None and task.status == "completed" and task.error_message:
            message = task.error_message  # 完成但有降级说明（如人物与标注没抽出来）
        out[chapter.id] = {"status": status, "message": message}
    return out


def chapter_brief(chapter: Chapter) -> dict:
    return {"id": chapter.id, "chapter_number": chapter.chapter_number, "title": chapter.title}


def previous_issues_message(issues: PreviousChapterIssues) -> str:
    parts = []
    if issues.unanalyzed:
        numbers = ", ".join(str(c.chapter_number) for c in issues.unanalyzed)
        parts.append(f"前面有 {len(issues.unanalyzed)} 章尚未分析（缺少记忆状态）：第 {numbers} 章。")
    if issues.stale:
        numbers = ", ".join(str(c.chapter_number) for c in issues.stale)
        parts.append(f"有 {len(issues.stale)} 章分析后正文又改过（记忆状态已过期）：第 {numbers} 章。")
    if not parts:
        return ""
    return "".join(parts) + "缺少或过期的记忆状态可能影响续写的剧情连贯性，是否继续生成？"
