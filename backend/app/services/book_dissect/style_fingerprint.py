"""拆书 V5 S4b：文风指纹 = 代码统计（外部传入）+ LLM 定性 + 逐字核验的例句库。

定性失败 → 整体 None；某章例句失败 / 伪造 → 跳过该章 / 该段，不影响其它。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from app.services.book_dissect._base_v3_generator import BaseV3Generator
from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.prompts_v5 import EXCERPT_PROMPT, STYLE_PROMPT, SYSTEM_STYLE
from app.services.book_dissect.style_stats import format_metrics_brief, pick_even_indices
from app.services.book_dissect.v5_types import ChapterCard

logger = logging.getLogger(__name__)
_WS = re.compile(r"\s+")
EXCERPT_KINDS = ("opening", "dialogue", "action", "payoff", "ending_hook", "description")


def _str_items(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(t).strip() for t in value if str(t).strip()][:limit]


class StyleFingerprintBuilder(BaseV3Generator):
    DEFAULT_TEMPERATURE = 0.4
    SAMPLE_CHAPTERS = 6
    SAMPLE_HEAD = 500
    SAMPLE_MID = 500
    EXCERPT_MIN = 120
    EXCERPT_MAX = 320
    EXCERPT_CHAPTER_CHARS = 9000
    MAX_EXAMPLES = 8

    def __init__(self, ai_service):
        self.ai_service = ai_service

    async def build(self, chapters: Sequence[Chapter], cards: Sequence[ChapterCard], metrics: dict[str, Any]) -> Optional[dict[str, Any]]:
        qual = await self._qualitative(chapters, metrics)
        if qual is None:
            return None
        examples = await self._excerpts(chapters, cards)
        return {**qual, "metrics": metrics or {}, "examples": examples, "pipeline_version": 5}

    # ---------------- 定性 ----------------

    async def _qualitative(self, chapters: Sequence[Chapter], metrics: dict[str, Any]) -> Optional[dict[str, Any]]:
        ordered = sorted(chapters, key=lambda c: c.chapter_number)
        picked = [ordered[i] for i in pick_even_indices(len(ordered), self.SAMPLE_CHAPTERS)]
        samples = []
        for ch in picked:
            text = (ch.content or "").strip()
            mid = max(0, len(text) // 2 - self.SAMPLE_MID // 2)
            samples.append(
                f"【第{ch.chapter_number}章 开头】\n{text[: self.SAMPLE_HEAD]}\n"
                f"【第{ch.chapter_number}章 中段】\n{text[mid: mid + self.SAMPLE_MID]}"
            )
        data = await self._call_and_parse_object(
            prompt=STYLE_PROMPT.format(metrics_brief=format_metrics_brief(metrics), samples="\n\n".join(samples) or "（无）"),
            system_prompt=SYSTEM_STYLE, temperature=self.DEFAULT_TEMPERATURE,
            label="[拆书V5-文风]", schema_hint="name, description, prompt_content, traits, dialogue_style, narration_habits, avoid_list",
        )
        if not isinstance(data, dict) or not str(data.get("prompt_content") or "").strip():
            return None
        return {
            "name": str(data.get("name") or "未命名文风").strip()[:20],
            "description": str(data.get("description") or "").strip()[:200],
            "prompt_content": str(data["prompt_content"]).strip()[:1500],
            "traits": _str_items(data.get("traits"), 8),
            "dialogue_style": str(data.get("dialogue_style") or "").strip()[:300],
            "narration_habits": str(data.get("narration_habits") or "").strip()[:300],
            "avoid_list": _str_items(data.get("avoid_list"), 5),
        }

    # ---------------- 例句 ----------------

    def _pick_excerpt_chapters(self, cards: Sequence[ChapterCard], available: set[int]) -> list[tuple[str, int]]:
        """选 3 章：爽点章（张力最高）/ 代入章 / 钩子章，去重保序。"""
        usable = [c for c in cards if c.chapter_number in available]
        if not usable:
            return []
        picks: list[tuple[str, int]] = []
        with_payoff = [c for c in usable if c.payoff_points]
        if with_payoff:
            picks.append(("爽点 / 兑现章（优先摘 payoff、dialogue）", max(with_payoff, key=lambda c: c.tension).chapter_number))
        intro = [c for c in usable if {"日常代入", "开局立足"} & set(c.function_tags)]
        picks.append(("代入 / 日常章（优先摘 opening、description）", (intro[0] if intro else usable[0]).chapter_number))
        hooked = [c for c in usable if c.ending_hook_type in ("悬念", "危机", "反转")]
        if hooked:
            picks.append(("章末钩子章（优先摘 ending_hook、action）", max(hooked, key=lambda c: c.tension).chapter_number))
        seen: set[int] = set()
        out: list[tuple[str, int]] = []
        for kind, num in picks:
            if num not in seen:
                seen.add(num)
                out.append((kind, num))
        return out

    async def _excerpts(self, chapters: Sequence[Chapter], cards: Sequence[ChapterCard]) -> list[dict[str, Any]]:
        by_num = {c.chapter_number: c for c in chapters}
        out: list[dict[str, Any]] = []
        for kind_hint, num in self._pick_excerpt_chapters(cards, set(by_num)):
            text = (by_num[num].content or "").strip()[: self.EXCERPT_CHAPTER_CHARS]
            data = await self._call_and_parse_object(
                prompt=EXCERPT_PROMPT.format(kind_hint=kind_hint, chapter_number=num, chapter_text=text),
                system_prompt=SYSTEM_STYLE, temperature=0.1, label="[拆书V5-例句]", schema_hint="excerpts",
            )
            items = data.get("excerpts") if isinstance(data, dict) else None
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                excerpt = str(item.get("text") or "").strip()
                if not (self.EXCERPT_MIN <= len(excerpt) <= self.EXCERPT_MAX) or not self.is_verbatim(excerpt, text):
                    logger.info("[拆书V5-例句] 第%d章片段不在原文或长度不合规，丢弃", num)
                    continue
                kind = str(item.get("kind") or "").strip()
                out.append({"kind": kind if kind in EXCERPT_KINDS else "description", "chapter": num, "text": excerpt})
                if len(out) >= self.MAX_EXAMPLES:
                    return out
        return out

    @staticmethod
    def is_verbatim(excerpt: str, source: str) -> bool:
        return _WS.sub("", excerpt) in _WS.sub("", source)
