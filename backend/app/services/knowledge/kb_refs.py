"""引用：生成结果对标了知识库哪一条（设计稿 6.6）。

K 编号只在这一次提示词里有效（KbContext.refs），落库时换成条目 id + 修订号；同一目标重新生成时整体替换。
条目被删或修订号变了 = 过期：界面标「对标已过期」，下次生成重新对位。
target：volume = 卷 id；unit = "卷id:单元序号"；chapter_outline = 章纲 id；chapter_candidate = 候选稿 id。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KbEntry, KnowledgeCitation

REF_PATTERN = re.compile(r"[Kk]\s*(\d{1,3})")


@dataclass
class KbRef:
    key: str
    entry_id: str
    entry_revision: int
    source_id: str
    entry_type: str
    label: str
    prompt_label: str
    reason: str
    span_index: Optional[int] = None


def normalize_ref(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    match = REF_PATTERN.search(value)
    return f"K{int(match.group(1))}" if match else None


async def clear_citations(db: AsyncSession, project_id: str, target_type: str, *,
                          target_ids: Optional[Iterable[str]] = None, prefix: Optional[str] = None) -> None:
    stmt = delete(KnowledgeCitation).where(
        KnowledgeCitation.project_id == project_id, KnowledgeCitation.target_type == target_type,
    )
    if target_ids is not None:
        stmt = stmt.where(KnowledgeCitation.target_id.in_(list(target_ids)))
    if prefix is not None:
        stmt = stmt.where(KnowledgeCitation.target_id.startswith(prefix, autoescape=True))
    await db.execute(stmt)


def _row(project_id: str, ref: KbRef, scene: str, target_type: str, target_id: str) -> KnowledgeCitation:
    return KnowledgeCitation(
        project_id=project_id, target_type=target_type, target_id=target_id, entry_id=ref.entry_id,
        entry_revision=ref.entry_revision, source_id=ref.source_id, scene=scene, label=ref.label[:255],
        reason=ref.reason[:500],
    )


async def save_citations(db: AsyncSession, project_id: str, refs: dict[str, KbRef], scene: str, target_type: str,
                         pairs: Iterable[tuple[str, Any]]) -> int:
    """每个目标按模型写的 ref 记一条；编号不在本次参考里的跳过。返回实际记下的条数。"""
    pairs = list(pairs)
    await clear_citations(db, project_id, target_type, target_ids=[target for target, _ in pairs])
    saved = 0
    for target_id, raw in pairs:
        key = normalize_ref(raw)
        ref = refs.get(key) if key else None
        if ref is not None:
            db.add(_row(project_id, ref, scene, target_type, target_id))
            saved += 1
    return saved


async def save_all_citations(db: AsyncSession, project_id: str, refs: dict[str, KbRef], scene: str, target_type: str,
                             target_id: str) -> int:
    """正文候选稿：本次注入的每一条都记下（正文不回填编号）。"""
    await clear_citations(db, project_id, target_type, target_ids=[target_id])
    for ref in refs.values():
        db.add(_row(project_id, ref, scene, target_type, target_id))
    return len(refs)


async def cited_entry(db: AsyncSession, project_id: str, target_type: str, target_id: str) -> Optional[KbEntry]:
    row = (await db.execute(
        select(KnowledgeCitation).where(
            KnowledgeCitation.project_id == project_id, KnowledgeCitation.target_type == target_type,
            KnowledgeCitation.target_id == target_id,
        ).order_by(KnowledgeCitation.created_at.desc())
    )).scalars().first()
    return await db.get(KbEntry, row.entry_id) if row is not None else None


async def citations_for(db: AsyncSession, project_id: str, target_type: str,
                        target_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    ids = [t for t in target_ids if t]
    if not ids:
        return {}
    rows = (await db.execute(
        select(KnowledgeCitation).where(
            KnowledgeCitation.project_id == project_id, KnowledgeCitation.target_type == target_type,
            KnowledgeCitation.target_id.in_(ids),
        ).order_by(KnowledgeCitation.target_id, KnowledgeCitation.created_at)
    )).scalars().all()
    entry_ids = {r.entry_id for r in rows}
    entries = {e.id: e for e in (await db.execute(select(KbEntry).where(KbEntry.id.in_(entry_ids)))).scalars().all()} \
        if entry_ids else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        entry = entries.get(r.entry_id)
        out.setdefault(r.target_id, []).append({
            "entry_id": r.entry_id, "source_id": r.source_id, "label": r.label, "reason": r.reason, "scene": r.scene,
            "stale": entry is None or (entry.revision or 1) != r.entry_revision,
        })
    return out
