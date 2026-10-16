"""检索索引（向量库）：对账本派生条目（章节档案 / 事件 / 因果 / 伏笔）做语义检索。

真相在账本表里，这里随时可重建：换向量模型、导入项目、索引为空而账本不空时整体重建，不调用大模型。
- 集合名 wl2_u{用户}_p{项目}{模型指纹}：换模型 = 换集合；旧版（u_…_p_…）集合在重建 / 删项目时清掉
- 编码与 Chroma 调用都放进线程，不卡事件循环（分析 / 生成时行内补全、自动保存照常响应）
- 余弦距离、批量编码；bge 中文模型查询前加检索指令
缺模型 / 向量库故障时降级：所有方法空返回，召回器只用实体 / 关键词通道。
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.logger import get_logger
from app.services.embedding_runtime import (
    EMBEDDING_PATH, collection_suffix, encode_texts, get_chroma_client, get_embedding_model, get_embedding_model_name,
    query_instruction, register_consumer,
)
from app.services.story_index_items import IndexItem

logger = get_logger(__name__)

UPSERT_BATCH = 256


def _hashes(user_id: str, project_id: str) -> tuple[str, str]:
    return hashlib.sha256(user_id.encode()).hexdigest()[:8], hashlib.sha256(project_id.encode()).hexdigest()[:8]


def collection_name_for(user_id: str, project_id: str) -> str:
    """wl2_u{用户哈希}_p{项目哈希}{_e模型指纹}：≤ 63 字符、字母数字下划线（Chroma 命名规则）。"""
    user_hash, project_hash = _hashes(user_id, project_id)
    return f"wl2_u{user_hash}_p{project_hash}{collection_suffix()}"


def _project_prefixes(user_id: str, project_id: str) -> tuple[str, ...]:
    user_hash, project_hash = _hashes(user_id, project_id)
    return f"wl2_u{user_hash}_p{project_hash}", f"u_{user_hash}_p_{project_hash}"


@dataclass(frozen=True)
class IndexHit:
    id: str
    kind: str
    ref_id: str
    chapter_id: str
    chapter_number: int
    text: str
    similarity: float


class MemoryService:
    """单例：共享 embedding_runtime 里的 Chroma 客户端与向量模型。"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        try:
            self.client = get_chroma_client()
            self.embedding_model = get_embedding_model()
            if self.embedding_model is None:
                raise RuntimeError("无法加载任何 Embedding 模型")
            logger.info("✅ 检索索引服务初始化成功")
        except Exception as e:  # noqa: BLE001 - 降级而非崩溃
            logger.error(f"❌ 检索索引服务初始化失败: {e}")
            logger.error("⚠️ 将以「无向量检索」模式运行：召回只用人物 / 关键词匹配")
            logger.error(f"💡 修复方式：在「设置 → 记忆检索」里下载模型（即时生效），或把模型放入 {EMBEDDING_PATH} 后重启")
            self.client = None
            self.embedding_model = None
        register_consumer(self)  # 设置页换模型时由 embedding_runtime.switch_model 一起换
        self._initialized = True

    # ---------------- 基础 ----------------

    @property
    def available(self) -> bool:
        return self.client is not None and self.embedding_model is not None

    def _collection(self, user_id: str, project_id: str):
        if not self.available:
            raise RuntimeError("向量检索不可用（embedding 模型未加载）")
        name = collection_name_for(user_id, project_id)
        try:
            return self.client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine", "project_id": project_id}, embedding_function=None,
            )
        except TypeError:  # 老版本 chromadb 不认 embedding_function=None
            return self.client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine", "project_id": project_id})

    async def _encode(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(encode_texts, self.embedding_model, texts)

    @staticmethod
    def _metadata(item: IndexItem) -> dict[str, Any]:
        return {"kind": item.kind, "chapter_id": item.chapter_id, "chapter_number": int(item.chapter_number or 0),
                "ref_id": item.ref_id}

    # ---------------- 写 ----------------

    async def upsert_items(self, user_id: str, project_id: str, items: Iterable[IndexItem]) -> int:
        items = [i for i in items if i.text]
        if not items or not self.available:
            return 0
        try:
            collection = self._collection(user_id, project_id)
            done = 0
            for start in range(0, len(items), UPSERT_BATCH):
                batch = items[start:start + UPSERT_BATCH]
                vectors = await self._encode([i.text for i in batch])
                await asyncio.to_thread(
                    collection.upsert, ids=[i.id for i in batch], embeddings=vectors,
                    documents=[i.text for i in batch], metadatas=[self._metadata(i) for i in batch],
                )
                done += len(batch)
            return done
        except Exception as e:  # noqa: BLE001 - 索引写失败不影响账本，之后可重建
            logger.error(f"❌ 写入检索索引失败: {e}")
            return 0

    async def delete_items(self, user_id: str, project_id: str, ids: Iterable[str]) -> None:
        ids = [i for i in ids if i]
        if not ids or not self.available:
            return
        try:
            collection = self._collection(user_id, project_id)
            await asyncio.to_thread(collection.delete, ids=ids)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ 删除检索索引条目失败: {e}")

    async def delete_chapter_memories(self, user_id: str, project_id: str, chapter_id: str) -> bool:
        """删掉某章的全部索引条目。"""
        if not self.available:
            return False
        try:
            collection = self._collection(user_id, project_id)
            await asyncio.to_thread(collection.delete, where={"chapter_id": chapter_id})
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ 删除章节索引失败: {e}")
            return False

    async def refresh_chapter(self, user_id: str, project_id: str, chapter_id: str, items: Iterable[IndexItem]) -> int:
        """某章重新分析后：先清本章旧条目再写新条目（被删掉的事件 / 伏笔不会残留）。"""
        if not self.available:
            return 0
        await self.delete_chapter_memories(user_id, project_id, chapter_id)
        return await self.upsert_items(user_id, project_id, items)

    async def rebuild(self, user_id: str, project_id: str, items: Iterable[IndexItem]) -> int:
        """整体重建：删掉本项目的全部集合（含旧版 / 别的模型的），按当前模型重新编码写入。"""
        if not self.available:
            return 0
        await self.delete_project_memories(user_id, project_id)
        count = await self.upsert_items(user_id, project_id, items)
        logger.info(f"🧱 检索索引已重建: 项目 {project_id[:8]} 共 {count} 条（模型 {get_embedding_model_name()}）")
        return count

    async def delete_project_memories(self, user_id: str, project_id: str) -> bool:
        """删掉本项目所有版本 / 所有模型的集合。"""
        if self.client is None:
            return False
        prefixes = _project_prefixes(user_id, project_id)
        try:
            collections = await asyncio.to_thread(self.client.list_collections)
            for collection in collections:
                name = getattr(collection, "name", collection)
                if isinstance(name, str) and name.startswith(prefixes):
                    await asyncio.to_thread(self.client.delete_collection, name=name)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"❌ 删除项目检索索引失败: {e}")
            return False

    # ---------------- 读 ----------------

    async def count(self, user_id: str, project_id: str) -> int:
        if not self.available:
            return 0
        try:
            collection = self._collection(user_id, project_id)
            return int(await asyncio.to_thread(collection.count))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ 读取检索索引条数失败: {e}")
            return 0

    async def search(
        self,
        user_id: str,
        project_id: str,
        query: str,
        *,
        kinds: Optional[Iterable[str]] = None,
        before_chapter: Optional[int] = None,
        exclude_chapters: Optional[Iterable[int]] = None,
        limit: int = 20,
    ) -> list[IndexHit]:
        """语义检索：只在本章之前、排除给定章号（近程窗口里已经有全文 / 概要的章）。"""
        query = (query or "").strip()
        if not query or not self.available:
            return []
        try:
            collection = self._collection(user_id, project_id)
            total = int(await asyncio.to_thread(collection.count))
            if total == 0:
                return []
            conditions: list[dict] = []
            kinds = list(kinds or [])
            if kinds:
                conditions.append({"kind": {"$in": kinds}})
            if before_chapter is not None:
                conditions.append({"chapter_number": {"$lt": int(before_chapter)}})
            excluded = sorted({int(n) for n in (exclude_chapters or [])})
            if excluded:
                conditions.append({"chapter_number": {"$nin": excluded}})
            where = conditions[0] if len(conditions) == 1 else ({"$and": conditions} if conditions else None)
            vector = (await self._encode([query_instruction() + query[:400]]))[0]
            result = await asyncio.to_thread(
                collection.query, query_embeddings=[vector], n_results=max(1, min(limit, total)), where=where,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"❌ 检索索引查询失败: {e}")
            return []
        hits: list[IndexHit] = []
        ids = (result.get("ids") or [[]])[0]
        for i, item_id in enumerate(ids):
            meta = (result.get("metadatas") or [[]])[0][i] or {}
            distance = ((result.get("distances") or [[]])[0] or [1.0] * len(ids))[i]
            hits.append(IndexHit(
                id=item_id, kind=str(meta.get("kind") or ""), ref_id=str(meta.get("ref_id") or ""),
                chapter_id=str(meta.get("chapter_id") or ""), chapter_number=int(meta.get("chapter_number") or 0),
                text=(result.get("documents") or [[]])[0][i] or "", similarity=max(0.0, 1.0 - float(distance)),
            ))
        return hits

    async def index_status(self, user_id: str, project_id: str) -> dict[str, Any]:
        return {
            "available": self.available,
            "model": get_embedding_model_name(),
            "count": await self.count(user_id, project_id) if self.available else 0,
        }


memory_service = MemoryService()
