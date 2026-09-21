"""拆书 V5 S2：滚动窗口喂拆书卡（不喂正文），识别自然闭合的情节单元。

- 窗口从第一张未消费的卡开始取 window_new 张（由 batch_planner.plan_arc_window 按模型上下文 / Max Tokens 规划，
  大模型一轮几十张；未闭合的尾部自然留在下一窗口开头）；单元 ≤ max_arc_len 章
- 连续性按「窗口内位置」判定（采样模式章号不连续也能用）：必须从窗口首卡开始、首尾相接
- 失败（LLM 异常 / 输出截断 / 未接受任何单元）：
  - 大窗口（> max_arc_len）：多半是输出过长被截断或 JSON 坏掉，窗口减半重试（下限 max_arc_len），不硬凑兜底
  - 小窗口、非最终：模型说尚未闭合 → 扩窗继续（最多扩到 max_arc_len）
  - 小窗口已到 max_arc_len 或最终窗口：规则兜底切一段
- 成功一轮后窗口恢复为 window_new；单轮失败不中断全书
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, Sequence

from app.services.book_dissect.prompts_v5 import ARC_PROMPT, SYSTEM_ARC
from app.services.book_dissect.v5_types import ChapterCard, StoryArc, normalize_chapter_roles
from app.utils.json_cleaner import safe_parse_json

logger = logging.getLogger(__name__)
_LOG = "[拆书V5-情节单元]"

OnWindow = Callable[[int, int, int], None]


class StoryArcBuilder:
    DEFAULT_TEMPERATURE = 0.2
    CARD_OUTLINE_CHARS = 400
    CARD_HOOK_CHARS = 40

    def __init__(self, ai_service, *, window_new: int = 8, max_arc_len: int = 12):
        self.ai_service = ai_service
        self.window_new = max(1, window_new)
        self.max_arc_len = max(2, max_arc_len)

    async def build(self, cards: Sequence[ChapterCard], on_window: Optional[OnWindow] = None) -> list[StoryArc]:
        ordered = sorted((c for c in cards if c.has_content()), key=lambda c: c.chapter_number)
        arcs: list[StoryArc] = []
        pos = 0
        size = self.window_new
        while pos < len(ordered):
            window = ordered[pos: pos + size]
            is_final = pos + len(window) >= len(ordered)
            accepted = self._accept(await self._ask(window, is_final), window)
            if not accepted:
                if len(window) > self.max_arc_len:
                    size = max(self.max_arc_len, len(window) // 2)
                    logger.info("%s 窗口 %d-%d（%d 张）未识别出单元，减半到 %d 张重试",
                                _LOG, window[0].chapter_number, window[-1].chapter_number, len(window), size)
                    continue
                if not is_final and len(window) < self.max_arc_len:
                    size = min(self.max_arc_len, len(window) + self.window_new)
                    continue
                accepted = [self._fallback(window[: self.max_arc_len])]
            for arc in accepted:
                arc.arc_index = len(arcs) + 1
                arcs.append(arc)
            consumed_end = accepted[-1].end_chapter
            pos += next(i for i, c in enumerate(window) if c.chapter_number == consumed_end) + 1
            size = self.window_new
            if on_window:
                on_window(len(arcs), window[0].chapter_number, window[-1].chapter_number)
        return arcs

    # ---------------- LLM ----------------

    async def _ask(self, window: list[ChapterCard], is_final: bool) -> Optional[dict[str, Any]]:
        prompt = ARC_PROMPT.format(
            start=window[0].chapter_number, end=window[-1].chapter_number,
            max_len=self.max_arc_len, is_final="是" if is_final else "否",
            cards_json=json.dumps([self._compact(c) for c in window], ensure_ascii=False),
        )
        try:
            resp = await self.ai_service.generate_text_stream_collect(
                prompt=prompt, system_prompt=SYSTEM_ARC, temperature=self.DEFAULT_TEMPERATURE,
                context="拆书V5-情节单元",
            )
        except Exception as exc:
            logger.warning("%s 窗口 %d-%d LLM 失败: %s", _LOG, window[0].chapter_number, window[-1].chapter_number, exc)
            return None
        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if isinstance(resp, dict) and resp.get("finish_reason") == "length":
            logger.warning("%s 窗口 %d-%d（%d 张）输出被 Max Tokens 截断", _LOG,
                           window[0].chapter_number, window[-1].chapter_number, len(window))
            return None
        if not content:
            return None
        data = safe_parse_json(content, default=None, expected_type="object", log_prefix=_LOG)
        return data if isinstance(data, dict) else None

    def _compact(self, c: ChapterCard) -> dict[str, Any]:
        return {
            "chapter_number": c.chapter_number, "title": c.title,
            "outline": c.outline[: self.CARD_OUTLINE_CHARS],
            "function_tags": c.function_tags, "pace": c.pace, "tension": c.tension,
            "ending_hook_type": c.ending_hook_type, "ending_hook_text": c.ending_hook_text[: self.CARD_HOOK_CHARS],
            "payoff_points": c.payoff_points, "protagonist_delta": c.protagonist_delta,
        }

    # ---------------- 校验 / 兜底 ----------------

    def _accept(self, payload: Optional[dict[str, Any]], window: list[ChapterCard]) -> list[StoryArc]:
        items = (payload or {}).get("completed_arcs")
        if not isinstance(items, list):
            return []
        pos = {c.chapter_number: i for i, c in enumerate(window)}
        expected = 0
        out: list[StoryArc] = []
        for item in items:
            if not isinstance(item, dict):
                break
            try:
                s, e = int(item.get("start_chapter")), int(item.get("end_chapter"))
            except (TypeError, ValueError):
                break
            si, ei = pos.get(s), pos.get(e)
            if si is None or ei is None or si != expected or ei < si or ei - si + 1 > self.max_arc_len:
                break
            chapters = [window[i].chapter_number for i in range(si, ei + 1)]
            out.append(StoryArc.from_llm(item, chapters=chapters))
            expected = ei + 1
        return out

    @staticmethod
    def _fallback(window: list[ChapterCard]) -> StoryArc:
        chapters = [c.chapter_number for c in window]
        peak = max(window, key=lambda c: c.tension).chapter_number
        payoffs = [p for c in window for p in c.payoff_points]
        return StoryArc(
            start_chapter=chapters[0], end_chapter=chapters[-1],
            title=f"第{chapters[0]}-{chapters[-1]}章过渡情节",
            function="阶段推进（规则兜底：模型未识别出自然边界）",
            boundary_reason="窗口达到上限或范围结束，按拆书卡兜底收束",
            structure="；".join(f"第{c.chapter_number}章 {c.outline[:120]}" for c in window),
            protagonist_chain=" -> ".join(c.protagonist_delta for c in window if c.protagonist_delta != "无"),
            emotion_curve=" -> ".join(c.emotion_tone for c in window if c.emotion_tone),
            payoff="；".join(payoffs) if payoffs else "无强爽点，主要承担推进 / 铺垫功能",
            payoff_type="无强爽点",
            chapter_roles=normalize_chapter_roles({}, chapters, peak),
            tension_peak_chapter=peak,
            origin="fallback",
        )
