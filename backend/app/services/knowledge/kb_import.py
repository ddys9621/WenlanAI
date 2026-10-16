"""拆书结果 → 知识库：确定性转换（不调模型），按（来源，条目键）幂等写入。

- 拆书完成时 extractor_v5 调 import_dissect_task；打开书架时 ensure_dissect_sources 给还没入库的已完成拆书补导
- 生成的条目内容变了才更新（revision + 1，回到「未核对」）；作者改过的（origin=author）不覆盖，只标 upstream_changed
- 重新拆书后不再产出的条目：生成的删掉；作者改过的保留并标 upstream_changed
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import fields
from pathlib import PurePath
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.book_dissect_chapter_fact import BookDissectChapterFact
from app.models.book_dissect_story_arc import BookDissectStoryArc
from app.models.book_dissect_task import BookDissectTask
from app.models.knowledge import KbEntry, KbProjectLink, KbSource
from app.models.reference_pack import ReferencePack
from app.services.book_dissect.v5_types import ChapterCard, StoryArc
from app.services.knowledge.dissect_entries import DissectSnapshot, EntryDraft, build_entries

logger = get_logger(__name__)
READY_PACK_STATUSES = ("ready", "partial")
_ARC_FIELDS = frozenset(f.name for f in fields(StoryArc))


def _json(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _book_title(raw: str) -> str:
    text = (raw or "").strip()
    if text.lower().endswith((".txt", ".md")):
        text = PurePath(text).stem
    return text or "未命名拆书"


def search_text(*parts: Any) -> str:
    return unicodedata.normalize("NFKC", "\n".join(str(p) for p in parts if p)).lower()


def draft_hash(d: EntryDraft) -> str:
    payload = [d.entry_type, d.title, d.summary, d.body, d.denamed_body, d.data, d.tags, d.chapter_start,
               d.chapter_end, d.volume_index, d.arc_index, d.position, d.sort_order]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_draft(row: KbEntry, d: EntryDraft, digest: str) -> None:
    row.entry_type, row.layer = d.entry_type, d.layer
    row.title, row.summary = d.title[:255], d.summary[:500]
    row.body, row.denamed_body = d.body, d.denamed_body
    row.data_json = json.dumps(d.data, ensure_ascii=False, default=str)
    row.tags = json.dumps(d.tags, ensure_ascii=False)
    row.chapter_start, row.chapter_end = d.chapter_start, d.chapter_end
    row.volume_index, row.arc_index, row.position, row.sort_order = d.volume_index, d.arc_index, d.position, d.sort_order
    row.search_text = search_text(d.entry_key, d.title, d.summary, d.body, " ".join(d.tags))
    row.generated_hash = digest
    row.origin, row.status, row.upstream_changed = "generated", "unreviewed", 0


async def load_snapshot(db: AsyncSession, task: BookDissectTask) -> Optional[DissectSnapshot]:
    pack = (await db.execute(select(ReferencePack).where(ReferencePack.task_id == task.id))).scalar_one_or_none()
    facts = (await db.execute(
        select(BookDissectChapterFact.fact_json).where(
            BookDissectChapterFact.task_id == task.id, BookDissectChapterFact.extraction_status == "success",
        )
    )).scalars().all()
    cards = [ChapterCard.from_dict(d) for d in map(_json, facts) if isinstance(d, dict) and d.get("chapter_number")]
    arc_rows = (await db.execute(
        select(BookDissectStoryArc.arc_json).where(BookDissectStoryArc.task_id == task.id)
    )).scalars().all()
    arc_dicts = [d for d in map(_json, arc_rows) if isinstance(d, dict)]
    arcs = [StoryArc.from_dict(d) for d in arc_dicts]
    arc_extras = {a.arc_index: {k: v for k, v in d.items() if k not in _ARC_FIELDS} for a, d in zip(arcs, arc_dicts)}
    if pack is None and not cards:
        return None
    dims: dict[str, Any] = {}
    if pack is not None:
        dims = {
            "synopsis": _json(pack.synopsis_json), "characters": _json(pack.character_archive_json),
            "methodology": _json(pack.methodology_json), "structure": _json(pack.structure_json),
            "style": _json(pack.style_json),
        }
    return DissectSnapshot(
        title=_book_title(pack.source_book_title if pack is not None else (task.file_name or "")),
        chapter_count=task.chapter_count or len(cards), total_words=task.total_words or 0,
        cards=cards, arcs=arcs, arc_extras=arc_extras, **dims,
    )


async def _upsert(db: AsyncSession, source: KbSource, drafts: list[EntryDraft]) -> int:
    existing = {e.entry_key: e for e in (await db.execute(
        select(KbEntry).where(KbEntry.source_id == source.id)
    )).scalars().all()}
    changed = 0
    for d in drafts:
        digest = draft_hash(d)
        row = existing.pop(d.entry_key, None)
        if row is None:
            row = KbEntry(user_id=source.user_id, source_id=source.id, entry_key=d.entry_key)
            apply_draft(row, d, digest)
            db.add(row)
            changed += 1
        elif row.generated_hash != digest:
            if row.origin == "author":
                if not row.upstream_changed:
                    row.upstream_changed = 1
                    changed += 1
            else:
                apply_draft(row, d, digest)
                row.revision = (row.revision or 1) + 1
                changed += 1
    for row in existing.values():
        if row.origin == "author":
            if not row.upstream_changed:
                row.upstream_changed = 1
                changed += 1
        else:
            await db.delete(row)
            changed += 1
    return changed


async def import_dissect_task(db: AsyncSession, task_id: str, user_id: str) -> Optional[KbSource]:
    task = (await db.execute(
        select(BookDissectTask).where(BookDissectTask.id == task_id, BookDissectTask.user_id == user_id)
    )).scalar_one_or_none()
    if task is None:
        return None
    snap = await load_snapshot(db, task)
    if snap is None:
        return None
    source = (await db.execute(select(KbSource).where(KbSource.dissect_task_id == task_id))).scalar_one_or_none()
    if source is None:
        source = KbSource(user_id=user_id, kind="dissect", dissect_task_id=task_id, title=snap.title[:255])
        db.add(source)
        await db.flush()
    source.chapter_count, source.total_words = snap.chapter_count, snap.total_words
    if not source.genre:
        synopsis = snap.synopsis if isinstance(snap.synopsis, dict) else {}
        source.genre = str(synopsis.get("genre_tag") or "").strip()[:50] or None
    changed = await _upsert(db, source, build_entries(snap))
    await db.commit()
    logger.info("[知识库] 拆书 task=%s → 来源 %s，变动 %d 条", task_id, source.id, changed)
    return source


async def ensure_dissect_sources(db: AsyncSession, user_id: str) -> int:
    done = set((await db.execute(
        select(KbSource.dissect_task_id).where(KbSource.user_id == user_id, KbSource.dissect_task_id.isnot(None))
    )).scalars().all())
    task_ids = (await db.execute(
        select(BookDissectTask.id)
        .join(ReferencePack, ReferencePack.task_id == BookDissectTask.id)
        .where(BookDissectTask.user_id == user_id, BookDissectTask.status == "completed",
               ReferencePack.status.in_(READY_PACK_STATUSES))
        .order_by(BookDissectTask.created_at)
    )).scalars().all()
    imported = 0
    for task_id in task_ids:
        if task_id not in done and await import_dissect_task(db, task_id, user_id) is not None:
            imported += 1
    return imported


async def delete_source_rows(db: AsyncSession, source_ids: list[str]) -> None:
    """删来源：条目与项目对标关联一起删（引用保留，界面按「条目不存在」标过期）。不 commit。"""
    if source_ids:
        await db.execute(delete(KbEntry).where(KbEntry.source_id.in_(source_ids)))
        await db.execute(delete(KbProjectLink).where(KbProjectLink.source_id.in_(source_ids)))
        await db.execute(delete(KbSource).where(KbSource.id.in_(source_ids)))


async def delete_dissect_source(db: AsyncSession, task_id: str) -> None:
    ids = (await db.execute(select(KbSource.id).where(KbSource.dissect_task_id == task_id))).scalars().all()
    await delete_source_rows(db, list(ids))


async def regenerate_entry(db: AsyncSession, entry: KbEntry) -> bool:
    source = await db.get(KbSource, entry.source_id)
    task = await db.get(BookDissectTask, source.dissect_task_id) if source is not None and source.dissect_task_id else None
    snap = await load_snapshot(db, task) if task is not None else None
    draft = next((d for d in build_entries(snap) if d.entry_key == entry.entry_key), None) if snap is not None else None
    if draft is None:
        return False
    apply_draft(entry, draft, draft_hash(draft))
    entry.revision = (entry.revision or 1) + 1
    return True
