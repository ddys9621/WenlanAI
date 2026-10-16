"""角色状态卡（长篇设定集）。

数据源是章节分析结算出的连续性信号（chapter_continuity_signals）：生死 / 地点 / 能力 / 境界 / 物品 / 伤势 /
目标 / 故事时间 / 出场。按章号回放得到"写第 N 章时每个角色的当前状态"——信号随章节重新分析、重写覆盖
自动清理重结算，状态天然幂等，不另存一份会过期的快照。作者修正（author_state_signals）一起回放，
同一章排在 AI 信号之后（以作者为准），重新分析不会清掉。

正文生成只注入本章相关的少数角色（章纲涉及 / 视角 / 近期活跃 / 与视角有关系 / 主角），不再把全部角色
（自动建档后会有几百个）塞进每章提示词；死亡 / 失踪角色单列名单作为硬约束，防止"死人复活"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.character import Character
from app.models.ledger_override import AuthorStateSignal
from app.models.relationship import CharacterRelationship
from app.services.relationship_timeline import relationship_states_before

STATE_SIGNAL_TYPES: tuple[str, ...] = (
    "life_state", "location", "ability", "realm", "item", "injury", "goal", "presence",
)
ROLE_LABELS = {"protagonist": "主角", "antagonist": "反派", "major": "重要配角", "supporting": "配角", "minor": "龙套"}
LIFE_LABELS = {"dead": "已死亡", "missing": "失踪"}
ITEM_LIMIT = 6
RECENT_DEAD_WINDOW = 80


@dataclass
class CharacterState:
    name: str
    life: Optional[str] = None
    life_chapter: Optional[int] = None
    location: Optional[str] = None
    location_chapter: Optional[int] = None
    realm: Optional[str] = None
    realm_chapter: Optional[int] = None
    items: list[str] = field(default_factory=list)
    injuries: list[str] = field(default_factory=list)
    abilities: list[str] = field(default_factory=list)
    goal: Optional[str] = None
    last_seen: Optional[int] = None

    @property
    def absent(self) -> bool:
        return self.life in LIFE_LABELS


def _norm(name: Optional[str]) -> str:
    return (name or "").strip()


def replay_signals(signals: Iterable[Any]) -> dict[str, CharacterState]:
    """按章号（同章按给定顺序）回放信号，得到每个角色的当前状态（纯函数）。"""
    states: dict[str, CharacterState] = {}
    for sig in sorted(signals, key=lambda s: s.chapter_number or 0):
        name = _norm(getattr(sig, "character_name", None))
        if not name:
            continue
        st = states.setdefault(name, CharacterState(name=name))
        kind, key, value, n = sig.signal_type, _norm(sig.signal_key), (sig.signal_value or "").lower(), sig.chapter_number
        if kind == "life_state":
            if value in ("revived", "survived"):
                st.life, st.life_chapter = None, n
            else:
                st.life, st.life_chapter = value, n
        elif kind == "location" and key:
            if value == "left":
                if st.location == key:
                    st.location = None
            else:
                st.location, st.location_chapter = key, n
        elif kind == "realm" and key:
            st.realm, st.realm_chapter = key, n
        elif kind == "item" and key:
            if value == "gained":
                if key not in st.items:
                    st.items.append(key)
            elif key in st.items:
                st.items.remove(key)
        elif kind == "injury" and key:
            if value == "injured":
                if key not in st.injuries:
                    st.injuries.append(key)
            elif key in st.injuries:
                st.injuries.remove(key)
        elif kind == "ability" and key:
            if value in ("learned", "mastered"):
                if key not in st.abilities:
                    st.abilities.append(key)
            elif value in ("lost", "forgotten") and key in st.abilities:
                st.abilities.remove(key)
        elif kind == "goal" and key:
            st.goal = key
        if kind in ("presence", "realm", "item", "injury", "location", "ability", "goal"):
            st.last_seen = max(st.last_seen or 0, n or 0)
    return states


@dataclass(frozen=True)
class SignalRow:
    """回放用的一条信号（AI 结算或作者修正，字段同 chapter_continuity_signals）。"""
    chapter_number: int
    signal_type: str
    character_name: Optional[str]
    signal_key: Optional[str]
    signal_value: str
    source: str = "ai"
    evidence_text: Optional[str] = None


async def state_signal_rows(
    db: AsyncSession,
    project_id: str,
    before_chapter: Optional[int],
    types: Iterable[str],
    names: Optional[Iterable[str]] = None,
) -> list[SignalRow]:
    """AI 信号 + 作者修正，按章号排序；同一章作者修正排在后面（回放时覆盖 AI）。before_chapter=None 不限章。"""
    types = list(types)
    wanted = [n for n in (names or []) if n]
    if names is not None and not wanted:
        return []
    out: list[SignalRow] = []
    for model, source in ((ChapterContinuitySignal, "ai"), (AuthorStateSignal, "author")):
        query = select(model).where(model.project_id == project_id, model.signal_type.in_(types))
        if before_chapter is not None:
            query = query.where(model.chapter_number < before_chapter)
        if wanted:
            query = query.where(model.character_name.in_(wanted))
        for row in (await db.execute(query.order_by(model.chapter_number))).scalars().all():
            out.append(SignalRow(
                chapter_number=row.chapter_number or 0, signal_type=row.signal_type, character_name=row.character_name,
                signal_key=row.signal_key, signal_value=row.signal_value, source=source,
                evidence_text=getattr(row, "evidence_text", None) or getattr(row, "note", None),
            ))
    return sorted(out, key=lambda r: r.chapter_number)  # 稳定排序：同章 AI 在前、作者在后


async def load_character_states(
    db: AsyncSession, project_id: str, before_chapter: int, names: Optional[Iterable[str]] = None,
) -> dict[str, CharacterState]:
    """写第 before_chapter 章时的角色状态（只回放此前章节的信号与作者修正）。names 给定时只查这些人。"""
    return replay_signals(await state_signal_rows(db, project_id, before_chapter, STATE_SIGNAL_TYPES, names))


async def load_absent_states(db: AsyncSession, project_id: str, before_chapter: int) -> dict[str, CharacterState]:
    """只回放生死信号：死亡 / 失踪名单要覆盖全体角色，但不必拉全部状态信号。"""
    rows = await state_signal_rows(db, project_id, before_chapter, ("life_state",))
    return {name: st for name, st in replay_signals(rows).items() if st.absent}


async def latest_story_time(db: AsyncSession, project_id: str, before_chapter: int) -> Optional[tuple[str, int]]:
    rows = [r for r in await state_signal_rows(db, project_id, before_chapter, ("story_time",)) if r.signal_key]
    return (rows[-1].signal_key, rows[-1].chapter_number) if rows else None


async def recent_presence(db: AsyncSession, project_id: str, before_chapter: int, window: int = 3) -> list[str]:
    """最近 window 章出场过的角色，越近越靠前（去重）。"""
    rows = (await db.execute(
        select(ChapterContinuitySignal.character_name, ChapterContinuitySignal.chapter_number)
        .where(
            ChapterContinuitySignal.project_id == project_id,
            ChapterContinuitySignal.signal_type == "presence",
            ChapterContinuitySignal.chapter_number < before_chapter,
            ChapterContinuitySignal.chapter_number >= before_chapter - window,
        )
        .order_by(ChapterContinuitySignal.chapter_number.desc())
    )).all()
    out: list[str] = []
    for name, _n in rows:
        if name and name not in out:
            out.append(name)
    return out


def _aliases(character: Any) -> list[str]:
    import json

    raw = getattr(character, "aliases", None)
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(a).strip() for a in data if str(a).strip()] if isinstance(data, list) else []


def _matches(character: Any, names: set[str]) -> bool:
    return _norm(character.name) in names or any(a in names for a in _aliases(character))


def select_relevant_characters(
    characters: Iterable[Any],
    *,
    involved: Iterable[str],
    pov: Optional[str],
    recent: Iterable[str],
    related_ids: set[str],
    limit: int = 12,
) -> list[Any]:
    """本章相关角色：章纲涉及 > 视角 > 主角 > 近期出场（越近越前）> 与视角有关系 > 反派；组织不在此列。"""
    involved_set = {_norm(n) for n in involved if _norm(n)}
    recent_list = [_norm(n) for n in recent if _norm(n)]
    pov_name = _norm(pov)
    scored: list[tuple[float, int, Any]] = []
    for idx, c in enumerate(characters):
        if getattr(c, "is_organization", False):
            continue
        role = (getattr(c, "role_type", None) or "").lower()
        score = 0.0
        if _matches(c, involved_set):
            score += 100
        if pov_name and _matches(c, {pov_name}):
            score += 90
        if role == "protagonist":
            score += 80
        for rank, name in enumerate(recent_list):
            if _matches(c, {name}):
                score += max(60 - rank, 30)
                break
        if getattr(c, "id", None) in related_ids:
            score += 30
        if role == "antagonist":
            score += 20
        if score > 0:
            scored.append((score, idx, c))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _s, _i, c in scored[:limit]]


def select_relevant_organizations(organizations: Iterable[Any], text: str, involved: Iterable[str], limit: int = 5) -> list[Any]:
    names = {_norm(n) for n in involved if _norm(n)}
    out = [o for o in organizations if getattr(o, "is_organization", False)
           and (_norm(o.name) in names or (o.name and o.name in (text or "")))]
    return out[:limit]


async def _relationship_states(
    db: AsyncSession, project_id: str, character_id: str, before_chapter: Optional[int],
) -> list[tuple[CharacterRelationship, Optional[int], Optional[str]]]:
    """某角色的关系及其状态：给 before_chapter 时按写第 N 章时（之后才出现 / 变化的不算），否则取现状。"""
    if before_chapter is not None:
        return await relationship_states_before(db, project_id, character_id, before_chapter)
    rows = (await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.project_id == project_id,
            or_(CharacterRelationship.character_from_id == character_id,
                CharacterRelationship.character_to_id == character_id),
        )
    )).scalars().all()
    return [(rel, rel.intimacy_level, rel.status) for rel in rows]


async def load_related_ids(
    db: AsyncSession, project_id: str, character_id: Optional[str], before_chapter: Optional[int] = None,
) -> set[str]:
    if not character_id:
        return set()
    states = await _relationship_states(db, project_id, character_id, before_chapter)
    return {
        cid
        for rel, _intimacy, _status in states
        for cid in (rel.character_from_id, rel.character_to_id)
        if cid and cid != character_id
    }


async def load_protagonist_relations(
    db: AsyncSession, project_id: str, protagonist: Optional[Any], characters: Iterable[Any],
    before_chapter: Optional[int] = None,
) -> dict[str, str]:
    """角色名 → 与主角的关系一句话（自定义关系名 / 状态 / 亲密度）；给 before_chapter 时取写第 N 章时的状态。"""
    if protagonist is None:
        return {}
    by_id = {c.id: c for c in characters if getattr(c, "id", None)}
    out: dict[str, str] = {}
    for rel, intimacy, status in await _relationship_states(db, project_id, protagonist.id, before_chapter):
        other_id = rel.character_to_id if rel.character_from_id == protagonist.id else rel.character_from_id
        other = by_id.get(other_id)
        if other is None or other.name in out:
            continue
        parts = [p for p in (rel.relationship_name, status if status and status != "active" else None) if p]
        if intimacy is not None:
            parts.append(f"亲密度{intimacy}")
        out[other.name] = "，".join(parts)
    return out


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_character_cards(
    characters: Iterable[Any], states: dict[str, CharacterState], relations: Optional[dict[str, str]] = None,
) -> str:
    """每人一行：身份｜状态（死亡 / 失踪）｜境界｜位置｜伤势｜持有｜目标｜说话｜性格｜与主角｜最近出场。"""
    relations = relations or {}
    lines: list[str] = []
    for c in characters:
        st = states.get(_norm(c.name)) or next((states[a] for a in _aliases(c) if a in states), None)
        role = ROLE_LABELS.get((getattr(c, "role_type", None) or "").lower(), "角色")
        parts = [f"{c.name}（{role}）"]
        if st and st.absent:
            parts.append(f"⚠️{LIFE_LABELS[st.life]}（第{st.life_chapter}章）")
        if st and st.realm:
            parts.append(f"境界：{st.realm}（第{st.realm_chapter}章）")
        if st and st.location:
            parts.append(f"位置：{st.location}")
        if st and st.injuries:
            parts.append(f"伤势：{'、'.join(st.injuries[-3:])}")
        if st and st.items:
            parts.append(f"持有：{'、'.join(st.items[-ITEM_LIMIT:])}")
        if st and st.goal:
            parts.append(f"当前目标：{_clip(st.goal, 30)}")
        if getattr(c, "speech_style", None):
            parts.append(f"说话：{_clip(c.speech_style, 40)}")
        if getattr(c, "personality", None):
            parts.append(f"性格：{_clip(c.personality, 40)}")
        if relations.get(c.name):
            parts.append(f"与主角：{_clip(relations[c.name], 30)}")
        if st and st.last_seen:
            parts.append(f"最近出场：第{st.last_seen}章")
        lines.append("- " + "｜".join(parts))
    return "\n".join(lines)


def render_absent_list(
    states: dict[str, CharacterState], involved: Iterable[str], current_chapter: int, limit: int = 15,
) -> str:
    """死亡 / 失踪名单：章纲涉及的排最前并加警示；其余只列最近 RECENT_DEAD_WINDOW 章内的。"""
    involved_set = {_norm(n) for n in involved if _norm(n)}
    absent = [s for s in states.values() if s.absent]
    flagged = [s for s in absent if s.name in involved_set]
    others = sorted(
        (s for s in absent if s.name not in involved_set and current_chapter - (s.life_chapter or 0) <= RECENT_DEAD_WINDOW),
        key=lambda s: -(s.life_chapter or 0),
    )
    lines = [
        f"- ⚠️{s.name}：第{s.life_chapter}章{LIFE_LABELS[s.life]}，本章章纲涉及此人——只能以回忆 / 传闻 / 遗物出现，"
        f"除非本章明确写复活或身份反转"
        for s in flagged
    ]
    lines += [f"- {s.name}：第{s.life_chapter}章{LIFE_LABELS[s.life]}" for s in others]
    return "\n".join(lines[:limit])


async def load_characters(db: AsyncSession, project_id: str) -> list[Character]:
    return list((await db.execute(select(Character).where(Character.project_id == project_id))).scalars().all())
