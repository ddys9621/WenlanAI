"""生成前的就绪检查：前置章节的分析是否还对得上正文（从未分析 / 分析后正文又改过）。

都是提醒，不阻断生成。分析结果绑定分析时的正文指纹；旧记录没有指纹时按「正文修改时间晚于分析时间」判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
