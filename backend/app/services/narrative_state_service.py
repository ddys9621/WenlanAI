"""Settle chapter analysis into durable narrative state and build generation context."""

from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.character import Character
from app.models.character_known_info import CharacterKnownInfo
from app.models.narrative_promise import NarrativePromise
from app.models.plot_line import PlotLine
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.relationship_event import RelationshipEvent
from app.models.timeline_event import TimelineEvent
from app.utils.character_names import build_name_index

logger = get_logger(__name__)


class NarrativeStateService:
    PROMISE_TYPE_MAP = {
        "foreshadow": "foreshadow",
        "promise": "promise",
        "mystery": "mystery",
        "conflict": "conflict",
    }
    PRIORITY_MAP = {"low": "low", "medium": "medium", "high": "high", "critical": "critical"}
    STATUS_MAP = {
        "open": "open",
        "progressing": "progressing",
        "resolved": "resolved",
        "broken": "broken",
        "closed": "resolved",
        "completed": "resolved",
    }
    KNOWLEDGE_SOURCE_MAP = {
        "witnessed": "witnessed",
        "hearsay": "hearsay",
        "deduced": "deduced",
        "document": "document",
    }
    VISIBILITY_MAP = {"public": "public", "private": "private", "secret": "secret"}
    RELATION_STATUS_MAP = {"active": "active", "broken": "broken", "past": "past", "complicated": "complicated"}
    PRIORITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    async def settle_chapter_state(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
    ) -> Dict[str, int]:
        """Persist analysis-derived state in idempotent way."""
        characters = await self._load_character_map(db, project_id)
        plot_lines = await self._load_plot_line_map(db, project_id)

        await self.clear_chapter_state(db, chapter.id)

        causal_count = await self._store_causal_links(db, project_id, chapter, analysis, characters, plot_lines)
        promise_count = await self._store_promises(db, project_id, chapter, analysis, characters, plot_lines)
        relationship_count = await self._store_relationship_events(db, project_id, chapter, analysis, characters)
        timeline_count = await self._store_timeline_events(db, project_id, chapter, analysis, characters, plot_lines)
        knowledge_count = await self._store_known_info(db, project_id, chapter, analysis, characters)

        logger.info(
            "✅ 章节状态结算完成: causal=%s promise=%s relationship=%s timeline=%s knowledge=%s",
            causal_count,
            promise_count,
            relationship_count,
            timeline_count,
            knowledge_count,
        )
        return {
            "causal_links": causal_count,
            "narrative_promises": promise_count,
            "relationship_events": relationship_count,
            "timeline_events": timeline_count,
            "known_infos": knowledge_count,
        }

    async def clear_chapter_state(self, db: AsyncSession, chapter_id: str) -> None:
        """清掉某章分析结算出的全部叙事状态：关系变化回滚、因果 / 时间轴 / 已知信息 / 关系事件、本章埋设的承诺、本章的回收标记。

        重新结算前（settle_chapter_state）与「重写覆盖正文」（api/chapters._purge_chapter_analysis_and_memory）都走这里。
        """
        await self._rollback_relationship_events(db, chapter_id)
        await self._clear_chapter_records(db, chapter_id)
        await self._clear_promise_resolutions(db, chapter_id)

    async def build_generation_context(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
        pov_character_name: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build context blocks for generation from durable narrative state."""
        active_promises = await self._maybe_await(self._get_active_promises(db, project_id, current_chapter))
        recent_causal_links = await self._maybe_await(self._get_recent_causal_links(db, project_id, current_chapter))
        recent_relationships = await self._maybe_await(
            self._get_recent_relationship_events(db, project_id, current_chapter, pov_character_name)
        )
        recent_timeline = await self._maybe_await(self._get_recent_timeline_events(db, project_id, current_chapter))
        pov_known_info = await self._maybe_await(
            self._get_pov_known_info(db, project_id, current_chapter, pov_character_name)
        )

        affiliation_records = await self._maybe_await(
            self._get_affiliation_dynamics(db, project_id)
        )

        return {
            "causal_chains": self._format_causal_links(recent_causal_links),
            "narrative_promises": self._format_promises(active_promises, current_chapter),
            "relationship_dynamics": self._format_relationship_events(recent_relationships),
            "timeline_events": self._format_timeline_events(recent_timeline),
            "pov_known_info": self._format_known_info(pov_character_name, pov_known_info),
            "affiliation_dynamics": self._format_affiliation_dynamics(affiliation_records),
        }

    async def _load_character_map(self, db: AsyncSession, project_id: str) -> dict[str, Character]:
        result = await db.execute(select(Character).where(Character.project_id == project_id))
        # 正式名 + 曾用名都指向同一角色（改名后 AI 仍可能沿用旧名）
        return build_name_index(result.scalars().all(), key=self._normalize_key)

    async def _load_plot_line_map(self, db: AsyncSession, project_id: str) -> dict[str, PlotLine]:
        result = await db.execute(select(PlotLine).where(PlotLine.project_id == project_id))
        return {self._normalize_key(item.title): item for item in result.scalars().all() if item.title}

    async def _find_character_by_name(self, db: AsyncSession, project_id: str, name: Optional[str]) -> Optional[Character]:
        """按名字找角色：走正式名 + 曾用名索引。characters.name 无唯一约束，同名多条时取索引里的第一条，
        不能用 scalar_one_or_none()（会抛 MultipleResultsFound，直接把整章生成打断）。"""
        if not name:
            return None
        characters = await self._load_character_map(db, project_id)
        return characters.get(self._normalize_key(name))

    async def _find_relationship(
        self, db: AsyncSession, project_id: str, from_id: str, to_id: str,
    ) -> Optional[CharacterRelationship]:
        """同一对角色间可能有多条关系（手动建关系接口不查重），取最早的一条作为结算 / 回滚目标。"""
        result = await db.execute(
            select(CharacterRelationship)
            .where(
                CharacterRelationship.project_id == project_id,
                CharacterRelationship.character_from_id == from_id,
                CharacterRelationship.character_to_id == to_id,
            )
            .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
        )
        return result.scalars().first()

    async def _rollback_relationship_events(self, db: AsyncSession, chapter_id: str) -> None:
        result = await db.execute(
            select(RelationshipEvent).where(RelationshipEvent.chapter_id == chapter_id)
        )
        for event in result.scalars().all():
            relationship = await self._find_relationship(
                db, event.project_id, event.character_from_id, event.character_to_id
            )
            if relationship is None:
                continue

            if event.created_relationship and event.old_intimacy_level is None:
                await db.delete(relationship)
                continue

            relationship.intimacy_level = event.old_intimacy_level if event.old_intimacy_level is not None else 50
            relationship.status = event.old_status or "active"

    async def _clear_chapter_records(self, db: AsyncSession, chapter_id: str) -> None:
        await db.execute(delete(ChapterCausalLink).where(ChapterCausalLink.chapter_id == chapter_id))
        await db.execute(delete(TimelineEvent).where(TimelineEvent.chapter_id == chapter_id))
        await db.execute(delete(CharacterKnownInfo).where(CharacterKnownInfo.chapter_id == chapter_id))
        await db.execute(delete(RelationshipEvent).where(RelationshipEvent.chapter_id == chapter_id))
        await db.execute(delete(NarrativePromise).where(NarrativePromise.source_chapter_id == chapter_id))

    async def _clear_promise_resolutions(self, db: AsyncSession, chapter_id: str) -> None:
        result = await db.execute(
            select(NarrativePromise).where(NarrativePromise.resolved_chapter_id == chapter_id)
        )
        for promise in result.scalars().all():
            promise.resolved_chapter_id = None
            promise.resolved_chapter_number = None
            promise.resolution_note = None
            if promise.status == "resolved":
                promise.status = "open"

    async def _store_causal_links(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
        characters: dict[str, Character],
        plot_lines: dict[str, PlotLine],
    ) -> int:
        causal_links = analysis.get("causal_links", []) or []
        count = 0
        for item in causal_links:
            if not any((item.get("cause"), item.get("event"), item.get("effect"))):
                continue
            db.add(
                ChapterCausalLink(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    cause=(item.get("cause") or "").strip(),
                    event=(item.get("event") or "").strip(),
                    effect=(item.get("effect") or "").strip(),
                    decision=(item.get("decision") or "").strip() or None,
                    actor_ids=self._map_character_ids(item.get("actor_names", []), characters),
                    target_ids=self._map_character_ids(item.get("target_names", []), characters),
                    plot_line_id=self._match_plot_line_id(item.get("plot_line_hint"), plot_lines),
                    importance_score=self._clamp_float(item.get("importance"), 0.0, 1.0, 0.5),
                    is_reversible=bool(item.get("reversible", False)),
                    evidence_text=(item.get("evidence") or "").strip() or None,
                )
            )
            count += 1
        return count

    async def _store_promises(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
        characters: dict[str, Character],
        plot_lines: dict[str, PlotLine],
    ) -> int:
        count = 0

        # 1) explicit narrative promises
        for item in analysis.get("narrative_promises", []) or []:
            count += await self._upsert_promise_from_item(db, project_id, chapter, item, characters, plot_lines)

        # 2) fallback from foreshadow extraction
        for index, item in enumerate(analysis.get("foreshadows", []) or []):
            promise_item = {
                "promise_type": "foreshadow",
                "title": (item.get("content") or f"伏笔-{index + 1}")[:200],
                "content": item.get("content") or "",
                "priority": "medium",
                "status": "resolved" if item.get("type") == "resolved" else "open",
                "reference_chapter": item.get("reference_chapter"),
                "evidence": item.get("keyword") or "",
            }
            count += await self._upsert_promise_from_item(db, project_id, chapter, promise_item, characters, plot_lines)

        return count

    async def _upsert_promise_from_item(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        item: Dict[str, Any],
        characters: dict[str, Character],
        plot_lines: dict[str, PlotLine],
    ) -> int:
        promise_type = self._normalize_promise_type(item.get("promise_type"))
        title = (item.get("title") or item.get("content") or "").strip()[:200]
        content = (item.get("content") or "").strip()
        if not title or not content:
            return 0

        status = self._normalize_promise_status(item.get("status"))
        if status == "resolved":
            matched = await self._find_resolvable_promise(
                db=db,
                project_id=project_id,
                current_chapter=chapter.chapter_number,
                promise_type=promise_type,
                title=title,
                content=content,
                resolves_title=item.get("resolves_title"),
                reference_chapter=item.get("reference_chapter"),
            )
            if matched:
                matched.status = "resolved"
                matched.last_activated_chapter = chapter.chapter_number
                matched.resolved_chapter_id = chapter.id
                matched.resolved_chapter_number = chapter.chapter_number
                matched.resolution_note = content[:1000]
                return 1

        db.add(
            NarrativePromise(
                project_id=project_id,
                source_chapter_id=chapter.id,
                source_chapter_number=chapter.chapter_number,
                promise_type=promise_type,
                title=title,
                content=content,
                owner_character_id=self._match_character_id(item.get("owner_character_name"), characters),
                target_character_id=self._match_character_id(item.get("target_character_name"), characters),
                plot_line_id=self._match_plot_line_id(item.get("plot_line_hint"), plot_lines),
                priority=self._normalize_priority(item.get("priority")),
                status=status,
                deadline_chapter=self._safe_int(item.get("deadline_chapter")),
                last_activated_chapter=chapter.chapter_number,
                evidence_text=(item.get("evidence") or "").strip() or None,
                resolved_chapter_id=chapter.id if status == "resolved" else None,
                resolved_chapter_number=chapter.chapter_number if status == "resolved" else None,
                resolution_note=content[:1000] if status == "resolved" else None,
            )
        )
        return 1

    async def _find_resolvable_promise(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
        promise_type: str,
        title: str,
        content: str,
        resolves_title: Optional[str],
        reference_chapter: Any,
    ) -> Optional[NarrativePromise]:
        result = await db.execute(
            select(NarrativePromise).where(
                NarrativePromise.project_id == project_id,
                NarrativePromise.source_chapter_number < current_chapter,
                NarrativePromise.status.in_(["open", "progressing"]),
                NarrativePromise.promise_type == promise_type,
            )
        )
        candidates = result.scalars().all()
        if not candidates:
            return None

        normalized_resolves = self._normalize_key(resolves_title or "")
        normalized_title = self._normalize_key(title)
        normalized_content = self._normalize_key(content[:80])
        ref_chapter = self._safe_int(reference_chapter)

        for candidate in candidates:
            if ref_chapter and candidate.source_chapter_number == ref_chapter:
                return candidate
            if normalized_resolves and normalized_resolves in self._normalize_key(candidate.title):
                return candidate
            if normalized_title and normalized_title in self._normalize_key(candidate.title):
                return candidate
            if normalized_content and normalized_content[:20] and normalized_content[:20] in self._normalize_key(candidate.content):
                return candidate

        return candidates[0]

    async def _store_relationship_events(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
        characters: dict[str, Character],
    ) -> int:
        count = 0
        for item in analysis.get("relationship_deltas", []) or []:
            from_id = self._match_character_id(item.get("from_character_name"), characters)
            to_id = self._match_character_id(item.get("to_character_name"), characters)
            if not from_id or not to_id or from_id == to_id:
                continue

            delta = self._clamp_int(item.get("delta"), -100, 100, 0)
            if delta == 0:
                continue

            relationship = await self._find_relationship(db, project_id, from_id, to_id)
            created_relationship = 0

            if relationship is None:
                relationship = CharacterRelationship(
                    project_id=project_id,
                    character_from_id=from_id,
                    character_to_id=to_id,
                    intimacy_level=50,
                    status="active",
                    source="ai",
                )
                db.add(relationship)
                created_relationship = 1
                old_intimacy = None
                old_status = None
            else:
                old_intimacy = relationship.intimacy_level
                old_status = relationship.status
            relationship.intimacy_level = max(-100, min(100, (relationship.intimacy_level or 50) + delta))
            relationship.status = self._normalize_relationship_status(item.get("new_status"), fallback=old_status or "active")
            relationship.description = (item.get("reason") or relationship.description or "")[:1000]

            db.add(
                RelationshipEvent(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    character_from_id=from_id,
                    character_to_id=to_id,
                    delta=delta,
                    reason_type=(item.get("reason_type") or "other")[:50],
                    reason_text=(item.get("reason") or "").strip()[:1000] or None,
                    evidence_text=(item.get("evidence") or "").strip()[:500] or None,
                    old_intimacy_level=old_intimacy,
                    new_intimacy_level=relationship.intimacy_level,
                    old_status=old_status,
                    new_status=relationship.status,
                    created_relationship=created_relationship,
                )
            )
            count += 1

        return count

    async def _store_timeline_events(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
        characters: dict[str, Character],
        plot_lines: dict[str, PlotLine],
    ) -> int:
        count = 0
        for item in analysis.get("timeline_events", []) or []:
            title = (item.get("title") or "").strip()[:200]
            description = (item.get("description") or "").strip()
            if not title or not description:
                continue
            db.add(
                TimelineEvent(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    event_type=(item.get("event_type") or "other")[:50],
                    title=title,
                    description=description,
                    location=(item.get("location") or "").strip()[:200] or None,
                    time_marker=(item.get("time_marker") or "").strip()[:200] or None,
                    actor_ids=self._map_character_ids(item.get("actor_names", []), characters),
                    target_ids=self._map_character_ids(item.get("target_names", []), characters),
                    plot_line_ids=self._map_plot_line_ids(item.get("plot_line_hints", []), plot_lines),
                    public_visibility=self._normalize_visibility(item.get("public_visibility")),
                )
            )
            count += 1
        return count

    async def _store_known_info(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: Dict[str, Any],
        characters: dict[str, Character],
    ) -> int:
        count = 0
        for item in analysis.get("knowledge_changes", []) or []:
            character_id = self._match_character_id(item.get("character_name"), characters)
            info_key = (item.get("info_key") or "").strip()[:200]
            content = (item.get("content") or "").strip()
            if not character_id or not info_key or not content:
                continue
            db.add(
                CharacterKnownInfo(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    character_id=character_id,
                    info_key=info_key,
                    content=content,
                    source_type=self._normalize_knowledge_source(item.get("source")),
                    learned_in_chapter=chapter.chapter_number,
                    confidence=self._clamp_float(item.get("confidence"), 0.0, 1.0, 1.0),
                    secret_level=self._normalize_visibility(item.get("secret_level"), allow_secret=True),
                )
            )
            count += 1
        return count

    async def _get_active_promises(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
    ) -> list[NarrativePromise]:
        result = await db.execute(
            select(NarrativePromise).where(
                NarrativePromise.project_id == project_id,
                NarrativePromise.source_chapter_number < current_chapter,
                NarrativePromise.status.in_(["open", "progressing", "broken"]),
            )
        )
        promises = result.scalars().all()
        promises.sort(
            key=lambda item: (
                -self.PRIORITY_WEIGHT.get(item.priority or "medium", 2),
                -(item.last_activated_chapter or item.source_chapter_number or 0),
            )
        )
        return promises[:8]

    async def _get_recent_causal_links(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
    ) -> list[ChapterCausalLink]:
        result = await db.execute(
            select(ChapterCausalLink).where(
                ChapterCausalLink.project_id == project_id,
                ChapterCausalLink.chapter_number < current_chapter,
            )
        )
        items = result.scalars().all()
        items.sort(key=lambda item: (item.chapter_number, item.importance_score or 0), reverse=True)
        return items[:6]

    async def _get_recent_relationship_events(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
        pov_character_name: Optional[str],
    ) -> list[RelationshipEvent]:
        pov_character = await self._find_character_by_name(db, project_id, pov_character_name)
        character_id = pov_character.id if pov_character else None

        query = select(RelationshipEvent).where(
            RelationshipEvent.project_id == project_id,
            RelationshipEvent.chapter_number < current_chapter,
        )
        if character_id:
            query = query.where(
                or_(
                    RelationshipEvent.character_from_id == character_id,
                    RelationshipEvent.character_to_id == character_id,
                )
            )

        result = await db.execute(query)
        items = result.scalars().all()
        items.sort(key=lambda item: item.chapter_number, reverse=True)
        return items[:8]

    async def _get_recent_timeline_events(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
    ) -> list[TimelineEvent]:
        result = await db.execute(
            select(TimelineEvent).where(
                TimelineEvent.project_id == project_id,
                TimelineEvent.chapter_number < current_chapter,
            )
        )
        items = result.scalars().all()
        items.sort(key=lambda item: item.chapter_number, reverse=True)
        return items[:8]

    async def _get_pov_known_info(
        self,
        db: AsyncSession,
        project_id: str,
        current_chapter: int,
        pov_character_name: Optional[str],
    ) -> list[CharacterKnownInfo]:
        character = await self._find_character_by_name(db, project_id, pov_character_name)
        if character is None:
            return []

        info_result = await db.execute(
            select(CharacterKnownInfo).where(
                CharacterKnownInfo.project_id == project_id,
                CharacterKnownInfo.character_id == character.id,
                CharacterKnownInfo.learned_in_chapter < current_chapter,
            )
        )
        items = info_result.scalars().all()
        items.sort(key=lambda item: item.learned_in_chapter, reverse=True)
        return items[:10]

    def _format_causal_links(self, items: Iterable[ChapterCausalLink]) -> str:
        items = list(items)
        if not items:
            return "【因果链账本】\n暂无可用因果链\n"

        lines = ["【因果链账本】"]
        for item in items:
            lines.append(
                f"- 第{item.chapter_number}章：因={item.cause}；事={item.event}；果={item.effect}；决={item.decision or '无'}"
            )
        return "\n".join(lines) + "\n"

    def _format_promises(self, items: Iterable[NarrativePromise], current_chapter: int) -> str:
        items = list(items)
        if not items:
            return "【叙事承诺清单】\n暂无未回收承诺\n"

        lines = ["【叙事承诺清单】"]
        for item in items:
            overdue = ""
            if item.deadline_chapter and current_chapter > item.deadline_chapter:
                overdue = " ⚠️已超期"
            elif item.last_activated_chapter and current_chapter - item.last_activated_chapter >= 5:
                overdue = " ⚠️掉线预警"
            lines.append(
                f"- [{item.promise_type}/{item.priority}/{item.status}] {item.title}（起于第{item.source_chapter_number}章）{overdue}: {item.content[:120]}"
            )
        return "\n".join(lines) + "\n"

    def _format_relationship_events(self, items: Iterable[RelationshipEvent]) -> str:
        items = list(items)
        if not items:
            return "【关系动态】\n暂无最近关系变化\n"

        lines = ["【关系动态】"]
        for item in items:
            lines.append(
                f"- 第{item.chapter_number}章：关系变化 {item.delta:+d}，原因={item.reason_text or item.reason_type or '未知'}"
            )
        return "\n".join(lines) + "\n"

    def _format_timeline_events(self, items: Iterable[TimelineEvent]) -> str:
        items = list(items)
        if not items:
            return "【全局时间轴】\n暂无最近时间轴事件\n"

        lines = ["【全局时间轴】"]
        for item in items:
            location = f" @ {item.location}" if item.location else ""
            time_marker = f" / {item.time_marker}" if item.time_marker else ""
            lines.append(
                f"- 第{item.chapter_number}章：{item.title}{location}{time_marker} -> {item.description[:120]}"
            )
        return "\n".join(lines) + "\n"

    def _format_known_info(self, pov_character_name: Optional[str], items: Iterable[CharacterKnownInfo]) -> str:
        items = list(items)
        if not pov_character_name:
            return "【视角信息边界】\n本章未指定 POV，默认按公共信息与前文共识处理\n"
        if not items:
            return f"【视角信息边界】\n本章 POV={pov_character_name}，暂无已登记私有信息，仅可使用公共信息与眼前所见\n"

        lines = [f"【视角信息边界】\n本章 POV={pov_character_name}，只能使用以下已知信息："]
        for item in items:
            lines.append(
                f"- 第{item.learned_in_chapter}章获得[{item.source_type}/{item.secret_level}/{item.confidence:.1f}] {item.info_key}: {item.content[:120]}"
            )
        return "\n".join(lines) + "\n"

    async def _get_affiliation_dynamics(self, db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
        """Get all organization membership records with character and org names."""
        # Get all organizations for this project
        org_result = await db.execute(
            select(Organization).where(Organization.project_id == project_id)
        )
        orgs = {org.id: org for org in org_result.scalars().all()}
        if not orgs:
            return []

        # Get org character names
        org_char_ids = [org.character_id for org in orgs.values()]
        char_result = await db.execute(
            select(Character).where(Character.id.in_(org_char_ids))
        )
        org_name_map = {c.id: c.name for c in char_result.scalars().all()}

        # Get all members across these orgs
        member_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id.in_(list(orgs.keys()))
            )
        )
        members = member_result.scalars().all()
        if not members:
            return []

        # Get member character names
        member_char_ids = list({m.character_id for m in members})
        member_char_result = await db.execute(
            select(Character).where(Character.id.in_(member_char_ids))
        )
        member_name_map = {c.id: c.name for c in member_char_result.scalars().all()}

        records = []
        for m in members:
            org = orgs.get(m.organization_id)
            if not org:
                continue
            org_name = org_name_map.get(org.character_id, "未知组织")
            char_name = member_name_map.get(m.character_id, "未知角色")
            records.append({
                "character": char_name,
                "organization": org_name,
                "position": m.position or "成员",
                "status": m.status or "active",
                "joined_at": m.joined_at,
                "left_at": m.left_at,
                "notes": m.notes,
            })
        return records

    def _format_affiliation_dynamics(self, records: list[dict[str, Any]]) -> str:
        if not records:
            return "【组织归属】\n暂无角色组织归属记录\n"

        lines = ["【组织归属】"]
        for r in records:
            status_label = {
                "active": "在职",
                "left": "已离开",
                "expelled": "被逐出",
                "inactive": "不活跃",
            }.get(r["status"], r["status"])

            entry = f"- {r['character']} → {r['organization']}（{r['position']}，{status_label}）"
            if r.get("joined_at"):
                entry += f" 加入于{r['joined_at']}"
            if r.get("left_at"):
                entry += f" 离开于{r['left_at']}"
            if r.get("notes"):
                # Show last note line only (most recent event)
                last_note = r["notes"].strip().split("\n")[-1]
                entry += f" | {last_note}"
            lines.append(entry)
        return "\n".join(lines) + "\n"

    def _match_character_id(self, name: Optional[str], characters: dict[str, Character]) -> Optional[str]:
        if not name:
            return None
        character = characters.get(self._normalize_key(name))
        return character.id if character else None

    def _map_character_ids(self, names: Iterable[str], characters: dict[str, Character]) -> list[str]:
        ids: list[str] = []
        for name in names or []:
            character_id = self._match_character_id(name, characters)
            if character_id and character_id not in ids:
                ids.append(character_id)
        return ids

    def _match_plot_line_id(self, hint: Optional[str], plot_lines: dict[str, PlotLine]) -> Optional[str]:
        if not hint:
            return None
        line = plot_lines.get(self._normalize_key(hint))
        return line.id if line else None

    def _map_plot_line_ids(self, hints: Iterable[str], plot_lines: dict[str, PlotLine]) -> list[str]:
        ids: list[str] = []
        for hint in hints or []:
            plot_line_id = self._match_plot_line_id(hint, plot_lines)
            if plot_line_id and plot_line_id not in ids:
                ids.append(plot_line_id)
        return ids

    def _normalize_promise_type(self, value: Optional[str]) -> str:
        return self.PROMISE_TYPE_MAP.get((value or "").strip().lower(), "promise")

    def _normalize_priority(self, value: Optional[str]) -> str:
        return self.PRIORITY_MAP.get((value or "").strip().lower(), "medium")

    def _normalize_promise_status(self, value: Optional[str]) -> str:
        return self.STATUS_MAP.get((value or "").strip().lower(), "open")

    def _normalize_knowledge_source(self, value: Optional[str]) -> str:
        return self.KNOWLEDGE_SOURCE_MAP.get((value or "").strip().lower(), "witnessed")

    def _normalize_visibility(self, value: Optional[str], allow_secret: bool = True) -> str:
        normalized = self.VISIBILITY_MAP.get((value or "").strip().lower(), "private")
        if not allow_secret and normalized == "secret":
            return "private"
        return normalized

    def _normalize_relationship_status(self, value: Optional[str], fallback: str = "active") -> str:
        return self.RELATION_STATUS_MAP.get((value or "").strip().lower(), fallback)

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clamp_int(self, value: Any, min_value: int, max_value: int, default: int) -> int:
        try:
            return max(min_value, min(max_value, int(value)))
        except (TypeError, ValueError):
            return default

    def _clamp_float(self, value: Any, min_value: float, max_value: float, default: float) -> float:
        try:
            return max(min_value, min(max_value, float(value)))
        except (TypeError, ValueError):
            return default

    def _normalize_key(self, value: Optional[str]) -> str:
        return (value or "").strip().lower()

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value


narrative_state_service = NarrativeStateService()
