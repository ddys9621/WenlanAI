"""知识库查询：来源列表（含各类条目数）、条目列表、关键词检索、作者修改。

检索沿用岚笺的做法：查询按空白 / 标点切词，每个词都要命中（AND），在 search_text（NFKC 小写的键 + 标题 + 摘要 +
正文 + 标签）里找；% 和 _ 按字面匹配。P2 再加语义检索。来源列表按创建时间先后。
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KbEntry, KbSource
from app.services.knowledge.kb_import import search_text

MAX_TERMS = 16
_SPLIT = re.compile(r"[\s,;、。，；]+")


def query_terms(query: str) -> list[str]:
    text = unicodedata.normalize("NFKC", query or "").lower()
    return [t for t in _SPLIT.split(text) if t][:MAX_TERMS]


async def entry_counts(db: AsyncSession, source_ids: list[str]) -> dict[str, dict[str, int]]:
    if not source_ids:
        return {}
    rows = await db.execute(
        select(KbEntry.source_id, KbEntry.entry_type, func.count(KbEntry.id))
        .where(KbEntry.source_id.in_(source_ids))
        .group_by(KbEntry.source_id, KbEntry.entry_type)
    )
    out: dict[str, dict[str, int]] = {}
    for source_id, entry_type, count in rows.all():
        out.setdefault(source_id, {})[entry_type] = int(count)
    return out


async def list_sources(db: AsyncSession, user_id: str) -> list[KbSource]:
    return list((await db.execute(
        select(KbSource).where(KbSource.user_id == user_id).order_by(KbSource.created_at, KbSource.id)
        .execution_options(populate_existing=True)
    )).scalars().all())


async def get_source(db: AsyncSession, user_id: str, source_id: str) -> Optional[KbSource]:
    return (await db.execute(
        select(KbSource).where(KbSource.id == source_id, KbSource.user_id == user_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def get_entry(db: AsyncSession, user_id: str, entry_id: str) -> Optional[KbEntry]:
    return (await db.execute(
        select(KbEntry).where(KbEntry.id == entry_id, KbEntry.user_id == user_id)
    )).scalar_one_or_none()


async def list_entries(db: AsyncSession, source_id: str, entry_type: Optional[str] = None) -> list[KbEntry]:
    stmt = select(KbEntry).where(KbEntry.source_id == source_id)
    if entry_type:
        stmt = stmt.where(KbEntry.entry_type == entry_type)
    return list((await db.execute(stmt.order_by(KbEntry.sort_order))).scalars().all())


async def search_entries(
    db: AsyncSession, user_id: str, query: str, *, source_id: Optional[str] = None,
    entry_type: Optional[str] = None, limit: int = 20, offset: int = 0,
) -> tuple[list[KbEntry], int]:
    stmt = select(KbEntry).where(KbEntry.user_id == user_id)
    if source_id:
        stmt = stmt.where(KbEntry.source_id == source_id)
    if entry_type:
        stmt = stmt.where(KbEntry.entry_type == entry_type)
    for term in query_terms(query):
        stmt = stmt.where(KbEntry.search_text.contains(term, autoescape=True))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await db.execute(
        stmt.order_by(KbEntry.source_id, KbEntry.sort_order).limit(limit).offset(offset)
    )).scalars().all()
    return list(rows), total


def update_entry(entry: KbEntry, *, title: Optional[str] = None, summary: Optional[str] = None,
                 body: Optional[str] = None, denamed_body: Optional[str] = None) -> bool:
    changes = {k: v for k, v in (("title", title), ("summary", summary), ("body", body), ("denamed_body", denamed_body))
               if v is not None and v != getattr(entry, k)}
    if not changes:
        return False
    for key, value in changes.items():
        setattr(entry, key, value)
    tags = json.loads(entry.tags) if entry.tags else []
    entry.search_text = search_text(entry.entry_key, entry.title, entry.summary, entry.body, " ".join(tags))
    entry.origin, entry.status = "author", "confirmed"
    entry.revision = (entry.revision or 1) + 1
    return True
