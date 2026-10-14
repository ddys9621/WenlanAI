"""全局智能助笔 · 「核对」清单：本书现在需要作者注意的事项（只读，不改任何数据）。

待确认 / 上游已改的章纲、未分析 / 分析过期的章节、待审的候选稿（章节与内容修改）、一致性问题。
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantFieldCandidate
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_outline import ChapterOutline
from app.models.memory import PlotAnalysis
from app.services.chapter_readiness_service import analysis_is_stale

LIMIT_PER_KIND = 20
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def project_checks(db: AsyncSession, project_id: str) -> dict:
    items: list[dict] = []

    outlines = (await db.execute(
        select(ChapterOutline)
        .where(ChapterOutline.project_id == project_id,
               or_(ChapterOutline.review_status == "draft", ChapterOutline.upstream_stale.is_(True)))
        .order_by(ChapterOutline.chapter_number).limit(LIMIT_PER_KIND)
    )).scalars().all()
    for o in outlines:
        stale = bool(o.upstream_stale)
        items.append({
            "kind": "outline_unconfirmed", "severity": "warning",
            "title": f"第{o.chapter_number}章章纲{'上游已改' if stale else '待确认'}《{o.title}》",
            "detail": (o.upstream_reason or "上游规划改过") if stale else "AI 草拟的章纲，确认后再写正文更稳",
            "page": "outline", "target_id": o.id, "chapter_number": o.chapter_number,
        })

    chapters = (await db.execute(
        select(Chapter.id, Chapter.chapter_number, Chapter.title, Chapter.content, Chapter.updated_at)
        .where(Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "")
        .order_by(Chapter.chapter_number)
    )).all()
    analyses = {a.chapter_id: a for a in (await db.execute(
        select(PlotAnalysis).where(PlotAnalysis.project_id == project_id)
    )).scalars().all()}
    missing = stale_rows = 0
    for row in chapters:
        analysis = analyses.get(row.id)
        if analysis is None and missing < LIMIT_PER_KIND:
            missing += 1
            items.append({"kind": "analysis_missing", "severity": "info", "title": f"第{row.chapter_number}章还没分析",
                          "detail": "没有记忆状态，后面章节写作时会缺这一章的前情", "page": "chapter-analysis",
                          "target_id": row.id, "chapter_number": row.chapter_number})
        elif analysis is not None and analysis_is_stale(analysis, row) and stale_rows < LIMIT_PER_KIND:
            stale_rows += 1
            items.append({"kind": "analysis_stale", "severity": "warning", "title": f"第{row.chapter_number}章分析已过期",
                          "detail": "分析之后正文又改过，记忆状态对不上了", "page": "chapter-analysis",
                          "target_id": row.id, "chapter_number": row.chapter_number})

    pending = (await db.execute(
        select(Chapter.id, Chapter.chapter_number, Chapter.title, func.count(ChapterCandidate.id))
        .join(ChapterCandidate, ChapterCandidate.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id, ChapterCandidate.status == "pending")
        .group_by(Chapter.id).order_by(Chapter.chapter_number).limit(LIMIT_PER_KIND)
    )).all()
    for chapter_id, number, title, count in pending:
        items.append({"kind": "candidate_pending", "severity": "info", "title": f"第{number}章有 {count} 份候选稿待审",
                      "detail": f"《{title}》：审阅后采用才会写入正文", "page": "chapter-analysis",
                      "target_id": chapter_id, "chapter_number": number})

    fields_pending = (await db.execute(
        select(AssistantFieldCandidate)
        .where(AssistantFieldCandidate.project_id == project_id, AssistantFieldCandidate.status == "candidate")
        .order_by(AssistantFieldCandidate.created_at.desc()).limit(LIMIT_PER_KIND)
    )).scalars().all()
    for c in fields_pending:
        items.append({"kind": "field_candidate", "severity": "info", "title": f"「{c.target_label}」有修改候选待确认",
                      "detail": c.reason or "在助笔对话里比较后应用或不用", "page": c.page or "", "target_id": c.id})

    issues = (await db.execute(
        select(ChapterConsistencyIssue).where(ChapterConsistencyIssue.project_id == project_id)
    )).scalars().all()
    issues = sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.chapter_number))[:LIMIT_PER_KIND]
    for i in issues:
        items.append({"kind": "consistency", "severity": i.severity, "title": f"第{i.chapter_number}章：{i.title}",
                      "detail": i.details, "page": "chapter-analysis", "target_id": i.chapter_id,
                      "chapter_number": i.chapter_number})

    return {"items": items, "counts": dict(Counter(item["kind"] for item in items))}
