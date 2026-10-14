"""世界地图 → 写作参考：把作者在地图上摆好的位置翻译成 AI 用得上的方位与远近。

- 坐标是平面布局的 0–100 百分比（x 西→东、y 北→南），没有比例尺：不给数字，只给八方位 + 远近档
- 写正文：本章相关地点（章纲场景 / 章纲点名 / 出场角色所在）的档案、相对场景的方位远近、场景附近的地点
- 章纲展开 / 桥段规划：全书地图概要（各区域在地图哪一片、有哪些地点、主要地点之间的方位远近）
- 认地点用「地点名 + 绑定的原文地点」：整串相同优先，否则取文字里出现的最长地名（至少 2 个字）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.world_map import WorldMapLocation
from app.models.world_rule import WorldRule
from app.services import world_map_service as wms
from app.services.character_state_service import load_character_states

KIND_LABELS = {
    "city": "城池", "town": "城镇", "village": "村落", "sect": "宗门", "palace": "宫殿", "mountain": "山岳", "forest": "森林",
    "river": "河流", "lake": "湖泊", "sea": "海域", "desert": "荒漠", "ruin": "遗迹", "pass": "关隘", "island": "岛屿",
}
DIRECTIONS = ("正东", "东北", "正北", "西北", "正西", "西南", "正南", "东南")
SAME_SPOT = 4.0
DISTANCE_BANDS = ((12.0, "很近"), (30.0, "不远"), (55.0, "较远"))
NEARBY_RADIUS = 30.0
CHAPTER_PLACE_LIMIT = 8
NEARBY_LIMIT = 3
OVERVIEW_PLACE_LIMIT = 40
OVERVIEW_RELATION_LIMIT = 8
SEA_LABELS = {"east": "东边", "west": "西边", "north": "北边", "south": "南边"}
MAP_NOTE = "作者在世界地图上的布局：上北下南，远近只是相对的，不是具体里程"
MENTIONED = "章纲提到"


@dataclass
class Place:
    loc: WorldMapLocation
    rule: Optional[WorldRule] = None

    @property
    def name(self) -> str:
        return self.loc.name

    @property
    def placed(self) -> bool:
        return self.loc.x is not None and self.loc.y is not None


@dataclass
class MapReference:
    text: str = ""
    items: list[dict[str, str]] = field(default_factory=list)  # 生成过程「参考资料」条目


async def load_places(db: AsyncSession, project_id: str) -> list[Place]:
    rules = {r.id: r for r in await wms.list_location_rules(db, project_id)}
    return [Place(loc, rules.get(loc.rule_id)) for loc in await wms.list_locations(db, project_id)]


def _dist(a: Any, b: Any) -> float:
    return math.dist((a.x, a.y), (b.x, b.y))


def direction(origin: Any, target: Any) -> str:
    """target 在 origin 的哪个方向（x 向东、y 向南）。"""
    angle = math.degrees(math.atan2(origin.y - target.y, target.x - origin.x)) % 360
    return DIRECTIONS[int((angle + 22.5) // 45) % 8]


def distance_label(d: float) -> str:
    return next((label for limit, label in DISTANCE_BANDS if d < limit), "很远")


def relation(origin: Any, target: Any) -> str:
    d = _dist(origin, target)
    if d < SAME_SPOT:
        return f"{target.name}和{origin.name}几乎在同一处"
    return f"{target.name}在{origin.name}{direction(origin, target)}方向，{distance_label(d)}"


def map_area(x: float, y: float) -> str:
    """落在地图哪一片（九宫格）。"""
    ew = "西" if x < 34 else "东" if x > 66 else ""
    ns = "北" if y < 34 else "南" if y > 66 else ""
    return f"{(ew + ns) or '中'}部"


def _clip(text: Optional[str], limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _kind(loc: WorldMapLocation) -> str:
    return KIND_LABELS.get(loc.kind or "", "")


def _index(places: list[Place]) -> dict[str, Place]:
    index: dict[str, Place] = {}
    for place in places:
        for name in wms.bound_names(place.loc):
            if name:
                index.setdefault(name, place)
    return index


def find_place(raw: Optional[str], index: dict[str, Place]) -> Optional[Place]:
    """整串相同优先；否则取原文里出现的最长地名（至少 2 个字）。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw in index:
        return index[raw]
    hits = [name for name in index if len(name) >= 2 and name in raw]
    return index[max(hits, key=len)] if hits else None


def mentioned_places(text: str, index: dict[str, Place]) -> list[Place]:
    """文字里点到名的地点（至少 2 个字），按首次出现的位置排；长名先认，认过的字不再拿去配短名。"""
    found: list[tuple[int, Place]] = []
    for name in sorted((n for n in index if len(n) >= 2), key=len, reverse=True):
        pos = text.find(name)
        if pos < 0:
            continue
        if all(place is not index[name] for _, place in found):
            found.append((pos, index[name]))
        text = text.replace(name, "\0" * len(name))
    return [place for _, place in sorted(found, key=lambda item: item[0])]


def _place_line(place: Place, tags: list[str]) -> str:
    loc = place.loc
    meta = "·".join(x for x in (_kind(loc), (loc.region or "").strip()) if x)
    head = f"- {loc.name}" + (f"（{meta}）" if meta else "") + (f"〔{'；'.join(tags)}〕" if tags else "")
    facts = [_clip(loc.description, 60)]
    summary = (place.rule.summary or "").strip() if place.rule else ""
    if summary and summary != (loc.description or "").strip():
        facts.append("设定：" + _clip(summary, 50))
    if not place.placed:
        facts.append("地图上还没定位")
    body = "；".join(f for f in facts if f)
    return f"{head}：{body}" if body else head


