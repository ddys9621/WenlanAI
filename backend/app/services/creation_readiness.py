"""生成前的就绪检查（共创室）：每类生成要哪些前置，按创作顺序找最上游的第一个缺口；以及每轮带进上下文的「现在能做什么」。

缺口 Need.kind：
- basics：作品信息（简介 / 主题 / 类型）缺 → 灵感模式出候选，作者在系统提问卡里选（选定直接写入）
- settings：全书章数 / 叙事视角 / 目标字数缺 → 系统提问卡问作者（选定直接写入）
- generate：必需的上游没有 → 先按原逻辑生成上游卡片，作者确认后接着做
- confirm：上游有了但还在待确认（本段对话的修改卡 / 新建卡，或分卷 / 细化 / 章纲草案）→ 等作者确认
- blocked：补不了（如前面的章还没写），只能如实说明
declined：作者没采用的层（续跑时带来）和这一轮跳过的作品信息字段（project.xxx）：不再自动补，交给作者决定。只读，不写库。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate, AssistantFieldCandidate
from app.services import story_progress as sp
from app.services.volume_planning import loads_units, unit_at

ALL_BASICS = ("description", "theme", "genre")
GENRE_BASICS = ("theme", "genre")
OUTLINE_SETTINGS = ("chapter_count", "narrative_perspective", "target_words")
WORLD_KEYS = tuple(key for key, _label in sp.WORLD_FIELDS)
WORLD_LABELS = dict(sp.WORLD_FIELDS)
SETTING_LABELS = dict(sp.SETTING_FIELDS)
TARGET_LABELS = {
    "basics": "作品信息", "settings": "章数 / 视角 / 字数", "world": "世界设定", "world_rules": "世界规则",
    "setting_entries": "设定条目", "cast": "角色与组织", "relationships": "人物关系", "outline": "总纲",
    "volumes": "分卷", "detail": "剧情单元", "outlines": "章纲", "chapter": "正文",
}
TABLE_TARGETS = ("world", "world_rules", "setting_entries", "cast", "relationships", "outline", "volumes")
FIELD_LAYERS = (("project.world_", "world"), ("project.", "basics"), ("story_outline.", "outline"))
ENTITY_LAYERS = {"character": "cast", "organization": "cast", "world_rule": "world_rules",
                 "setting_entry": "setting_entries", "relationship": "relationships", "membership": "relationships"}
CHAINS: dict[str, tuple[tuple, ...]] = {
    "basics": (),
    "world": (("basics", ALL_BASICS),),
    "world_rules": (("basics", GENRE_BASICS), ("world", False)),
    "setting_entries": (("basics", GENRE_BASICS), ("world", False)),
    "cast": (("basics", GENRE_BASICS), ("world", False)),
    "relationships": (("people",),),
    "outline": (("basics", ALL_BASICS), ("world", False), ("protagonist",), ("settings", OUTLINE_SETTINGS)),
    "volumes": (("basics", ALL_BASICS), ("world", True), ("protagonist",), ("outline",), ("settings", ("chapter_count",))),
}


@dataclass(frozen=True)
class Need:
    kind: str
    layer: str
    label: str
    fields: tuple[str, ...] = ()
    waiting: dict = field(default_factory=dict)
    args: dict = field(default_factory=dict)


def field_layer(field_id: str) -> str:
    return next((layer for prefix, layer in FIELD_LAYERS if field_id.startswith(prefix)), "")


@dataclass
class Checker:
    state: sp.BookState
    fields: list
    entities: list
    declined: set

    @property
    def project(self) -> Any:
        return self.state.project

    def _waiting_fields(self, *prefixes: str) -> list[str]:
        return [c.id for c in self.fields if c.field_id.startswith(prefixes)]

    def _waiting_entities(self, *types: str) -> list[str]:
        return [c.id for c in self.entities if c.entity_type in types]

    def basics(self, keys: tuple[str, ...]) -> Optional[Need]:
        waiting = self._waiting_fields(*(f"project.{k}" for k in keys))
        if waiting:
            return Need("confirm", "basics", "作品信息的修改卡还在待确认", waiting={"candidates": waiting})
        missing = [(k, label) for k, label in sp.missing_basics(self.project)
                   if k in keys and f"project.{k}" not in self.declined]
        if missing:
            return Need("basics", "basics", f"作品信息还缺{'、'.join(label for _k, label in missing)}",
                        fields=tuple(k for k, _label in missing))
        return None

    def settings(self, keys: tuple[str, ...]) -> Optional[Need]:
        missing = [(k, label) for k, label in sp.missing_settings(self.project)
                   if k in keys and f"project.{k}" not in self.declined]
        if missing:
            return Need("settings", "settings", f"要作者先定{'、'.join(label for _k, label in missing)}",
                        fields=tuple(k for k, _label in missing))
        return None

    def world(self, complete: bool) -> Optional[Need]:
        waiting = self._waiting_fields("project.world_")
        if waiting:
            return Need("confirm", "world", "世界设定的修改卡还在待确认", waiting={"candidates": waiting})
        empty = [k for k in WORLD_KEYS if not (getattr(self.project, k, None) or "").strip()]
        if len(empty) == len(WORLD_KEYS) or (complete and empty):
            label = ("世界设定还空着" if len(empty) == len(WORLD_KEYS)
                     else f"世界设定还缺{'、'.join(WORLD_LABELS[k] for k in empty)}")
            return Need("generate", "world", label, args={"fields": empty})
        return None

    def protagonist(self) -> Optional[Need]:
        if self.state.heroes:
            return None
        waiting = self._waiting_entities("character")
        if waiting:
            return Need("confirm", "cast", "人物的新建卡还在待确认", waiting={"entity_candidates": waiting})
        if self.state.people:
            return Need("generate", "cast", "还没有主角", args={
                "character_count": 1, "organization_count": 0, "requirements": "生成本书的主角（protagonist）"})
        size = max(3, min(int(getattr(self.project, "character_count", 0) or 5), 8))
        return Need("generate", "cast", "还没有人物", args={
            "character_count": size, "organization_count": 1, "requirements": "至少包含 1 个主角（protagonist）"})

    def people(self) -> Optional[Need]:
        if len(self.state.people) >= 2 or (self.state.people and self.state.orgs):
            return None
        waiting = self._waiting_entities("character", "organization")
        if waiting:
            return Need("confirm", "cast", "人物 / 组织的新建卡还在待确认", waiting={"entity_candidates": waiting})
        return Need("generate", "cast", "人物还不够理关系（至少两个人物，或人物加组织）",
                    args={"character_count": 3, "organization_count": 0, "requirements": ""})

    def outline(self) -> Optional[Need]:
        waiting = self._waiting_fields("story_outline.")
        if waiting:
            return Need("confirm", "outline", "总纲的修改卡还在待确认", waiting={"candidates": waiting})
        if not (self.state.story.get("premise") and self.state.story.get("main_plot")):
            return Need("generate", "outline", "总纲还缺梗概或全书主线")
        return None

    def _volume(self, number: Optional[int]) -> Any:
        return next((v for v in self.state.volumes if v.volume_number == number), None)

    def volume(self, number: Optional[int]) -> Optional[Need]:
        volume = self._volume(number)
        if volume is None:
            return Need("generate", "volumes", f"还没有第 {number} 卷" if self.state.volumes else "还没有分卷")
        if volume.review_status == "draft" and not loads_units(volume.units):
            return Need("confirm", "volumes", f"第{number}卷的分卷草案还没确认", waiting={"volume_ids": [volume.id]})
        return None

    def units(self, number: Optional[int], unit_index: Optional[int] = None) -> Optional[Need]:
        need = self.volume(number)
        if need:
            return need
        volume = self._volume(number)
        units = loads_units(volume.units)
        if not units:
            return Need("generate", "detail", f"第{number}卷还没细化成剧情单元", args={"volume_number": number})
        if volume.review_status == "draft":
            return Need("confirm", "detail", f"第{number}卷的剧情单元草案还没确认", waiting={"volume_ids": [volume.id]})
        if unit_index is not None and not any(int(u.get("index") or 0) == unit_index for u in units):
            return Need("blocked", "detail", f"第{number}卷没有剧情单元 {unit_index}")
        return None

    def chapter(self, number: Optional[int]) -> Optional[Need]:
        outline = self.state.outlines.get(number)
        if outline is None:
            volume = next((v for v in self.state.volumes if v.chapter_start <= (number or 0) <= v.chapter_end), None)
            if volume is None:
                return Need("generate", "volumes", f"第 {number} 章还没有卷纲")
            units = loads_units(volume.units)
            unit = unit_at(units, number) if units else None
            need = self.units(volume.volume_number, int(unit["index"]) if unit else None)
            if need:
                return need
            if unit is None:
                return Need("blocked", "detail", f"第{volume.volume_number}卷的剧情单元没覆盖第 {number} 章，要重新细化本卷")
            return Need("generate", "outlines", f"第 {number} 章还没有章纲",
                        args={"volume_number": volume.volume_number, "unit_index": int(unit["index"])})
        if outline.review_status == "draft" or outline.upstream_stale:
            return Need("confirm", "outlines", f"第 {number} 章的章纲还没确认", waiting={"outline_ids": [outline.id]})
        missing = sorted(n for n in self.state.chapters if n < number and n not in self.state.written)
        if missing:
            return Need("blocked", "chapter", f"前面还有 {len(missing)} 章没写（从第 {missing[0]} 章起）：单章要按顺序写，"
                                              "可以先用 write_chapters 批量写这几章")
        return None


async def load_checker(db: AsyncSession, project_id: str, session_id: Optional[str],
                       declined: Iterable[str] = ()) -> Checker:
    state = await sp.load_state(db, project_id)
    if not session_id:
        return Checker(state, [], [], set(declined))
    fields_ = list((await db.execute(select(AssistantFieldCandidate).where(
        AssistantFieldCandidate.session_id == session_id, AssistantFieldCandidate.status == "candidate",
    ))).scalars())
    entities = list((await db.execute(select(AssistantEntityCandidate).where(
        AssistantEntityCandidate.session_id == session_id, AssistantEntityCandidate.status == "candidate",
    ))).scalars())
    return Checker(state, fields_, entities, set(declined))


def need_for(checker: Checker, target: str, *, volume_number: Optional[int] = None, unit_index: Optional[int] = None,
             chapter_number: Optional[int] = None) -> Optional[Need]:
    """target 这件事现在缺的最上游的那一步（不含沿着 generate 往上追，追的事由生成总入口做）；齐了返回 None。"""
    if target == "detail":
        return checker.volume(volume_number)
    if target == "outlines":
        return checker.units(volume_number, unit_index)
    if target == "chapter":
        return checker.chapter(chapter_number)
    for name, *args in CHAINS[target]:
        need = getattr(checker, name)(*args)
        if need:
            return need
    return None


def need_text(need: Need) -> str:
    if need.kind == "basics":
        return f"{need.label} → 先用灵感模式出候选让作者选"
    if need.kind == "settings":
        return f"{need.label} → 先用提问卡问作者"
    if need.kind == "generate":
        return f"{need.label} → 调用时会先按原逻辑生成{TARGET_LABELS[need.layer]}"
    if need.kind == "confirm":
        return f"{need.label} → 等作者在待确认栏处理"
    return need.label


def _setting_value(project: Any, key: str) -> str:
    value = getattr(project, key, None)
    if not value:
        return "未定"
    return f"{value} 章" if key == "chapter_count" else f"{value} 字" if key == "target_words" else str(value)


def basics_line(project: Any) -> str:
    marks = "、".join(f"{label} {'已写' if (getattr(project, key, None) or '').strip() else '缺'}"
                      for key, label in sp.BASICS_FIELDS)
    settings = "、".join(f"{label} {_setting_value(project, key)}" for key, label in sp.SETTING_FIELDS)
    return f"作品信息：书名《{project.title or '未命名'}》｜{marks}｜{settings}"


async def readiness_text(db: AsyncSession, project_id: str, session_id: Optional[str],
                         declined: Iterable[str] = ()) -> str:
    checker = await load_checker(db, project_id, session_id, declined)
    if checker.project is None:
        return ""
    lines = [basics_line(checker.project)]
    for target in TABLE_TARGETS:
        need = need_for(checker, target)
        lines.append(f"- {TARGET_LABELS[target]}：{'可以生成' if need is None else need_text(need)}")
    return "\n".join(lines)
