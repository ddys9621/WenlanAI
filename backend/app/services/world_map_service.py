"""世界地图（参考岚笺「作者标注沙盘」）：平面布局 + 地点档案；底图由前端按 seed / 地形提示程序化绘制。

- 坐标是作者平面布局的 0–100 百分比，不是经纬度；未定位的地点不按列表序号或名字子串自动落点
- 故事地点按原文收集（时间轴事件 / 人物地点信号 / 章纲场景 / 作品地理设定），不拆分复合地点、不猜同名
- 地点档案只按「地点名 + 作者绑定的原文地点（source_names）」精确匹配，按章节顺序列出处
- AI 只产出布局候选（存在 world_maps.candidate_json），作者采用才写入；默认不挪动已放好的地点，
  候选里的原文绑定只接受真实收集到的地点原文
- 世界规则「地图位置」每条都在地图上有一个绑定地点（rule_id）：规则增删改时同步，打开地图时兜底补齐；
  地图上没登记的地点由作者决定是否登记成规则（不自动登记，免得零碎小地点挤占写作时的设定检索）
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.timeline_event import TimelineEvent
from app.models.world_map import WorldMap, WorldMapLocation
from app.models.world_rule import WorldRule
from app.schemas.world_map import LOCATION_KINDS
from app.utils.json_cleaner import safe_parse_json
from app.utils.prompt_safety import UNTRUSTED_DATA_RULE, quote_untrusted

logger = get_logger(__name__)

CANVAS_MIN, CANVAS_MAX = 2.0, 98.0
MAX_CANDIDATE_LOCATIONS = 200
MAX_SOURCE_NAMES = 256
SETTING_LOCATION_MAX_CHARS = 40
PROMPT_STORY_LOCATIONS = 80
SEA_SIDES = ("east", "west", "north", "south", "none")
SIGNAL_LABELS = {"arrived": "来到这里", "left": "离开这里", "current": "在这里"}
RULE_CATEGORY = "map_location"


class WorldMapError(Exception):
    status_code = 400


class WorldMapValidation(WorldMapError):
    status_code = 400


class WorldMapConflict(WorldMapError):
    status_code = 409


class WorldMapNotFound(WorldMapError):
    status_code = 404


def default_seed(project_id: str) -> int:
    return int(hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647


def _loads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def clean_source_names(names: Optional[Iterable[str]]) -> list[str]:
    out: list[str] = []
    for name in names or []:
        text = str(name or "").strip()[:2000]
        if text and text not in out:
            out.append(text)
    return out[:MAX_SOURCE_NAMES]


def normalize_kind(kind: Optional[str]) -> str:
    return kind if kind in LOCATION_KINDS else "other"


def location_view(loc: WorldMapLocation) -> dict:
    return {
        "id": loc.id,
        "name": loc.name,
        "x": loc.x,
        "y": loc.y,
        "kind": loc.kind or "other",
        "region": loc.region,
        "description": loc.description,
        "source_names": _loads(loc.source_names, []),
        "origin": loc.origin or "author",
        "rule_id": loc.rule_id,
    }


def map_view(world_map: Optional[WorldMap], project_id: str) -> dict:
    if world_map is None:
        return {"seed": default_seed(project_id), "style": "paper-atlas", "terrain": {}, "revision": 0, "has_candidate": False}
    return {
        "seed": world_map.seed,
        "style": world_map.style or "paper-atlas",
        "terrain": _loads(world_map.terrain_json, {}),
        "revision": world_map.revision or 0,
        "has_candidate": bool(world_map.candidate_json),
    }


async def load_map(db: AsyncSession, project_id: str) -> Optional[WorldMap]:
    return (await db.execute(select(WorldMap).where(WorldMap.project_id == project_id))).scalar_one_or_none()


async def ensure_map(db: AsyncSession, project_id: str) -> WorldMap:
    """读不建表行；第一次真正保存（布局 / 地点 / 候选）时才建。"""
    world_map = await load_map(db, project_id)
    if world_map is None:
        world_map = WorldMap(project_id=project_id, seed=default_seed(project_id), style="paper-atlas", revision=0)
        db.add(world_map)
        await db.flush()
    return world_map


async def _bump(db: AsyncSession, project_id: str) -> WorldMap:
    world_map = await ensure_map(db, project_id)
    world_map.revision = (world_map.revision or 0) + 1
    return world_map


async def list_locations(db: AsyncSession, project_id: str) -> list[WorldMapLocation]:
    return list((await db.execute(
        select(WorldMapLocation).where(WorldMapLocation.project_id == project_id).order_by(WorldMapLocation.name)
    )).scalars().all())


async def collect_story_locations(db: AsyncSession, project_id: str) -> list[dict]:
    """故事里出现过的地点原文：提及次数、首末章、来源（按提及次数降序）。"""
    found: dict[str, dict] = {}

    def add(raw: Optional[str], chapter: Optional[int], source: str) -> None:
        name = (raw or "").strip()
        if not name:
            return
        entry = found.setdefault(name, {"name": name, "mentions": 0, "first_chapter": None, "last_chapter": None,
                                        "sources": []})
        entry["mentions"] += 1
        if chapter is not None:
            entry["first_chapter"] = chapter if entry["first_chapter"] is None else min(entry["first_chapter"], chapter)
            entry["last_chapter"] = chapter if entry["last_chapter"] is None else max(entry["last_chapter"], chapter)
        if source not in entry["sources"]:
            entry["sources"].append(source)

    for location, chapter in (await db.execute(
        select(TimelineEvent.location, TimelineEvent.chapter_number).where(TimelineEvent.project_id == project_id)
    )).all():
        add(location, chapter, "timeline")
    for key, chapter in (await db.execute(
        select(ChapterContinuitySignal.signal_key, ChapterContinuitySignal.chapter_number).where(
            ChapterContinuitySignal.project_id == project_id, ChapterContinuitySignal.signal_type == "location",
        )
    )).all():
        add(key, chapter, "signal")
    for scene, chapter in (await db.execute(
        select(ChapterOutline.scene, ChapterOutline.chapter_number).where(ChapterOutline.project_id == project_id)
    )).all():
        add(scene, chapter, "outline")
    project = await db.get(Project, project_id)
    setting = (getattr(project, "world_location", None) or "").strip()
    if setting and len(setting) <= SETTING_LOCATION_MAX_CHARS:
        add(setting, None, "setting")
    return sorted(found.values(), key=lambda e: (-e["mentions"], e["first_chapter"] or 10**9, e["name"]))


def bound_names(loc: WorldMapLocation) -> set[str]:
    return {loc.name.strip(), *_loads(loc.source_names, [])}


def _place_name(rule: WorldRule) -> str:
    return (rule.name or "").strip()[:100]


def _rule_view(rule: WorldRule) -> dict:
    return {"id": rule.id, "key": rule.key, "name": rule.name, "summary": rule.summary, "details": rule.details}


async def list_location_rules(db: AsyncSession, project_id: str) -> list[WorldRule]:
    return list((await db.execute(
        select(WorldRule).where(WorldRule.project_id == project_id, WorldRule.category == RULE_CATEGORY)
        .order_by(WorldRule.order_index, WorldRule.created_at)
    )).scalars().all())


async def _linked_rule(db: AsyncSession, loc: WorldMapLocation) -> Optional[WorldRule]:
    rule = await db.get(WorldRule, loc.rule_id) if loc.rule_id else None
    return rule if rule is not None and rule.category == RULE_CATEGORY and rule.project_id == loc.project_id else None


async def check_rule_location_name(db: AsyncSession, project_id: str, name: str, rule_id: Optional[str] = None) -> None:
    """「地图位置」规则新建 / 改名 / 改成这一类之前：规则之间不重名；地图上的同名地点只能是它自己的，或还没登记的（会直接绑上）。"""
    name = (name or "").strip()
    query = select(WorldRule.id).where(
        WorldRule.project_id == project_id, WorldRule.category == RULE_CATEGORY, func.trim(WorldRule.name) == name,
    )
    if rule_id:
        query = query.where(WorldRule.id != rule_id)
    if (await db.execute(query)).first():
        raise WorldMapValidation(f"已经有叫「{name}」的地图位置规则了")
    same = (await db.execute(select(WorldMapLocation).where(
        WorldMapLocation.project_id == project_id, WorldMapLocation.name == name[:100],
    ))).scalar_one_or_none()
    if same is None or (rule_id and same.rule_id == rule_id):
        return
    owns_other = rule_id and (await db.execute(select(WorldMapLocation.id).where(
        WorldMapLocation.project_id == project_id, WorldMapLocation.rule_id == rule_id,
    ))).first()
    if owns_other or await _linked_rule(db, same) is not None:
        raise WorldMapConflict(f"世界地图上已经有叫「{name}」的地点了，请先在地图上给它改名或删掉")


async def sync_rule_locations(db: AsyncSession, project_id: str) -> bool:
    """让地图跟上世界规则「地图位置」：每条规则都有一个绑定地点（规则改名地点跟着改；地图上已有同名的直接绑上，没有就建一个未定位的）。
    绑定的规则没了 / 改了分类的解除绑定：规则生成、还没定位的（纯投影）删掉，放到过地图上的归作者、留作未登记地点。
    规则接口增删改时调用；向导生成 / 重生成、导入的规则在打开地图时由这里补齐。有改动时升版本并返回 True。"""
    rules = await list_location_rules(db, project_id)
    rule_ids = {r.id for r in rules}
    locations = await list_locations(db, project_id)
    by_name = {loc.name: loc for loc in locations}
    linked = {loc.rule_id: loc for loc in locations if loc.rule_id in rule_ids}
    changed = False
    for rule in rules:
        name = _place_name(rule)
        loc = linked.get(rule.id)
        if loc is not None:
            if name and loc.name != name and name not in by_name:
                by_name.pop(loc.name, None)
                loc.name, by_name[name] = name, loc
                changed = True
            continue
        if not name:
            continue
        loc = by_name.get(name)
        if loc is None:
            loc = WorldMapLocation(project_id=project_id, name=name, kind="other", description=rule.summary or None,
                                   source_names="[]", origin="rule")
            db.add(loc)
            by_name[name] = loc
        elif loc.rule_id in rule_ids:
            continue  # 同名地点已经归另一条规则
        elif not (loc.description or "").strip() and rule.summary:
            loc.description = rule.summary
        loc.rule_id = rule.id
        linked[rule.id] = loc
        changed = True
    for loc in locations:
        if loc.rule_id in rule_ids:
            continue
        if loc.rule_id:
            loc.rule_id = None
            changed = True
        if loc.origin == "rule":
            if loc.x is None or loc.y is None:
                await db.delete(loc)
            else:
                loc.origin = "author"
            changed = True
    if changed:
        await _bump(db, project_id)
    return changed


async def delete_rule_locations(db: AsyncSession, project_id: str, rule_id: str) -> None:
    """规则页删掉「地图位置」规则：地图上绑定的地点（连同坐标和档案）一并删除。"""
    locs = (await db.execute(select(WorldMapLocation).where(
        WorldMapLocation.project_id == project_id, WorldMapLocation.rule_id == rule_id,
    ))).scalars().all()
    for loc in locs:
        await db.delete(loc)
    if locs:
        await _bump(db, project_id)


def _new_rule_key(taken: set[str]) -> str:
    key = f"map_{uuid.uuid4().hex[:8]}"
    while key in taken:
        key = f"map_{uuid.uuid4().hex[:8]}"
    taken.add(key)
    return key


async def register_rules(db: AsyncSession, project_id: str, location_ids: Optional[list[str]] = None) -> list[WorldRule]:
    """把地图上还没登记的地点登记成世界规则「地图位置」：地点档案作简介，所属区域写进详情。返回新建的规则（提交后再向量化）。"""
    await sync_rule_locations(db, project_id)
    rules = await list_location_rules(db, project_id)
    names = {_place_name(r) for r in rules}
    keys = set((await db.execute(select(WorldRule.key).where(WorldRule.project_id == project_id))).scalars().all())
    order = max((r.order_index or 0 for r in rules), default=0)
    wanted = None if location_ids is None else set(location_ids)
    created: list[WorldRule] = []
    for loc in await list_locations(db, project_id):
        if loc.rule_id or loc.name in names or (wanted is not None and loc.id not in wanted):
            continue
        order += 1
        region = (loc.region or "").strip()
        rule = WorldRule(
            id=str(uuid.uuid4()), project_id=project_id, category=RULE_CATEGORY, key=_new_rule_key(keys), name=loc.name,
            order_index=order, summary=(loc.description or "").strip() or None,
            details=f"所属区域：{region}" if region else None,
        )
        db.add(rule)
        loc.rule_id = rule.id
        created.append(rule)
    if created:
        await _bump(db, project_id)
    return created


async def build_view(db: AsyncSession, project_id: str) -> dict:
    world_map = await load_map(db, project_id)
    locations = await list_locations(db, project_id)
    owner: dict[str, str] = {}
    for loc in locations:
        for name in bound_names(loc):
            owner.setdefault(name, loc.id)
    story = await collect_story_locations(db, project_id)
    for entry in story:
        entry["bound_to"] = owner.get(entry["name"])
    return {
        "map": map_view(world_map, project_id),
        "locations": [location_view(loc) for loc in locations],
        "story_locations": story,
    }


async def save_layout(db: AsyncSession, project_id: str, expected_revision: int, markers: list[Any]) -> None:
    world_map = await ensure_map(db, project_id)
    if expected_revision != (world_map.revision or 0):
        raise WorldMapConflict("地图在别处被改过（版本已变化），请刷新后再保存；你的调整不会被自动覆盖")
    names = [m.name.strip() for m in markers]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise WorldMapValidation(f"地点重名：{'、'.join(dupes)}")
    locations = await list_locations(db, project_id)
    by_id = {loc.id: loc for loc in locations}
    by_name = {loc.name: loc for loc in locations}
    for marker, name in zip(markers, names):
        if marker.id:
            loc = by_id.get(marker.id)
            if loc is None:
                raise WorldMapValidation(f"地点不存在：{name}")
        else:
            loc = by_name.get(name)
            if loc is None:
                loc = WorldMapLocation(project_id=project_id, name=name, kind="other", origin="author")
                db.add(loc)
                by_name[name] = loc
        loc.x, loc.y = float(marker.x), float(marker.y)
    world_map.revision = (world_map.revision or 0) + 1


async def get_location(db: AsyncSession, project_id: str, location_id: str) -> WorldMapLocation:
    loc = await db.get(WorldMapLocation, location_id)
    if loc is None or loc.project_id != project_id:
        raise WorldMapNotFound("地点不存在")
    return loc


async def _name_taken(db: AsyncSession, project_id: str, name: str, exclude_id: Optional[str] = None) -> bool:
    query = select(WorldMapLocation.id).where(WorldMapLocation.project_id == project_id, WorldMapLocation.name == name)
    if exclude_id:
        query = query.where(WorldMapLocation.id != exclude_id)
    return (await db.execute(query)).first() is not None


async def create_location(db: AsyncSession, project_id: str, data: Any) -> WorldMapLocation:
    name = data.name.strip()
    if await _name_taken(db, project_id, name):
        raise WorldMapConflict(f"已经有叫「{name}」的地点了")
    loc = WorldMapLocation(
        project_id=project_id, name=name, x=data.x, y=data.y, kind=normalize_kind(data.kind), region=data.region,
        description=data.description, source_names=json.dumps(clean_source_names(data.source_names), ensure_ascii=False),
        origin="author",
    )
    db.add(loc)
    await _bump(db, project_id)
    await db.flush()
    return loc


async def update_location(db: AsyncSession, loc: WorldMapLocation, data: Any) -> WorldMapLocation:
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        name = updates["name"].strip()
        if await _name_taken(db, loc.project_id, name, exclude_id=loc.id):
            raise WorldMapConflict(f"已经有叫「{name}」的地点了")
        rule = await _linked_rule(db, loc)
        if rule is not None and _place_name(rule) != name:
            await check_rule_location_name(db, loc.project_id, name, rule_id=rule.id)
            rule.name = name  # 规则地点改名，世界规则跟着改
        loc.name = name
    for field in ("x", "y", "region", "description"):
        if field in updates and updates[field] is not None:
            setattr(loc, field, updates[field])
    if updates.get("kind") is not None:
        loc.kind = normalize_kind(updates["kind"])
    if updates.get("source_names") is not None:
        loc.source_names = json.dumps(clean_source_names(updates["source_names"]), ensure_ascii=False)
    if updates.get("clear_position"):
        loc.x = loc.y = None
    await _bump(db, loc.project_id)
    return loc


async def delete_location(db: AsyncSession, loc: WorldMapLocation) -> None:
    if await _linked_rule(db, loc) is not None:
        raise WorldMapConflict(f"「{loc.name}」是世界规则里的地点，要删除请到世界规则页删掉这条规则；地图上可以取消定位")
    project_id = loc.project_id
    await db.delete(loc)
    await _bump(db, project_id)


async def dossier(db: AsyncSession, loc: WorldMapLocation) -> dict:
    names = bound_names(loc)
    titles = dict((await db.execute(
        select(Chapter.chapter_number, Chapter.title).where(Chapter.project_id == loc.project_id)
    )).all())
    mentions: list[dict] = []
    for event in (await db.execute(select(TimelineEvent).where(
        TimelineEvent.project_id == loc.project_id, TimelineEvent.location.in_(names),
    ))).scalars().all():
        mentions.append({"chapter_number": event.chapter_number, "source": "timeline", "raw_location": event.location,
                         "text": f"{event.title}：{event.description}"})
    for signal in (await db.execute(select(ChapterContinuitySignal).where(
        ChapterContinuitySignal.project_id == loc.project_id,
        ChapterContinuitySignal.signal_type == "location",
        ChapterContinuitySignal.signal_key.in_(names),
    ))).scalars().all():
        label = SIGNAL_LABELS.get(signal.signal_value or "", signal.signal_value or "")
        mentions.append({"chapter_number": signal.chapter_number, "source": "signal", "raw_location": signal.signal_key,
                         "text": f"{signal.character_name or '某人'}{label}"})
    for outline in (await db.execute(select(ChapterOutline).where(
        ChapterOutline.project_id == loc.project_id, ChapterOutline.scene.in_(names),
    ))).scalars().all():
        mentions.append({"chapter_number": outline.chapter_number, "source": "outline", "raw_location": outline.scene,
                         "text": f"章纲场景：{outline.title}"})
    order = {"timeline": 0, "signal": 1, "outline": 2}
    mentions.sort(key=lambda m: (m["chapter_number"], order[m["source"]]))
    for m in mentions:
        m["chapter_title"] = titles.get(m["chapter_number"])
    rule = await _linked_rule(db, loc)
    return {"location": location_view(loc), "rule": _rule_view(rule) if rule else None, "mentions": mentions}


def _coord(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(min(CANVAS_MAX, max(CANVAS_MIN, number)), 2)


def _sanitize_terrain(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    mountains = []
    for item in raw.get("mountains") if isinstance(raw.get("mountains"), list) else []:
        if isinstance(item, dict):
            x, y, r = _coord(item.get("x")), _coord(item.get("y")), _coord(item.get("r"))
            if x is not None and y is not None:
                mountains.append({"x": x, "y": y, "r": min(25.0, max(3.0, r or 8.0))})
    rivers = []
    for item in raw.get("rivers") if isinstance(raw.get("rivers"), list) else []:
        points = item.get("points") if isinstance(item, dict) else None
        cleaned = [
            [px, py] for px, py in ((_coord(p[0]), _coord(p[1])) for p in (points or [])
                                    if isinstance(p, (list, tuple)) and len(p) >= 2)
            if px is not None and py is not None
        ][:12]
        if len(cleaned) >= 2:
            rivers.append({"points": cleaned})
    regions = []
    for item in raw.get("regions") if isinstance(raw.get("regions"), list) else []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            x, y = _coord(item.get("x")), _coord(item.get("y"))
            if x is not None and y is not None:
                regions.append({"name": str(item["name"]).strip()[:20], "x": x, "y": y})
    return {
        "sea": raw.get("sea") if raw.get("sea") in SEA_SIDES else None,
        "mountains": mountains[:12],
        "rivers": rivers[:6],
        "regions": regions[:12],
    }


def parse_layout(raw: Any, known_raw_names: set[str]) -> dict:
    """模型给的布局 → 清洗后的候选：去重 / 坐标夹进画布 / 非法坐标当未定位 / 绑定只留真实原文地点。"""
    raw = raw if isinstance(raw, dict) else {}
    locations: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("locations") if isinstance(raw.get("locations"), list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:100]
        if not name or name in seen:
            continue
        seen.add(name)
        x, y = _coord(item.get("x")), _coord(item.get("y"))
        if x is None or y is None:
            x = y = None
        sources = [s for s in clean_source_names(item.get("source_names") if isinstance(item.get("source_names"), list) else [])
                   if s in known_raw_names]
        locations.append({
            "name": name, "x": x, "y": y, "kind": normalize_kind(item.get("kind")),
            "region": str(item.get("region") or "").strip()[:100] or None,
            "description": str(item.get("description") or "").strip()[:600] or None,
            "source_names": sources,
        })
        if len(locations) >= MAX_CANDIDATE_LOCATIONS:
            break
    return {"terrain": _sanitize_terrain(raw.get("terrain")), "locations": locations}


MAP_SYSTEM = (
    "你是小说世界的地图设计师：根据作品设定、世界规则里的地点和故事里出现过的地点，设计一张平面世界地图的布局。"
    "只依据给出的资料推断方位，不编造原文没有的情节。\n\n" + UNTRUSTED_DATA_RULE
)

MAP_PROMPT = """请为这部小说设计一张平面世界地图的布局。坐标是 0-100 的百分比（不是经纬度）：x 从西到东，y 从北到南。

