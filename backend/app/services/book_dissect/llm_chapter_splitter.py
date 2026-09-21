"""拆书 V3.1.4: 章节切分 LLM Fallback

当纯正则切分在"巨型单章"或"章节字数严重失衡"场景下失效时，调一次
LLM 推断边界模式，或降级到固定字数切分。

设计原则：
- 仅在必要时调用（`_needs_llm_fallback` 门控）
- LLM 失败不抛：降级到 fixed_size_split
- 不改动现有 `chapter_splitter.split_into_chapters` 行为，作为外层兜底

设计文档：agent-docs/features/book_dissect_v31_quality_optimization.md §6
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.services.book_dissect.chapter_splitter import (
    Chapter,
    _count_words,
    _normalize_text,
    decode_text,
    split_into_chapters,
)
from app.services.book_dissect.prompts import (
    LLM_BOUNDARY_PROMPT,
    SYSTEM_PROMPT_V31_BOUNDARY,
)
from app.utils.json_cleaner import safe_parse_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

# 触发 LLM fallback 的条件
GIANT_CHAPTER_THRESHOLD = 30_000    # 单章 > 此字符数视为巨型章
VERY_LARGE_CHAPTER = 50_000         # 任一章节 > 此值一定触发
MIN_TEXT_LENGTH_FOR_LLM = 10_000    # 文本总长 < 此值不值得调 LLM

# 采样段落长度（对应 prompt 的 head/mid/tail）
SAMPLE_HEAD_CHARS = 3_000
SAMPLE_MID_CHARS = 3_000
SAMPLE_TAIL_CHARS = 3_000

# 固定字数切分目标长度（当 fallback_action=fixed_size 或 LLM 失败时）
FIXED_SIZE_TARGET = 5_000
FIXED_SIZE_MIN = 1_500        # 最后一段短于此值则合并到前一段

# LLM 参数
DEFAULT_TEMPERATURE = 0.0      # 边界判定要稳定


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class LlmBoundaryDecision:
    """LLM 返回的边界判定。"""

    text_type: str                         # novel / essay / dialogue / notes / other
    boundary_pattern: Optional[str]        # Python regex（仅 regex_split 有效）
    estimated_chapter_count: Optional[int]
    estimated_chapter_chars: Optional[int]
    fallback_action: str                   # regex_split / fixed_size / single_chapter


# ---------------------------------------------------------------------------
# 判定：是否需要 LLM fallback
# ---------------------------------------------------------------------------


def needs_llm_fallback(chapters: list[Chapter]) -> bool:
    """判断是否值得调 LLM 重新切分。

    触发条件：
    1. 只切出 1 章且字符数 > GIANT_CHAPTER_THRESHOLD
    2. 任一章节字符数 > VERY_LARGE_CHAPTER
    """
    if not chapters:
        return False
    if len(chapters) == 1:
        total = len(chapters[0].content or "")
        return total > GIANT_CHAPTER_THRESHOLD
    # 多章但有巨型章节
    return any(len(c.content or "") > VERY_LARGE_CHAPTER for c in chapters)


# ---------------------------------------------------------------------------
# LLM 边界分析
# ---------------------------------------------------------------------------


class LlmChapterSplitter:
    """LLM 边界分析器：接收原始文本 → 返回 LlmBoundaryDecision。"""

    def __init__(self, ai_service):
        self.ai_service = ai_service

    async def analyze(self, text: str) -> Optional[LlmBoundaryDecision]:
        """主入口：采样三段给 LLM 分析边界。失败返回 None。"""
        if not text or len(text) < MIN_TEXT_LENGTH_FOR_LLM:
            return None

        head, mid, tail = _sample_head_mid_tail(text)

        user_prompt = LLM_BOUNDARY_PROMPT.format(
            head_text=head,
            mid_text=mid,
            tail_text=tail,
        )

        try:
            resp = await self.ai_service.generate_text_stream_collect(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT_V31_BOUNDARY,
                temperature=DEFAULT_TEMPERATURE,
                context="拆书V3.1-LLM切分",
            )
        except Exception as exc:
            logger.warning("[拆书V3.1-LLM切分] LLM 调用失败: %s", exc)
            return None

        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if not content:
            logger.warning("[拆书V3.1-LLM切分] LLM 返回空内容")
            return None

        return _parse_decision(content)


# ---------------------------------------------------------------------------
# 主对外接口
# ---------------------------------------------------------------------------


async def split_with_llm_fallback(
    raw_text: str,
    ai_service,
) -> list[Chapter]:
    """主对外接口：先跑正则切分，必要时调 LLM 兜底。

    Args:
        raw_text: 已解码的全文
        ai_service: app.services.ai_service.AIService 实例

    Returns:
        list[Chapter]，长度 ≥ 1
    """
    # 1. 先走现有正则切分（纯 CPU，几百万字的书放线程里跑，不卡事件循环）
    chapters = await asyncio.to_thread(split_into_chapters, raw_text)

    # 2. 判定是否需要 LLM 兜底
    if not needs_llm_fallback(chapters):
        return chapters

    logger.info(
        "[拆书V3.1-LLM切分] 触发 LLM fallback：当前章节数=%d 最大字数=%d",
        len(chapters),
        max((len(c.content or "") for c in chapters), default=0),
    )

    # 3. 调 LLM 分析边界
    splitter = LlmChapterSplitter(ai_service=ai_service)
    normalized = _normalize_text(raw_text)
    decision = await splitter.analyze(normalized)

    if decision is None:
        # LLM 失败 → 固定字数兜底
        logger.info("[拆书V3.1-LLM切分] LLM 分析失败，降级 fixed_size_split")
        return _fixed_size_split(normalized)

    logger.info(
        "[拆书V3.1-LLM切分] LLM 决策: action=%s type=%s pattern=%r",
        decision.fallback_action, decision.text_type,
        (decision.boundary_pattern or "")[:80],
    )

    # 4. 按决策执行
    if decision.fallback_action == "regex_split" and decision.boundary_pattern:
        result = _split_by_llm_regex(normalized, decision.boundary_pattern)
        if result and len(result) >= 2:
            return result
        logger.info("[拆书V3.1-LLM切分] regex 切分无效，降级 fixed_size")
        return _fixed_size_split(normalized)

    if decision.fallback_action == "single_chapter":
        # 保留现有单章结果
        return chapters

    # 默认或 fixed_size
    return _fixed_size_split(normalized)


async def split_bytes_with_llm_fallback(
    raw: bytes,
    ai_service,
) -> tuple[list[Chapter], str]:
    """从原始字节一键切分 + LLM 兜底。返回 (chapters, encoding_used)。"""
    text, enc = decode_text(raw)
    chapters = await split_with_llm_fallback(text, ai_service=ai_service)
    return chapters, enc


# ---------------------------------------------------------------------------
# 内部：采样
# ---------------------------------------------------------------------------


def _sample_head_mid_tail(text: str) -> tuple[str, str, str]:
    """从文本头 / 中 / 尾各取采样段。短文本重复 head 填充。"""
    total = len(text)
    if total <= SAMPLE_HEAD_CHARS + SAMPLE_MID_CHARS + SAMPLE_TAIL_CHARS:
        # 短文本：直接返回整段给 head，mid/tail 置短
        return text[:SAMPLE_HEAD_CHARS], "", ""
    head = text[:SAMPLE_HEAD_CHARS]
    mid_start = max(
        SAMPLE_HEAD_CHARS,
        (total // 2) - (SAMPLE_MID_CHARS // 2),
    )
    mid = text[mid_start: mid_start + SAMPLE_MID_CHARS]
    tail = text[-SAMPLE_TAIL_CHARS:]
    return head, mid, tail


# ---------------------------------------------------------------------------
# 内部：LLM 决策解析
# ---------------------------------------------------------------------------


def _parse_decision(raw_text: str) -> Optional[LlmBoundaryDecision]:
    result = safe_parse_json(
        raw_text,
        default=None,
        expected_type="object",
        log_prefix="[拆书V3.1-LLM切分]",
    )
    if not isinstance(result, dict):
        logger.warning("[拆书V3.1-LLM切分] JSON 解析非 object")
        return None

    text_type = result.get("text_type")
    if not isinstance(text_type, str):
        text_type = "other"

    action = result.get("fallback_action")
    if action not in ("regex_split", "fixed_size", "single_chapter"):
        logger.warning("[拆书V3.1-LLM切分] 非法 fallback_action: %r", action)
        return None

    pattern = result.get("boundary_pattern")
    if not isinstance(pattern, str):
        pattern = None

    try:
        chapter_count = int(result.get("estimated_chapter_count"))
    except (TypeError, ValueError):
        chapter_count = None
    try:
        chapter_chars = int(result.get("estimated_chapter_chars"))
    except (TypeError, ValueError):
        chapter_chars = None

    return LlmBoundaryDecision(
        text_type=text_type,
        boundary_pattern=pattern,
        estimated_chapter_count=chapter_count,
        estimated_chapter_chars=chapter_chars,
        fallback_action=action,
    )


# ---------------------------------------------------------------------------
# 内部：LLM regex 切分
# ---------------------------------------------------------------------------


def _split_by_llm_regex(text: str, pattern: str) -> Optional[list[Chapter]]:
    """用 LLM 给出的 regex 在全文切分。非法 regex / 无匹配时返回 None。"""
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        logger.warning("[拆书V3.1-LLM切分] regex 非法: %r err=%s", pattern, exc)
        return None

    matches = list(compiled.finditer(text))
    if len(matches) < 2:
        return None

    chapters: list[Chapter] = []

    # 第一个 match 之前（前言）
    first = matches[0]
    if first.start() > 200:  # 保留一定长度的前言
        preamble = text[:first.start()].strip()
        if preamble:
            chapters.append(Chapter(
                chapter_number=len(chapters) + 1,
                title="前言",
                raw_title="前言",
                content=preamble,
                word_count=_count_words(preamble),
                kind="preamble",
            ))

    for i, m in enumerate(matches):
        # LLM 给的 pattern 通常只匹配「第N章」这个前缀：标题取到行尾，正文从下一行开始，
        # 否则标题名会漏进正文；相邻的重复标题行（"347.第345章xx" 紧跟 "第345章xx"）也会因正文为空被合并掉
        line_end = text.find("\n", m.end())
        if line_end == -1 or line_end - m.start() > 120:
            line_end = m.end()
        title = text[m.start(): line_end].strip()[:80] or f"第{i+1}段"
        content_start = line_end
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        if not content:
            continue
        chapters.append(Chapter(
            chapter_number=len(chapters) + 1,
            title=title,
            raw_title=title,
            content=content,
            word_count=_count_words(content),
            kind="chapter",
        ))

    if not chapters:
        return None
    return chapters


# ---------------------------------------------------------------------------
# 内部：fixed_size 兜底切分
# ---------------------------------------------------------------------------


def _fixed_size_split(text: str) -> list[Chapter]:
    """按段落边界的固定字数切分。最后一段过短时合并到前段。"""
    text = text.strip()
    if not text:
        return []
    total = len(text)
    if total <= FIXED_SIZE_TARGET:
        return [Chapter(
            chapter_number=1,
            title="全文",
            raw_title="全文",
            content=text,
            word_count=_count_words(text),
            kind="preamble",
        )]

    chapters: list[Chapter] = []
    cursor = 0
    seg_idx = 0
    while cursor < total:
        seg_idx += 1
        target = cursor + FIXED_SIZE_TARGET
        if target >= total:
            # 最后一段
            content = text[cursor:].strip()
            if content:
                if chapters and len(content) < FIXED_SIZE_MIN:
                    # 过短合并到前段
                    prev = chapters[-1]
                    merged = (prev.content + "\n\n" + content).strip()
                    chapters[-1] = Chapter(
                        chapter_number=prev.chapter_number,
                        title=prev.title,
                        raw_title=prev.raw_title,
                        content=merged,
                        word_count=_count_words(merged),
                        kind=prev.kind,
                    )
                else:
                    chapters.append(Chapter(
                        chapter_number=len(chapters) + 1,
                        title=f"第 {seg_idx} 段",
                        raw_title=f"第 {seg_idx} 段",
                        content=content,
                        word_count=_count_words(content),
                        kind="chapter",
                    ))
            break

        # 查找最近的段落边界（\n\n）
        split_at = text.rfind("\n\n", cursor, target)
        if split_at == -1 or split_at <= cursor + FIXED_SIZE_MIN:
            # 退而求其次：查找 \n
            split_at = text.rfind("\n", cursor, target)
        if split_at == -1 or split_at <= cursor + FIXED_SIZE_MIN:
            split_at = target

        content = text[cursor:split_at].strip()
        if content:
            chapters.append(Chapter(
                chapter_number=len(chapters) + 1,
                title=f"第 {seg_idx} 段",
                raw_title=f"第 {seg_idx} 段",
                content=content,
                word_count=_count_words(content),
                kind="chapter",
            ))
        cursor = split_at
        # 避免死循环
        while cursor < total and text[cursor] in "\n\r":
            cursor += 1

    if not chapters:
        chapters.append(Chapter(
            chapter_number=1,
            title="全文",
            raw_title="全文",
            content=text,
            word_count=_count_words(text),
            kind="preamble",
        ))
    return chapters
