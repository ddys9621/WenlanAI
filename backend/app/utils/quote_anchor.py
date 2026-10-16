"""按原文引句在当前正文里定位（标注用）：逐字命中 > 忽略标点空白命中 > 前缀命中 > 找不到 (-1, 0)。"""
from __future__ import annotations

import re

_NOISE = re.compile(r"[\s\u3000，。！？、；：,.!?;:\"'“”‘’「」『』（）()《》<>〈〉…—\-·~～]")
MIN_QUOTE = 4
PREFIX = 6


def _normalized_with_index(text: str) -> tuple[str, list[int]]:
    chars, index = [], []
    for i, ch in enumerate(text):
        if not _NOISE.match(ch):
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


def locate_quote(content: str, quote: str) -> tuple[int, int]:
    content, quote = content or "", (quote or "").strip()
    if len(quote) < MIN_QUOTE or not content:
        return -1, 0
    pos = content.find(quote)
    if pos >= 0:
        return pos, len(quote)
    body, index = _normalized_with_index(content)
    key, _ = _normalized_with_index(quote)
    if len(key) >= MIN_QUOTE:
        pos = body.find(key)
        if pos >= 0:
            start, end = index[pos], index[pos + len(key) - 1] + 1
            return start, end - start
        prefix = key[:PREFIX]
        if len(prefix) >= MIN_QUOTE:
            pos = body.find(prefix)
            if pos >= 0:
                start, end = index[pos], index[pos + len(prefix) - 1] + 1
                return start, end - start
    return -1, 0
