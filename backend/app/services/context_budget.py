"""正文提示词的上下文预算器（纯函数，无 DB / 无 LLM）。

长篇写到几百章后，"全书章纲 / 全部角色 / 全部组织归属"这类随章数线性增长的上下文会把单章提示词撑到
几十万字。这里给每个上下文区块定优先级与上限：
1. 每块先按自身 max_chars 截断（keep 决定保留开头还是结尾），空文本直接丢弃；
2. 总长仍超预算 → 按 priority 从低到高把区块压到 min_chars（min_chars=0 即整块丢弃），直到不超预算；
3. required 区块（本章任务）永不裁剪；输出保持原顺序。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

TRIM_MARKER = "…（略）"


@dataclass(frozen=True)
class ContextSection:
    key: str
    title: str
    text: str
    priority: int
    max_chars: int
    min_chars: int = 0
    keep: str = "head"  # head 保留开头 / tail 保留结尾（如上一章正文要的是结尾衔接）
    required: bool = False
    trimmed: bool = False


def clip_text(text: str, limit: int, keep: str = "head") -> str:
    """截到 limit 字：超长时用省略标记占位（标记计入长度）；limit 比标记还短则硬截。"""
    text = text or ""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRIM_MARKER):
        return text[-limit:] if keep == "tail" else text[:limit]
    body = limit - len(TRIM_MARKER)
    return TRIM_MARKER + text[-body:] if keep == "tail" else text[:body] + TRIM_MARKER


def _with_text(section: ContextSection, limit: int) -> ContextSection:
    clipped = clip_text(section.text, limit, section.keep)
    return replace(section, text=clipped, trimmed=section.trimmed or clipped != section.text)


def fit_sections(sections: Iterable[ContextSection], total_chars: int) -> list[ContextSection]:
    """按自身上限截断 + 总预算裁剪，返回保持原顺序的新列表（被裁过的区块 trimmed=True）。"""
    fitted = [
        s if s.required else _with_text(s, s.max_chars)
        for s in sections
        if (s.text or "").strip()
    ]
    overflow = sum(len(s.text) for s in fitted) - total_chars
    if overflow <= 0:
        return fitted

    order = sorted(
        (i for i, s in enumerate(fitted) if not s.required),
        key=lambda i: (fitted[i].priority, -i),
    )
    for i in order:
        if overflow <= 0:
            break
        current = len(fitted[i].text)
        floor = min(fitted[i].min_chars, current)
        absorb = min(overflow, current - floor)
        if absorb <= 0:
            continue
        fitted[i] = _with_text(fitted[i], current - absorb)
        overflow -= absorb
    return [s for s in fitted if s.text.strip()]


def render_sections(sections: Iterable[ContextSection]) -> str:
    """【标题】+ 正文，区块间空一行；标题为空的区块直接输出正文。"""
    blocks = [f"【{s.title}】\n{s.text}" if s.title else s.text for s in sections if (s.text or "").strip()]
    return "\n\n".join(blocks)


def budget_report(sections: Iterable[ContextSection]) -> dict[str, dict[str, int | bool]]:
    """各区块最终字数与是否被裁剪（写日志 / 过程追踪用）。"""
    return {s.key: {"chars": len(s.text), "trimmed": s.trimmed} for s in sections}
