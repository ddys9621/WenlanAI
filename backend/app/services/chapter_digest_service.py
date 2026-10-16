"""章节档案（摘要 + 章末状态）的读写规则。

- 分析写入：没有档案就建（source=ai）；AI 档案直接覆盖；作者改过的不覆盖，AI 结果放进建议字段
- 作者编辑 → source=author、清掉旧建议；采用建议 → 回到 AI 版本；忽略建议 → 只清建议
- 整章替换正文：AI 档案删掉（回到未分析）；作者档案留着（指纹对不上即显示「可能过期」）
- migrate_legacy_summaries：旧库 story_memories 里的章节摘要启动时一次性拷进来（同步函数，配合 run_sync）
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import delete, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_digest import ChapterDigest
from app.services.chapter_version_service import content_hash

SUMMARY_LIMIT = 1000
END_STATE_LIMIT = 500


def _clip(value: Optional[str], limit: int) -> str:
    return (value or "").strip()[:limit]


async def get_digest(db: AsyncSession, chapter_id: str) -> Optional[ChapterDigest]:
    return (await db.execute(select(ChapterDigest).where(ChapterDigest.chapter_id == chapter_id))).scalar_one_or_none()


async def upsert_from_analysis(
    db: AsyncSession, chapter: Chapter, *, summary: str, end_state: str, analyzed_hash: Optional[str],
) -> ChapterDigest:
    """分析结果写进档案（不提交）。"""
    summary, end_state = _clip(summary, SUMMARY_LIMIT), _clip(end_state, END_STATE_LIMIT)
    row = await get_digest(db, chapter.id)
    if row is None:
        row = ChapterDigest(project_id=chapter.project_id, chapter_id=chapter.id, source="ai")
        db.add(row)
    if row.source == "author":
        row.ai_summary, row.ai_end_state = summary, end_state or None
    else:
        row.summary, row.end_state, row.source = summary, end_state or None, "ai"
        row.ai_summary = row.ai_end_state = None
    row.content_hash = analyzed_hash
    return row


async def author_update(
    db: AsyncSession, chapter: Chapter, *, summary: Optional[str], end_state: Optional[str],
) -> ChapterDigest:
    """作者手改档案（不提交）。summary / end_state 为 None 表示不改这一项。"""
    row = await get_digest(db, chapter.id)
    if row is None:
        row = ChapterDigest(project_id=chapter.project_id, chapter_id=chapter.id, summary="")
        db.add(row)
    if summary is not None:
        row.summary = _clip(summary, SUMMARY_LIMIT)
    if end_state is not None:
        row.end_state = _clip(end_state, END_STATE_LIMIT) or None
    row.source = "author"
    row.ai_summary = row.ai_end_state = None
    return row


async def accept_suggestion(db: AsyncSession, chapter: Chapter) -> Optional[ChapterDigest]:
    row = await get_digest(db, chapter.id)
    if row is None or row.ai_summary is None:
        return row
    row.summary, row.end_state = row.ai_summary, row.ai_end_state
    row.source = "ai"
    row.ai_summary = row.ai_end_state = None
    return row


async def dismiss_suggestion(db: AsyncSession, chapter: Chapter) -> Optional[ChapterDigest]:
    row = await get_digest(db, chapter.id)
    if row is not None:
        row.ai_summary = row.ai_end_state = None
    return row


async def purge_for_replacement(db: AsyncSession, chapter_id: str) -> None:
    """整章替换正文：AI 档案删掉；作者档案保留（建议是针对旧稿的，一并清掉）。"""
    row = await get_digest(db, chapter_id)
    if row is None:
        return
    if row.source == "author":
        row.ai_summary = row.ai_end_state = None
    else:
        await db.delete(row)


async def delete_for_chapter(db: AsyncSession, chapter_id: str) -> None:
    await db.execute(delete(ChapterDigest).where(ChapterDigest.chapter_id == chapter_id))


def digest_view(row: Optional[ChapterDigest], chapter: Any) -> Optional[dict]:
    if row is None:
        return None
    return {
        "chapter_id": row.chapter_id,
        "summary": row.summary or "",
        "end_state": row.end_state or "",
        "source": row.source or "ai",
        "suggestion": (
            {"summary": row.ai_summary or "", "end_state": row.ai_end_state or ""} if row.ai_summary is not None else None
        ),
        "stale": bool(row.content_hash) and row.content_hash != content_hash(getattr(chapter, "content", None)),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def digests_by_number(
    db: AsyncSession,
    project_id: str,
    *,
    numbers: Optional[Iterable[int]] = None,
    before: Optional[int] = None,
) -> dict[int, ChapterDigest]:
    """章号 → 档案（按当前章号联表，章号改过也对得上）。"""
    query = (
        select(Chapter.chapter_number, ChapterDigest)
        .join(ChapterDigest, ChapterDigest.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id)
    )
    wanted = None if numbers is None else sorted({int(n) for n in numbers})
    if wanted is not None:
        if not wanted:
            return {}
        query = query.where(Chapter.chapter_number.in_(wanted))
    if before is not None:
        query = query.where(Chapter.chapter_number < before)
    return {number: row for number, row in (await db.execute(query)).all() if (row.summary or "").strip()}


def migrate_legacy_summaries(conn: Any) -> int:
    """旧库 story_memories(memory_type=chapter_summary) → chapter_digests，已有档案的章跳过；返回新建条数。"""
    tables = set(inspect(conn).get_table_names())
    if "story_memories" not in tables or "chapter_digests" not in tables:
        return 0
    rows = conn.execute(text(
        "SELECT sm.project_id, sm.chapter_id, sm.content, pa.content_hash FROM story_memories sm "
        "JOIN chapters c ON c.id = sm.chapter_id "
        "LEFT JOIN plot_analysis pa ON pa.chapter_id = sm.chapter_id "
        "WHERE sm.memory_type = 'chapter_summary' AND sm.content IS NOT NULL AND sm.content != '' "
        "AND NOT EXISTS (SELECT 1 FROM chapter_digests d WHERE d.chapter_id = sm.chapter_id)"
    )).fetchall()
    created: set[str] = set()
    for project_id, chapter_id, summary, analyzed_hash in rows:
        if chapter_id in created:
            continue
        created.add(chapter_id)
        conn.execute(ChapterDigest.__table__.insert().values(
            id=str(uuid.uuid4()), project_id=project_id, chapter_id=chapter_id,
            summary=_clip(summary, SUMMARY_LIMIT), source="ai", content_hash=analyzed_hash,
        ))
    return len(created)
