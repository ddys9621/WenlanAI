"""故事账本：作者看得见、改得了的伏笔 / 人物状态 / 章节档案 / 时间线（API 层只做鉴权与参数校验转发）。

- 伏笔：作者改标题 / 内容 / 类型 / 优先级 / 计划回收章、标回收、放弃、重新打开、新建、合并重复；
  改过的字段记进 PromiseAuthorLock，埋设章重新分析时不覆盖，对账也不会删掉这条
- 人物状态修正：写进 author_state_signals，和 AI 信号一起按章回放（同章作者优先），重新分析不清
都只改关系库、不提交；检索索引由调用方刷新。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.ledger_override import AuthorStateSignal, PromiseAuthorLock
from app.models.narrative_promise import NarrativePromise
from app.models.timeline_event import TimelineEvent
from app.services import character_state_service as css
from app.services.chapter_digest_service import digest_view
from app.services.narrative_state_service import narrative_state_service as nss


class LedgerError(ValueError):
    """作者的修改不合法（消息直接给作者看）。"""


PROMISE_STATUS_LABELS = {
    "open": "未回收", "progressing": "推进中", "resolved": "已回收", "broken": "已破裂", "abandoned": "已放弃",
}
PROMISE_TYPES = ("foreshadow", "promise", "mystery", "conflict")
PRIORITIES = ("low", "medium", "high", "critical")
ACTIVE_STATUSES = ("open", "progressing", "broken")
EDITABLE_FIELDS = ("title", "content", "promise_type", "priority", "deadline_chapter")

AUTHOR_SIGNALS: dict[str, tuple[str, ...]] = {
    "life_state": ("dead", "missing", "revived", "survived"),
    "location": ("current", "arrived", "left"),
    "realm": ("current",),
    "item": ("gained", "lost"),
    "injury": ("injured", "recovered"),
    "goal": ("current",),
    "ability": ("learned", "mastered", "lost", "forgotten"),
    "story_time": ("current",),
}
SIGNAL_LABELS = {
    "life_state": "生死", "location": "位置", "realm": "境界", "item": "物品", "injury": "伤势", "goal": "目标",
    "ability": "能力", "story_time": "故事时间", "presence": "出场",
}


def _key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


async def _chapter_id(db: AsyncSession, project_id: str, number: int) -> Optional[str]:
    return (await db.execute(
        select(Chapter.id).where(Chapter.project_id == project_id, Chapter.chapter_number == number)
    )).scalar_one_or_none()


async def _locks(db: AsyncSession, project_id: str) -> dict[str, set[str]]:
    rows = (await db.execute(select(PromiseAuthorLock).where(PromiseAuthorLock.project_id == project_id))).scalars()
    return {row.promise_id: set(row.fields or []) for row in rows}


async def _lock(
    db: AsyncSession, promise: NarrativePromise, fields: Iterable[str], note: Optional[str] = None,
    origin_title: Optional[str] = None,
) -> None:
    """记下作者改过的字段；第一次改标题时留住 AI 原标题（埋设章重新分析时按它认回同一条）。"""
    fields = set(fields)
    if not fields:
        return
    row = await db.get(PromiseAuthorLock, promise.id)
    if row is None:
        db.add(PromiseAuthorLock(promise_id=promise.id, project_id=promise.project_id, fields=sorted(fields), note=note,
                                 origin_title=origin_title))
        return
    current = set(row.fields or [])
    if "*" not in current:
        row.fields = sorted(current | fields)
    if note:
        row.note = note
    if origin_title and not row.origin_title:
        row.origin_title = origin_title


async def _promise(db: AsyncSession, project_id: str, promise_id: str) -> NarrativePromise:
    promise = await db.get(NarrativePromise, promise_id)
    if promise is None or promise.project_id != project_id:
        raise LedgerError("这条伏笔不存在（可能已被合并或删除）")
    return promise


def promise_view(promise: NarrativePromise, as_of: int, locked: Optional[set[str]] = None,
                 names: Optional[dict[str, str]] = None) -> dict:
    names = names or {}
    status = promise.status or "open"
    return {
        "id": promise.id,
        "promise_type": promise.promise_type,
        "title": promise.title,
        "content": promise.content,
        "priority": promise.priority or "medium",
        "status": status,
        "status_label": PROMISE_STATUS_LABELS.get(status, status),
        "source_chapter_number": promise.source_chapter_number,
        "resolved_chapter_number": promise.resolved_chapter_number,
        "deadline_chapter": promise.deadline_chapter,
        "last_activated_chapter": promise.last_activated_chapter,
        "flag": nss._promise_flag(promise, as_of).strip() if status in ACTIVE_STATUSES else "",
        "owner_name": names.get(promise.owner_character_id or ""),
        "target_name": names.get(promise.target_character_id or ""),
        "resolution_note": promise.resolution_note,
        "evidence": promise.evidence_text,
        "locked_fields": sorted(locked or set()),
    }


async def _character_names(db: AsyncSession, project_id: str) -> dict[str, str]:
    rows = (await db.execute(select(Character.id, Character.name).where(Character.project_id == project_id))).all()
    return {cid: name for cid, name in rows}


async def list_promises(
    db: AsyncSession, project_id: str, *, status: str = "active", as_of: int = 1, query: str = "", limit: int = 500,
) -> list[dict]:
    stmt = select(NarrativePromise).where(NarrativePromise.project_id == project_id)
    if status == "active":
        stmt = stmt.where(NarrativePromise.status.in_(ACTIVE_STATUSES))
    elif status in ("resolved", "abandoned"):
        stmt = stmt.where(NarrativePromise.status == status)
    rows = list((await db.execute(stmt)).scalars().all())
    key = _key(query)
    if key:
        rows = [p for p in rows if key in _key(p.title) or key in _key(p.content)]
    if status == "active":
        def sort_key(p: NarrativePromise) -> tuple:
            flag = nss._promise_flag(p, as_of)
            return (0 if ("超期" in flag or "临近" in flag) else 1, -nss.PRIORITY_WEIGHT.get(p.priority or "medium", 2),
                    0 if "掉线" in flag else 1, -(p.last_activated_chapter or p.source_chapter_number or 0))
        rows.sort(key=sort_key)
    else:
        rows.sort(key=lambda p: (-(p.resolved_chapter_number or p.source_chapter_number or 0), p.title))
    locks = await _locks(db, project_id)
    names = await _character_names(db, project_id)
    return [promise_view(p, as_of, locks.get(p.id), names) for p in rows[:limit]]


def _int(value: Any, label: str, *, minimum: int = 1, allow_none: bool = False) -> Optional[int]:
    if value in (None, "", 0) and allow_none:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise LedgerError(f"{label}应是整数")
    if number < minimum:
        raise LedgerError(f"{label}不能小于 {minimum}")
    return number


async def update_promise(db: AsyncSession, project_id: str, promise_id: str, changes: dict) -> NarrativePromise:
    """作者改一条伏笔；改到的字段加锁。status：open（重新打开）/ resolved（需 resolved_chapter_number）/ abandoned。"""
    promise = await _promise(db, project_id, promise_id)
    original_title = promise.title
    touched: set[str] = set()
    if "title" in changes and changes["title"] is not None:
        title = str(changes["title"]).strip()[:200]
        if not title:
            raise LedgerError("标题不能为空")
        promise.title = title
        touched.add("title")
    if "content" in changes and changes["content"] is not None:
        promise.content = str(changes["content"]).strip()[:1000] or promise.title
        touched.add("content")
    if changes.get("promise_type") is not None:
        if changes["promise_type"] not in PROMISE_TYPES:
            raise LedgerError("类型只能是 伏笔 / 承诺 / 悬念 / 冲突")
        promise.promise_type = changes["promise_type"]
        touched.add("promise_type")
    if changes.get("priority") is not None:
        if changes["priority"] not in PRIORITIES:
            raise LedgerError("优先级只能是 低 / 中 / 高 / 紧急")
        promise.priority = changes["priority"]
        touched.add("priority")
    if "deadline_chapter" in changes:
        promise.deadline_chapter = _int(changes["deadline_chapter"], "计划回收章", allow_none=True)
        touched.add("deadline_chapter")

    status = changes.get("status")
    note = (str(changes.get("note") or "").strip()[:1000]) or None
    if status is not None:
        if status == "resolved":
            number = _int(changes.get("resolved_chapter_number"), "回收章")
            if number < (promise.source_chapter_number or 1):
                raise LedgerError("回收章不能早于埋设章")
            promise.status = "resolved"
            promise.resolved_chapter_number = number
            promise.resolved_chapter_id = await _chapter_id(db, project_id, number)
            promise.resolution_note = note or promise.resolution_note
            promise.last_activated_chapter = max(promise.last_activated_chapter or 0, number)
        elif status == "abandoned":
            promise.status = "abandoned"
            promise.resolution_note = note or "作者放弃追踪"
        elif status == "open":
            promise.status = "open"
            promise.resolved_chapter_id = promise.resolved_chapter_number = None
            promise.resolution_note = None
        else:
            raise LedgerError("状态只能是 未回收 / 已回收 / 已放弃")
        touched.add("status")
    if not touched:
        raise LedgerError("没有要修改的内容")
    await _lock(db, promise, touched, note,
                origin_title=original_title if "title" in touched and original_title != promise.title else None)
    return promise


async def create_promise(db: AsyncSession, project_id: str, data: dict) -> NarrativePromise:
    """作者手动登记一条伏笔（以作者为准：所有字段加锁，埋设章重新分析不删）。"""
    title = str(data.get("title") or "").strip()[:200]
    if not title:
        raise LedgerError("标题不能为空")
    number = _int(data.get("source_chapter_number"), "埋设章")
    chapter_id = await _chapter_id(db, project_id, number)
    if chapter_id is None:
        raise LedgerError(f"第 {number} 章还没有章节，先建章节再登记伏笔")
    promise_type = data.get("promise_type") or "foreshadow"
    priority = data.get("priority") or "medium"
    if promise_type not in PROMISE_TYPES or priority not in PRIORITIES:
        raise LedgerError("类型或优先级不合法")
    promise = NarrativePromise(
        project_id=project_id, source_chapter_id=chapter_id, source_chapter_number=number, promise_type=promise_type,
        title=title, content=str(data.get("content") or "").strip()[:1000] or title, priority=priority, status="open",
        deadline_chapter=_int(data.get("deadline_chapter"), "计划回收章", allow_none=True),
        last_activated_chapter=number,
    )
    db.add(promise)
    await db.flush()
    db.add(PromiseAuthorLock(promise_id=promise.id, project_id=project_id, fields=["*"], note="作者新建"))
    return promise


def _repoint_tasks(raw: Optional[str], merged: set[str], keep_id: str) -> Optional[str]:
    try:
        data = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    changed = False
    for kind in ("resolve", "advance"):
        for item in data.get(kind) or []:
            if isinstance(item, dict) and item.get("promise_id") in merged:
                item["promise_id"] = keep_id
                changed = True
    return json.dumps(data, ensure_ascii=False) if changed else None


async def merge_promises(db: AsyncSession, project_id: str, keep_id: str, merge_ids: Iterable[str]) -> NarrativePromise:
    """把重复的伏笔并进 keep：章纲叙事任务里的引用改指向 keep，被并的删除。"""
    keep = await _promise(db, project_id, keep_id)
    merged_ids = [i for i in dict.fromkeys(merge_ids) if i]
    if not merged_ids or keep_id in merged_ids:
        raise LedgerError("请选择要并进来的其他伏笔")
    merged = [await _promise(db, project_id, pid) for pid in merged_ids]
    keep.last_activated_chapter = max([keep.last_activated_chapter or 0] + [m.last_activated_chapter or 0 for m in merged])
    ids = {m.id for m in merged}
    outlines = (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.narrative_tasks.isnot(None))
    )).scalars().all()
    for outline in outlines:
        updated = _repoint_tasks(outline.narrative_tasks, ids, keep.id)
        if updated is not None:
            outline.narrative_tasks = updated
    for promise in merged:
        lock = await db.get(PromiseAuthorLock, promise.id)
        if lock is not None:
            await db.delete(lock)
        await db.delete(promise)
    return keep


def _validate_signal(data: dict) -> tuple[str, str, Optional[str], str]:
    signal_type = str(data.get("signal_type") or "")
    if signal_type not in AUTHOR_SIGNALS:
        raise LedgerError("修正类型只能是 生死 / 位置 / 境界 / 物品 / 伤势 / 目标 / 能力 / 故事时间")
    value = str(data.get("signal_value") or "").strip().lower()
    if value not in AUTHOR_SIGNALS[signal_type]:
        raise LedgerError(f"「{SIGNAL_LABELS[signal_type]}」的取值不合法：{value or '（空）'}")
    name = str(data.get("character_name") or "").strip()[:100]
    if signal_type != "story_time" and not name:
        raise LedgerError("请填写人物")
    key = " ".join(str(data.get("signal_key") or "").split())[:200] or None
    if signal_type != "life_state" and not key:
        raise LedgerError(f"请填写{SIGNAL_LABELS[signal_type]}的内容")
    return signal_type, name, key, value


async def add_state_correction(db: AsyncSession, project_id: str, data: dict) -> AuthorStateSignal:
    """作者修正：第 N 章结束时某人的状态（写第 N+1 章起生效，回放时盖过同章 AI 信号）。"""
    signal_type, name, key, value = _validate_signal(data)
    row = AuthorStateSignal(
        project_id=project_id, chapter_number=_int(data.get("chapter_number"), "章号"), signal_type=signal_type,
        character_name=name, signal_key=key, signal_value=value, note=(str(data.get("note") or "").strip()[:500] or None),
    )
    db.add(row)
    await db.flush()
    return row


async def delete_state_correction(db: AsyncSession, project_id: str, correction_id: str) -> None:
    row = await db.get(AuthorStateSignal, correction_id)
    if row is None or row.project_id != project_id:
        raise LedgerError("这条修正不存在")
    await db.delete(row)


async def character_history(db: AsyncSession, project_id: str, name: str, before: Optional[int] = None) -> list[dict]:
    """某人的状态变化记录（AI 结算 + 作者修正，按章号；同章 AI 在前）。按正式名 + 曾用名查。"""
    names = {name}
    character = (await db.execute(
        select(Character).where(Character.project_id == project_id, Character.name == name)
    )).scalars().first()
    if character is not None:
        names.update(css._aliases(character))
    out: list[dict] = []
    for model, source in ((ChapterContinuitySignal, "ai"), (AuthorStateSignal, "author")):
        # 出场记录只用来算「最近出场」，列进变化记录全是噪音
        stmt = select(model).where(model.project_id == project_id, model.character_name.in_(names),
                                   model.signal_type != "presence")
        if before is not None:
            stmt = stmt.where(model.chapter_number < before)
        for row in (await db.execute(stmt.order_by(model.chapter_number))).scalars():
            out.append({
                "id": row.id, "source": source, "chapter_number": row.chapter_number, "signal_type": row.signal_type,
                "label": SIGNAL_LABELS.get(row.signal_type, row.signal_type), "signal_key": row.signal_key,
                "signal_value": row.signal_value,
                "evidence": getattr(row, "evidence_text", None) if source == "ai" else row.note,
            })
    return sorted(out, key=lambda r: (r["chapter_number"] or 0, 0 if r["source"] == "ai" else 1))


async def character_states(db: AsyncSession, project_id: str, as_of: int) -> list[dict]:
    """写第 as_of 章时每个人的状态（有状态信号的人 + 主要角色）。"""
    states = await css.load_character_states(db, project_id, as_of)
    characters = [c for c in await css.load_characters(db, project_id) if not getattr(c, "is_organization", False)]
    corrections: dict[str, int] = {}
    for (name,) in (await db.execute(
        select(AuthorStateSignal.character_name).where(AuthorStateSignal.project_id == project_id)
    )).all():
        corrections[name] = corrections.get(name, 0) + 1
    rows: list[dict] = []
    seen: set[str] = set()

    def view(name: str, role: Optional[str], st: Optional[css.CharacterState], aliases: Iterable[str] = ()) -> dict:
        return {
            "name": name, "role": role,
            "life": st.life if st else None, "life_chapter": st.life_chapter if st else None,
            "location": st.location if st else None, "realm": st.realm if st else None,
            "items": list(st.items) if st else [], "injuries": list(st.injuries) if st else [],
            "abilities": list(st.abilities) if st else [], "goal": st.goal if st else None,
            "last_seen": st.last_seen if st else None,
            "corrections": corrections.get(name, 0) + sum(corrections.get(a, 0) for a in aliases),
        }

    for character in characters:
        aliases = css._aliases(character)
        state = states.get(character.name) or next((states[a] for a in aliases if a in states), None)
        role = (character.role_type or "").lower() or None
        if state is None and role not in ("protagonist", "antagonist", "major"):
            continue
        seen.update([character.name, *aliases])
        rows.append(view(character.name, role, state, aliases))
    for name, state in states.items():
        if name not in seen:
            rows.append(view(name, None, state))
    order = {"protagonist": 0, "antagonist": 1, "major": 2, "supporting": 3}
    rows.sort(key=lambda r: (order.get(r["role"] or "", 9), -(r["last_seen"] or 0), r["name"]))
    return rows


async def digest_rows(db: AsyncSession, project_id: str, statuses: dict[str, dict]) -> list[dict]:
    """每个有正文的章：档案（摘要 / 章末状态 / 来源 / 建议 / 是否过期）+ 分析状态。"""
    from app.models.chapter_digest import ChapterDigest

    chapters = (await db.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "")
        .order_by(Chapter.chapter_number)
    )).scalars().all()
    digests = {d.chapter_id: d for d in (await db.execute(
        select(ChapterDigest).where(ChapterDigest.project_id == project_id)
    )).scalars().all()}
    return [{
        "chapter_id": c.id, "chapter_number": c.chapter_number, "title": c.title,
        "digest": digest_view(digests.get(c.id), c),
        "analysis_status": (statuses.get(c.id) or {}).get("status", "missing"),
        "analysis_message": (statuses.get(c.id) or {}).get("message"),
    } for c in chapters]


async def timeline(
    db: AsyncSession, project_id: str, *, character: Optional[str] = None, from_chapter: Optional[int] = None,
    to_chapter: Optional[int] = None, limit: int = 300,
) -> list[dict]:
    """时间轴事件 + 因果链（按章序）；给人物时只看和他有关的。"""
    names = await _character_names(db, project_id)
    wanted: Optional[set[str]] = None
    if character:
        wanted = {cid for cid, name in names.items() if name == character}
        target = (await db.execute(
            select(Character).where(Character.project_id == project_id, Character.name == character)
        )).scalars().first()
        if target is not None:
            wanted.add(target.id)

    def in_range(n: int) -> bool:
        return (from_chapter is None or n >= from_chapter) and (to_chapter is None or n <= to_chapter)

    def touches(row: Any) -> bool:
        if wanted is None:
            return True
        return bool((set(row.actor_ids or []) | set(row.target_ids or [])) & wanted)

    out: list[dict] = []
    for row in (await db.execute(select(TimelineEvent).where(TimelineEvent.project_id == project_id))).scalars():
        if in_range(row.chapter_number or 0) and touches(row):
            out.append({
                "kind": "event", "id": row.id, "chapter_number": row.chapter_number, "event_type": row.event_type,
                "title": row.title, "description": row.description, "location": row.location, "time_marker": row.time_marker,
                "actors": [names.get(i, i) for i in row.actor_ids or []], "targets": [names.get(i, i) for i in row.target_ids or []],
                "visibility": row.public_visibility,
            })
    for row in (await db.execute(select(ChapterCausalLink).where(ChapterCausalLink.project_id == project_id))).scalars():
        if in_range(row.chapter_number or 0) and touches(row):
            out.append({
                "kind": "causal", "id": row.id, "chapter_number": row.chapter_number, "cause": row.cause, "event": row.event,
                "effect": row.effect, "decision": row.decision, "importance": row.importance_score,
                "actors": [names.get(i, i) for i in row.actor_ids or []], "targets": [names.get(i, i) for i in row.target_ids or []],
            })
    out.sort(key=lambda r: (r["chapter_number"] or 0, 0 if r["kind"] == "event" else 1))
    return out[-limit:]
