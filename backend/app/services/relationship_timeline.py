"""关系时序：关系状态 = 基础状态 + 各章关系事件按章顺序回放。

- 基础状态记在最早那条事件的 old_*（关系由事件创建时 old_* 为空、created_relationship=1）
- 任何一章的事件增删后都整对重放：乱序重新分析 / 清掉前面某章，后面章节的变化不会被冲掉
- 生成第 N 章时只看第 N 章之前的状态（state_before），重写前面章节不会提前知道后来的关系变化

requested_status 是分析给出的显式状态（"" 表示没给）；旧数据为空时从 old/new 是否不同推断一次。
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.relationship import CharacterRelationship
from app.models.relationship_event import RelationshipEvent

BaseState = tuple[bool, int, str]  # (事件之前关系是否已存在, 亲密度, 状态)


def _clamp(value: int) -> int:
    return max(-100, min(100, value))


async def find_relationship(
    db: AsyncSession, project_id: str, from_id: str, to_id: str,
) -> Optional[CharacterRelationship]:
    """同一对角色间可能有多条关系（手动建关系接口不查重），取最早的一条作为结算目标。"""
    return (await db.execute(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.project_id == project_id,
            CharacterRelationship.character_from_id == from_id,
            CharacterRelationship.character_to_id == to_id,
        )
        .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
    )).scalars().first()


async def pair_events(db: AsyncSession, project_id: str, from_id: str, to_id: str) -> list[RelationshipEvent]:
    return list((await db.execute(
        select(RelationshipEvent)
        .where(
            RelationshipEvent.project_id == project_id,
            RelationshipEvent.character_from_id == from_id,
            RelationshipEvent.character_to_id == to_id,
        )
        .order_by(RelationshipEvent.chapter_number, RelationshipEvent.created_at, RelationshipEvent.id)
    )).scalars().all())


def base_state(events: list[RelationshipEvent]) -> BaseState:
    first = events[0]
    if first.created_relationship and first.old_intimacy_level is None:
        return False, 50, "active"
    intimacy = first.old_intimacy_level if first.old_intimacy_level is not None else 50
    return True, intimacy, first.old_status or "active"


async def base_state_for_new_events(db: AsyncSession, project_id: str, from_id: str, to_id: str) -> BaseState:
    """新增事件前的基础状态：已有事件 → 取最早事件记的基础；没有事件 → 关系现状（不存在则视为新建）。"""
    existing = await pair_events(db, project_id, from_id, to_id)
    if existing:
        return base_state(existing)
    relationship = await find_relationship(db, project_id, from_id, to_id)
    if relationship is None:
        return False, 50, "active"
    intimacy = relationship.intimacy_level if relationship.intimacy_level is not None else 50
    return True, intimacy, relationship.status or "active"


def _explicit_status(event: RelationshipEvent) -> Optional[str]:
    requested = event.requested_status
    if requested is None:  # 旧数据：结算时状态有变化就当作分析显式给出的
        changed = event.new_status and event.new_status != (event.old_status or "active")
        requested = event.new_status if changed else ""
        event.requested_status = requested
    return requested or None


async def replay_pair(
    db: AsyncSession, project_id: str, from_id: str, to_id: str, base: BaseState,
) -> Optional[CharacterRelationship]:
    """按章顺序重放这一对角色的全部事件，改写事件的 old/new 与关系现状；没有事件且关系由事件创建 → 删掉关系。"""
    exists, intimacy, status = base
    events = await pair_events(db, project_id, from_id, to_id)
    relationship = await find_relationship(db, project_id, from_id, to_id)
    if not events:
        if relationship is not None and not exists:
            await db.delete(relationship)
            return None
        if relationship is not None:
            relationship.intimacy_level, relationship.status = intimacy, status
        return relationship
    if relationship is None:
        relationship = CharacterRelationship(
            project_id=project_id, character_from_id=from_id, character_to_id=to_id,
            intimacy_level=intimacy, status=status, source="ai",
        )
        db.add(relationship)
    for index, event in enumerate(events):
        explicit = _explicit_status(event)
        created_here = index == 0 and not exists
        event.created_relationship = 1 if created_here else 0
        event.old_intimacy_level = None if created_here else intimacy
        event.old_status = None if created_here else status
        intimacy = _clamp(intimacy + (event.delta or 0))
        status = explicit or status
        event.new_intimacy_level = intimacy
        event.new_status = status
    relationship.intimacy_level, relationship.status = intimacy, status
    return relationship


def state_before(
    relationship: CharacterRelationship, events: list[RelationshipEvent], before_chapter: int,
) -> Optional[tuple[int, str]]:
    """第 before_chapter 章开写时这条关系的 (亲密度, 状态)；那时关系还不存在 → None。"""
    if not events:
        return relationship.intimacy_level if relationship.intimacy_level is not None else 50, relationship.status or "active"
    prior = [e for e in events if e.chapter_number < before_chapter]
    if prior:
        last = prior[-1]
        intimacy = last.new_intimacy_level if last.new_intimacy_level is not None else relationship.intimacy_level
        return intimacy if intimacy is not None else 50, last.new_status or relationship.status or "active"
    exists, intimacy, status = base_state(events)
    return (intimacy, status) if exists else None


async def relationship_states_before(
    db: AsyncSession, project_id: str, character_id: str, before_chapter: int,
) -> list[tuple[CharacterRelationship, int, str]]:
    """某角色参与的全部关系在第 before_chapter 章开写时的状态（当时还不存在的关系不返回）。"""
    involved = or_(
        CharacterRelationship.character_from_id == character_id,
        CharacterRelationship.character_to_id == character_id,
    )
    relationships = (await db.execute(
        select(CharacterRelationship)
        .where(CharacterRelationship.project_id == project_id, involved)
        .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
    )).scalars().all()
    events = (await db.execute(
        select(RelationshipEvent)
        .where(
            RelationshipEvent.project_id == project_id,
            or_(RelationshipEvent.character_from_id == character_id, RelationshipEvent.character_to_id == character_id),
        )
        .order_by(RelationshipEvent.chapter_number, RelationshipEvent.created_at, RelationshipEvent.id)
    )).scalars().all()
    by_pair: dict[tuple[str, str], list[RelationshipEvent]] = {}
    for event in events:
        by_pair.setdefault((event.character_from_id, event.character_to_id), []).append(event)
    seen_pairs: set[tuple[str, str]] = set()
    out: list[tuple[CharacterRelationship, int, str]] = []
    for relationship in relationships:
        pair = (relationship.character_from_id, relationship.character_to_id)
        # 事件只挂在每对角色最早的那条关系上；重复的关系行按现状处理
        pair_history = by_pair.get(pair, []) if pair not in seen_pairs else []
        seen_pairs.add(pair)
        state = state_before(relationship, pair_history, before_chapter)
        if state is not None:
            out.append((relationship, state[0], state[1]))
    return out


async def replay_pairs(db: AsyncSession, bases: dict[tuple[str, str, str], BaseState]) -> None:
    await db.flush()
    for (project_id, from_id, to_id), base in bases.items():
        await replay_pair(db, project_id, from_id, to_id, base)


def pair_keys(events: Iterable[RelationshipEvent]) -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for event in events:
        key = (event.project_id, event.character_from_id, event.character_to_id)
        if key not in keys:
            keys.append(key)
    return keys
