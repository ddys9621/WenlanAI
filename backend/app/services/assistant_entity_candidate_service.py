"""全局智能助笔 · 新建对象候选：工具只记下要新建的角色 / 组织 / 设定条目，作者「应用」才真正建行，可放弃。

与 assistant_candidate_service（改既有字段）互补：那边管「改已有的」，这边管「从无到有创建新对象」。
- 生成候选时按对象类型校验字段（类型 / 长度 / 取值），只落候选表，不碰真实对象
- 作者应用才 INSERT 真实行，并把新建行的 id 记进候选（created_entity_id），供跳转 / 去重
- 字段上限与 Character 列、assistant_fields 的白名单保持一致
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate
from app.models.chapter_candidate import utcnow
from app.models.character import Character
from app.models.setting_entry import SETTING_CATEGORIES


class EntityError(Exception):
    status_code = 400


class EntityConflict(EntityError):
    status_code = 409


class EntityNotFound(EntityError):
    status_code = 404


@dataclass(frozen=True)
class FieldDef:
    key: str
    name: str
    max_length: int
    required: bool = False
    choices: tuple[str, ...] = ()


# 角色字段（上限与 Character 列、assistant_fields 对齐）
_CHARACTER_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("name", "姓名", 100, required=True),
    FieldDef("role_type", "角色类型", 50, choices=("protagonist", "supporting", "antagonist")),
    FieldDef("age", "年龄", 50),
    FieldDef("gender", "性别", 50),
    FieldDef("personality", "性格", 5000),
    FieldDef("background", "背景故事", 20000),
    FieldDef("appearance", "外貌", 5000),
    FieldDef("speech_style", "说话风格", 5000),
)
# 组织字段
_ORGANIZATION_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("name", "名称", 100, required=True),
    FieldDef("personality", "组织特性", 5000),
    FieldDef("background", "背景", 20000),
    FieldDef("organization_type", "组织类型", 100),
    FieldDef("organization_purpose", "宗旨", 500),
)

# 世界设定条目字段（术语 / 铁律 / 势力 / 规则等）
_SETTING_ENTRY_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("title", "名称", 200, required=True),
    FieldDef("category", "分类", 50, choices=SETTING_CATEGORIES),
    FieldDef("summary", "简述", 2000),
    FieldDef("content", "详细设定", 20000),
)

ENTITY_FIELDS: dict[str, tuple[FieldDef, ...]] = {
    "character": _CHARACTER_FIELDS,
    "organization": _ORGANIZATION_FIELDS,
    "setting_entry": _SETTING_ENTRY_FIELDS,
}
ENTITY_PAGE = {"character": "characters", "organization": "characters", "setting_entry": "setting-entries"}
ENTITY_LABEL = {"character": "角色", "organization": "组织", "setting_entry": "设定条目"}
ENTITY_NAME_KEY = {"character": "name", "organization": "name", "setting_entry": "title"}


def _clean_field(field: FieldDef, value: Any) -> Optional[str]:
    if value is None:
        if field.required:
            raise EntityError(f"缺少{field.name}")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise EntityError(f"{field.name}应是一段文字")
    text = str(value).strip()
    if not text:
        if field.required:
            raise EntityError(f"缺少{field.name}")
        return None
    if len(text) > field.max_length:
        raise EntityError(f"{field.name}不超过 {field.max_length} 字（现在 {len(text)} 字）")
    if field.choices and text not in field.choices:
        raise EntityError(f"{field.name}只能是 {'/'.join(field.choices)}")
    return text


def normalize_entity_payload(entity_type: str, raw: Any) -> dict[str, str]:
    """按对象类型校验并规整字段；只保留白名单内、非空的字段。"""
    fields = ENTITY_FIELDS.get(entity_type)
    if fields is None:
        raise EntityError(f"不支持新建这种对象：{entity_type}")
    if not isinstance(raw, dict):
        raise EntityError("新建内容应是一组字段")
    out: dict[str, str] = {}
    for field in fields:
        cleaned = _clean_field(field, raw.get(field.key))
        if cleaned is not None:
            out[field.key] = cleaned
    return out


async def create_entity_candidate(
    db: AsyncSession, *, project_id: str, session_id: Optional[str], run_id: Optional[str],
    entity_type: str, payload: Any, reason: str = "",
) -> AssistantEntityCandidate:
    normalized = normalize_entity_payload(entity_type, payload)
    display = normalized[ENTITY_NAME_KEY[entity_type]]
    label = f"新建{ENTITY_LABEL[entity_type]}「{display}」"
    candidate = AssistantEntityCandidate(
        project_id=project_id, session_id=session_id, run_id=run_id, entity_type=entity_type,
        payload_json=json.dumps(normalized, ensure_ascii=False), label=label[:300],
        page=ENTITY_PAGE[entity_type], reason=(reason or "")[:1000], status="candidate",
    )
    db.add(candidate)
    await db.flush()
    return candidate


def _payload(candidate: AssistantEntityCandidate) -> dict:
    try:
        return json.loads(candidate.payload_json) if candidate.payload_json else {}
    except (TypeError, ValueError):
        return {}


def entity_candidate_view(candidate: AssistantEntityCandidate) -> dict:
    return {
        "id": candidate.id,
        "entity_type": candidate.entity_type,
        "label": candidate.label,
        "page": candidate.page,
        "payload": _payload(candidate),
        "reason": candidate.reason or "",
        "status": candidate.status,
        "run_id": candidate.run_id,
        "created_entity_id": candidate.created_entity_id,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }


async def apply_entity_candidate(db: AsyncSession, candidate: AssistantEntityCandidate) -> str:
    """作者应用：真正建行。返回新建行的 id。"""
    if candidate.status != "candidate":
        raise EntityConflict("这份候选已经处理过了")
    payload = _payload(candidate)
    if candidate.entity_type in ("character", "organization"):
        entity_id = await _create_character(db, candidate.project_id, candidate.entity_type, payload)
    elif candidate.entity_type == "setting_entry":
        entity_id = await _create_setting_entry(db, candidate.project_id, payload)
    else:
        raise EntityError(f"不支持新建这种对象：{candidate.entity_type}")
    candidate.status = "applied"
    candidate.created_entity_id = entity_id
    candidate.decided_at = utcnow()
    return entity_id


async def _create_character(db: AsyncSession, project_id: str, entity_type: str, payload: dict) -> str:
    entity_id = str(uuid.uuid4())
    character = Character(
        id=entity_id, project_id=project_id, is_organization=(entity_type == "organization"),
        name=payload["name"], role_type=payload.get("role_type"), age=payload.get("age"),
        gender=payload.get("gender"), personality=payload.get("personality"), background=payload.get("background"),
        appearance=payload.get("appearance"), speech_style=payload.get("speech_style"),
        organization_type=payload.get("organization_type"), organization_purpose=payload.get("organization_purpose"),
    )
    db.add(character)
    await db.flush()
    return entity_id


async def _create_setting_entry(db: AsyncSession, project_id: str, payload: dict) -> str:
    from app.services import setting_entry_service  # 延迟导入，避免把向量依赖拉进工具导入链
    entry = await setting_entry_service.create_entry(
        db, project_id, category=payload.get("category") or "other", title=payload["title"],
        summary=payload.get("summary", ""), content=payload.get("content", ""),
    )
    return entry.id


async def reject_entity_candidate(db: AsyncSession, candidate: AssistantEntityCandidate) -> None:
    if candidate.status != "candidate":
        raise EntityConflict("这份候选已经处理过了")
    candidate.status = "rejected"
    candidate.decided_at = utcnow()
