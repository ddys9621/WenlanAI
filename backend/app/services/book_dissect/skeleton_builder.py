"""拆书 S3：剧情单元 → 分卷（对齐卷纲）→ 全书骨架（对齐总纲）；人物功能谱；写法手册。四步各自独立失败（返回 None）。"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Optional, Sequence

from app.services.book_dissect._base_v3_generator import BaseV3Generator
from app.services.book_dissect.dissect_stats import format_stats_brief
from app.services.book_dissect.prompts_v5 import (
    CHARACTERS_PROMPT, METHODOLOGY_PROMPT, SKELETON_PROMPT, SYSTEM_SKELETON, VOLUME_PROMPT,
)
from app.services.book_dissect.v5_types import ChapterCard, StoryArc

logger = logging.getLogger(__name__)

METHODOLOGY_KEYS = ("opening_pattern", "volume_rhythm", "unit_design", "tension_rhythm",
                    "growth_progression", "advantage_usage")
VOLUME_KEYS = ("title", "summary", "goal", "climax", "ending_hook", "growth")
SKELETON_KEYS = (
    "genre_tag", "premise", "main_plot", "main_conflict", "golden_finger", "selling_points", "main_tropes",
    "growth_route", "power_system", "ultimate_goal", "high_points", "long_foreshadowing", "opening_strategy",
)
_LIST_LIMITS = {"selling_points": 5, "main_tropes": 6, "high_points": 5, "long_foreshadowing": 8}


def fallback_volumes(arcs: Sequence[StoryArc], per_volume: int = 10) -> list[dict[str, Any]]:
    """规则兜底：每 per_volume 个单元一卷。"""
    out = []
    for i in range(0, len(arcs), per_volume):
        chunk = arcs[i: i + per_volume]
        out.append(_volume_dict({"title": f"第{chunk[0].start_chapter}-{chunk[-1].end_chapter}章"},
                                chunk[0].arc_index, chunk[-1].arc_index, arcs, origin="fallback"))
    return out


def _volume_dict(raw: dict[str, Any], arc_start: int, arc_end: int, arcs: Sequence[StoryArc], *, origin: str = "llm") -> dict[str, Any]:
    by_idx = {a.arc_index: a for a in arcs}
    threads = raw.get("threads")
    return {
        **{k: str(raw.get(k) or "").strip()[:600] for k in VOLUME_KEYS},
        "threads": [str(t).strip()[:120] for t in threads if str(t).strip()][:6] if isinstance(threads, list) else [],
        "arc_start": arc_start, "arc_end": arc_end,
        "chapter_start": by_idx[arc_start].start_chapter, "chapter_end": by_idx[arc_end].end_chapter,
        "status": "closed", "origin": origin,
    }


class SkeletonBuilder(BaseV3Generator):
    DEFAULT_TEMPERATURE = 0.3
    VOLUME_CHUNK = 40

    def __init__(self, ai_service):
        self.ai_service = ai_service

    # ---------------- 分卷 ----------------

    async def build_volumes(self, arcs: Sequence[StoryArc]) -> list[dict[str, Any]]:
        """每 VOLUME_CHUNK 个单元一次 LLM；上一块未闭合（open）的卷带到下一块继续，由本块第一卷替换。"""
        arcs = sorted(arcs, key=lambda a: a.arc_index)
        if not arcs:
            return []
        volumes: list[dict[str, Any]] = []
        open_volume: Optional[dict[str, Any]] = None
        for start in range(0, len(arcs), self.VOLUME_CHUNK):
            chunk = arcs[start: start + self.VOLUME_CHUNK]
            is_final = start + self.VOLUME_CHUNK >= len(arcs)
            first_idx = open_volume["arc_start"] if open_volume else chunk[0].arc_index
            prompt = VOLUME_PROMPT.format(
                first=chunk[0].arc_index, last=chunk[-1].arc_index, total=len(arcs),
                is_final_note="这是最终块" if is_final else "后面还有更多单元",
                open_volume_block=(
                    "【上一块未闭合的卷】本块第一卷必须是它的延续：沿用 title，arc_start 保持 "
                    f"{open_volume['arc_start']}，只更新 arc_end 与其它字段。\n{json.dumps(open_volume, ensure_ascii=False)}\n"
                    if open_volume else ""
                ),
                arc_lines="\n".join(self._arc_line(a) for a in chunk),
            )
            data = await self._call_and_parse_object(
                prompt=prompt, system_prompt=SYSTEM_SKELETON, temperature=self.DEFAULT_TEMPERATURE,
                label="[拆书-分卷]", schema_hint="volumes",
            )
            accepted = self._accept_volumes(data, first_idx, chunk[-1].arc_index, arcs, is_final)
            if not accepted:
                accepted = [_volume_dict(
                    {"title": f"第{arcs[first_idx - 1].start_chapter}-{chunk[-1].end_chapter}章"},
                    first_idx, chunk[-1].arc_index, arcs, origin="fallback",
                )]
            if open_volume:
                volumes = volumes[:-1]                    # 用本块第一卷替换上一块的 open 卷
            open_volume = accepted[-1] if not is_final and accepted[-1].get("status") == "open" else None
            volumes.extend(accepted)
        for v in volumes:
            v["status"] = "closed"
        return volumes

    @staticmethod
    def _arc_line(a: StoryArc) -> str:
        return (f"#{a.arc_index} 第{a.start_chapter}-{a.end_chapter}章｜{a.title}｜作用:{a.function[:40]}"
                f"｜结束时:{a.turn[:60]}｜兑现:{a.payoff_type}｜收获:{a.gains_costs[:60]}")

    def _accept_volumes(self, data: Any, first_idx: int, last_idx: int, arcs: Sequence[StoryArc], is_final: bool) -> list[dict[str, Any]]:
        """卷必须从 first_idx 起首尾相接覆盖到 last_idx，任一处不合法整块作废（走兜底）。"""
        items = data.get("volumes") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return []
        expected = first_idx
        out: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return []
            try:
                s, e = int(item.get("arc_start")), int(item.get("arc_end"))
            except (TypeError, ValueError):
                return []
            if s != expected or e < s or e > last_idx:
                return []
            volume = _volume_dict(item, s, e, arcs)
            if not is_final and i == len(items) - 1 and str(item.get("status", "")).lower() == "open":
                volume["status"] = "open"
            out.append(volume)
            expected = e + 1
        return out if expected == last_idx + 1 else []

    # ---------------- 全书骨架 ----------------

    async def build_skeleton(self, volumes: list[dict[str, Any]], cards: Sequence[ChapterCard], stats: dict[str, Any]) -> Optional[dict[str, Any]]:
        data = await self._call_and_parse_object(
            prompt=SKELETON_PROMPT.format(
                volumes_json=json.dumps(volumes, ensure_ascii=False),
                stats_brief=format_stats_brief(stats),
                opening_cards=self._opening_cards(cards),
            ),
            system_prompt=SYSTEM_SKELETON, temperature=self.DEFAULT_TEMPERATURE,
            label="[拆书-骨架]", schema_hint="genre_tag, premise, main_plot, main_conflict, golden_finger, volumes",
        )
        if not isinstance(data, dict):
            return None
        out = {k: data.get(k) for k in SKELETON_KEYS}
        for key, limit in _LIST_LIMITS.items():
            out[key] = out[key][:limit] if isinstance(out[key], list) else []
        llm_volumes = data.get("volumes")
        out["volumes"] = llm_volumes if isinstance(llm_volumes, list) and llm_volumes else volumes
        out["pipeline_version"] = 5
        return out

    # ---------------- 人物功能谱 ----------------

    async def build_character_functions(self, volumes: list[dict[str, Any]], arcs: Sequence[StoryArc], cards: Sequence[ChapterCard]) -> Optional[dict[str, Any]]:
        freq: dict[str, list[int]] = defaultdict(list)
        for c in cards:
            for name in c.characters:
                freq[name].append(c.chapter_number)
        top = sorted(freq.items(), key=lambda kv: -len(kv[1]))[:30]
        data = await self._call_and_parse_object(
            prompt=CHARACTERS_PROMPT.format(
                volumes_json=json.dumps(
                    [{k: v.get(k) for k in ("title", "chapter_start", "chapter_end", "goal")} for v in volumes],
                    ensure_ascii=False,
                ),
                character_freq="\n".join(f"{n}｜{len(chs)}｜{min(chs)}-{max(chs)}" for n, chs in top) or "（无）",
                arc_changes="\n".join(
                    f"#{a.arc_index} 第{a.start_chapter}-{a.end_chapter}章：{a.character_changes[:160]}"
                    for a in arcs if a.character_changes
                ) or "（无）",
            ),
            system_prompt=SYSTEM_SKELETON, temperature=self.DEFAULT_TEMPERATURE,
            label="[拆书-人物]", schema_hint="protagonist, allies, antagonists, function_slots",
        )
        if not isinstance(data, dict) or not isinstance(data.get("protagonist"), dict):
            return None
        return {
            "protagonist": data["protagonist"],
            "allies": data.get("allies") if isinstance(data.get("allies"), list) else [],
            "antagonists": data.get("antagonists") if isinstance(data.get("antagonists"), list) else [],
            "function_slots": data.get("function_slots") if isinstance(data.get("function_slots"), list) else [],
            "pipeline_version": 5,
        }

    # ---------------- 写法手册 ----------------

    async def build_methodology(self, skeleton: dict[str, Any], stats: dict[str, Any], cards: Sequence[ChapterCard]) -> Optional[dict[str, Any]]:
        slim = {k: skeleton.get(k) for k in (
            "genre_tag", "premise", "main_plot", "main_conflict", "golden_finger", "growth_route",
            "selling_points", "high_points", "opening_strategy",
        )}
        slim["volumes"] = [{k: v.get(k) for k in ("title", "chapter_start", "chapter_end", "goal", "climax")}
                           for v in (skeleton.get("volumes") or []) if isinstance(v, dict)]
        data = await self._call_and_parse_object(
            prompt=METHODOLOGY_PROMPT.format(
                skeleton_json=json.dumps(slim, ensure_ascii=False),
                stats_brief=format_stats_brief(stats),
                opening_cards=self._opening_cards(cards),
            ),
            system_prompt=SYSTEM_SKELETON, temperature=self.DEFAULT_TEMPERATURE,
            label="[拆书-手册]", schema_hint=", ".join(METHODOLOGY_KEYS),
        )
        if not isinstance(data, dict):
            return None
        out = {k: (data.get(k) if isinstance(data.get(k), dict) else None) for k in METHODOLOGY_KEYS}
        return out if any(out.values()) else None

    @staticmethod
    def _opening_cards(cards: Sequence[ChapterCard]) -> str:
        first = sorted(cards, key=lambda c: c.chapter_number)[:3]
        return "\n".join(
            f"第{c.chapter_number}章｜{c.title}｜钩子[{c.ending_hook_type}]{c.ending_hook_text}｜标签{c.function_tags}\n{c.outline}"
            for c in first
        ) or "（无）"
