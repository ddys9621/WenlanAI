"""世界设定条目服务：CRUD + 语义检索注入。

向量部分复用共享的 embedding_runtime（与 WorldRuleService / MemoryService 同一份 ChromaDB + 向量模型）：
集合名带向量模型指纹，换模型后新集合为空时第一次检索自动补齐；向量不可用时一律优雅降级为按库直接列出。
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.setting_entry import SettingEntry
from app.services.embedding_runtime import (
    collection_suffix, encode_texts, get_chroma_client, get_embedding_model, query_instruction, register_consumer,
)
from app.services.generation_trace import trace_reference

logger = get_logger(__name__)

CATEGORY_LABELS = {
    "term": "术语", "law": "铁律", "faction": "势力", "rule": "规则", "other": "其他",
}
VALID_CATEGORIES = tuple(CATEGORY_LABELS)
SUMMARY_BUDGET = 6000


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


# ---------------- CRUD ----------------

async def list_entries(db: AsyncSession, project_id: str, category: Optional[str] = None) -> List[SettingEntry]:
    conditions = [SettingEntry.project_id == project_id]
    if category:
        conditions.append(SettingEntry.category == category)
    rows = await db.execute(
        select(SettingEntry).where(*conditions).order_by(SettingEntry.order_index.asc(), SettingEntry.created_at.asc())
    )
    return list(rows.scalars().all())


async def get_entry(db: AsyncSession, project_id: str, entry_id: str) -> Optional[SettingEntry]:
    entry = await db.get(SettingEntry, entry_id)
    if entry is None or entry.project_id != project_id:
        return None
    return entry


async def create_entry(db: AsyncSession, project_id: str, *, category: str, title: str, summary: str = "",
                       content: str = "", order_index: int = 0) -> SettingEntry:
    entry = SettingEntry(
        id=str(uuid.uuid4()), project_id=project_id, category=category or "other", title=title,
        summary=summary or "", content=content or "", order_index=order_index,
    )
    db.add(entry)
    await db.flush()
    return entry


def entry_view(entry: SettingEntry) -> dict:
    return {
        "id": entry.id, "project_id": entry.project_id, "category": entry.category,
        "category_label": category_label(entry.category), "title": entry.title, "summary": entry.summary or "",
        "content": entry.content or "", "order_index": entry.order_index or 0,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


# ---------------- 向量检索 ----------------

class SettingEntryIndex:
    """世界设定条目的向量索引（单例，接共享 ChromaDB）；任何一步失败都不抛给上层。"""

    _instance: Optional["SettingEntryIndex"] = None

    def __new__(cls) -> "SettingEntryIndex":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        try:
            self.client = get_chroma_client()
            self.embedding_model = get_embedding_model()
        except Exception as exc:  # noqa: BLE001 - 向量只是增强，初始化失败就降级
            logger.warning(f"⚠️ 设定条目向量索引初始化失败，降级为不检索：{exc}")
            self.client = None
            self.embedding_model = None
        register_consumer(self)  # 换向量模型时一起切集合

    def _available(self) -> bool:
        return bool(self.client) and self.embedding_model is not None

    def _collection(self, project_id: str):
        name = f"setting_entries_p_{hashlib.sha256(project_id.encode()).hexdigest()[:8]}{collection_suffix()}"
        return self.client.get_or_create_collection(name=name, metadata={"project_id": project_id, "type": "setting_entries"})

    @staticmethod
    def _text(entry: SettingEntry) -> str:
        parts = [f"分类：{category_label(entry.category)}", f"名称：{entry.title}"]
        if entry.summary:
            parts.append(f"简述：{entry.summary}")
        if entry.content:
            parts.append(f"详细：{entry.content}")
        return "\n".join(parts)

    async def _upsert(self, collection, entries: List[SettingEntry]) -> None:
        if not entries:
            return
        texts = [self._text(e) for e in entries]
        vectors = await asyncio.to_thread(encode_texts, self.embedding_model, texts)
        await asyncio.to_thread(
            collection.upsert, ids=[e.id for e in entries], embeddings=vectors, documents=texts,
            metadatas=[{"entry_id": e.id, "project_id": e.project_id, "category": e.category} for e in entries],
        )

    async def sync(self, entry: SettingEntry) -> None:
        if not self._available():
            return
        try:
            await self._upsert(self._collection(entry.project_id), [entry])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"⚠️ 设定条目向量化失败（{entry.title}）：{exc}")

    async def remove(self, project_id: str, entry_id: str) -> None:
        if not self._available():
            return
        try:
            await asyncio.to_thread(self._collection(project_id).delete, ids=[entry_id])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"⚠️ 设定条目向量删除失败（{entry_id}）：{exc}")

    async def search(self, db: AsyncSession, project_id: str, query: str, limit: int) -> List[SettingEntry]:
        if not self._available():
            return await list_entries(db, project_id)
        try:
            collection = self._collection(project_id)
            want = await list_entries(db, project_id)
            if not want:
                return []
            have = int(await asyncio.to_thread(collection.count))
            if have < len(want):  # 新集合 / 有新条目没进向量库：补齐（upsert 覆盖同 id，删掉的旧向量在下面按库过滤掉）
                await self._upsert(collection, want)
            embedding = (await asyncio.to_thread(
                encode_texts, self.embedding_model, [query_instruction() + (query or "")[:400]]
            ))[0]
            results = await asyncio.to_thread(
                collection.query, query_embeddings=[embedding], n_results=max(1, min(limit, len(want))),
            )
            ids = (results.get("ids") or [[]])[0]
            if not ids:
                return await list_entries(db, project_id)
            rows = (await db.execute(
                select(SettingEntry).where(SettingEntry.project_id == project_id, SettingEntry.id.in_(ids))
                .order_by(SettingEntry.order_index)
            )).scalars().all()
            return list(rows)
        except Exception as exc:  # noqa: BLE001 - 检索失败就退回按库列出
            logger.warning(f"⚠️ 设定条目向量检索失败，降级为列出全部：{exc}")
            return await list_entries(db, project_id)


def _format(entries: List[SettingEntry], heading: str) -> str:
    if not entries:
        return ""
    by_cat: dict[str, List[SettingEntry]] = {}
    for e in entries:
        by_cat.setdefault(e.category, []).append(e)
    parts = [heading]
    for category, items in by_cat.items():
        parts.append(f"### {category_label(category)}")
        for e in items:
            line = f"- **{e.title}**"
            if e.summary:
                line += f"：{e.summary}"
            if e.content:
                line += f"\n  {e.content}"
            parts.append(line)
    text = "\n".join(parts)
    return text[:SUMMARY_BUDGET]


async def generate_summary_text(db: AsyncSession, project_id: str, category: Optional[str] = None) -> str:
    """按库列出全部设定条目，格式化给 prompt（不检索）。"""
    return _format(await list_entries(db, project_id, category), "## 世界设定条目")


async def generate_summary_with_search(db: AsyncSession, project_id: str, query: str, limit: int = 6) -> str:
    """语义检索相关设定条目，格式化给 prompt；向量不可用 / 没命中时退回列出全部。"""
    entries = await setting_entry_index().search(db, project_id, query, limit)
    if not entries:
        return ""
    trace_reference(
        "setting_entries", "世界设定条目（语义检索）",
        [{"title": e.title, "detail": category_label(e.category)} for e in entries], query=(query or "")[:80],
    )
    return _format(entries, "## 相关世界设定条目（语义检索）")


_index: Optional[SettingEntryIndex] = None


def setting_entry_index() -> SettingEntryIndex:
    global _index
    if _index is None:
        _index = SettingEntryIndex()
    return _index