async def chapter_map_reference(
    db: AsyncSession, project_id: str, chapter_number: int, *,
    scene: Optional[str], text: str, character_names: Iterable[str] = (),
) -> MapReference:
    """写正文用：本章相关地点的档案 + 相对场景的方位远近 + 场景附近的地点。没有对得上的地点返回空。"""
    places = await load_places(db, project_id)
    if not places:
        return MapReference()
    index = _index(places)
    order: list[Place] = []
    tags: dict[str, list[str]] = {}
    people: dict[str, list[str]] = {}

    def pick(place: Optional[Place], tag: Optional[str] = None, person: Optional[str] = None) -> None:
        if place is None:
            return
        if place.loc.id not in tags:
            order.append(place)
            tags[place.loc.id], people[place.loc.id] = [], []
        if tag and tag not in tags[place.loc.id]:
            tags[place.loc.id].append(tag)
        if person:
            people[place.loc.id].append(person)

    pick(find_place(scene, index), "本章场景")
    for place in mentioned_places(text or "", index):
        pick(place, MENTIONED)
    names = [n for n in character_names if n]
    if names:
        for name, state in (await load_character_states(db, project_id, chapter_number, names=names)).items():
            if state.location and not state.absent:
                pick(find_place(state.location, index), person=name)
    if not order:
        return MapReference()

    order = order[:CHAPTER_PLACE_LIMIT]
    lines, items = [f"（{MAP_NOTE}）", "相关地点："], []
    for place in order:
        shown = list(tags[place.loc.id])
        if people[place.loc.id]:
            shown.append(f"{'、'.join(people[place.loc.id])}在此")
        if MENTIONED in shown and len(shown) > 1:
            shown.remove(MENTIONED)
        lines.append(_place_line(place, shown))
        items.append({"title": place.name, "detail": "；".join(shown)})

    placed = [p for p in order if p.placed]
    anchor = placed[0] if placed else None
    if anchor is not None:
        relations = [f"- {relation(anchor.loc, p.loc)}" for p in placed[1:]]
        if relations:
            lines += ["方位与远近：", *relations]
        picked = {p.loc.id for p in order}
        nearby = sorted(
            (p for p in places if p.placed and p.loc.id not in picked and _dist(anchor.loc, p.loc) < NEARBY_RADIUS),
            key=lambda p: _dist(anchor.loc, p.loc),
        )[:NEARBY_LIMIT]
        if nearby:
            lines.append(f"{anchor.name}附近还有：" + "、".join(
                f"{p.name}（{direction(anchor.loc, p.loc)}，{distance_label(_dist(anchor.loc, p.loc))}）" for p in nearby
            ))
            items += [{"title": p.name, "detail": f"{anchor.name}附近"} for p in nearby]
    return MapReference("\n".join(lines), items)


def _brief(place: Place) -> str:
    kind = _kind(place.loc)
    return f"{place.name}（{kind}）" if kind else place.name


async def map_overview(db: AsyncSession, project_id: str) -> str:
    """章纲展开 / 桥段规划用：各区域在地图哪一片、有哪些地点，主要地点之间的方位远近。没有定位过的地点返回空。"""
    places = [p for p in await load_places(db, project_id) if p.placed]
    if not places:
        return ""
    places.sort(key=lambda p: (p.rule is None, p.name))  # 世界规则里的地点排前面
    groups: dict[str, list[Place]] = {}
    for place in places[:OVERVIEW_PLACE_LIMIT]:
        groups.setdefault((place.loc.region or "").strip(), []).append(place)

    lines = [f"（{MAP_NOTE}；安排场景和行程照这个来，地名尽量用这里的）"]
    for region, members in sorted(groups.items(), key=lambda kv: (kv[0] == "", -len(kv[1]))):
        if region:
            cx = sum(p.loc.x for p in members) / len(members)
            cy = sum(p.loc.y for p in members) / len(members)
            lines.append(f"- {region}（地图{map_area(cx, cy)}）：" + "、".join(_brief(p) for p in members))
        else:
            lines.append("- 其他：" + "、".join(f"{p.name}（地图{map_area(p.loc.x, p.loc.y)}）" for p in members))
    sea = wms.map_view(await wms.load_map(db, project_id), project_id)["terrain"].get("sea")
    if sea in SEA_LABELS:
        lines.append(f"海在地图{SEA_LABELS[sea]}。")

    main = [p for p in places if p.rule is not None]
    main = (main if len(main) >= 2 else places)[:OVERVIEW_RELATION_LIMIT + 1]
    seen: set[frozenset[str]] = set()
    relations: list[str] = []
    for place in main:
        nearest = min((q for q in main if q is not place), key=lambda q: _dist(place.loc, q.loc), default=None)
        pair = frozenset((place.loc.id, nearest.loc.id)) if nearest else None
        if pair and pair not in seen:
            seen.add(pair)
            relations.append(f"- {relation(nearest.loc, place.loc)}")
    if relations:
        lines += ["主要地点之间：", *relations[:OVERVIEW_RELATION_LIMIT]]
    return "\n".join(lines)
