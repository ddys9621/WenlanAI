"""拆书 V5 S1：一批连续章节 → 拆书卡。

一次 LLM 调用产出整批卡。失败一律抛 ChapterCardExtractionError，kind 标明性质，编排器据此重试 / 拆半 / 中止：
- 调模型出错：按 failure_policy.classify_llm_error 分类（fatal / rate_limited / network / context_overflow / rejected / truncated / unknown）
- truncated：finish_reason=length，或靠修补才解析出来、上游又没说正常结束、还缺结尾哨兵 end（网关不回 finish_reason 时
  json-repair 会把半截 JSON 补全，最后一张卡只剩半截章纲）。partial 带上前面完整的卡（最后一张可能被截断，丢掉），
  编排器只补抽剩下的章，不再整批拆半重来
- bad_output：空内容 / 非 JSON / 没有 cards 字段
LLM 漏给的章不在返回值里，编排器组成子批补抽。单章一批时模型常把章号照抄模板里的 12：唯一一张卡直接认成这一章。
LLM 走流式累积（generate_text_stream_collect）：整批输出动辄上百秒，非流式请求会被中转网关的
100s 首字节上限掐断（Cloudflare 524 + HTML 错误页），每次拆半重试都再白等 100s。
跨批一致性靠两段注入：前批累计出场最多的角色名 + 前几张卡的章纲。
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Iterable, Optional, Sequence

from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.failure_policy import classify_llm_error
from app.services.book_dissect.prompts_v5 import CARD_COMPACT_NOTE, CARD_PROMPT, SYSTEM_CARD
from app.services.book_dissect.v5_types import ChapterCard
from app.services.chapter_analysis_schema import parse_model_json
from app.utils.json_cleaner import safe_parse_json

logger = logging.getLogger(__name__)
_LOG = "[拆书V5-拆书卡]"


class ChapterCardExtractionError(Exception):
    """整批失败（消息会原样显示在拆书表里，写人话）。kind 见模块说明；reason 是不带「调用模型失败」前缀的原因；
    partial 是截断时前面完整的卡；retry_after 是限流时接口给的等待秒数。"""

    def __init__(self, message: str, *, kind: str = "bad_output", partial: Sequence[ChapterCard] = (),
                 retry_after: Optional[float] = None, reason: Optional[str] = None):
        super().__init__(message)
        self.kind = kind
        self.reason = reason or message
        self.partial = list(partial)
        self.retry_after = retry_after


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
        compact: bool = False,
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
        ) + (CARD_COMPACT_NOTE if compact else "")
        try:
            resp = await self.ai_service.generate_text_stream_collect(
                prompt=prompt, system_prompt=SYSTEM_CARD, temperature=self.DEFAULT_TEMPERATURE,
                context="拆书V5-拆书卡",
            )
        except Exception as exc:
            failure = classify_llm_error(exc)
            raise ChapterCardExtractionError(
                f"调用模型失败：{failure.reason}", kind=failure.kind, retry_after=failure.retry_after, reason=failure.reason,
            ) from exc
        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if not content:
            raise ChapterCardExtractionError("模型返回了空内容")
        finish_reason = resp.get("finish_reason") if isinstance(resp, dict) else None
        data, repaired = parse_model_json(content)
        if data is None:
            data = safe_parse_json(content, default=None, expected_type="object", log_prefix=_LOG)
            repaired = True
        items = data.get("cards") if isinstance(data, dict) else None
        if not isinstance(items, list):
            if finish_reason == "length":
                raise ChapterCardExtractionError(f"输出被 Max Tokens 截断（{len(chapters)} 章一批）", kind="truncated")
            raise ChapterCardExtractionError("模型返回的不是要求的 JSON 格式")

        cards, last_item_used = self._cards_from_items(items, chapters, truncated)
        cut = data.get("end") is not True and (finish_reason == "length" or (repaired and finish_reason != "stop"))
        if cut:
            partial = sorted(cards[:-1] if last_item_used else cards, key=lambda c: c.chapter_number)
            raise ChapterCardExtractionError(
                f"输出被截断（{len(chapters)} 章只完整拿到 {len(partial)} 张卡）", kind="truncated", partial=partial,
            )
        cards.sort(key=lambda c: c.chapter_number)
        got = {c.chapter_number for c in cards}
        missing = [ch.chapter_number for ch in chapters if ch.chapter_number not in got]
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

    @staticmethod
    def _cards_from_items(
        items: list[Any], chapters: Sequence[Chapter], truncated: dict[int, bool],
    ) -> tuple[list[ChapterCard], bool]:
        """按模型输出顺序转成卡，并返回最后一项是否成了卡（截断时只有它可能是半截的）。单章一批且只有一张卡时不认章号。"""
        lenient = len(chapters) == 1 and sum(isinstance(item, dict) for item in items) == 1
        by_num = {ch.chapter_number: ch for ch in chapters}
        cards: list[ChapterCard] = []
        seen: set[int] = set()
        last_used = False
        for item in items:
            last_used = False
            if not isinstance(item, dict):
                continue
            if lenient:
                item = {**item, "chapter_number": chapters[0].chapter_number}
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
            last_used = True
        return cards, last_used

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
