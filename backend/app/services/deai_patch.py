"""去 AI 味补丁式改稿：模型只输出 {"edits":[{find, replace, why}]}，这里在原文上机械套用。

为什么不让模型输出全文：refactor.md 第 7 条"没有缺陷的句子原样保留"靠 prompt 管不住——整章重写时模型会顺手
改写没问题的句子。补丁式把这条从"请求"变成"保证"：没被 find 命中的字一个都不会变；对话引语、多处匹配、重叠
修改都在这里机械拦截，而不是指望模型自觉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.deai_anchor import count_matches, locate, quote_spans
from app.utils.json_cleaner import safe_parse_json

MIN_FIND_CHARS = 4  # find 短于这个长度几乎必然多处匹配或误伤，直接拒


@dataclass
class PatchResult:
    content: str
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0


def parse_edits(raw: str) -> list[dict[str, str]]:
    """容忍代码块 / 裸数组；缺 find 或结构不对的条目丢弃；replace 为 null 视为删除。"""
    data = safe_parse_json(raw or "", default=None, log_prefix="[deai-patch]")
    items = data.get("edits") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    edits: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        find = str(item.get("find") or "")
        if not find.strip():
            continue
        replace = item.get("replace")
        edits.append({"find": find, "replace": "" if replace is None else str(replace), "why": str(item.get("why") or "").strip()})
    return edits


def _touches_protected_quote(start: int, end: int, quotes: list[tuple[int, int]], allowed: set[tuple[int, int]]) -> bool:
    return any(start < q_end and end > q_start and (q_start, q_end) not in allowed for q_start, q_end in quotes)


def apply_edits(
    content: str,
    edits: list[dict[str, Any]],
    *,
    allowed_quote_spans: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
) -> PatchResult:
    """在 content 上套用 edits。每条 find 必须在原文中唯一定位（精确或规范化，不模糊）。

    跳过并记原因：定位片段太短 / 原文中未找到 / 多处匹配 / 改前改后相同 / 对话引语不动 / 与前一处修改重叠。
    allowed_quote_spans：修改指令明确指向的引语区间（与诊断 finding 锚点相交的引语），这些引语允许改。
    """
    quotes = quote_spans(content)
    allowed = {tuple(span) for span in allowed_quote_spans}
    located: list[tuple[int, int, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []

    for edit in edits:
        find, replace = str(edit.get("find") or ""), str(edit.get("replace") or "")
        if len(find.strip()) < MIN_FIND_CHARS:
            skipped.append({**edit, "reason": "定位片段太短"})
            continue
        if find.strip() == replace.strip():
            skipped.append({**edit, "reason": "改前改后相同"})
            continue
        anchor = locate(content, find, allow_fuzzy=False, unique=True)
        if anchor is None:
            hits = count_matches(content, find)
            skipped.append({**edit, "reason": f"多处匹配（{hits} 处），无法唯一定位" if hits > 1 else "原文中未找到"})
            continue
        start, end, _ = anchor
        if _touches_protected_quote(start, end, quotes, allowed):
            skipped.append({**edit, "reason": "对话引语不动"})
            continue
        located.append((start, end, edit))

    located.sort(key=lambda item: (item[0], item[1]))
    applied: list[dict[str, Any]] = []
    pieces: list[str] = []
    cursor = 0
    for start, end, edit in located:
        if start < cursor:
            skipped.append({**edit, "reason": "与前一处修改重叠"})
            continue
        pieces.append(content[cursor:start])
        pieces.append(str(edit.get("replace") or ""))
        cursor = end
        applied.append({**edit, "start": start, "end": end})
    pieces.append(content[cursor:])
    new_content = "".join(pieces)
    return PatchResult(
        content=new_content, applied=applied, skipped=skipped,
        chars_before=len(content), chars_after=len(new_content),
    )
