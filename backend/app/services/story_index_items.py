"""检索索引的条目：全部从账本表派生（章节档案 / 时间轴事件 / 因果 / 伏笔），向量库只是随时可重建的索引。

条目 id = 「类别:行 id」；每条带 chapter_id / chapter_number，按章刷新、按章过滤。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_digest import ChapterDigest
from app.models.narrative_promise import NarrativePromise
from app.models.timeline_event import TimelineEvent

KINDS = ("digest", "event", "causal", "promise")
RECALL_KINDS = ("digest", "event", "causal")


@dataclass(frozen=True)
class IndexItem:
    id: str
    kind: str
    text: str
    chapter_id: str
    chapter_number: int
    ref_id: str


def _join(*parts: Optional[str], sep: str = "；") -> str:
    return sep.join(p.strip() for p in parts if p and p.strip())


def digest_text(summary: Optional[str], end_state: Optional[str]) -> str:
    return _join(summary, f"章末：{end_state}" if end_state else None)


def event_text(title: Optional[str], description: Optional[str], location: Optional[str] = None,
               time_marker: Optional[str] = None) -> str:
    where = _join(location, time_marker, sep=" ")
    return _join(f"{title}：{description}" if title and description else (title or description),
                 f"（{where}）" if where else None, sep="")


def causal_text(cause: Optional[str], event: Optional[str], effect: Optional[str]) -> str:
    return _join(cause, event, effect, sep=" → ")


async def _items(db: AsyncSession, project_id: str, chapter_ids: Optional[Iterable[str]]) -> list[IndexItem]:
    ids = None if chapter_ids is None else list(chapter_ids)
    items: list[IndexItem] = []

    digest_q = (
        select(Chapter.id, Chapter.chapter_number, ChapterDigest.summary, ChapterDigest.end_state)
        .join(ChapterDigest, ChapterDigest.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id)
    )
    if ids is not None:
        digest_q = digest_q.where(Chapter.id.in_(ids))
    for chapter_id, number, summary, end_state in (await db.execute(digest_q)).all():
        text = digest_text(summary, end_state)
        if text:
            items.append(IndexItem(f"digest:{chapter_id}", "digest", text, chapter_id, number or 0, chapter_id))

    timeline_q = select(TimelineEvent).where(TimelineEvent.project_id == project_id)
    if ids is not None:
        timeline_q = timeline_q.where(TimelineEvent.chapter_id.in_(ids))
    for row in (await db.execute(timeline_q)).scalars():
        text = event_text(row.title, row.description, row.location, row.time_marker)
        if text and row.chapter_id:
            items.append(IndexItem(f"event:{row.id}", "event", text, row.chapter_id, row.chapter_number or 0, row.id))

    causal_q = select(ChapterCausalLink).where(ChapterCausalLink.project_id == project_id)
    if ids is not None:
        causal_q = causal_q.where(ChapterCausalLink.chapter_id.in_(ids))
    for row in (await db.execute(causal_q)).scalars():
        text = causal_text(row.cause, row.event, row.effect)
        if text and row.chapter_id:
            items.append(IndexItem(f"causal:{row.id}", "causal", text, row.chapter_id, row.chapter_number or 0, row.id))

    promise_q = select(NarrativePromise).where(NarrativePromise.project_id == project_id)
    if ids is not None:
        promise_q = promise_q.where(NarrativePromise.source_chapter_id.in_(ids))
    for row in (await db.execute(promise_q)).scalars():
        text = _join(row.title, row.content if row.content != row.title else None, sep="：")
        if text and row.source_chapter_id:
            items.append(IndexItem(f"promise:{row.id}", "promise", text, row.source_chapter_id,
                                   row.source_chapter_number or 0, row.id))
    return items


async def promise_items(db: AsyncSession, project_id: str, promise_ids: Iterable[str]) -> list[IndexItem]:
    ids = [i for i in promise_ids if i]
    if not ids:
        return []
    rows = (await db.execute(
        select(NarrativePromise).where(NarrativePromise.project_id == project_id, NarrativePromise.id.in_(ids))
    )).scalars().all()
    return [
        IndexItem(f"promise:{row.id}", "promise", _join(row.title, row.content if row.content != row.title else None, sep="："),
                  row.source_chapter_id, row.source_chapter_number or 0, row.id)
        for row in rows if row.source_chapter_id
    ]


async def chapter_items(db: AsyncSession, project_id: str, chapter_id: str) -> list[IndexItem]:
    return await _items(db, project_id, [chapter_id])


async def project_items(db: AsyncSession, project_id: str) -> list[IndexItem]:
    return await _items(db, project_id, None)


async def project_item_count(db: AsyncSession, project_id: str) -> int:
    """账本里有多少可索引的章节档案（用来判断索引是否需要重建：账本有内容而索引为空）。"""
    rows = await db.execute(
        select(ChapterDigest.id).join(Chapter, Chapter.id == ChapterDigest.chapter_id).where(Chapter.project_id == project_id)
    )
    return len(rows.all())
