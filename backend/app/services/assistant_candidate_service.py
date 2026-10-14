"""全局智能助笔 · 字段修改候选：生成时记下修改前，作者「应用」才写入，可撤销（参考岚笺 FieldAssistantCandidate）。

- 应用前核对：这项内容仍等于生成时的「修改前」，否则拒绝（不覆盖作者在别处的修改）
- 撤销前核对：这项内容仍等于「修改后」，否则拒绝（应用后作者又改过）
- 修改后与原值相同不算候选
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantFieldCandidate
from app.models.chapter_candidate import utcnow
from app.services import assistant_fields as fields


def _loads(raw: Optional[str]) -> Any:
    return json.loads(raw) if raw else ""


async def create_field_candidate(
    db: AsyncSession, *, project_id: str, session_id: Optional[str], run_id: Optional[str],
    field_id: str, target_id: str, value: Any, reason: str = "",
) -> AssistantFieldCandidate:
    current = await fields.read_field(db, project_id, field_id, target_id)
    after = fields.normalize_value(fields.spec_of(field_id), value)
    if after == current["value"]:
        raise fields.FieldError("修改后的内容和现在一样，没有生成候选")
    candidate = AssistantFieldCandidate(
        project_id=project_id, session_id=session_id, run_id=run_id, field_id=field_id, target_id=current["target_id"],
        target_label=current["label"][:300], page=current["page"],
        before_json=json.dumps(current["value"], ensure_ascii=False), after_json=json.dumps(after, ensure_ascii=False),
        reason=(reason or "")[:1000], status="candidate",
    )
    db.add(candidate)
    await db.flush()
    return candidate


def candidate_view(candidate: AssistantFieldCandidate) -> dict:
    return {
        "id": candidate.id,
        "field_id": candidate.field_id,
        "target_id": candidate.target_id,
        "entity": fields.entity_of(candidate.field_id),
        "label": candidate.target_label,
        "page": candidate.page,
        "before": _loads(candidate.before_json),
        "after": _loads(candidate.after_json),
        "reason": candidate.reason or "",
        "status": candidate.status,
        "run_id": candidate.run_id,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }


async def _current(db: AsyncSession, candidate: AssistantFieldCandidate) -> Any:
    return (await fields.read_field(db, candidate.project_id, candidate.field_id, candidate.target_id))["value"]


async def apply_candidate(db: AsyncSession, candidate: AssistantFieldCandidate) -> None:
    if candidate.status != "candidate":
        raise fields.FieldConflict("这份候选已经处理过了")
    if await _current(db, candidate) != _loads(candidate.before_json):
        raise fields.FieldConflict("这项内容在生成候选之后被改过，为免覆盖你的修改没有应用；可以让助笔按现在的内容重新生成")
    await fields.write_field(db, candidate.project_id, candidate.field_id, candidate.target_id, _loads(candidate.after_json))
    candidate.status = "applied"
    candidate.decided_at = utcnow()


async def undo_candidate(db: AsyncSession, candidate: AssistantFieldCandidate) -> None:
    if candidate.status != "applied":
        raise fields.FieldConflict("只有已应用的候选可以撤销")
    if await _current(db, candidate) != _loads(candidate.after_json):
        raise fields.FieldConflict("应用之后这项内容又被改过，撤销会覆盖你的修改，已停止")
    await fields.write_field(db, candidate.project_id, candidate.field_id, candidate.target_id, _loads(candidate.before_json))
    candidate.status = "undone"
    candidate.decided_at = utcnow()


async def reject_candidate(db: AsyncSession, candidate: AssistantFieldCandidate) -> None:
    if candidate.status != "candidate":
        raise fields.FieldConflict("这份候选已经处理过了")
    candidate.status = "rejected"
    candidate.decided_at = utcnow()
