"""全局智能助笔 · 新建对象候选：工具只记下要新建的角色 / 组织 / 设定条目 / 世界规则，作者「应用」才真正建行，可放弃。

与 assistant_candidate_service（改既有字段）互补：那边管「改已有的」，这边管「从无到有创建新对象」。
- 生成候选时按对象类型校验字段（类型 / 长度 / 取值），只落候选表，不碰真实对象
- 作者应用才 INSERT 真实行，并把新建行的 id 记进候选（created_entity_id），供跳转 / 去重
- 建档与页面手动新建同一套连带处理：组织同时建组织详情（组织管理页按它列），「地图位置」规则出现在世界地图上，
  世界规则进向量索引
- 字段上限与 Character 列、assistant_fields 的白名单保持一致
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate
from app.models.chapter_candidate import utcnow
from app.models.character import Character
from app.models.setting_entry import SETTING_CATEGORIES, SettingEntry
from app.models.world_rule import WorldRule
from app.services import world_map_service as wms
from app.services.assistant_fields import ROLE_TYPES, WORLD_RULE_LABELS, sync_world_rule
from app.utils.data_consistency import ensure_organization_record
from app.utils.role_type import normalize_role_type


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


# 角色字段（上限与 Character 列、assistant_fields 对齐；顺序 = 卡片上的显示顺序，短的在前）
_CHARACTER_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("name", "姓名", 100, required=True),
    FieldDef("role_type", "角色类型", 50, choices=ROLE_TYPES),
    FieldDef("age", "年龄", 50),
    FieldDef("gender", "性别", 50),
    FieldDef("appearance", "外貌", 5000),
    FieldDef("speech_style", "说话风格", 5000),
    FieldDef("personality", "性格", 5000),
    FieldDef("background", "背景故事", 20000),
)
# 组织字段（所在地 / 座右铭存组织详情表，建档时一起写）
_ORGANIZATION_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("name", "名称", 100, required=True),
    FieldDef("organization_type", "组织类型", 100),
    FieldDef("organization_purpose", "宗旨", 500),
    FieldDef("location", "所在地", 2000),
    FieldDef("motto", "座右铭", 200),
    FieldDef("personality", "组织特性", 5000),
    FieldDef("background", "背景", 20000),
)

# 世界设定条目字段（术语 / 铁律 / 势力 / 规则等）
_SETTING_ENTRY_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("title", "名称", 200, required=True),
    FieldDef("category", "分类", 50, choices=SETTING_CATEGORIES),
    FieldDef("summary", "简述", 2000),
    FieldDef("content", "详细设定", 20000),
)

# 世界规则字段（修炼境界 / 装备模板 / 地图位置，与世界规则页一致；标识 key 建档时自动生成）
_WORLD_RULE_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("category", "分类", 50, required=True, choices=tuple(WORLD_RULE_LABELS)),
    FieldDef("name", "名称", 200, required=True),
    FieldDef("summary", "简述", 2000),
    FieldDef("details", "详细设定", 20000),
)

ENTITY_FIELDS: dict[str, tuple[FieldDef, ...]] = {
    "character": _CHARACTER_FIELDS,
    "organization": _ORGANIZATION_FIELDS,
    "setting_entry": _SETTING_ENTRY_FIELDS,
    "world_rule": _WORLD_RULE_FIELDS,
}
ENTITY_PAGE = {"character": "characters", "organization": "characters", "setting_entry": "setting-entries",
               "world_rule": "world-rules"}
ENTITY_LABEL = {"character": "角色", "organization": "组织", "setting_entry": "设定条目", "world_rule": "世界规则"}
ENTITY_NAME_KEY = {"character": "name", "organization": "name", "setting_entry": "title", "world_rule": "name"}


def _clean_field(field: FieldDef, value: Any) -> Optional[str]:
    if value is None:
        if field.required:
            raise EntityError(f"缺少{field.name}")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise EntityError(f"{field.name}应是一段文字")
    text = str(value).strip()
    if field.key == "role_type":  # 和角色页一样认「主角 / 配角 / 反派」等中文写法
        text = normalize_role_type(text) or ""
    if not text:
        if field.required:
            raise EntityError(f"缺少{field.name}")
        return None
    if len(text) > field.max_length:
        raise EntityError(f"{field.name}不超过 {field.max_length} 字（现在 {len(text)} 字）")
    if field.choices and text not in field.choices:
        raise EntityError(f"{field.name}只能是 {'/'.join(field.choices)}")
    return text


def kind_label(entity_type: str, payload: dict) -> str:
    """「角色 / 组织 / 设定条目」；世界规则写到具体分类（修炼境界 / 装备模板 / 地图位置）。"""
    if entity_type == "world_rule":
        return WORLD_RULE_LABELS.get(payload.get("category", ""), "世界规则")
    return ENTITY_LABEL[entity_type]


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
    label = f"新建{kind_label(entity_type, normalized)}「{display}」"
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


def _display_fields(entity_type: str, payload: dict) -> list[dict]:
    """卡片上逐行列的字段（名称、顺序照页面）：名字当标题、世界规则的分类在类别标签上，不再重复列。"""
    skip = {ENTITY_NAME_KEY.get(entity_type), *(("category",) if entity_type == "world_rule" else ())}
    return [{"key": f.key, "label": f.name} for f in ENTITY_FIELDS.get(entity_type, ())
            if f.key not in skip and payload.get(f.key)]


def entity_candidate_view(candidate: AssistantEntityCandidate, missing: bool = False) -> dict:
    """missing：已建档、建出来的那一行却不在了（见 gone_entity_candidates），卡片上标出来、可重新建档。"""
    payload = _payload(candidate)
    return {
        "id": candidate.id,
        "entity_type": candidate.entity_type,
        "label": candidate.label,
        "page": candidate.page,
        "payload": payload,
        "fields": _display_fields(candidate.entity_type, payload),
        "reason": candidate.reason or "",
        "status": candidate.status,
        "entity_missing": missing,
        "run_id": candidate.run_id,
        "created_entity_id": candidate.created_entity_id,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }


_NAME_NOISE = re.compile(r"[\s《》〈〉「」『』“”‘’\"'·・]")


def name_key(name: Optional[str]) -> str:
    """判断同名用：去掉空白、书名号 / 引号和间隔号，英文不分大小写（「《沪光报》」和「沪光报」算同名）。"""
    return _NAME_NOISE.sub("", name or "").lower()


def _namespace(entity_type: str, payload: dict) -> str:
    """同名比对的范围：角色 / 组织 / 设定条目共用一套名字；世界规则只和同一分类的规则比（门派「青云宗」和地点「青云宗」可以并存）。"""
    return f"world_rule:{payload.get('category', '')}" if entity_type == "world_rule" else "named"


async def existing_same_name(db: AsyncSession, project_id: str, entity_type: str, payload: dict) -> Optional[tuple[str, str]]:
    """书里已有的同名对象（名字, 类别）：角色 / 组织 / 设定条目共用一套名字，世界规则只比同一分类；没有返回 None。"""
    if entity_type == "world_rule":
        category = payload.get("category", "")
        existing = [(name, WORLD_RULE_LABELS.get(category, "世界规则")) for (name,) in (await db.execute(
            select(WorldRule.name).where(WorldRule.project_id == project_id, WorldRule.category == category)
        )).all()]
    else:
        existing = [(name, "组织" if is_org else "角色") for name, is_org in (await db.execute(
            select(Character.name, Character.is_organization).where(Character.project_id == project_id)
        )).all()]
        existing += [(title, "设定条目") for (title,) in (await db.execute(
            select(SettingEntry.title).where(SettingEntry.project_id == project_id)
        )).all()]
    key = name_key(payload.get(ENTITY_NAME_KEY[entity_type]))
    return next(((name, kind) for name, kind in existing if name_key(name) == key), None)


async def same_name_conflict(db: AsyncSession, project_id: str, session_id: Optional[str], entity_type: str,
                             payload: dict) -> Optional[str]:
    """拟新建的对象和本书已有的对象，或本段对话里还在等作者确认的新建候选同名时，说明撞了谁、该怎么办。"""
    key = name_key(payload.get(ENTITY_NAME_KEY[entity_type]))
    space = _namespace(entity_type, payload)
    found = await existing_same_name(db, project_id, entity_type, payload)
    if found:
        name, kind = found
        return f"本书已有同名{kind}「{name}」：要补充或修改它，先 list_fields 定位、再 propose_edit；确实是另一个对象就换个能区分的名字"
    if entity_type == "world_rule" and payload.get("category") == wms.RULE_CATEGORY:
        try:  # 「地图位置」和世界地图上的地点一一对应：地图上已有别的同名地点也不行
            await wms.check_rule_location_name(db, project_id, payload.get("name", ""))
        except wms.WorldMapError as exc:
            return str(exc)
    pending = (await db.execute(select(AssistantEntityCandidate).where(
        AssistantEntityCandidate.session_id == session_id, AssistantEntityCandidate.status == "candidate",
    ))).scalars() if session_id else []
    for cand in pending:
        other = _payload(cand)
        if _namespace(cand.entity_type, other) == space and name_key(other.get(ENTITY_NAME_KEY.get(cand.entity_type, "name"))) == key:
            return f"已有一份待作者确认的同名候选（{cand.label}）：不要重复提出；要改内容就在回复里说明，作者在卡片上放弃旧的之后再提"
    return None


async def apply_entity_candidate(db: AsyncSession, candidate: AssistantEntityCandidate) -> str:
    """作者应用：真正建行。返回新建行的 id。"""
    if candidate.status != "candidate":
        raise EntityConflict("这份候选已经处理过了")
    payload = _payload(candidate)
    found = await existing_same_name(db, candidate.project_id, candidate.entity_type, payload)
    if found:  # 卡片提出来以后作者在页面上建了同名的（或删了又重建）：不再重复建一份
        name, kind = found
        raise EntityConflict(f"本书已有同名{kind}「{name}」，没有重复建档：要补充它就到页面上改，或让助笔修改它；"
                             "确实是另一个对象，请助笔换个能区分的名字重新提")
    if candidate.entity_type in ("character", "organization"):
        entity_id = await _create_character(db, candidate.project_id, candidate.entity_type, payload)
    elif candidate.entity_type == "setting_entry":
        entity_id = await _create_setting_entry(db, candidate.project_id, payload)
    elif candidate.entity_type == "world_rule":
        entity_id = await _create_world_rule(db, candidate.project_id, payload)
    else:
        raise EntityError(f"不支持新建这种对象：{candidate.entity_type}")
    candidate.status = "applied"
    candidate.created_entity_id = entity_id
    candidate.decided_at = utcnow()
    return entity_id


async def _create_character(db: AsyncSession, project_id: str, entity_type: str, payload: dict) -> str:
    entity_id = str(uuid.uuid4())
    is_org = entity_type == "organization"
    character = Character(
        id=entity_id, project_id=project_id, is_organization=is_org,
        name=payload["name"], role_type=None if is_org else normalize_role_type(payload.get("role_type"), "supporting"),
        age=payload.get("age"), gender=payload.get("gender"), personality=payload.get("personality"),
        background=payload.get("background"), appearance=payload.get("appearance"), speech_style=payload.get("speech_style"),
        organization_type=payload.get("organization_type"), organization_purpose=payload.get("organization_purpose"),
    )
    db.add(character)
    await db.flush()
    if is_org:  # 组织管理页按组织详情列组织：和 AI 生成组织一样同时建一条，否则建了也只在角色页看得到
        await ensure_organization_record(character, db, location=payload.get("location"), motto=payload.get("motto"))
    return entity_id


async def _create_world_rule(db: AsyncSession, project_id: str, payload: dict) -> str:
    """和世界规则页「添加规则」相同：标识自动生成、排在同类最后；「地图位置」查重名并出现在世界地图上；进向量索引。"""
    category, name = payload["category"], payload["name"]
    if category == wms.RULE_CATEGORY:
        try:
            await wms.check_rule_location_name(db, project_id, name)
        except wms.WorldMapError as exc:
            raise EntityConflict(str(exc)) from exc
    last = await db.scalar(select(func.max(WorldRule.order_index)).where(
        WorldRule.project_id == project_id, WorldRule.category == category))
    rule = WorldRule(id=str(uuid.uuid4()), project_id=project_id, category=category,
                     key=f"{category}_{uuid.uuid4().hex[:8]}", name=name, order_index=(last or 0) + 1,
                     summary=payload.get("summary", ""), details=payload.get("details", ""))
    db.add(rule)
    await db.flush()
    if category == wms.RULE_CATEGORY:
        await wms.sync_rule_locations(db, project_id)
    await sync_world_rule(rule)
    return rule.id


async def _create_setting_entry(db: AsyncSession, project_id: str, payload: dict) -> str:
    from app.services import setting_entry_service  # 延迟导入，避免把向量依赖拉进工具导入链
    entry = await setting_entry_service.create_entry(
        db, project_id, category=payload.get("category") or "other", title=payload["title"],
        summary=payload.get("summary", ""), content=payload.get("content", ""),
    )
    return entry.id


_ENTITY_MODELS = {"character": Character, "organization": Character, "setting_entry": SettingEntry, "world_rule": WorldRule}


async def created_entity_exists(db: AsyncSession, entity_type: str, entity_id: Optional[str]) -> bool:
    """建档后读回核对：建出来的那一行真的在库里（所有会话共用一个 SQLite 连接，别的请求收尾时的回滚可能把它冲掉，
    候选却照样记成了已建档——作者看到「已建档」，页面上却没有）。"""
    model = _ENTITY_MODELS.get(entity_type)
    return bool(model and entity_id and await db.scalar(select(model.id).where(model.id == entity_id)))


async def gone_entity_candidates(db: AsyncSession, candidates: list[AssistantEntityCandidate]) -> set[str]:
    """已建档、建出来的那一行却不在了（修复前被别的请求回滚冲掉，或作者后来删了），书里也没有同名对象的候选 id：
    作者看到的「已建档」名不副实，卡片上要标出来、让他能重新建档。删了又在页面上建了同名的不算。"""
    applied = [c for c in candidates if c.status == "applied"]
    wanted: dict[Any, set[str]] = {}
    for c in applied:
        model = _ENTITY_MODELS.get(c.entity_type)
        if model is not None and c.created_entity_id:
            wanted.setdefault(model, set()).add(c.created_entity_id)
    present: set[str] = set()
    for model, ids in wanted.items():
        present.update((await db.execute(select(model.id).where(model.id.in_(ids)))).scalars())
    gone: set[str] = set()
    for c in applied:
        if c.created_entity_id not in present and not await existing_same_name(db, c.project_id, c.entity_type, _payload(c)):
            gone.add(c.id)
    return gone


def reopen_entity_candidate(candidate: AssistantEntityCandidate) -> None:
    """记成了已建档、建出来的那一行却没留下：退回待确认，好再建一次。"""
    candidate.status = "candidate"
    candidate.created_entity_id = None
    candidate.decided_at = None


async def reject_entity_candidate(db: AsyncSession, candidate: AssistantEntityCandidate) -> None:
    if candidate.status != "candidate":
        raise EntityConflict("这份候选已经处理过了")
    candidate.status = "rejected"
    candidate.decided_at = utcnow()
