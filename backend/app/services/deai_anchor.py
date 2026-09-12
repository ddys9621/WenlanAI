"""去 AI 味共用的片段定位：诊断引证落字符偏移、补丁 find 唯一定位都走这里。

模型引用原文时常见三种走样：引号 / 标点变体（「」vs “”、全半角）、多余空白、漏一两个字。
定位按代价递增三级：精确子串 → 规范化后子串 → 最长公共子串模糊匹配；每级都把结果映射回原文偏移。
补丁套用只允许前两级且要求唯一命中（模糊替换会改错地方）。
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

Anchor = tuple[int, int, str]  # (start, end, method)  method ∈ exact | normalized | fuzzy

_PUNCT_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'", "「": '"', "」": '"', "『": '"', "』": '"',
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":", "（": "(", "）": ")",
    "—": "-", "－": "-", "～": "~", "…": ".", "、": ",",
})
_EDGE_PUNCT = " \t\r\n\"'“”‘’「」『』，。！？；：、…—-,.!?;:"
_QUOTE_RE = re.compile(r"“[^”\n]*”|「[^」\n]*」|\"[^\"\n]*\"")

FUZZY_MIN_CHARS = 6  # 规范化后不足这么多字的片段不做模糊匹配（太短必然误配）
FUZZY_MIN_RATIO = 0.6  # 最长公共子串至少覆盖片段的这个比例才算命中


def normalize_for_match(text: str) -> tuple[str, list[int]]:
    """去空白、统一引号与标点变体；返回 (规范化串, 规范化下标 → 原文下标)。"""
    chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text or ""):
        if ch.isspace():
            continue
        chars.append(ch.translate(_PUNCT_MAP))
        index_map.append(i)
    return "".join(chars), index_map


def _normalized_core(snippet: str) -> str:
    return normalize_for_match(snippet.strip(_EDGE_PUNCT))[0]


def count_matches(content: str, snippet: str) -> int:
    """规范化后 snippet 在 content 里出现的次数（首尾标点不参与比较）。"""
    core = _normalized_core(snippet or "")
    return normalize_for_match(content or "")[0].count(core) if core else 0


def locate(content: str, snippet: str, *, allow_fuzzy: bool = True, unique: bool = False) -> Optional[Anchor]:
    """在 content 中定位 snippet，返回原文偏移 (start, end, method)；找不到返回 None。

    unique=True：精确 / 规范化任一级出现多处即返回 None（补丁套用用）。
    """
    snippet = (snippet or "").strip()
    if not content or not snippet:
        return None

    hits = content.count(snippet)
    if hits == 1 or (hits > 1 and not unique):
        start = content.index(snippet)
        return start, start + len(snippet), "exact"
    if hits > 1:
        return None

    n_content, index_map = normalize_for_match(content)
    n_full = normalize_for_match(snippet)[0]
    n_core = _normalized_core(snippet)
    # 先整段规范化匹配（保住首尾引号 / 句号），再退到去掉首尾标点的核心
    for candidate in dict.fromkeys(c for c in (n_full, n_core) if c):
        n_hits = n_content.count(candidate)
        if n_hits == 1 or (n_hits > 1 and not unique):
            pos = n_content.index(candidate)
            return index_map[pos], index_map[pos + len(candidate) - 1] + 1, "normalized"
        if n_hits > 1:
            return None

    n_snip = n_core
    if not allow_fuzzy or len(n_snip) < FUZZY_MIN_CHARS:
        return None
    matcher = difflib.SequenceMatcher(None, n_content, n_snip, autojunk=False)
    block = matcher.find_longest_match(0, len(n_content), 0, len(n_snip))
    if block.size < max(FUZZY_MIN_CHARS, int(len(n_snip) * FUZZY_MIN_RATIO)):
        return None
    start_n = max(0, block.a - block.b)
    end_n = min(len(n_content), start_n + len(n_snip))
    return index_map[start_n], index_map[end_n - 1] + 1, "fuzzy"


def quote_spans(content: str) -> list[tuple[int, int]]:
    """对话引语区间（含引号本身）：“…”、「…」、"…"，不跨行。"""
    return [(m.start(), m.end()) for m in _QUOTE_RE.finditer(content or "")]