【作品】
{project}

【故事里出现过的地点（原文写法，按提及次数）】
{story}

【作者已经放好的地点（坐标不要改，照抄）】
{placed}

【地图上已有、还没定位的地点（每个都要给坐标，名字逐字照抄）】
{pending}

要求：
- 给每个故事地点一个合理位置：同一区域的彼此靠近；按故事先后到达的地点沿路线排布；信息不足就按名字和类型推断大致方位
- 带「设定」的是世界规则里的地点：按设定里的地理位置、与其他地点的关系摆放
- 同一处的不同叫法可以合并成一个地点，把这些原文写法放进 source_names（必须逐字来自上面的列表）
- description 用 1-2 句写它在故事里是什么地方，不编造情节
- terrain 写海在哪一侧（east/west/north/south/none）、主要山脉（圆心与半径）、河流（折线点）、区域名

只输出 JSON 对象（不要 markdown）：
{{"terrain": {{"sea": "east", "mountains": [{{"x": 30, "y": 20, "r": 10}}], "rivers": [{{"points": [[10, 40], [50, 55], [90, 60]]}}],
  "regions": [{{"name": "东荒", "x": 75, "y": 40}}]}},
 "locations": [{{"name": "地点名", "x": 40, "y": 55, "kind": "{kinds}", "region": "所属区域", "description": "地点档案", "source_names": ["原文写法"]}}]}}"""


def _rule_hint(rule: Optional[WorldRule]) -> str:
    """规则地点的设定摘要（地理位置 / 与其他地点的关系等），供 AI 排布局。"""
    if rule is None:
        return ""
    text = " ".join(f"{rule.summary or ''} {rule.details or ''}".split())
    return f"｜设定：{text[:160]}" if text else ""


def build_generation_prompt(
    project: Any, story: list[dict], locations: list[WorldMapLocation], rules: Iterable[WorldRule] = (),
) -> str:
    project_lines = [
        f"书名：{getattr(project, 'title', '')}｜类型：{getattr(project, 'genre', '') or '未设定'}",
        f"时代背景：{(getattr(project, 'world_time_period', None) or '未设定')[:300]}",
        f"地理设定：{(getattr(project, 'world_location', None) or '未设定')[:600]}",
        f"世界规则：{(getattr(project, 'world_rules', None) or '未设定')[:600]}",
    ]
    story_lines = "\n".join(
        f"- {e['name']}（提及 {e['mentions']} 次" + (f"，首次第 {e['first_chapter']} 章）" if e["first_chapter"] else "）")
        for e in story[:PROMPT_STORY_LOCATIONS]
    ) or "（暂无）"
    rule_by_id = {r.id: r for r in rules}
    placed_lines = "\n".join(
        f"- {loc.name} ({loc.x:g}, {loc.y:g}){_rule_hint(rule_by_id.get(loc.rule_id))}"
        for loc in locations if loc.x is not None and loc.y is not None
    ) or "（暂无）"
    pending = sorted((loc for loc in locations if loc.x is None or loc.y is None), key=lambda loc: loc.rule_id not in rule_by_id)
    pending_lines = "\n".join(
        f"- {loc.name}{_rule_hint(rule_by_id.get(loc.rule_id))}" for loc in pending[:PROMPT_STORY_LOCATIONS]
    ) or "（暂无）"
    return MAP_PROMPT.format(
        project=quote_untrusted("\n".join(project_lines), "作品设定"),
        story=quote_untrusted(story_lines, "故事地点"),
        placed=quote_untrusted(placed_lines, "已放好的地点"),
        pending=quote_untrusted(pending_lines, "待定位地点"),
        kinds="/".join(LOCATION_KINDS),
    )


async def generate_candidate(job: Any, *, session_factory: Any, project_id: str, ai_service: Any) -> dict:
    async with session_factory() as db:
        project = await db.get(Project, project_id)
        story = await collect_story_locations(db, project_id)
        locations = await list_locations(db, project_id)
        rules = await list_location_rules(db, project_id)
        job.progress(f"整理出 {len(story)} 个故事地点，设计布局中…", 20)
        result = await ai_service.generate_text_stream_collect(
            prompt=build_generation_prompt(project, story, locations, rules), system_prompt=MAP_SYSTEM, temperature=0.6,
        )
        raw = safe_parse_json((result or {}).get("content") or "", default=None, expected_type="object",
                              log_prefix="[世界地图]")
        layout = parse_layout(raw, {e["name"] for e in story})
        if not layout["locations"]:
            raise ValueError("模型没有给出可用的地点布局，请稍后重试")
        world_map = await ensure_map(db, project_id)
        world_map.candidate_json = json.dumps(layout, ensure_ascii=False)
        await db.commit()
        job.progress(f"布局候选已生成：{len(layout['locations'])} 个地点，采用后才写入地图", 95)
        return {"candidate": layout}


async def adopt_candidate(db: AsyncSession, project_id: str, replace_positions: bool = False) -> None:
    world_map = await load_map(db, project_id)
    layout = _loads(world_map.candidate_json if world_map else None, None)
    if not layout:
        raise WorldMapValidation("没有待采用的地图候选")
    by_name = {loc.name: loc for loc in await list_locations(db, project_id)}
    for item in layout.get("locations") or []:
        loc = by_name.get(item["name"])
        if loc is None:
            db.add(WorldMapLocation(
                project_id=project_id, name=item["name"], x=item.get("x"), y=item.get("y"),
                kind=normalize_kind(item.get("kind")), region=item.get("region"), description=item.get("description"),
                source_names=json.dumps(item.get("source_names") or [], ensure_ascii=False), origin="ai",
            ))
            continue
        if item.get("x") is not None and item.get("y") is not None and (replace_positions or loc.x is None or loc.y is None):
            loc.x, loc.y = item["x"], item["y"]
        if not (loc.description or "").strip() and item.get("description"):
            loc.description = item["description"]
        if not (loc.region or "").strip() and item.get("region"):
            loc.region = item["region"]
        if (loc.kind or "other") == "other" and item.get("kind") and item["kind"] != "other":
            loc.kind = item["kind"]
        merged = clean_source_names([*_loads(loc.source_names, []), *(item.get("source_names") or [])])
        loc.source_names = json.dumps(merged, ensure_ascii=False)
    terrain = layout.get("terrain") or {}
    if any(terrain.get(k) for k in ("sea", "mountains", "rivers", "regions")):
        world_map.terrain_json = json.dumps(terrain, ensure_ascii=False)
    world_map.candidate_json = None
    world_map.revision = (world_map.revision or 0) + 1


async def discard_candidate(db: AsyncSession, project_id: str) -> None:
    world_map = await load_map(db, project_id)
    if world_map is not None:
        world_map.candidate_json = None


async def update_settings(db: AsyncSession, project_id: str, seed: Optional[int], style: Optional[str]) -> None:
    world_map = await ensure_map(db, project_id)
    if seed is not None:
        world_map.seed = seed
    if style:
        world_map.style = style[:30]
    world_map.revision = (world_map.revision or 0) + 1


def candidate_of(world_map: Optional[WorldMap]) -> Optional[dict]:
    return _loads(world_map.candidate_json, None) if world_map else None
