"""拆书 V3.1: 长上下文多章抽取器

把一批连续章节（可以是整本书，也可以是分批规划出的若干章）一次塞给 LLM，
返回 list[ChapterFact]。
与 ChapterFactExtractor（逐章版）的关键差异：
- 1 次 LLM 调用产出整批 ChapterFact 数组，LLM 自己在批内做共指
- 可选注入全书字典 / 前批摘要，保证跨批规范名一致（整本一次时两者为空）
- finish_reason=length 视为整批失败（截断的 JSON 会静默丢章），交上层拆半重试

设计文档：agent-docs/features/book_dissect_v31_quality_optimization.md §4

业界证据：
- NovelHopQA 2025：完整上下文 + 强模型 EM>95%
- LaRA ICML 2025：32k 内长上下文 ≥ RAG，128k 持平

批大小由 batch_planner.plan_batches 决定，调用方需保证单批在模型预算内。
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.book_dissect.chapter_fact_extractor import (
    ChapterFactExtractor,
    _get_str,
    _parse_characters,
    _parse_concepts,
    _parse_events,
    _parse_items,
    _parse_locations,
    _parse_orgs,
    _parse_relationships,
)
from app.services.book_dissect.chapter_splitter import Chapter
from app.services.book_dissect.prompts import (
    LONG_CONTEXT_EXTRACT_PROMPT,
    SYSTEM_PROMPT_V31_LONG_CONTEXT,
)
from app.services.book_dissect.v2_types import ChapterFact, DictionaryEntry
from app.utils.json_cleaner import safe_parse_json

logger = logging.getLogger(__name__)


class LongContextExtractionError(Exception):
    """长上下文抽取彻底失败（LLM 调用 / JSON 解析 / 输出截断）。"""


class LongContextExtractor:
    """一批章节一次性抽取 ChapterFact 列表。"""

    DEFAULT_TEMPERATURE = 0.1

    # 章节边界标记，与 prompt 中的 "=== 第 N 章 标题 ===" 对齐
    BOUNDARY_TEMPLATE = "=== 第 {n} 章 {title} ==="

    def __init__(self, ai_service):
        """
        Args:
            ai_service: app.services.ai_service.AIService 实例
        """
        self.ai_service = ai_service

    async def extract_all(
        self,
        chapters: list[Chapter],
        dictionary: Optional[list[DictionaryEntry]] = None,
        prior_summary: Optional[str] = None,
    ) -> list[ChapterFact]:
        """主入口：一次 LLM 调用产出整批 ChapterFact。

        Args:
            chapters: 章节列表（必须非空，且预先经 batch_planner 规划在预算内）
            dictionary: 全书实体字典（分批模式注入 top N 规范名；整本一次可不传）
            prior_summary: 前批章节摘要（分批模式注入；第一批 / 整本一次为空）

        Returns:
            list[ChapterFact]，按 chapter_number 升序，长度 = len(chapters)
            漏给的章节用空 ChapterFact 填充

        Raises:
            LongContextExtractionError: LLM 调用失败 / 返回非 JSON / 输出被截断等彻底失败
        """
        if not chapters:
            return []

        full_text = self._build_full_text(chapters)
        user_prompt = LONG_CONTEXT_EXTRACT_PROMPT.format(
            prior_context=self._build_prior_context(prior_summary),
            dictionary_context=self._build_dictionary_context(dictionary),
            full_text=full_text,
        )

        try:
            resp = await self.ai_service.generate_text(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT_V31_LONG_CONTEXT,
                temperature=self.DEFAULT_TEMPERATURE,
            )
        except Exception as exc:
            logger.error("[拆书V3.1-长上下文] LLM 调用失败: %s", exc)
            raise LongContextExtractionError(
                f"long-context LLM call failed: {exc}"
            ) from exc

        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if not content:
            logger.warning("[拆书V3.1-长上下文] LLM 返回空内容")
            raise LongContextExtractionError("long-context LLM returned empty content")

        # 输出被 Max Tokens 截断：json_repair 能补全括号但后半批章节已丢，
        # 静默接受会让这些章记成 failed；抛错让上层拆半重试更划算
        finish_reason = resp.get("finish_reason") if isinstance(resp, dict) else None
        if finish_reason == "length":
            logger.warning(
                "[拆书V3.1-长上下文] 输出被截断（finish_reason=length，%d 章 / %d 字符）",
                len(chapters), len(content),
            )
            raise LongContextExtractionError(
                f"long-context output truncated by max_tokens ({len(chapters)} chapters)"
            )

        return self._parse_response(content, chapters)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prior_context(prior_summary: Optional[str]) -> str:
        return f"【前文已发生情节摘要】\n{prior_summary}" if prior_summary else ""

    @staticmethod
    def _build_dictionary_context(dictionary: Optional[list[DictionaryEntry]]) -> str:
        lines = []
        for entry in (dictionary or [])[: ChapterFactExtractor.DICTIONARY_TOP_N]:
            if entry.entity_type in ("rejected", "unknown"):
                continue
            alias_part = f" (别名：{', '.join(entry.aliases)})" if entry.aliases else ""
            lines.append(f"- {entry.name} [{entry.entity_type}]{alias_part}")
        return "【全书已知实体（请优先复用这些规范名）】\n" + "\n".join(lines) if lines else ""

    def _build_full_text(self, chapters: list[Chapter]) -> str:
        """用边界标记拼接所有章节正文。"""
        parts: list[str] = []
        for ch in chapters:
            title = ch.title or ch.raw_title or ""
            boundary = self.BOUNDARY_TEMPLATE.format(n=ch.chapter_number, title=title)
            content = (ch.content or "").strip()
            parts.append(boundary)
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def _parse_response(
        self,
        raw_text: str,
        input_chapters: list[Chapter],
    ) -> list[ChapterFact]:
        """解析 LLM 输出为 ChapterFact 列表。漏给的章节用空 ChapterFact 填补。"""
        result = safe_parse_json(
            raw_text,
            default=None,
            expected_type="object",
            log_prefix="[拆书V3.1-长上下文]",
        )
        if not isinstance(result, dict):
            logger.warning("[拆书V3.1-长上下文] JSON 解析非 object")
            raise LongContextExtractionError("long-context response not a JSON object")

        items = result.get("chapters")
        if not isinstance(items, list):
            logger.warning("[拆书V3.1-长上下文] chapters 字段非 list")
            raise LongContextExtractionError("long-context response missing 'chapters' list")

        # 按 chapter_number 索引：LLM 给的章节
        by_num: dict[int, ChapterFact] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            num_raw = item.get("chapter_number")
            try:
                num = int(num_raw)
            except (TypeError, ValueError):
                logger.debug(
                    "[拆书V3.1-长上下文] 跳过 chapter_number 非整数: %r", num_raw
                )
                continue

            fact = ChapterFact(
                chapter_number=num,
                chapter_title=_get_str(item, "chapter_title"),
                summary=_get_str(item, "summary"),
                characters=_parse_characters(item.get("characters")),
                relationships=_parse_relationships(item.get("relationships")),
                locations=_parse_locations(item.get("locations")),
                events=_parse_events(item.get("events")),
                item_events=_parse_items(item.get("item_events")),
                org_events=_parse_orgs(item.get("org_events")),
                new_concepts=_parse_concepts(item.get("new_concepts")),
            )
            by_num[num] = fact

        # 按输入章节顺序产出，漏给的用空 ChapterFact 填补
        out: list[ChapterFact] = []
        missing: list[int] = []
        for ch in input_chapters:
            f = by_num.get(ch.chapter_number)
            if f is None:
                # LLM 漏给：用空 ChapterFact 占位（保留 chapter_title 便于后续审查）
                out.append(ChapterFact(
                    chapter_number=ch.chapter_number,
                    chapter_title=ch.title or ch.raw_title or "",
                ))
                missing.append(ch.chapter_number)
                continue
            # LLM 给了但 chapter_title 可能空，从输入兜底
            if not f.chapter_title:
                f.chapter_title = ch.title or ch.raw_title or ""
            out.append(f)

        # 排序：按 chapter_number 升序（防 LLM 乱序）
        out.sort(key=lambda f: f.chapter_number)

        if missing:
            logger.warning(
                "[拆书V3.1-长上下文] LLM 漏给 %d 章，使用空 ChapterFact 占位: %s",
                len(missing),
                missing[:10] + (["..."] if len(missing) > 10 else []),
            )

        # 计算非空章节占比，过低则抛错（聚合层兜底无意义）
        non_empty = sum(
            1 for f in out
            if f.summary or f.characters or f.events or f.locations
        )
        if non_empty == 0:
            raise LongContextExtractionError(
                "long-context response yielded no usable chapter facts"
            )
        coverage = non_empty / len(out) if out else 0
        if coverage < 0.3:
            logger.warning(
                "[拆书V3.1-长上下文] 章节有效抽取覆盖率仅 %.1f%%，可能需要切回逐章模式",
                coverage * 100,
            )

        return out
