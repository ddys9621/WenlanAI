"""故事账本的导出 / 导入（导出格式 2.1.0 的 ledger 段）：导入一本书后不用整本重新分析。

章节一律按章号、人物按名字、卷按卷序号对应（导入后 id 全是新的）：
- 伏笔导出带原 id 作 key；导入时建新 id，章纲叙事任务里引用的旧 id 改指向新 id（没导入的旧 id 清掉）
- 时间轴 / 因果的 actor_ids / target_ids、关系事件两端、已知信息的人物 → 人名 → 新角色 id（对不上的丢掉）
- 层级摘要的 arc_key 里有卷 id（unit:<卷id>:<序号> / vchunk:… / volume:…）→ 导出成 @vol<卷序号>，导入换回新卷 id
检索索引不导出（导入后按账本自动重建）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.arc_summary import ArcSummary
from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_digest import ChapterDigest
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.character_known_info import CharacterKnownInfo
from app.models.ledger_override import AuthorStateSignal, PromiseAuthorLock
from app.models.memory import PlotAnalysis
from app.models.narrative_promise import NarrativePromise
from app.models.relationship_event import RelationshipEvent
from app.models.timeline_event import TimelineEvent
from app.models.volume import Volume

_VOLUME_KEY = re.compile(r"^(unit|vchunk|volume):([^:]+)(.*)$")


async def _maps(db: AsyncSession, project_id: str) -> tuple[dict[str, int], dict[str, str], dict[str, int]]:
    chapter_numbers = dict((await db.execute(
        select(Chapter.id, Chapter.chapter_number).where(Chapter.project_id == project_id)
    )).all())
    names = dict((await db.execute(select(Character.id, Character.name).where(Character.project_id == project_id))).all())
    volumes = dict((await db.execute(select(Volume.id, Volume.volume_number).where(Volume.project_id == project_id))).all())
    return chapter_numbers, names, volumes


def _names(ids: Any, names: dict[str, str]) -> list[str]:
    return [names[i] for i in (ids or []) if i in names]


async def export_ledger(db: AsyncSession, project_id: str) -> dict[str, list[dict]]:
    chapter_numbers, names, volumes = await _maps(db, project_id)

    def rows(model):
        return select(model).where(model.project_id == project_id)

    out: dict[str, list[dict]] = {key: [] for key in (
        "chapter_analyses", "chapter_digests", "narrative_promises", "continuity_signals", "author_state_signals",
        "timeline_events", "causal_links", "relationship_events", "known_infos", "consistency_issues", "arc_summaries",
    )}
    for a in (await db.execute(rows(PlotAnalysis))).scalars():
        if a.chapter_id in chapter_numbers:
            out["chapter_analyses"].append({
                "chapter_number": chapter_numbers[a.chapter_id], "hooks": a.hooks or [], "foreshadows": a.foreshadows or [],
                "plot_points": a.plot_points or [], "character_states": a.character_states or [], "scenes": a.scenes or [],
                "content_hash": a.content_hash,
            })
    for d in (await db.execute(rows(ChapterDigest))).scalars():
        if d.chapter_id in chapter_numbers:
            out["chapter_digests"].append({
                "chapter_number": chapter_numbers[d.chapter_id], "summary": d.summary, "end_state": d.end_state,
                "source": d.source, "ai_summary": d.ai_summary, "ai_end_state": d.ai_end_state, "content_hash": d.content_hash,
            })
    locks = {lk.promise_id: lk for lk in (await db.execute(rows(PromiseAuthorLock))).scalars()}
    for p in (await db.execute(rows(NarrativePromise))).scalars():
        lock = locks.get(p.id)
        out["narrative_promises"].append({
            "key": p.id, "source_chapter_number": p.source_chapter_number, "promise_type": p.promise_type, "title": p.title,
            "content": p.content, "owner_name": names.get(p.owner_character_id or ""),
            "target_name": names.get(p.target_character_id or ""), "priority": p.priority, "status": p.status,
            "deadline_chapter": p.deadline_chapter, "last_activated_chapter": p.last_activated_chapter,
            "resolved_chapter_number": p.resolved_chapter_number, "resolution_note": p.resolution_note,
            "evidence_text": p.evidence_text,
            "author_lock": {"fields": lock.fields or [], "origin_title": lock.origin_title, "note": lock.note} if lock else None,
        })
    for s in (await db.execute(rows(ChapterContinuitySignal))).scalars():
        out["continuity_signals"].append({
            "chapter_number": s.chapter_number, "signal_type": s.signal_type, "character_name": s.character_name,
            "signal_key": s.signal_key, "signal_value": s.signal_value, "evidence_text": s.evidence_text,
        })
    for s in (await db.execute(rows(AuthorStateSignal))).scalars():
        out["author_state_signals"].append({
            "chapter_number": s.chapter_number, "signal_type": s.signal_type, "character_name": s.character_name,
            "signal_key": s.signal_key, "signal_value": s.signal_value, "note": s.note,
        })
    for e in (await db.execute(rows(TimelineEvent))).scalars():
        out["timeline_events"].append({
            "chapter_number": e.chapter_number, "event_type": e.event_type, "title": e.title, "description": e.description,
            "location": e.location, "time_marker": e.time_marker, "actor_names": _names(e.actor_ids, names),
            "target_names": _names(e.target_ids, names), "public_visibility": e.public_visibility,
        })
    for c in (await db.execute(rows(ChapterCausalLink))).scalars():
        out["causal_links"].append({
            "chapter_number": c.chapter_number, "cause": c.cause, "event": c.event, "effect": c.effect, "decision": c.decision,
            "actor_names": _names(c.actor_ids, names), "target_names": _names(c.target_ids, names),
            "importance_score": c.importance_score, "is_reversible": c.is_reversible, "evidence_text": c.evidence_text,
        })
    for r in (await db.execute(rows(RelationshipEvent))).scalars():
        if r.character_from_id in names and r.character_to_id in names:
            out["relationship_events"].append({
                "chapter_number": r.chapter_number, "from_name": names[r.character_from_id], "to_name": names[r.character_to_id],
                "delta": r.delta, "reason_type": r.reason_type, "reason_text": r.reason_text, "evidence_text": r.evidence_text,
                "old_intimacy_level": r.old_intimacy_level, "new_intimacy_level": r.new_intimacy_level,
                "old_status": r.old_status, "new_status": r.new_status, "requested_status": r.requested_status,
                "created_relationship": r.created_relationship,
            })
    for k in (await db.execute(rows(CharacterKnownInfo))).scalars():
        if k.character_id in names:
            out["known_infos"].append({
                "chapter_number": k.learned_in_chapter, "character_name": names[k.character_id], "info_key": k.info_key,
                "content": k.content, "source_type": k.source_type, "confidence": k.confidence, "secret_level": k.secret_level,
            })
    for i in (await db.execute(rows(ChapterConsistencyIssue))).scalars():
        out["consistency_issues"].append({
            "chapter_number": i.chapter_number, "severity": i.severity, "issue_type": i.issue_type, "rule_code": i.rule_code,
            "title": i.title, "details": i.details, "evidence_text": i.evidence_text, "character_name": i.character_name,
            "signal_key": i.signal_key, "reference_chapter_number": i.reference_chapter_number,
        })
    for a in (await db.execute(rows(ArcSummary))).scalars():
        key = a.arc_key
        match = _VOLUME_KEY.match(key or "")
        if match and match.group(2) in volumes:
            key = f"{match.group(1)}:@vol{volumes[match.group(2)]}{match.group(3)}"
        elif match:
            continue  # 卷已删的旧摘要不导出
        out["arc_summaries"].append({
            "level": a.level, "arc_key": key, "chapter_start": a.chapter_start, "chapter_end": a.chapter_end,
            "title": a.title, "content": a.content, "review": a.review, "source_signature": a.source_signature,
        })
    return out


def ledger_statistics(ledger: Optional[dict]) -> dict[str, int]:
    ledger = ledger if isinstance(ledger, dict) else {}
    return {
        "ledger_digests": len(ledger.get("chapter_digests") or []),
        "ledger_promises": len(ledger.get("narrative_promises") or []),
        "ledger_signals": len(ledger.get("continuity_signals") or []) + len(ledger.get("author_state_signals") or []),
        "ledger_events": len(ledger.get("timeline_events") or []) + len(ledger.get("causal_links") or []),
    }


def _list(ledger: dict, key: str) -> list[dict]:
    return [x for x in (ledger.get(key) or []) if isinstance(x, dict)]


def _remap_tasks(raw: Optional[str], mapping: dict[str, str]) -> Optional[str]:
    try:
        data = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict):
        return raw
    for kind in ("resolve", "advance"):
        for item in data.get(kind) or []:
            if isinstance(item, dict) and item.get("promise_id"):
                item["promise_id"] = mapping.get(str(item["promise_id"]))
    return json.dumps(data, ensure_ascii=False)


async def import_ledger(db: AsyncSession, project_id: str, ledger: Optional[dict]) -> dict[str, int]:
    """把 ledger 段写进新项目（章节 / 角色 / 卷 / 章纲已导入并 flush）；返回统计。ledger 为空只做章纲任务清理。"""
    ledger = ledger if isinstance(ledger, dict) else {}
    chapters = {n: cid for cid, n in (await db.execute(
        select(Chapter.id, Chapter.chapter_number).where(Chapter.project_id == project_id)
    )).all()}
    people = {name: cid for cid, name in (await db.execute(
        select(Character.id, Character.name).where(Character.project_id == project_id)
    )).all()}
    volumes = {n: vid for vid, n in (await db.execute(
        select(Volume.id, Volume.volume_number).where(Volume.project_id == project_id)
    )).all()}

    def ids(names: Any) -> list[str]:
        return [people[n] for n in (names or []) if n in people]

    # 分析时间记成导入之后一秒：章节目录只给「分析后又改过」的章重算指纹，同一时刻导入的章不必每次都算
    analyzed_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
    for a in _list(ledger, "chapter_analyses"):
        if a.get("chapter_number") in chapters:
            db.add(PlotAnalysis(
                project_id=project_id, chapter_id=chapters[a["chapter_number"]], hooks=a.get("hooks") or [],
                foreshadows=a.get("foreshadows") or [], plot_points=a.get("plot_points") or [],
                character_states=a.get("character_states") or [], scenes=a.get("scenes") or [],
                content_hash=a.get("content_hash"), created_at=analyzed_at,
            ))
    for d in _list(ledger, "chapter_digests"):
        if d.get("chapter_number") in chapters and (d.get("summary") or "").strip():
            db.add(ChapterDigest(
                project_id=project_id, chapter_id=chapters[d["chapter_number"]], summary=d["summary"],
                end_state=d.get("end_state"), source=d.get("source") if d.get("source") in ("ai", "author") else "ai",
                ai_summary=d.get("ai_summary"), ai_end_state=d.get("ai_end_state"), content_hash=d.get("content_hash"),
            ))
    mapping: dict[str, str] = {}
    for p in _list(ledger, "narrative_promises"):
        source = p.get("source_chapter_number")
        if source not in chapters or not (p.get("title") or "").strip():
            continue
        resolved = p.get("resolved_chapter_number")
        promise = NarrativePromise(
            project_id=project_id, source_chapter_id=chapters[source], source_chapter_number=source,
            promise_type=p.get("promise_type") or "foreshadow", title=p["title"], content=p.get("content") or p["title"],
            owner_character_id=people.get(p.get("owner_name") or ""), target_character_id=people.get(p.get("target_name") or ""),
            priority=p.get("priority") or "medium", status=p.get("status") or "open", deadline_chapter=p.get("deadline_chapter"),
            last_activated_chapter=p.get("last_activated_chapter"), resolved_chapter_number=resolved,
            resolved_chapter_id=chapters.get(resolved) if resolved else None, resolution_note=p.get("resolution_note"),
            evidence_text=p.get("evidence_text"),
        )
        db.add(promise)
        await db.flush()
        if p.get("key"):
            mapping[str(p["key"])] = promise.id
        lock = p.get("author_lock")
        if isinstance(lock, dict):
            db.add(PromiseAuthorLock(promise_id=promise.id, project_id=project_id, fields=list(lock.get("fields") or []),
                                     origin_title=lock.get("origin_title"), note=lock.get("note")))
    for outline in (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.narrative_tasks.isnot(None))
    )).scalars():
        outline.narrative_tasks = _remap_tasks(outline.narrative_tasks, mapping)

    for s in _list(ledger, "continuity_signals"):
        if s.get("chapter_number") in chapters and s.get("signal_type") and s.get("signal_value"):
            db.add(ChapterContinuitySignal(
                project_id=project_id, chapter_id=chapters[s["chapter_number"]], chapter_number=s["chapter_number"],
                signal_type=s["signal_type"], character_name=s.get("character_name"), signal_key=s.get("signal_key"),
                signal_value=s["signal_value"], evidence_text=s.get("evidence_text"),
            ))
    for s in _list(ledger, "author_state_signals"):
        if s.get("chapter_number") and s.get("signal_type") and s.get("signal_value"):
            db.add(AuthorStateSignal(
                project_id=project_id, chapter_number=int(s["chapter_number"]), signal_type=s["signal_type"],
                character_name=s.get("character_name") or "", signal_key=s.get("signal_key"), signal_value=s["signal_value"],
                note=s.get("note"),
            ))
    for e in _list(ledger, "timeline_events"):
        if e.get("chapter_number") in chapters and e.get("title"):
            db.add(TimelineEvent(
                project_id=project_id, chapter_id=chapters[e["chapter_number"]], chapter_number=e["chapter_number"],
                event_type=e.get("event_type") or "other", title=e["title"], description=e.get("description") or e["title"],
                location=e.get("location"), time_marker=e.get("time_marker"), actor_ids=ids(e.get("actor_names")),
                target_ids=ids(e.get("target_names")), public_visibility=e.get("public_visibility") or "public",
            ))
    for c in _list(ledger, "causal_links"):
        if c.get("chapter_number") in chapters:
            db.add(ChapterCausalLink(
                project_id=project_id, chapter_id=chapters[c["chapter_number"]], chapter_number=c["chapter_number"],
                cause=c.get("cause") or "", event=c.get("event") or "", effect=c.get("effect") or "", decision=c.get("decision"),
                actor_ids=ids(c.get("actor_names")), target_ids=ids(c.get("target_names")),
                importance_score=c.get("importance_score"), is_reversible=c.get("is_reversible"),
                evidence_text=c.get("evidence_text"),
            ))
    for r in _list(ledger, "relationship_events"):
        a, b = people.get(r.get("from_name") or ""), people.get(r.get("to_name") or "")
        if r.get("chapter_number") in chapters and a and b:
            db.add(RelationshipEvent(
                project_id=project_id, chapter_id=chapters[r["chapter_number"]], chapter_number=r["chapter_number"],
                character_from_id=a, character_to_id=b, delta=int(r.get("delta") or 0), reason_type=r.get("reason_type"),
                reason_text=r.get("reason_text"), evidence_text=r.get("evidence_text"),
                old_intimacy_level=r.get("old_intimacy_level"), new_intimacy_level=r.get("new_intimacy_level"),
                old_status=r.get("old_status"), new_status=r.get("new_status"), requested_status=r.get("requested_status"),
                created_relationship=r.get("created_relationship"),
            ))
    for k in _list(ledger, "known_infos"):
        who = people.get(k.get("character_name") or "")
        if k.get("chapter_number") in chapters and who and k.get("info_key") and k.get("content"):
            db.add(CharacterKnownInfo(
                project_id=project_id, chapter_id=chapters[k["chapter_number"]], character_id=who, info_key=k["info_key"],
                content=k["content"], source_type=k.get("source_type"), learned_in_chapter=k["chapter_number"],
                confidence=k.get("confidence"), secret_level=k.get("secret_level"),
            ))
    for i in _list(ledger, "consistency_issues"):
        if i.get("chapter_number") in chapters and i.get("title"):
            db.add(ChapterConsistencyIssue(
                project_id=project_id, chapter_id=chapters[i["chapter_number"]], chapter_number=i["chapter_number"],
                severity=i.get("severity") or "warning", issue_type=i.get("issue_type") or "other",
                rule_code=i.get("rule_code") or "imported", title=i["title"], details=i.get("details") or "",
                evidence_text=i.get("evidence_text"), character_name=i.get("character_name"), signal_key=i.get("signal_key"),
                reference_chapter_number=i.get("reference_chapter_number"),
            ))
    for a in _list(ledger, "arc_summaries"):
        key = str(a.get("arc_key") or "")
        match = re.match(r"^(unit|vchunk|volume):@vol(\d+)(.*)$", key)
        if match:
            volume_id = volumes.get(int(match.group(2)))
            if volume_id is None:
                continue
            key = f"{match.group(1)}:{volume_id}{match.group(3)}"
        if key and a.get("content") and a.get("level"):
            db.add(ArcSummary(
                project_id=project_id, level=a["level"], arc_key=key, chapter_start=int(a.get("chapter_start") or 1),
                chapter_end=int(a.get("chapter_end") or 1), title=a.get("title"), content=a["content"],
                review=a.get("review"), source_signature=a.get("source_signature"),
            ))
    await db.flush()
    return ledger_statistics(ledger)
