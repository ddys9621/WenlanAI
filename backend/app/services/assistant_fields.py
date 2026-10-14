"""全局智能助笔 · 可修改内容目录（参考岚笺 assistant-field-catalog：静态白名单，不开放任意字段 / 删除 / 密钥）。

每一项 = 字段（field_id）+ 目标（target_id，所属对象）：作品设定、人物、组织、章纲、故事前提、地图地点。
读写都在这里校验类型与长度；写入时补上与手动编辑相同的连带处理（改故事前提 → 章纲标「上游已改」，改地点 → 地图版本号前移）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.story_outline import StoryOutline
from app.models.world_map import WorldMapLocation
from app.services import outline_review_service as outline_review
from app.services.world_map_service import load_map


class FieldError(Exception):
    status_code = 400


class FieldConflict(FieldError):
    status_code = 409


class FieldNotFound(FieldError):
    status_code = 404


@dataclass(frozen=True)
class FieldSpec:
    id: str
    entity: str
    attr: str
    name: str
    kind: str = "text"  # text | list
    max_length: int = 20000
    max_items: int = 30
    page: str = ""
    group: str = ""


ENTITY_PAGES = {
    "project": "world-setting", "character": "characters", "organization": "characters",
    "chapter_outline": "outline", "story_outline": "outline", "location": "world-map",
}
ENTITY_GROUPS = {
    "project": "设定", "character": "人物", "organization": "组织", "chapter_outline": "谋篇",
    "story_outline": "谋篇", "location": "地图",
}


def _spec(entity: str, attr: str, name: str, **kw: Any) -> FieldSpec:
    field_id = f"{entity}.{attr}"
    return FieldSpec(id=field_id, entity=entity, attr=attr, name=name, page=ENTITY_PAGES[entity],
                     group=ENTITY_GROUPS[entity], **kw)


_SPECS = [
    _spec("project", "description", "简介", max_length=5000),
    _spec("project", "theme", "主题", max_length=2000),
    _spec("project", "world_time_period", "时间背景", max_length=5000),
    _spec("project", "world_location", "地理位置", max_length=5000),
    _spec("project", "world_atmosphere", "氛围基调", max_length=5000),
    _spec("project", "world_rules", "世界规则", max_length=20000),
    _spec("character", "personality", "性格", max_length=5000),
    _spec("character", "background", "背景故事", max_length=20000),
    _spec("character", "appearance", "外貌", max_length=5000),
    _spec("character", "speech_style", "说话风格", max_length=5000),
    _spec("character", "age", "年龄", max_length=50),
    _spec("organization", "personality", "组织特性", max_length=5000),
    _spec("organization", "background", "背景", max_length=20000),
    _spec("organization", "organization_purpose", "宗旨", max_length=500),
    _spec("organization", "organization_type", "组织类型", max_length=100),
    _spec("chapter_outline", "title", "标题", max_length=200),
    _spec("chapter_outline", "plot_points", "剧情要点", max_length=10000),
    _spec("chapter_outline", "scene", "场景", max_length=500),
    _spec("chapter_outline", "pov", "视角角色", max_length=100),
    _spec("chapter_outline", "entry_state", "进入状态", max_length=2000),
    _spec("chapter_outline", "exit_state", "退出状态", max_length=2000),
    _spec("chapter_outline", "key_events", "关键事件", kind="list", max_length=300, max_items=20),
    _spec("chapter_outline", "forbidden", "禁止事项", kind="list", max_length=300, max_items=20),
    _spec("story_outline", "content", "故事前提", max_length=50000),
    _spec("location", "description", "地点档案", max_length=4000),
    _spec("location", "region", "所属区域", max_length=100),
]
FIELD_SPECS: dict[str, FieldSpec] = {s.id: s for s in _SPECS}
LIST_LIMIT = 60
PREVIEW_CHARS = 60


def _target_label(entity: str, obj: Any) -> str:
    if entity == "project":
        return "作品设定"
    if entity == "character":
        return f"角色「{obj.name}」"
    if entity == "organization":
        return f"组织「{obj.name}」"
    if entity == "chapter_outline":
        return f"第{obj.chapter_number}章章纲《{obj.title}》"
    if entity == "story_outline":
        return f"故事大纲《{obj.title}》"
    return f"地点「{obj.name}」"


def field_label(spec: FieldSpec, obj: Any) -> str:
    return f"{_target_label(spec.entity, obj)}·{spec.name}"


async def _entity_rows(db: AsyncSession, project_id: str, entity: str) -> list[Any]:
    if entity == "project":
        project = await db.get(Project, project_id)
        return [project] if project else []
    if entity in ("character", "organization"):
        want_org = entity == "organization"
        rows = (await db.execute(
            select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
        )).scalars().all()
        return [c for c in rows if bool(c.is_organization) == want_org]
    if entity == "chapter_outline":
        return list((await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id).order_by(ChapterOutline.chapter_number)
        )).scalars().all())
    if entity == "story_outline":
        return list((await db.execute(
            select(StoryOutline).where(StoryOutline.project_id == project_id)
            .order_by(StoryOutline.is_active.desc(), StoryOutline.order_index)
        )).scalars().all())
    return list((await db.execute(
        select(WorldMapLocation).where(WorldMapLocation.project_id == project_id).order_by(WorldMapLocation.name)
    )).scalars().all())


def get_value(spec: FieldSpec, obj: Any) -> Any:
    raw = getattr(obj, spec.attr, None)
    if spec.kind == "list":
        if isinstance(raw, list):
            return [str(x) for x in raw]
        try:
            parsed = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            parsed = [line for line in str(raw).splitlines() if line.strip()]
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    return "" if raw is None else str(raw)


def _preview(value: Any) -> str:
    text = "、".join(value) if isinstance(value, list) else str(value or "")
    text = text.replace("\n", " ").strip()
    return text[:PREVIEW_CHARS] + ("…" if len(text) > PREVIEW_CHARS else "") if text else "（空白）"


async def list_fields(db: AsyncSession, project_id: str, query: str = "") -> list[dict]:
    """可修改的内容项（按名称筛选；不传就列全部，最多 60 项）。"""
    terms = [t for t in (query or "").split() if t]
    out: list[dict] = []
    for entity in ENTITY_PAGES:
        rows = await _entity_rows(db, project_id, entity)
        for spec in (s for s in _SPECS if s.entity == entity):
            for obj in rows:
                label = field_label(spec, obj)
                haystack = f"{label} {spec.group}"
                if terms and not all(t in haystack for t in terms):
                    continue
                out.append({
                    "field_id": spec.id, "target_id": obj.id, "label": label, "group": spec.group,
                    "kind": spec.kind, "page": spec.page, "preview": _preview(get_value(spec, obj)),
                })
                if len(out) >= LIST_LIMIT:
                    return out
    return out


def spec_of(field_id: str) -> FieldSpec:
    spec = FIELD_SPECS.get(field_id)
    if spec is None:
        raise FieldError(f"没有这个可修改的内容项：{field_id}（先用 list_fields 查找）")
    return spec


async def load_target(db: AsyncSession, project_id: str, spec: FieldSpec, target_id: str) -> Any:
    model = {
        "project": Project, "character": Character, "organization": Character, "chapter_outline": ChapterOutline,
        "story_outline": StoryOutline, "location": WorldMapLocation,
    }[spec.entity]
    obj = await db.get(model, target_id) if target_id else None
    owner = getattr(obj, "id" if spec.entity == "project" else "project_id", None) if obj is not None else None
    if obj is None or owner != project_id:
        raise FieldNotFound(f"在本书里找不到这项内容：{spec.name}（{target_id}）")
    if spec.entity in ("character", "organization") and bool(obj.is_organization) != (spec.entity == "organization"):
        raise FieldNotFound(f"「{obj.name}」不是{'组织' if spec.entity == 'organization' else '人物'}")
    return obj


async def read_field(db: AsyncSession, project_id: str, field_id: str, target_id: str) -> dict:
    spec = spec_of(field_id)
    obj = await load_target(db, project_id, spec, target_id)
    return {
        "field_id": spec.id, "target_id": obj.id, "label": field_label(spec, obj), "kind": spec.kind,
        "value": get_value(spec, obj), "page": spec.page, "group": spec.group, "max_length": spec.max_length,
    }


def normalize_value(spec: FieldSpec, value: Any) -> Any:
    if spec.kind == "list":
        if isinstance(value, str):
            items = value.splitlines()
        elif isinstance(value, list):
            if any(isinstance(x, (dict, list, bool)) or x is None for x in value):
                raise FieldError(f"{spec.name}的每一项都应是文字")
            items = [str(x) for x in value]
        else:
            raise FieldError(f"{spec.name}应是文字列表")
        cleaned = [x.strip() for x in items if x and x.strip()]
        if len(cleaned) > spec.max_items:
            raise FieldError(f"{spec.name}最多 {spec.max_items} 条")
        if any(len(x) > spec.max_length for x in cleaned):
            raise FieldError(f"{spec.name}每条不超过 {spec.max_length} 字")
        return cleaned
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FieldError(f"{spec.name}应是一段文字")
    text = str(value).strip()
    if len(text) > spec.max_length:
        raise FieldError(f"{spec.name}不超过 {spec.max_length} 字（现在 {len(text)} 字）")
    return text


async def write_field(db: AsyncSession, project_id: str, field_id: str, target_id: str, value: Any) -> Any:
    """写入一项内容（与手动编辑相同的连带处理）；返回规整后的值。"""
    spec = spec_of(field_id)
    obj = await load_target(db, project_id, spec, target_id)
    normalized = normalize_value(spec, value)
    changed = get_value(spec, obj) != normalized
    setattr(obj, spec.attr, json.dumps(normalized, ensure_ascii=False) if spec.kind == "list" else normalized)
    if changed and spec.entity == "story_outline":
        await outline_review.mark_project_outlines(db, project_id, "故事大纲（故事前提）已修改")
    if changed and spec.entity == "location":
        world_map = await load_map(db, project_id)
        if world_map is not None:
            world_map.revision = (world_map.revision or 0) + 1
    await db.flush()
    return normalized


def entity_of(field_id: str) -> Optional[str]:
    spec = FIELD_SPECS.get(field_id)
    return spec.entity if spec else None
