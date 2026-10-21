"""全局智能助笔 · 可修改内容目录（参考岚笺 assistant-field-catalog：静态白名单，不开放任意字段 / 删除 / 密钥）。

每一项 = 字段（field_id）+ 目标（target_id，所属对象）：作品设定、人物、组织（含组织详情）、章纲、卷纲、
总纲（梗概 / 全书主线等分字段；本书还没有总纲时目标是 new，作者应用时才建出来）、地图地点、世界设定条目、世界规则条目。
读写都在这里校验类型与长度；写入时补上与手动编辑相同的连带处理（改总纲 → 卷纲 / 章纲标「上游已改」，改卷纲 → 本卷章纲标「上游已改」，
改地点 → 地图版本号前移，改设定条目 / 世界规则 → 向量索引重同步，「地图位置」规则改名 → 地图跟着改，人物改名 → 别处的名字快照跟着改）。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.character import Character
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.relationship import Organization
from app.models.setting_entry import SETTING_CATEGORIES, SettingEntry
from app.models.story_outline import StoryOutline
from app.models.volume import Volume
from app.models.world_map import WorldMapLocation
from app.models.world_rule import WorldRule
from app.services import outline_review_service as outline_review
from app.services import world_map_service as wms
from app.services.character_rename_service import propagate_character_rename
from app.services.world_map_service import load_map
from app.utils.character_names import record_former_name
from app.utils.data_consistency import ensure_organization_record
from app.utils.role_type import normalize_role_type
from app.utils.story_outline_fields import parse_story_outline_fields

logger = get_logger(__name__)


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
    choices: tuple[str, ...] = ()  # 非空 = 文字字段只能取这些值（如设定条目分类）
    required: bool = False  # 文字字段不能清空（如设定条目名称）
    json_key: str = ""  # 非空 = 值存在 StoryOutline.content 这份 JSON 的这个键下（总纲按字段改，其余键原样保留）
    hidden: bool = False  # 不在目录里列出（只为让以前生成的候选还能应用 / 撤销）
    aliases: str = ""  # 页面上 / 作者口中的别的叫法，定位内容时一起比对（如「时代背景」也叫「时间背景」）
    detail: bool = False  # 值存在组织详情表（organizations，按 character_id 一对一），不在 characters 表上


ENTITY_PAGES = {
    "project": "world-setting", "character": "characters", "organization": "characters",
    "chapter_outline": "outline", "volume": "outline", "story_outline": "outline", "location": "world-map",
    "setting_entry": "setting-entries", "world_rule": "world-rules",
}
ENTITY_GROUPS = {
    "project": "设定", "character": "人物", "organization": "组织", "chapter_outline": "谋篇",
    "volume": "卷纲", "story_outline": "总纲", "location": "地图", "setting_entry": "设定条目",
    "world_rule": "世界规则",
}
# 同一类对象共用的别的叫法（和每个字段自己的 aliases 一起比对）
ENTITY_ALIASES = {
    "chapter_outline": "章纲", "volume": "谋篇 分卷", "story_outline": "大纲 故事大纲", "location": "地点",
    "world_rule": "境界 装备 地图位置",
}
NEW_OUTLINE = "new"  # 本书还没有总纲时总纲各字段的目标：先当一份空白总纲列出，作者应用修改时才真正建
WORLD_RULE_LABELS = {"cultivation_realm": "修炼境界", "equipment_template": "装备模板", "map_location": "地图位置"}
ROLE_TYPES = ("protagonist", "supporting", "antagonist", "mentor", "ally", "extra")
PLATFORM_PRESETS = ("qidian", "fanqie", "jinjiang", "qimao")


def _spec(entity: str, attr: str, name: str, **kw: Any) -> FieldSpec:
    field_id = f"{entity}.{attr}"
    return FieldSpec(id=field_id, entity=entity, attr=attr, name=name, page=ENTITY_PAGES[entity],
                     group=ENTITY_GROUPS[entity], **kw)


# 名称跟页面上的标签一致（作者照着页面说，模型照着作者的话 list_fields）；别的叫法放 aliases
_SPECS = [
    _spec("project", "title", "书名", max_length=200, required=True),
    _spec("project", "genre", "类型", max_length=50, aliases="题材"),
    _spec("project", "platform_preset", "目标平台", max_length=20, choices=PLATFORM_PRESETS, aliases="平台"),
    _spec("project", "description", "简介", max_length=5000),
    _spec("project", "theme", "主题", max_length=2000),
    _spec("project", "world_time_period", "时代背景", max_length=5000, aliases="时间背景 年代 历史"),
    _spec("project", "world_location", "地点设定", max_length=5000, aliases="地理位置 地理 舞台"),
    _spec("project", "world_atmosphere", "氛围基调", max_length=5000, aliases="氛围 基调"),
    _spec("project", "world_rules", "世界规则", max_length=20000, aliases="规则 禁忌 代价"),
    _spec("character", "name", "姓名", max_length=100, required=True, aliases="名字 改名"),
    _spec("character", "role_type", "角色类型", max_length=50, choices=ROLE_TYPES, aliases="定位 主角 配角 反派"),
    _spec("character", "gender", "性别", max_length=50),
    _spec("character", "age", "年龄", max_length=50),
    _spec("character", "personality", "性格", max_length=5000, aliases="性格特点"),
    _spec("character", "background", "背景故事", max_length=20000),
    _spec("character", "appearance", "外貌", max_length=5000),
    _spec("character", "speech_style", "说话风格", max_length=5000, aliases="口头禅 称呼"),
    _spec("organization", "name", "名称", max_length=100, required=True, aliases="名字 改名"),
    _spec("organization", "organization_type", "组织类型", max_length=100),
    _spec("organization", "personality", "组织特性", max_length=5000, aliases="组织风格 氛围 描述"),
    _spec("organization", "background", "背景", max_length=20000, aliases="背景描述 历史"),
    _spec("organization", "organization_purpose", "宗旨", max_length=500, aliases="目标 组织宗旨"),
    _spec("organization", "location", "所在地", max_length=2000, detail=True),
    _spec("organization", "motto", "座右铭", max_length=200, detail=True, aliases="口号"),
    _spec("chapter_outline", "title", "标题", max_length=200),
    _spec("chapter_outline", "plot_points", "剧情要点", max_length=10000),
    _spec("chapter_outline", "scene", "场景", max_length=500),
    _spec("chapter_outline", "pov", "视角角色", max_length=100),
    _spec("chapter_outline", "entry_state", "进入状态", max_length=2000),
    _spec("chapter_outline", "exit_state", "退出状态", max_length=2000),
    _spec("chapter_outline", "key_events", "关键事件", kind="list", max_length=300, max_items=20),
    _spec("chapter_outline", "forbidden", "禁止事项", kind="list", max_length=300, max_items=20),
    # 卷纲：剧情单元是结构化的（章号区间要连续覆盖），拆单元交给 detail_volume，这里只开放文字部分
    _spec("volume", "title", "卷名", max_length=200, required=True),
    _spec("volume", "goal", "目标与核心冲突", max_length=5000, aliases="目标 冲突"),
    _spec("volume", "summary", "本卷故事", max_length=20000, aliases="剧情 梗概"),
    _spec("volume", "climax", "卷末高潮", max_length=5000, aliases="高潮"),
    _spec("volume", "ending_hook", "卷末钩子", max_length=5000, aliases="钩子"),
    _spec("volume", "threads", "线索编排", kind="list", max_length=500, max_items=30, aliases="线索 感情线 支线 伏笔"),
    # 总纲是一份 JSON（梗概 / 全书主线 / 主角特殊能力 / 卖点…，谋篇页按字段编辑）：整段改会把它换成纯文本、冲掉其余字段
    _spec("story_outline", "content", "故事前提", max_length=50000, hidden=True),
    _spec("story_outline", "premise", "故事梗概", json_key="premise", max_length=5000),
    _spec("story_outline", "main_plot", "全书主线", json_key="main_plot", max_length=20000),
    _spec("story_outline", "golden_finger", "主角特殊能力", json_key="golden_finger", max_length=5000, aliases="金手指"),
    _spec("story_outline", "selling_points", "核心卖点", json_key="selling_points", kind="list", max_length=300),
    _spec("story_outline", "power_system", "成长路线", json_key="power_system", max_length=5000),
    _spec("story_outline", "main_tropes", "主要套路", json_key="main_tropes", kind="list", max_length=300),
    _spec("story_outline", "ultimate_goal", "终极目标", json_key="ultimate_goal", max_length=2000),
    _spec("story_outline", "opening_hook", "开篇钩子", json_key="opening_hook", max_length=2000),
    _spec("location", "description", "地点档案", max_length=4000),
    _spec("location", "region", "所属区域", max_length=100),
    _spec("setting_entry", "title", "名称", max_length=200, required=True),
    _spec("setting_entry", "category", "分类", max_length=50, choices=SETTING_CATEGORIES),
    _spec("setting_entry", "summary", "简述", max_length=2000),
    _spec("setting_entry", "content", "详细设定", max_length=20000),
    _spec("world_rule", "name", "名称", max_length=200, required=True),
    _spec("world_rule", "summary", "简述", max_length=2000),
    _spec("world_rule", "details", "详细设定", max_length=20000),
]
FIELD_SPECS: dict[str, FieldSpec] = {s.id: s for s in _SPECS}
LIST_LIMIT = 60
PREVIEW_CHARS = 60
NEW_OUTLINE_PREVIEW = "（本书还没有总纲：直接 propose_edit，作者应用时新建这份总纲）"


@dataclass
class NewOutline:
    """本书还没有总纲时列给助笔的空白总纲（target_id = NEW_OUTLINE）；作者应用修改时 write_field 才真正建一份。"""
    id: str
    project_id: str
    title: str
    content: str = ""


def _target_label(entity: str, obj: Any) -> str:
    if entity == "project":
        return "作品设定"
    if entity == "character":
        return f"角色「{obj.name}」"
    if entity == "organization":
        return f"组织「{obj.name}」"
    if entity == "chapter_outline":
        return f"第{obj.chapter_number}章章纲《{obj.title}》"
    if entity == "volume":
        return f"第{obj.volume_number}卷《{obj.title}》"
    if entity == "story_outline":
        return f"总纲《{obj.title}》"
    if entity == "setting_entry":
        return f"设定条目「{obj.title}」"
    if entity == "world_rule":
        return f"{WORLD_RULE_LABELS.get(obj.category, '世界规则')}「{obj.name}」"
    return f"地点「{obj.name}」"


def field_label(spec: FieldSpec, obj: Any) -> str:
    return f"{_target_label(spec.entity, obj)}·{spec.name}"


async def _org_details(db: AsyncSession, characters: list[Character]) -> None:
    """组织详情（所在地 / 座右铭）存在 organizations 表：挂到组织角色上（_org_detail），没有详情记录就是 None。"""
    ids = [c.id for c in characters]
    found = {o.character_id: o for o in (await db.execute(
        select(Organization).where(Organization.character_id.in_(ids))
    )).scalars()} if ids else {}
    for c in characters:
        c._org_detail = found.get(c.id)


async def _entity_rows(db: AsyncSession, project_id: str, entity: str) -> list[Any]:
    if entity == "project":
        project = await db.get(Project, project_id)
        return [project] if project else []
    if entity in ("character", "organization"):
        want_org = entity == "organization"
        rows = (await db.execute(
            select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
        )).scalars().all()
        picked = [c for c in rows if bool(c.is_organization) == want_org]
        if want_org:
            await _org_details(db, picked)
        return picked
    if entity == "chapter_outline":
        return list((await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id).order_by(ChapterOutline.chapter_number)
        )).scalars().all())
    if entity == "volume":
        return list((await db.execute(
            select(Volume).where(Volume.project_id == project_id).order_by(Volume.volume_number)
        )).scalars().all())
    if entity == "story_outline":  # 只列生效的那版（创作进度、规划都读它）；没有生效版才列全部；一份都没有就列一份待建的空白总纲
        rows = list((await db.execute(
            select(StoryOutline).where(StoryOutline.project_id == project_id)
            .order_by(StoryOutline.is_active.desc(), StoryOutline.version.desc(), StoryOutline.order_index)
        )).scalars().all())
        if rows:
            return [o for o in rows if o.is_active] or rows
        project = await db.get(Project, project_id)
        return [NewOutline(id=NEW_OUTLINE, project_id=project_id, title=project.title or "总纲")] if project else []
    if entity == "setting_entry":
        return list((await db.execute(
            select(SettingEntry).where(SettingEntry.project_id == project_id)
            .order_by(SettingEntry.order_index, SettingEntry.created_at)
        )).scalars().all())
    if entity == "world_rule":
        return list((await db.execute(
            select(WorldRule).where(WorldRule.project_id == project_id)
            .order_by(WorldRule.category, WorldRule.order_index, WorldRule.created_at)
        )).scalars().all())
    return list((await db.execute(
        select(WorldMapLocation).where(WorldMapLocation.project_id == project_id).order_by(WorldMapLocation.name)
    )).scalars().all())


def get_value(spec: FieldSpec, obj: Any) -> Any:
    if spec.json_key:
        value = parse_story_outline_fields(obj.content).get(spec.json_key)
        return [str(x) for x in value or []] if spec.kind == "list" else str(value or "")
    if spec.detail:
        detail = getattr(obj, "_org_detail", None)
        raw = getattr(detail, spec.attr, None) if detail is not None else None
        return "" if raw is None else str(raw)
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


async def find_fields(db: AsyncSession, project_id: str, query: str = "") -> tuple[list[dict], int, bool]:
    """按名称筛选可修改的内容项，返回（最多 60 项, 一共几项, 是否放宽成任一关键词）。
    先要求每个关键词都命中；一项都没有、又给了好几个词，就按任一关键词列（命中多的在前）——模型常把同义词一起给。"""
    terms = [t for t in (query or "").split() if t]
    scored: list[tuple[int, FieldSpec, Any, str]] = []
    for entity in ENTITY_PAGES:
        rows = await _entity_rows(db, project_id, entity)
        for spec in (s for s in _SPECS if s.entity == entity and not s.hidden):
            for obj in rows:
                label = field_label(spec, obj)
                haystack = f"{label} {spec.group} {spec.aliases} {ENTITY_ALIASES.get(entity, '')}"
                hits = sum(1 for t in terms if t in haystack)
                if hits or not terms:
                    scored.append((hits, spec, obj, label))
    picked = [item for item in scored if item[0] == len(terms)]
    loose = not picked and len(terms) > 1
    if loose:
        picked = sorted(scored, key=lambda item: -item[0])
    return [{
        "field_id": spec.id, "target_id": obj.id, "label": label, "group": spec.group,
        "kind": spec.kind, "page": spec.page,
        "preview": NEW_OUTLINE_PREVIEW if isinstance(obj, NewOutline) else _preview(get_value(spec, obj)),
    } for _hits, spec, obj, label in picked[:LIST_LIMIT]], len(picked), loose


async def list_fields(db: AsyncSession, project_id: str, query: str = "") -> list[dict]:
    """可修改的内容项（按名称筛选；不传就列全部，最多 60 项）。"""
    return (await find_fields(db, project_id, query))[0]


def spec_of(field_id: str) -> FieldSpec:
    spec = FIELD_SPECS.get(field_id)
    if spec is None:
        raise FieldError(f"没有这个可修改的内容项：{field_id}（先用 list_fields 查找）")
    return spec


async def load_target(db: AsyncSession, project_id: str, spec: FieldSpec, target_id: str) -> Any:
    if spec.entity == "story_outline" and target_id == NEW_OUTLINE:
        # 待建的空白总纲；这期间作者在谋篇页建了总纲的话，就是那份生效的总纲
        rows = await _entity_rows(db, project_id, "story_outline")
        if not rows:
            raise FieldNotFound("在本书里找不到这项内容：总纲")
        return rows[0]
    model = {
        "project": Project, "character": Character, "organization": Character, "chapter_outline": ChapterOutline,
        "volume": Volume, "story_outline": StoryOutline, "location": WorldMapLocation, "setting_entry": SettingEntry,
        "world_rule": WorldRule,
    }[spec.entity]
    obj = await db.get(model, target_id) if target_id else None
    owner = getattr(obj, "id" if spec.entity == "project" else "project_id", None) if obj is not None else None
    if obj is None or owner != project_id:
        raise FieldNotFound(f"在本书里找不到这项内容：{spec.name}（{target_id}）")
    if spec.entity in ("character", "organization") and bool(obj.is_organization) != (spec.entity == "organization"):
        raise FieldNotFound(f"「{obj.name}」不是{'组织' if spec.entity == 'organization' else '人物'}")
    if spec.entity == "organization":
        await _org_details(db, [obj])
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
    if spec.id == "character.role_type":  # 和页面一样认「主角 / 配角 / 反派」等中文写法
        text = normalize_role_type(text) or ""
    if spec.required and not text:
        raise FieldError(f"{spec.name}不能为空")
    if len(text) > spec.max_length:
        raise FieldError(f"{spec.name}不超过 {spec.max_length} 字（现在 {len(text)} 字）")
    optional = spec.id == "project.platform_preset"  # 目标平台留空 = 通用
    if spec.choices and text not in spec.choices and not (optional and not text):
        raise FieldError(f"{spec.name}只能是 {'/'.join(spec.choices)}" + ("（留空 = 通用）" if optional else ""))
    return text


def _with_outline_key(content: Optional[str], key: str, value: Any) -> str:
    """改总纲的一个字段：其余键原样保留；原来是纯文本的总纲当作梗概，转成 JSON（与谋篇页的读法一致）。"""
    try:
        data = json.loads(content) if content else {}
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {"premise": content} if content else {}
    return json.dumps({**data, key: value}, ensure_ascii=False)


async def _create_outline(db: AsyncSession, placeholder: NewOutline) -> StoryOutline:
    """作者应用第一条总纲修改时才建出这份总纲（和谋篇页新建一样：第 1 版、生效）。"""
    outline = StoryOutline(id=str(uuid.uuid4()), project_id=placeholder.project_id, title=placeholder.title,
                           content="{}", version=1, is_active=True)
    db.add(outline)
    await db.flush()
    return outline


async def write_field(db: AsyncSession, project_id: str, field_id: str, target_id: str, value: Any) -> Any:
    """写入一项内容（与手动编辑相同的连带处理）；返回规整后的值。"""
    spec = spec_of(field_id)
    obj = await load_target(db, project_id, spec, target_id)
    normalized = normalize_value(spec, value)
    changed = get_value(spec, obj) != normalized
    if isinstance(obj, NewOutline):
        obj = await _create_outline(db, obj)
    if spec.entity == "volume":  # 与谋篇页保存卷纲同一处理：内容真的变了 → 本卷章纲标「上游已改」
        from app.services import volume_service  # 延迟导入：卷纲服务依赖多，不放进目录模块的导入链

        await volume_service.update_volume(db, obj, {spec.attr: normalized})
        return normalized
    renames_place = changed and spec.entity == "world_rule" and spec.attr == "name" and obj.category == wms.RULE_CATEGORY
    if renames_place:  # 「地图位置」规则和世界地图上的地点一一对应：先查重名
        try:
            await wms.check_rule_location_name(db, project_id, normalized, obj.id)
        except wms.WorldMapError as exc:
            raise FieldConflict(str(exc)) from exc
    if changed and spec.entity in ("character", "organization") and spec.attr == "name":
        # 与角色页改名相同：别处的名字快照一并改掉，旧名记进曾用名
        await propagate_character_rename(db, project_id, obj.name, normalized)
        obj.aliases = record_former_name(obj.aliases, obj.name, normalized)
    if spec.json_key:
        obj.content = _with_outline_key(obj.content, spec.json_key, normalized)
    elif spec.detail:
        detail = getattr(obj, "_org_detail", None) or await ensure_organization_record(obj, db)
        setattr(detail, spec.attr, normalized or None)
    else:
        setattr(obj, spec.attr, json.dumps(normalized, ensure_ascii=False) if spec.kind == "list" else normalized)
    if changed and spec.entity == "story_outline":
        await outline_review.mark_project_outlines(db, project_id, "总纲（故事大纲）已修改")
    if changed and spec.entity == "location":
        world_map = await load_map(db, project_id)
        if world_map is not None:
            world_map.revision = (world_map.revision or 0) + 1
    if renames_place:
        await wms.sync_rule_locations(db, project_id)  # 世界地图上的地点跟着改名
    await db.flush()
    if changed and spec.entity == "setting_entry":
        await _sync_setting_entry(obj)
    if changed and spec.entity == "world_rule":
        await sync_world_rule(obj)
    return normalized


async def sync_world_rule(rule: Any) -> None:
    """世界规则新建 / 修改后：向量索引同步成新内容（与世界规则页相同的连带处理）；失败只记日志，不影响写入。"""
    try:
        from app.services.world_rule_service import world_rule_service  # 延迟导入，不把向量依赖拉进导入链

        await world_rule_service.upsert_rule_to_vector_db(rule)
    except Exception as exc:  # noqa: BLE001 - 向量只是增强
        logger.warning(f"⚠️ 世界规则「{getattr(rule, 'name', '')}」向量同步失败（不影响修改）：{exc}")


async def _sync_setting_entry(entry: Any) -> None:
    """改了设定条目：向量索引同步成新内容（与页面手动编辑相同的连带处理）；失败只记日志，不影响写入。"""
    try:
        from app.services.setting_entry_service import setting_entry_index  # 延迟导入，不把向量依赖拉进导入链

        await setting_entry_index().sync(entry)
    except Exception as exc:  # noqa: BLE001 - 向量只是增强
        logger.warning(f"⚠️ 设定条目「{getattr(entry, 'title', '')}」向量重同步失败（不影响修改）：{exc}")


def entity_of(field_id: str) -> Optional[str]:
    spec = FIELD_SPECS.get(field_id)
    return spec.entity if spec else None
