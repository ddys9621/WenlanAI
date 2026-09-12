"""Continuity signal settlement, hard-rule auditing and chapter visualization payloads."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.narrative_promise import NarrativePromise
from app.models.relationship_event import RelationshipEvent
from app.models.timeline_event import TimelineEvent
from app.utils.character_names import build_name_index

logger = get_logger(__name__)


class ChapterConsistencyService:
    LIFE_SIGNAL_VALUES = {"dead", "missing", "revived", "survived"}
    ABILITY_SIGNAL_VALUES = {"learned", "mastered", "used", "lost", "forgotten"}
    LOCATION_SIGNAL_VALUES = {"arrived", "left", "current"}

    async def settle_signals_and_audit(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: dict[str, Any],
    ) -> dict[str, int]:
        signals = self._extract_continuity_signals(analysis)
        # AI 可能沿用角色曾用名；信号按名字串链，落库前统一归到正式名
        canonical_names = await self._load_canonical_names(db, project_id)
        for signal in signals:
            signal["character_name"] = self._canonical_name(signal.get("character_name"), canonical_names) or None

        await self.clear_chapter_records(db, chapter.id)

        signal_count = 0
        for signal in signals:
            db.add(
                ChapterContinuitySignal(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    signal_type=signal["signal_type"],
                    character_name=signal.get("character_name"),
                    signal_key=signal.get("signal_key"),
                    signal_value=signal["signal_value"],
                    evidence_text=signal.get("evidence_text"),
                )
            )
            signal_count += 1

        issues = await self._build_consistency_issues(
            db=db,
            project_id=project_id,
            chapter=chapter,
            analysis=analysis,
            signals=signals,
            canonical_names=canonical_names,
        )

        for issue in issues:
            db.add(
                ChapterConsistencyIssue(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    severity=issue["severity"],
                    issue_type=issue["issue_type"],
                    rule_code=issue["rule_code"],
                    title=issue["title"],
                    details=issue["details"],
                    evidence_text=issue.get("evidence_text"),
                    character_name=issue.get("character_name"),
                    signal_key=issue.get("signal_key"),
                    reference_chapter_number=issue.get("reference_chapter_number"),
                )
            )

        logger.info(
            "✅ 一致性审计完成: chapter=%s signals=%s issues=%s",
            chapter.chapter_number,
            signal_count,
            len(issues),
        )
        return {
            "continuity_signals": signal_count,
            "consistency_issues": len(issues),
            "critical_issues": sum(1 for item in issues if item["severity"] == "critical"),
        }

    async def clear_chapter_records(self, db: AsyncSession, chapter_id: str) -> None:
        """删掉某章的连续性信号与一致性问题（重新结算前 / 重写覆盖正文后）。"""
        await db.execute(delete(ChapterContinuitySignal).where(ChapterContinuitySignal.chapter_id == chapter_id))
        await db.execute(delete(ChapterConsistencyIssue).where(ChapterConsistencyIssue.chapter_id == chapter_id))

    async def build_chapter_visualization_payload(
        self,
        db: AsyncSession,
        chapter: Chapter,
    ) -> dict[str, Any]:
        character_name_by_id = await self._load_character_name_map(db, chapter.project_id)

        causal_result = await db.execute(
            select(ChapterCausalLink).where(ChapterCausalLink.chapter_id == chapter.id)
        )
        causal_links = causal_result.scalars().all()
        causal_links.sort(key=lambda item: item.importance_score or 0, reverse=True)

        promise_result = await db.execute(
            select(NarrativePromise).where(
                NarrativePromise.project_id == chapter.project_id,
                or_(
                    NarrativePromise.source_chapter_id == chapter.id,
                    NarrativePromise.resolved_chapter_id == chapter.id,
                ),
            )
        )
        promises = promise_result.scalars().all()
        promises.sort(key=lambda item: (item.source_chapter_number, item.created_at))

        timeline_result = await db.execute(
            select(TimelineEvent).where(TimelineEvent.chapter_id == chapter.id)
        )
        timeline_events = timeline_result.scalars().all()
        timeline_events.sort(key=lambda item: item.created_at)

        relationship_result = await db.execute(
            select(RelationshipEvent).where(RelationshipEvent.chapter_id == chapter.id)
        )
        relationship_events = relationship_result.scalars().all()
        relationship_events.sort(key=lambda item: abs(item.delta), reverse=True)

        issue_result = await db.execute(
            select(ChapterConsistencyIssue).where(ChapterConsistencyIssue.chapter_id == chapter.id)
        )
        issues = issue_result.scalars().all()
        issues.sort(key=lambda item: (self._severity_weight(item.severity), item.created_at), reverse=True)

        relationship_nodes: dict[str, dict[str, str]] = {}
        relationship_edges: list[dict[str, Any]] = []
        for event in relationship_events:
            from_name = character_name_by_id.get(event.character_from_id, event.character_from_id)
            to_name = character_name_by_id.get(event.character_to_id, event.character_to_id)
            relationship_nodes[from_name] = {"id": from_name, "label": from_name}
            relationship_nodes[to_name] = {"id": to_name, "label": to_name}
            relationship_edges.append(
                {
                    "source": from_name,
                    "target": to_name,
                    "delta": event.delta,
                    "reason": event.reason_text or event.reason_type or "",
                    "new_status": event.new_status or "",
                    "intimacy_level": event.new_intimacy_level,
                }
            )

        return {
            "causal_links": [
                {
                    "cause": item.cause,
                    "event": item.event,
                    "effect": item.effect,
                    "decision": item.decision,
                    "importance": item.importance_score or 0,
                    "reversible": bool(item.is_reversible),
                    "actor_names": [character_name_by_id.get(char_id, char_id) for char_id in (item.actor_ids or [])],
                    "target_names": [character_name_by_id.get(char_id, char_id) for char_id in (item.target_ids or [])],
                    "evidence": item.evidence_text,
                }
                for item in causal_links
            ],
            "promises": [
                {
                    "id": item.id,
                    "promise_type": item.promise_type,
                    "title": item.title,
                    "content": item.content,
                    "priority": item.priority,
                    "status": item.status,
                    "source_chapter_number": item.source_chapter_number,
                    "resolved_chapter_number": item.resolved_chapter_number,
                    "deadline_chapter": item.deadline_chapter,
                    "owner_character_name": character_name_by_id.get(item.owner_character_id, None),
                    "target_character_name": character_name_by_id.get(item.target_character_id, None),
                    "resolution_note": item.resolution_note,
                }
                for item in promises
            ],
            "timeline_events": [
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "title": item.title,
                    "description": item.description,
                    "location": item.location,
                    "time_marker": item.time_marker,
                    "actor_names": [character_name_by_id.get(char_id, char_id) for char_id in (item.actor_ids or [])],
                    "target_names": [character_name_by_id.get(char_id, char_id) for char_id in (item.target_ids or [])],
                    "public_visibility": item.public_visibility,
                }
                for item in timeline_events
            ],
            "relationship_graph": {
                "nodes": list(relationship_nodes.values()),
                "edges": relationship_edges,
            },
            "consistency_audit": {
                "summary": {
                    "total": len(issues),
                    "critical": sum(1 for item in issues if item.severity == "critical"),
                    "high": sum(1 for item in issues if item.severity == "high"),
                    "medium": sum(1 for item in issues if item.severity == "medium"),
                    "low": sum(1 for item in issues if item.severity == "low"),
                },
                "issues": [
                    {
                        "severity": item.severity,
                        "issue_type": item.issue_type,
                        "rule_code": item.rule_code,
                        "title": item.title,
                        "details": item.details,
                        "evidence": item.evidence_text,
                        "character_name": item.character_name,
                        "signal_key": item.signal_key,
                        "reference_chapter_number": item.reference_chapter_number,
                    }
                    for item in issues
                ],
            },
        }

    async def _build_consistency_issues(
        self,
        db: AsyncSession,
        project_id: str,
        chapter: Chapter,
        analysis: dict[str, Any],
        signals: list[dict[str, Optional[str]]],
        canonical_names: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        previous_life_result = await db.execute(
            select(ChapterContinuitySignal).where(
                ChapterContinuitySignal.project_id == project_id,
                ChapterContinuitySignal.chapter_number < chapter.chapter_number,
                ChapterContinuitySignal.signal_type == "life_state",
            )
        )
        previous_life_signals = previous_life_result.scalars().all()

        previous_dead_by_character: dict[str, int] = {}
        for item in previous_life_signals:
            character_name = self._normalize_name(item.character_name)
            if not character_name:
                continue
            if item.signal_value == "dead":
                previous_dead_by_character[character_name] = max(
                    previous_dead_by_character.get(character_name, 0),
                    item.chapter_number or 0,
                )
            elif item.signal_value == "revived":
                previous_dead_by_character.pop(character_name, None)

        current_life_signals = [item for item in signals if item["signal_type"] == "life_state"]
        revived_names = {
            self._normalize_name(item.get("character_name"))
            for item in current_life_signals
            if item["signal_value"] == "revived"
        }
        current_character_names = self._collect_current_character_names(analysis, canonical_names)
        for character_name in sorted(current_character_names):
            dead_at = previous_dead_by_character.get(character_name)
            if dead_at and character_name not in revived_names:
                issues.append(
                    {
                        "severity": "critical",
                        "issue_type": "dead_character",
                        "rule_code": "dead_character_reappears",
                        "title": f"已死亡角色再次出场：{character_name}",
                        "details": f"{character_name} 曾在第 {dead_at} 章被标记为死亡，但本章再次参与剧情，未检测到复活或回溯说明。",
                        "character_name": character_name,
                        "reference_chapter_number": dead_at,
                    }
                )

        previous_ability_result = await db.execute(
            select(ChapterContinuitySignal).where(
                ChapterContinuitySignal.project_id == project_id,
                ChapterContinuitySignal.chapter_number < chapter.chapter_number,
                ChapterContinuitySignal.signal_type == "ability",
            )
        )
        previous_ability_signals = previous_ability_result.scalars().all()
        previous_ability_signals.sort(key=lambda item: item.chapter_number or 0)
        learned_abilities: dict[tuple[str, str], int] = {}
        latest_ability_state: dict[tuple[str, str], tuple[str, int]] = {}
        for item in previous_ability_signals:
            character_name = self._normalize_name(item.character_name)
            ability_name = self._normalize_key(item.signal_key)
            if not character_name or not ability_name:
                continue
            key = (character_name, ability_name)
            if item.signal_value in {"learned", "mastered"}:
                learned_abilities[key] = max(learned_abilities.get(key, 0), item.chapter_number or 0)
            elif item.signal_value in {"lost", "forgotten"}:
                learned_abilities.pop(key, None)
            latest_ability_state[key] = (item.signal_value, item.chapter_number or 0)

        current_relearned_abilities = {
            (
                self._normalize_name(item.get("character_name")),
                self._normalize_key(item.get("signal_key")),
            )
            for item in signals
            if item["signal_type"] == "ability" and item["signal_value"] in {"learned", "mastered"}
        }
        for item in (signal for signal in signals if signal["signal_type"] == "ability"):
            character_name = self._normalize_name(item.get("character_name"))
            ability_name = self._normalize_key(item.get("signal_key"))
            signal_value = item["signal_value"]
            if not character_name or not ability_name:
                continue
            ability_key = (character_name, ability_name)
            if signal_value in {"lost", "forgotten"}:
                learned_at = learned_abilities.get(ability_key)
                if learned_at:
                    issues.append(
                        {
                            "severity": "high",
                            "issue_type": "ability",
                            "rule_code": "ability_forgotten_without_transition",
                            "title": f"能力连续性可疑：{character_name} · {item.get('signal_key')}",
                            "details": f"{character_name} 在第 {learned_at} 章已学会/掌握“{item.get('signal_key')}”，本章却被标记为{self._ability_value_label(signal_value)}，需要补桥段说明。",
                            "character_name": character_name,
                            "signal_key": item.get("signal_key"),
                            "reference_chapter_number": learned_at,
                            "evidence_text": item.get("evidence_text"),
                        }
                    )
                continue

            if signal_value != "used":
                continue

            latest_state = latest_ability_state.get(ability_key)
            if not latest_state:
                continue
            latest_value, changed_at = latest_state
            if latest_value not in {"lost", "forgotten"} or ability_key in current_relearned_abilities:
                continue

            issues.append(
                {
                    "severity": "high",
                    "issue_type": "ability",
                    "rule_code": "ability_used_after_loss",
                    "title": f"能力使用连续性冲突：{character_name} · {item.get('signal_key')}",
                    "details": f"{character_name} 的“{item.get('signal_key')}”在第 {changed_at} 章已被标记为{self._ability_value_label(latest_value)}，本章却再次直接使用，缺少重新学会/恢复的过渡。",
                    "character_name": character_name,
                    "signal_key": item.get("signal_key"),
                    "reference_chapter_number": changed_at,
                    "evidence_text": item.get("evidence_text"),
                }
            )

        outline_scene = await self._load_outline_scene(db, chapter)
        current_locations = self._collect_current_locations(analysis, signals)
        if outline_scene:
            if current_locations:
                if not self._is_location_match(outline_scene, current_locations):
                    issues.append(
                        {
                            "severity": "medium",
                            "issue_type": "location",
                            "rule_code": "outline_scene_mismatch",
                            "title": "章纲场景与正文地点不一致",
                            "details": f"章纲场景写的是“{outline_scene}”，但本章抽取到的主要地点为：{', '.join(current_locations)}。",
                            "signal_key": outline_scene,
                        }
                    )
            else:
                issues.append(
                    {
                        "severity": "low",
                        "issue_type": "location",
                        "rule_code": "outline_scene_missing_in_text",
                        "title": "正文未抽取到明确地点",
                        "details": f"章纲场景为“{outline_scene}”，但本章分析未提取到稳定地点信息，后续容易引发场景跳变。",
                        "signal_key": outline_scene,
                    }
                )

        current_location_signals = [item for item in signals if item["signal_type"] == "location" and item["signal_value"] == "current"]
        location_by_character: dict[str, set[str]] = defaultdict(set)
        for item in current_location_signals:
            character_name = self._normalize_name(item.get("character_name"))
            location_name = (item.get("signal_key") or "").strip()
            if character_name and location_name:
                location_by_character[character_name].add(location_name)
        for character_name, locations in location_by_character.items():
            if len(locations) > 1:
                issues.append(
                    {
                        "severity": "medium",
                        "issue_type": "location",
                        "rule_code": "multi_current_locations",
                        "title": f"角色地点冲突：{character_name}",
                        "details": f"{character_name} 在同一章内被标记为同时位于多个地点：{', '.join(sorted(locations))}。",
                        "character_name": character_name,
                    }
                )

        previous_location_result = await db.execute(
            select(ChapterContinuitySignal).where(
                ChapterContinuitySignal.project_id == project_id,
                ChapterContinuitySignal.chapter_number < chapter.chapter_number,
                ChapterContinuitySignal.signal_type == "location",
            )
        )
        previous_location_signals = previous_location_result.scalars().all()
        previous_location_signals.sort(key=lambda item: item.chapter_number or 0)
        last_known_location: dict[str, tuple[str, int]] = {}
        for item in previous_location_signals:
            character_name = self._normalize_name(item.character_name)
            location_name = (item.signal_key or "").strip()
            if not character_name or not location_name:
                continue
            if item.signal_value in {"current", "arrived"}:
                last_known_location[character_name] = (location_name, item.chapter_number or 0)
            elif item.signal_value == "left":
                last_known_location.pop(character_name, None)

        location_transition_flags: dict[str, set[str]] = defaultdict(set)
        for item in signals:
            if item["signal_type"] != "location":
                continue
            character_name = self._normalize_name(item.get("character_name"))
            if not character_name:
                continue
            location_transition_flags[character_name].add(item["signal_value"])

        for character_name, locations in location_by_character.items():
            if len(locations) != 1:
                continue
            previous_location = last_known_location.get(character_name)
            if not previous_location:
                continue
            current_location = next(iter(locations))
            previous_location_name, previous_chapter = previous_location
            if current_location == previous_location_name:
                continue
            if {"arrived", "left"} & location_transition_flags.get(character_name, set()):
                continue
            issues.append(
                {
                    "severity": "medium",
                    "issue_type": "location",
                    "rule_code": "location_changed_without_transition",
                    "title": f"地点切换缺少过渡：{character_name}",
                    "details": f"{character_name} 上一次在第 {previous_chapter} 章明确位于“{previous_location_name}”，本章直接出现在“{current_location}”，未检测到离开/抵达过渡信号。",
                    "character_name": character_name,
                    "signal_key": current_location,
                    "reference_chapter_number": previous_chapter,
                }
            )

        return issues

    def _extract_continuity_signals(self, analysis: dict[str, Any]) -> list[dict[str, Optional[str]]]:
        continuity = analysis.get("continuity_signals") or {}
        signals: list[dict[str, Optional[str]]] = []

        def append_signal(
            signal_type: str,
            character_name: Optional[str],
            signal_key: Optional[str],
            signal_value: Optional[str],
            evidence_text: Optional[str],
        ) -> None:
            normalized_value = (signal_value or "").strip().lower()
            if not normalized_value:
                return
            if signal_type == "life_state" and normalized_value not in self.LIFE_SIGNAL_VALUES:
                return
            if signal_type == "ability" and normalized_value not in self.ABILITY_SIGNAL_VALUES:
                return
            if signal_type == "location" and normalized_value not in self.LOCATION_SIGNAL_VALUES:
                return
            signals.append(
                {
                    "signal_type": signal_type,
                    "character_name": (character_name or "").strip() or None,
                    "signal_key": (signal_key or "").strip() or None,
                    "signal_value": normalized_value,
                    "evidence_text": (evidence_text or "").strip() or None,
                }
            )

        for item in continuity.get("life_state_changes", []) or []:
            append_signal(
                "life_state",
                item.get("character_name"),
                None,
                item.get("status"),
                item.get("evidence"),
            )

        for item in continuity.get("ability_updates", []) or []:
            append_signal(
                "ability",
                item.get("character_name"),
                item.get("ability_name"),
                item.get("change"),
                item.get("evidence"),
            )

        for item in continuity.get("location_updates", []) or []:
            append_signal(
                "location",
                item.get("character_name"),
                item.get("location"),
                item.get("status"),
                item.get("evidence"),
            )

        for item in analysis.get("timeline_events", []) or []:
            if (item.get("event_type") or "").strip().lower() == "death":
                names = item.get("target_names") or item.get("actor_names") or []
                for name in names:
                    append_signal("life_state", name, None, "dead", item.get("evidence") or item.get("description"))

        return signals

    def _collect_current_character_names(
        self,
        analysis: dict[str, Any],
        canonical_names: Optional[dict[str, str]] = None,
    ) -> set[str]:
        names: set[str] = set()

        def add(value: Any) -> None:
            name = self._canonical_name(value, canonical_names)
            if name:
                names.add(name)

        for item in analysis.get("character_states", []) or []:
            add(item.get("character_name"))

        for item in analysis.get("relationship_deltas", []) or []:
            for key in ("from_character_name", "to_character_name"):
                add(item.get(key))

        for item in analysis.get("timeline_events", []) or []:
            for key in ("actor_names", "target_names"):
                for raw_name in item.get(key, []) or []:
                    add(raw_name)

        for item in analysis.get("causal_links", []) or []:
            for key in ("actor_names", "target_names"):
                for raw_name in item.get(key, []) or []:
                    add(raw_name)

        for item in analysis.get("knowledge_changes", []) or []:
            add(item.get("character_name"))

        continuity = analysis.get("continuity_signals") or {}
        for item in continuity.get("life_state_changes", []) or []:
            if (item.get("status") or "").strip().lower() in {"dead", "missing"}:
                continue
            add(item.get("character_name"))

        return names

    def _collect_current_locations(
        self,
        analysis: dict[str, Any],
        signals: Iterable[dict[str, Optional[str]]],
    ) -> list[str]:
        locations: list[str] = []
        seen: set[str] = set()

        def add_location(value: Optional[str]) -> None:
            location = (value or "").strip()
            if location and location not in seen:
                seen.add(location)
                locations.append(location)

        for item in analysis.get("scenes", []) or []:
            add_location(item.get("location"))

        for item in analysis.get("timeline_events", []) or []:
            add_location(item.get("location"))

        for item in signals:
            if item["signal_type"] == "location" and item["signal_value"] in {"current", "arrived"}:
                add_location(item.get("signal_key"))

        return locations

    async def _load_outline_scene(self, db: AsyncSession, chapter: Chapter) -> Optional[str]:
        if not chapter.chapter_outline_id:
            return None
        result = await db.execute(
            select(ChapterOutline.scene).where(ChapterOutline.id == chapter.chapter_outline_id)
        )
        return result.scalar_one_or_none()

    async def _load_character_name_map(self, db: AsyncSession, project_id: str) -> dict[str, str]:
        result = await db.execute(select(Character).where(Character.project_id == project_id))
        return {item.id: item.name for item in result.scalars().all() if item.name}

    async def _load_canonical_names(self, db: AsyncSession, project_id: str) -> dict[str, str]:
        """{归一化键(正式名或曾用名): 正式名}，把 AI 沿用的旧名归到当前名。"""
        result = await db.execute(select(Character).where(Character.project_id == project_id))
        index = build_name_index(result.scalars().all(), key=self._normalize_key)
        return {key: character.name for key, character in index.items()}

    def _canonical_name(self, value: Any, canonical_names: Optional[dict[str, str]]) -> str:
        name = self._normalize_name(value)
        if not name or not canonical_names:
            return name
        return canonical_names.get(self._normalize_key(name), name)

    def _is_location_match(self, outline_scene: str, current_locations: Iterable[str]) -> bool:
        outline_tokens = self._location_tokens(outline_scene)
        if not outline_tokens:
            return True
        for location in current_locations:
            location_tokens = self._location_tokens(location)
            if outline_tokens & location_tokens:
                return True
            if self._normalize_key(outline_scene) in self._normalize_key(location) or self._normalize_key(location) in self._normalize_key(outline_scene):
                return True
        return False

    def _location_tokens(self, value: str) -> set[str]:
        normalized = re.sub(r"[→\-—/,，、\s]+", " ", value or "").strip()
        return {token for token in normalized.split(" ") if token}

    def _normalize_name(self, value: Any) -> str:
        return (value or "").strip()

    def _normalize_key(self, value: Any) -> str:
        return re.sub(r"\s+", "", (value or "").strip().lower())

    def _severity_weight(self, severity: Optional[str]) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get((severity or "").lower(), 0)

    def _ability_value_label(self, value: str) -> str:
        return {
            "lost": "失去",
            "forgotten": "忘记/不会使用",
        }.get(value, value)


chapter_consistency_service = ChapterConsistencyService()
