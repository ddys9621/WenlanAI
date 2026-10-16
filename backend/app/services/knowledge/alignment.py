"""对位：本书的卷 / 剧情单元 / 章 ↔ 对标书的哪一段（纯函数，设计稿 6.4）。

优先级：卷 = 作者卷对标表 > 分卷时的引用 > 全书相对位置；单元 = 细化时的引用 > 卷内相对位置；
章 = 单元内相对位置按比例取整。相对位置一律在对标书的「已拆范围」里算（只拆了前 40 章，就把本书全书铺到这 40 章上）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

EXCERPT_KINDS: dict[str, tuple[str, ...]] = {
    "open": ("opening", "description"),
    "advance": ("dialogue", "action"),
    "turn": ("payoff", "action"),
    "close": ("ending_hook", "payoff"),
    "transition": ("description", "dialogue"),
}
DEFAULT_EXCERPT_KINDS = ("dialogue", "action")


@dataclass(frozen=True)
class Span:
    """对标书的一段：index 是卷序号 / 单元编号 / 章号，start-end 是章号区间。"""

    index: int
    start: int
    end: int


def coverage(spans: Sequence[Span], fallback_total: int) -> tuple[int, int]:
    if not spans:
        return 1, max(fallback_total, 1)
    return min(s.start for s in spans), max(s.end for s in spans)


def relative(start: int, end: int, lo: int, hi: int) -> float:
    length = max(hi - lo + 1, 1)
    return min(max(((start + end) / 2 - lo + 0.5) / length, 0.0), 1.0)


def _nearest(position: float, spans: Sequence[Span], lo: int, hi: int) -> Optional[Span]:
    return min(spans, key=lambda s: (abs(relative(s.start, s.end, lo, hi) - position), s.index), default=None)


def align_volume(start: int, end: int, total: int, ref_volumes: Sequence[Span], *, covered: tuple[int, int],
                 mapped: Optional[int] = None, cited: Optional[int] = None) -> Optional[Span]:
    by_index = {v.index: v for v in ref_volumes}
    for choice in (mapped, cited):
        if choice in by_index:
            return by_index[choice]
    return _nearest(relative(start, end, 1, max(total, end, 1)), ref_volumes, *covered)


def align_unit(start: int, end: int, volume_start: int, volume_end: int, ref_units: Sequence[Span],
               ref_volume: Optional[Span], *, cited: Optional[int] = None) -> Optional[Span]:
    by_index = {u.index: u for u in ref_units}
    if cited in by_index:
        return by_index[cited]
    if not ref_units:
        return None
    lo, hi = (ref_volume.start, ref_volume.end) if ref_volume is not None else coverage(ref_units, 0)
    return _nearest(relative(start, end, volume_start, volume_end), ref_units, lo, hi)


def align_chapter(pos: int, length: int, ref_length: int) -> int:
    """本单元第 pos/length 章 ↔ 对标单元第几章（1 起；对标单元没有章时 0）。"""
    if ref_length <= 0:
        return 0
    if length <= 0:
        return 1
    return min(max(math.ceil(pos * ref_length / length), 1), ref_length)


def role_for(pos: int, length: int) -> str:
    return "open" if pos <= 1 else "close" if pos >= length else "advance"


def excerpt_kinds(role: Optional[str]) -> tuple[str, ...]:
    return EXCERPT_KINDS.get(role or "", DEFAULT_EXCERPT_KINDS)
