"""拆书 V5 S1：一批连续章节 → 拆书卡。

一次 LLM 调用产出整批卡；截断 / 非 JSON / 无 cards 字段视为整批失败（抛 ChapterCardExtractionError），
由编排器拆半重试；LLM 漏给的章不在返回值里，编排器组成子批补抽。
LLM 走流式累积（generate_text_stream_collect）：整批输出动辄上百秒，非流式请求会被中转网关的
100s 首字节上限掐断（Cloudflare 524 + HTML 错误页），每次拆半重试都再白等 100s。
跨批一致性靠两段注入：前批累计出场最多的角色名 + 前几张卡的章纲。
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Iterable, Sequence

from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.prompts_v5 import CARD_PROMPT, SYSTEM_CARD
from app.services.book_dissect.v5_types import ChapterCard
from app.utils.json_cleaner import safe_parse_json

logger = logging.getLogger(__name__)
_LOG = "[拆书V5-拆书卡]"


class ChapterCardExtractionError(Exception):
    """整批失败：LLM 报错 / 空内容 / 输出截断 / 非 JSON。"""


class ChapterCardExtractor:
    DEFAULT_TEMPERATURE = 0.2
    BOUNDARY = "=== 第 {n} 章 {title} ==="
    # 单章独占一批且超长时截头留尾（多章批由 batch_planner 保证在预算内）
    HEAD_CHARS = 6000
    TAIL_CHARS = 2500
    OMIT_MARK = "\n……（中间省略，只保留章首与章末）……\n"
    KNOWN_CHAR_TOP_N = 40
    PRIOR_OUTLINE_COUNT = 3
    PRIOR_OUTLINE_CHARS = 200

    def __init__(self, ai_service):
        self.ai_service = ai_service

    async def extract_batch(
        self,
        chapters: Sequence[Chapter],
        *,
        known_characters: Iterable[str] = (),
        prior_cards: Sequence[ChapterCard] = (),
    ) -> list[ChapterCard]:
        if not chapters:
            return []
        truncated: dict[int, bool] = {}
        full_text = self._build_full_text(chapters, truncated)
        prompt = CARD_PROMPT.format(
            known_characters_block=self._known_block(known_characters),
            prior_outlines_block=self._prior_block(prior_cards),
            count=len(chapters),
            full_text=full_text,
        )
        try:
            resp = await self.ai_service.generate_text_stream_collect(
                prompt=prompt, system_prompt=SYSTEM_CARD, temperature=self.DEFAULT_TEMPERATURE,
                context="拆书V5-拆书卡",
            )
        except Exception as exc:
            raise ChapterCardExtractionError(f"LLM 调用失败: {exc}") from exc
        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if not content:
            raise ChapterCardExtractionError("LLM 返回空内容")
        if isinstance(resp, dict) and resp.get("finish_reason") == "length":
            raise ChapterCardExtractionError(f"输出被 Max Tokens 截断（{len(chapters)} 章）")
        data = safe_parse_json(content, default=None, expected_type="object", log_prefix=_LOG)
        items = data.get("cards") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ChapterCardExtractionError("返回不是 {\"cards\": [...]} 结构")

        by_num = {ch.chapter_number: ch for ch in chapters}
        cards: list[ChapterCard] = []
        seen: set[int] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                num = int(str(item.get("chapter_number")).strip())
            except (TypeError, ValueError):
                continue
            ch = by_num.get(num)
            if ch is None or num in seen:
                continue
            seen.add(num)
            cards.append(ChapterCard.from_llm(
                item, chapter_number=num, title=ch.title or ch.raw_title or "",
                word_count=ch.word_count or len(ch.content or ""), truncated=truncated.get(num, False),
            ))
        cards.sort(key=lambda c: c.chapter_number)
        missing = [n for n in by_num if n not in seen]
        if missing:
            logger.warning("%s LLM 漏给 %d 章: %s", _LOG, len(missing), missing[:10])
        return cards

    @classmethod
    def build_known_characters(cls, cards: Sequence[ChapterCard]) -> list[str]:
        counter: Counter[str] = Counter()
        for card in cards:
            counter.update(name for name in card.characters if name)
        return [name for name, _ in counter.most_common(cls.KNOWN_CHAR_TOP_N)]

    # ---------------- 内部 ----------------

    def _build_full_text(self, chapters: Sequence[Chapter], truncated: dict[int, bool]) -> str:
        parts: list[str] = []
        single = len(chapters) == 1
        for ch in chapters:
            content = (ch.content or "").strip()
            if single and len(content) > self.HEAD_CHARS + self.TAIL_CHARS:
                content = content[: self.HEAD_CHARS] + self.OMIT_MARK + content[-self.TAIL_CHARS:]
                truncated[ch.chapter_number] = True
            parts.append(self.BOUNDARY.format(n=ch.chapter_number, title=ch.title or ch.raw_title or ""))
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    @staticmethod
    def _known_block(names: Iterable[str]) -> str:
        names = [n for n in names if n]
        return f"【已知角色（优先复用这些名字）】{'、'.join(names)}\n\n" if names else ""

    def _prior_block(self, prior_cards: Sequence[ChapterCard]) -> str:
        tail = [c for c in prior_cards if c.outline][-self.PRIOR_OUTLINE_COUNT:]
        if not tail:
            return ""
        lines = [f"第{c.chapter_number}章：{c.outline[: self.PRIOR_OUTLINE_CHARS]}" for c in tail]
        return "【前文章纲（承接用，不要重复写进本批）】\n" + "\n".join(lines) + "\n\n"
