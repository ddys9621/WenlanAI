"""全局智能助笔 · 新建对象候选：工具只记下要新建的世界规则 / 设定条目 / 角色 / 组织 / 人物关系 / 组织成员，
作者「应用」才真正建行，可放弃。

与 assistant_candidate_service（改既有字段）互补：那边管「改已有的」，这边管「从无到有创建新对象」。
- 生成候选时按对象类型校验字段（类型 / 长度 / 取值），只落候选表，不碰真实对象
- 作者应用才 INSERT 真实行，并把新建行的 id 记进候选（created_entity_id），供跳转 / 去重
- 建档与页面手动新建同一套连带处理：组织同时建组织详情（组织管理页按它列），「地图位置」规则出现在世界地图上，
  世界规则进向量索引，关系按名称认关系类型，加成员时组织的成员数跟着加
- 关系 / 组织成员（LINK_TYPES）两头按名字认：提出时可以是书里已有的，也可以是本段对话里还在待建档的人物 / 组织候选；
  建档时两头必须已经建好（待确认栏「全部采用」按创作顺序处理，人物在前）
- 字段上限与 Character 列、assistant_fields 的白名单保持一致
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate
from app.models.chapter_candidate import utcnow
from app.models.character import Character
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.setting_entry import SETTING_CATEGORY_LABELS, SettingEntry
from app.models.world_rule import WorldRule
from app.services import world_map_service as wms
from app.services.assistant_fields import (
    MEMBER_STATUS_LABELS, RELATIONSHIP_STATUS_LABELS, ROLE_LABELS, WORLD_RULE_LABELS, sync_world_rule,
)
from app.utils.character_names import build_name_index
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
    labels: tuple[tuple[str, str], ...] = ()  # 选项的中文含义（取值, 页面写法）：卡片上显示中文，提出时也认中文
    number: tuple[int, int] = ()  # 非空 = 整数字段的取值范围（存成文字，建档时转成数字）

    @property
    def allowed(self) -> tuple[str, ...]:
        return self.choices or tuple(value for value, _label in self.labels)

    def text(self, value: str) -> str:
        return dict(self.labels).get(value, value)


def _pairs(mapping: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(mapping.items())


# 角色字段（上限与 Character 列、assistant_fields 对齐；顺序 = 卡片上的显示顺序，短的在前）
_CHARACTER_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("name", "姓名", 100, required=True),
    FieldDef("role_type", "角色类型", 50, labels=_pairs(ROLE_LABELS)),
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
    FieldDef("category", "分类", 50, labels=_pairs(SETTING_CATEGORY_LABELS)),
    FieldDef("summary", "简述", 2000),
    FieldDef("content", "详细设定", 20000),
)

# 世界规则字段（修炼境界 / 装备模板 / 地图位置，与世界规则页一致；标识 key 建档时自动生成）
_WORLD_RULE_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("category", "分类", 50, required=True, labels=_pairs(WORLD_RULE_LABELS)),
    FieldDef("name", "名称", 200, required=True),
    FieldDef("summary", "简述", 2000),
    FieldDef("details", "详细设定", 20000),
)

# 人物关系（关系页：角色A、角色B、关系名称、亲密度、状态、关系描述）
_RELATIONSHIP_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("from_name", "角色A", 100, required=True),
    FieldDef("to_name", "角色B", 100, required=True),
    FieldDef("relationship_name", "关系", 100, required=True),
    FieldDef("intimacy_level", "亲密度", 4, number=(-100, 100)),
    FieldDef("status", "状态", 20, labels=_pairs(RELATIONSHIP_STATUS_LABELS)),
    FieldDef("description", "关系描述", 5000),
)

# 组织成员（组织页：人物、职位、等级、忠诚度；状态与 AI 生成成员一致）
_MEMBERSHIP_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("character_name", "人物", 100, required=True),
    FieldDef("organization_name", "组织", 100, required=True),
    FieldDef("position", "职位", 100, required=True),
    FieldDef("rank", "等级", 3, number=(0, 100)),
    FieldDef("loyalty", "忠诚度", 3, number=(0, 100)),
    FieldDef("status", "状态", 20, labels=_pairs(MEMBER_STATUS_LABELS)),
)

ENTITY_FIELDS: dict[str, tuple[FieldDef, ...]] = {
    "character": _CHARACTER_FIELDS,
    "organization": _ORGANIZATION_FIELDS,
    "setting_entry": _SETTING_ENTRY_FIELDS,
    "world_rule": _WORLD_RULE_FIELDS,
    "relationship": _RELATIONSHIP_FIELDS,
    "membership": _MEMBERSHIP_FIELDS,
}
ENTITY_PAGE = {"character": "characters", "organization": "characters", "setting_entry": "setting-entries",
               "world_rule": "world-rules", "relationship": "relationships", "membership": "organizations"}
ENTITY_LABEL = {"character": "角色", "organization": "组织", "setting_entry": "设定条目", "world_rule": "世界规则",
                "relationship": "关系", "membership": "组织成员"}
ENTITY_NAME_KEY = {"character": "name", "organization": "name", "setting_entry": "title", "world_rule": "name"}
# 关系 / 组织成员：连着两头的对象（键, 这一头要的是不是组织）
LINK_ENDS: dict[str, tuple[tuple[str, bool], ...]] = {
    "relationship": (("from_name", False), ("to_name", False)),
    "membership": (("character_name", False), ("organization_name", True)),
}
LINK_TYPES = tuple(LINK_ENDS)


def display_name(entity_type: str, payload: dict) -> str:
    """卡片标题 / 提示里怎么称呼它：有名字的用名字，关系写「甲 → 乙」，成员写「人物 · 组织」。"""
    if entity_type == "relationship":
        return f"{payload.get('from_name') or '？'} → {payload.get('to_name') or '？'}"
    if entity_type == "membership":
        return f"{payload.get('character_name') or '？'} · {payload.get('organization_name') or '？'}"
    return str(payload.get(ENTITY_NAME_KEY.get(entity_type, "name")) or "")


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
    text = {label: code for code, label in field.labels}.get(text, text)  # 页面上的中文写法也认
    if not text:
        if field.required:
            raise EntityError(f"缺少{field.name}")
        return None
    if field.number:
        low, high = field.number
        try:
            number = int(float(text))
        except (ValueError, OverflowError):
            raise EntityError(f"{field.name}应是整数（{low} 到 {high}）") from None
        if not low <= number <= high:
            raise EntityError(f"{field.name}应在 {low} 到 {high} 之间（现在 {number}）")
        return str(number)
    if len(text) > field.max_length:
        raise EntityError(f"{field.name}不超过 {field.max_length} 字（现在 {len(text)} 字）")
    if field.allowed and text not in field.allowed:
        meaning = " / ".join(f"{code}（{label}）" for code, label in field.labels) or "/".join(field.allowed)
        raise EntityError(f"{field.name}只能是 {meaning}")
    return text


def kind_label(entity_type: str, payload: dict) -> str:
    """「角色 / 组织 / 设定条目 / 关系 / 组织成员」；世界规则写到具体分类（修炼境界 / 装备模板 / 地图位置）。"""
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
    label = f"新建{kind_label(entity_type, normalized)}「{display_name(entity_type, normalized)}」"
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
    """卡片上逐行列的字段（名称、顺序照页面；选项给出中文 text）：名字当标题、世界规则的分类在类别标签上，不再重复列。"""
    skip = {ENTITY_NAME_KEY.get(entity_type), *(key for key, _org in LINK_ENDS.get(entity_type, ())),
            *(("category",) if entity_type == "world_rule" else ())}
    return [{"key": f.key, "label": f.name, "text": f.text(payload[f.key])} for f in ENTITY_FIELDS.get(entity_type, ())
            if f.key not in skip and payload.get(f.key)]


def entity_candidate_view(candidate: AssistantEntityCandidate, missing: bool = False) -> dict:
    """missing：已建档、建出来的那一行却不在了（见 gone_entity_candidates），卡片上标出来、可重新建档。"""
    payload = _payload(candidate)
    return {
        "id": candidate.id,
        "entity_type": candidate.entity_type,
        "label": candidate.label,
        "title": display_name(candidate.entity_type, payload),
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


def _identity(entity_type: str, payload: dict) -> str:
    """查重用的身份：角色 / 组织 / 设定条目共用一套名字；世界规则只和同一分类比（门派「青云宗」和地点「青云宗」可以并存）；
    关系按两头（不分先后），组织成员按「组织 + 人物」。"""
    if entity_type == "relationship":
        return "relationship:" + "|".join(sorted(name_key(payload.get(key)) for key, _org in LINK_ENDS[entity_type]))
    if entity_type == "membership":
        return f"membership:{name_key(payload.get('organization_name'))}|{name_key(payload.get('character_name'))}"
    space = f"world_rule:{payload.get('category', '')}" if entity_type == "world_rule" else "named"
    return f"{space}:{name_key(payload.get(ENTITY_NAME_KEY.get(entity_type, 'name')))}"


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


async def _cast_index(db: AsyncSession, project_id: str) -> dict[str, Character]:
    """本书的人物和组织，按名字（也认曾用名）查。"""
    rows = (await db.execute(select(Character).where(Character.project_id == project_id))).scalars().all()
    return build_name_index(rows, key=name_key)


async def existing_link(db: AsyncSession, project_id: str, entity_type: str, payload: dict,
                        index: Optional[dict[str, Character]] = None) -> Optional[str]:
    """书里已有的同一条关系（两头不分先后）/ 同一个成员记录：返回说明（「陈默」和「苏雪」的关系（师徒）），没有返回 None。"""
    index = index if index is not None else await _cast_index(db, project_id)
    first, second = (index.get(name_key(payload.get(key))) for key, _org in LINK_ENDS[entity_type])
    if first is None or second is None:
        return None
    if entity_type == "relationship":
        row = (await db.execute(select(CharacterRelationship).where(
            CharacterRelationship.project_id == project_id,
            or_(and_(CharacterRelationship.character_from_id == first.id, CharacterRelationship.character_to_id == second.id),
                and_(CharacterRelationship.character_from_id == second.id, CharacterRelationship.character_to_id == first.id)),
        ))).scalars().first()
        return f"「{first.name}」和「{second.name}」的关系（{row.relationship_name or '未命名'}）" if row else None
    member = (await db.execute(
        select(OrganizationMember).join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(Organization.character_id == second.id, OrganizationMember.character_id == first.id)
    )).scalars().first()
    return f"「{first.name}」在「{second.name}」的成员记录（{member.position}）" if member else None


async def _pending_cast(db: AsyncSession, session_id: Optional[str]) -> dict[str, str]:
    """本段对话里还在待建档的人物 / 组织候选：名字 → character / organization。"""
    if not session_id:
        return {}
    rows = (await db.execute(select(AssistantEntityCandidate).where(
        AssistantEntityCandidate.session_id == session_id, AssistantEntityCandidate.status == "candidate",
        AssistantEntityCandidate.entity_type.in_(("character", "organization")),
    ))).scalars()
    return {name_key(_payload(c).get("name")): c.entity_type for c in rows}


async def _link_problem(db: AsyncSession, project_id: str, session_id: Optional[str], entity_type: str,
                        payload: dict) -> Optional[str]:
    """关系 / 组织成员的两头：书里已有，或本段对话里待建档的候选；对不上类别、或已经有这一条，说明怎么办。"""
    index, pending = await _cast_index(db, project_id), await _pending_cast(db, session_id)
    ends = LINK_ENDS[entity_type]
    if entity_type == "relationship" and len({name_key(payload.get(key)) for key, _org in ends}) == 1:
        return "角色A和角色B是同一个人：关系要连两个不同的人物"
    for key, want_org in ends:
        name = payload.get(key, "")
        found = index.get(name_key(name))
        kind = ("organization" if found.is_organization else "character") if found else pending.get(name_key(name))
        if kind is None:
            tool = "propose_organization" if want_org else "propose_character"
            return (f"本书没有叫「{name}」的{'组织' if want_org else '人物'}，本段对话里也没有待建档的同名候选："
                    f"先用 {tool} 提出来，或核对名字（可以 search_project 查）")
        if want_org and kind != "organization":
            return f"「{name}」是人物，不是组织：organization_name 要填组织名"
        if not want_org and kind == "organization":
            return (f"「{name}」是组织：人物属于哪个组织用 propose_membership 记成组织成员" if entity_type == "relationship"
                    else f"「{name}」是组织，不能当组织成员：character_name 要填人物名")
    found = await existing_link(db, project_id, entity_type, payload, index)
    if found:
        return f"本书已有{found}：要补充或修改它，先 list_fields 定位、再 propose_edit"
    return None


async def same_name_conflict(db: AsyncSession, project_id: str, session_id: Optional[str], entity_type: str,
                             payload: dict) -> Optional[str]:
    """拟新建的对象和本书已有的对象，或本段对话里还在等作者确认的新建候选重复时，说明撞了谁、该怎么办；
    关系 / 组织成员还要两头对得上（人物 / 组织）。"""
    if entity_type in LINK_TYPES:
        problem = await _link_problem(db, project_id, session_id, entity_type, payload)
        if problem:
            return problem
    else:
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
    me = _identity(entity_type, payload)
    for cand in pending:
        if cand.entity_type in ENTITY_FIELDS and _identity(cand.entity_type, _payload(cand)) == me:
            same = {"relationship": "同一对人物的", "membership": "同一个成员的"}.get(entity_type, "同名")
            return f"已有一份待作者确认的{same}候选（{cand.label}）：不要重复提出；要改内容就在回复里说明，作者在卡片上放弃旧的之后再提"
    return None


async def _duplicate_in_book(db: AsyncSession, project_id: str, entity_type: str, payload: dict) -> Optional[str]:
    """书里已经有一样的东西（同名对象 / 同一条关系 / 同一个成员）：返回说明，没有返回 None。"""
    if entity_type in LINK_TYPES:
        return await existing_link(db, project_id, entity_type, payload)
    found = await existing_same_name(db, project_id, entity_type, payload)
    return f"同名{found[1]}「{found[0]}」" if found else None


async def apply_entity_candidate(db: AsyncSession, candidate: AssistantEntityCandidate) -> str:
    """作者应用：真正建行。返回新建行的 id。"""
    if candidate.status != "candidate":
        raise EntityConflict("这份候选已经处理过了")
    payload = _payload(candidate)
    found = await _duplicate_in_book(db, candidate.project_id, candidate.entity_type, payload)
    if found:  # 卡片提出来以后作者在页面上建了一样的（或删了又重建）：不再重复建一份
        raise EntityConflict(f"本书已有{found}，没有重复建档：要补充它就到页面上改，或让助笔修改它；"
                             "确实是另一个对象，请助笔换个能区分的名字重新提")
    if candidate.entity_type in ("character", "organization"):
        entity_id = await _create_character(db, candidate.project_id, candidate.entity_type, payload)
    elif candidate.entity_type == "setting_entry":
        entity_id = await _create_setting_entry(db, candidate.project_id, payload)
    elif candidate.entity_type == "world_rule":
        entity_id = await _create_world_rule(db, candidate.project_id, payload)
    elif candidate.entity_type == "relationship":
        entity_id = await _create_relationship(db, candidate.project_id, payload)
    elif candidate.entity_type == "membership":
        entity_id = await _create_membership(db, candidate.project_id, payload)
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


def _resolve_end(index: dict[str, Character], name: str, want_org: bool, what: str) -> Character:
    """建档时找关系 / 成员的一头：必须已经建好（提出时可以还是待建档的候选）。"""
    found = index.get(name_key(name))
    if found is None:
        raise EntityConflict(f"「{name}」还没建档：先在待确认里建档这个{'组织' if want_org else '人物'}，再建这条{what}")
    if bool(found.is_organization) != want_org:
        raise EntityConflict(f"「{name}」{'不是组织' if want_org else '是组织，不是人物'}，建不了这条{what}")
    return found


async def _create_relationship(db: AsyncSession, project_id: str, payload: dict) -> str:
    """和关系页「添加关系」相同的一行；关系类型按关系名称认（和 AI 生成关系一样），页面上的图标对得上。"""
    from app.services.relationship_matcher import match_relationship_type

    index = await _cast_index(db, project_id)
    first, second = (_resolve_end(index, payload[key], want_org, "关系") for key, want_org in LINK_ENDS["relationship"])
    relationship = CharacterRelationship(
        id=str(uuid.uuid4()), project_id=project_id, character_from_id=first.id, character_to_id=second.id,
        relationship_name=payload["relationship_name"], intimacy_level=int(payload.get("intimacy_level") or 50),
        status=payload.get("status") or "active", description=payload.get("description"), source="ai",
        relationship_type_id=await match_relationship_type(db, payload["relationship_name"]),
    )
    db.add(relationship)
    await db.flush()
    return relationship.id


async def _create_membership(db: AsyncSession, project_id: str, payload: dict) -> str:
    """和组织页「添加成员」相同：组织没有详情记录就补建，成员数跟着加。"""
    index = await _cast_index(db, project_id)
    person, org_character = (_resolve_end(index, payload[key], want_org, "成员记录")
                             for key, want_org in LINK_ENDS["membership"])
    organization = await ensure_organization_record(org_character, db)
    member = OrganizationMember(
        id=str(uuid.uuid4()), organization_id=organization.id, character_id=person.id, position=payload["position"],
        rank=int(payload.get("rank") or 0), loyalty=int(payload.get("loyalty") or 50),
        status=payload.get("status") or "active", source="ai",
    )
    db.add(member)
    organization.member_count = (organization.member_count or 0) + 1
    await db.flush()
    return member.id


_ENTITY_MODELS = {"character": Character, "organization": Character, "setting_entry": SettingEntry, "world_rule": WorldRule,
                  "relationship": CharacterRelationship, "membership": OrganizationMember}


async def created_entity_exists(db: AsyncSession, entity_type: str, entity_id: Optional[str]) -> bool:
    """建档后读回核对：建出来的那一行真的在库里（所有会话共用一个 SQLite 连接，别的请求收尾时的回滚可能把它冲掉，
    候选却照样记成了已建档——作者看到「已建档」，页面上却没有）。"""
    model = _ENTITY_MODELS.get(entity_type)
    return bool(model and entity_id and await db.scalar(select(model.id).where(model.id == entity_id)))


async def gone_entity_candidates(db: AsyncSession, candidates: list[AssistantEntityCandidate]) -> set[str]:
    """已建档、建出来的那一行却不在了（修复前被别的请求回滚冲掉，或作者后来删了），书里也没有一样的对象的候选 id：
    作者看到的「已建档」名不副实，卡片上要标出来、让他能重新建档。删了又在页面上建了一样的不算。"""
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
        if c.entity_type not in ENTITY_FIELDS:
            continue
        if c.created_entity_id not in present and not await _duplicate_in_book(db, c.project_id, c.entity_type, _payload(c)):
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
