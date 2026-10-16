"""共创室上下文预算（参照写代码 agent 的上下文窗口）。

- 上限按项目设（AssistantContextSetting）；空 = 自动：按成员实际用的模型查窗口表，查不到按 FALLBACK_WINDOW
- 预算 = 上限 − 给回复预留的 max_tokens（最多占四分之一窗口）− 5% 估算余量
- 每次调用模型前装填：系统规则、本书、所在页面、前情摘要、本轮要求永远带上；装不下时先把本轮较早的工具结果
  压成一句（最近 KEEP_FULL_STEPS 步保持完整），再从最旧的历史开始截，最后才把最近一步的结果截短
- 一轮开始时历史装不下（先给本轮工具结果留 STEP_HEADROOM）就压缩：最旧的那部分对话由模型压成前情摘要，
  压到历史只占剩余预算的 COMPACT_TARGET，留出接着聊的空间，免得每轮都压
- 用量是估算：非 ASCII 字符按模型族的字 / token 比（取上沿，偏大只会少装），ASCII 约 3.5 字符 1 token
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from app.services.book_dissect.long_context_router import _lookup_context_window
from app.services.context_budget import clip_text
from app.services.reference_pack.assembler import char_token_ratio
from app.utils.prompt_safety import quote_untrusted

FALLBACK_WINDOW = 64_000
MIN_WINDOW, MAX_WINDOW = 16_000, 2_000_000
PRESETS = (32_000, 64_000, 128_000, 200_000, 1_000_000)
DEFAULT_REPLY_TOKENS = 4_000
SAFETY_RATIO = 0.05
STEP_HEADROOM = 0.3
COMPACT_TARGET = 0.5
KEEP_FULL_STEPS = 2
SUMMARY_LIMIT = 1500


def estimate_tokens(text: str, model: Optional[str]) -> int:
    if not text:
        return 0
    narrow = len(text.encode("ascii", "ignore"))
    return math.ceil((len(text) - narrow) * char_token_ratio(model or "") + narrow / 3.5)


@dataclass(frozen=True)
class Window:
    tokens: int
    source: str  # manual 作者设的 / auto 按模型查到 / fallback 没查到，用默认值
    model: str


def resolve_window(setting: Optional[int], model: Optional[str]) -> Window:
    name = (model or "").strip()
    if setting:
        return Window(max(MIN_WINDOW, min(MAX_WINDOW, int(setting))), "manual", name)
    known = _lookup_context_window(name)
    return Window(known, "auto", name) if known else Window(FALLBACK_WINDOW, "fallback", name)


def reserve_tokens(window: int, max_tokens: Optional[int]) -> int:
    reply = max_tokens if max_tokens and max_tokens > 0 else DEFAULT_REPLY_TOKENS
    return min(reply, window // 4) + int(window * SAFETY_RATIO)


@dataclass(frozen=True)
class RoundPlan:
    history_from: int  # 只带 history[history_from:]
    compressed: frozenset  # 压成一句的步骤下标
    clip_last: bool  # 最近一步的结果截短（最后手段）
    used: int  # 估算的输入 token（含系统规则）


def plan_round(*, fixed: int, history: list[int], steps_full: list[int], steps_compact: list[int], budget: int,
               last_clipped: int = 0, keep_full: int = KEEP_FULL_STEPS) -> RoundPlan:
    """fixed = 必带部分；history 从旧到新每条的 token；steps_* = 本轮每步完整 / 压成一句时的 token。"""
    n = len(steps_full)
    compressed: set[int] = set()
    suffix = [0] * (len(history) + 1)
    for i in range(len(history) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + history[i]

    def total(start: int, clip: bool = False) -> int:
        steps = sum(steps_compact[i] if i in compressed else steps_full[i] for i in range(n))
        return fixed + steps + suffix[start] + (last_clipped - steps_full[-1] if clip else 0)

    def plan(start: int, clip: bool = False) -> RoundPlan:
        return RoundPlan(start, frozenset(compressed), clip, total(start, clip))

    if total(0) <= budget:
        return plan(0)
    for i in range(max(0, n - keep_full)):
        compressed.add(i)
        if total(0) <= budget:
            return plan(0)
    start = 0
    while start < len(history) and total(start) > budget:
        start += 1
    if total(start) <= budget:
        return plan(start)
    compressed.update(range(n - 1))
    if total(start) <= budget or not n:
        return plan(start)
    return plan(start, clip=True)


def compaction_split(*, fixed: int, history: list[int], budget: int, summary_tokens: int,
                     summary_now: int = 0) -> Optional[int]:
    """一轮开始时：历史装不下（先给本轮工具结果留 STEP_HEADROOM）就返回要压进摘要的条数 k（history[:k]）。

    summary_tokens = 新摘要按上限估的大小；summary_now = 现有摘要（压缩后会被新摘要取代）。
    """
    room = int(budget * (1 - STEP_HEADROOM)) - fixed
    if not history or summary_now + sum(history) <= room:
        return None
    target = int((room - summary_tokens) * COMPACT_TARGET)
    keep, kept = len(history), 0
    while keep > 0 and kept + history[keep - 1] <= target:
        keep -= 1
        kept += history[keep]
    return max(keep, 1)


def usage_report(*, window: Window, reserve: int, parts: dict[str, int], included: int, total: int, summarized: int,
                 compressed_steps: int = 0, will_compact: int = 0) -> dict:
    used = sum(parts.values())
    return {
        "used": used, "limit": window.tokens, "reserve": reserve, "percent": round(used * 100 / window.tokens),
        "source": window.source, "model": window.model, "parts": parts,
        "history": {"included": included, "total": total, "summarized": summarized},
        "compressed_steps": compressed_steps, "will_compact": will_compact,
    }


SUMMARY_SYSTEM = "你在帮一支小说创作团队整理对话记录：只依据给出的对话，不编造，不加评论。"


def _summary_prompt(previous: str, dialog: str) -> str:
    return f"""把下面这段作者与共创室团队的较早对话压成「前情摘要」，供团队之后接着聊时参考。
保留：作者定下的偏好与要求、已经确认或否决的方案、还没解决的问题与待办、提到的重要事实（人物、设定、章节）。
寒暄和处理过程不用记，对话里没有的不要写；已有摘要里仍然有效的内容要保留。用要点，不超过 {SUMMARY_LIMIT} 字。

【已有摘要】
{previous or "（无）"}

【要压缩的对话】
{quote_untrusted(dialog, "历史对话")}"""


async def compact_dialog(ai_service: Any, *, previous: str, lines: list[str], model: Optional[str], window: Window) -> str:
    """把较早的对话（每条一行「作者：…」）压进前情摘要；一次装不下就分段接着压，后一段带着前一段的结果。"""
    est = lambda text: estimate_tokens(text, window.model)  # noqa: E731
    reserve = reserve_tokens(window.tokens, getattr(ai_service, "default_max_tokens", None))
    room = max(1000, int((window.tokens - reserve) * 0.8) - est(SUMMARY_SYSTEM + _summary_prompt("", ""))
               - est("字" * SUMMARY_LIMIT))
    chunks: list[list[str]] = []
    size = 0
    for line in lines:
        tokens = est(line) + 1
        if chunks and size + tokens <= room:
            chunks[-1].append(line)
            size += tokens
        else:
            chunks.append([line])
            size = tokens
    summary = previous
    for chunk in chunks:
        response = await ai_service.generate_text_stream_collect(
            prompt=_summary_prompt(summary, "\n".join(chunk)), system_prompt=SUMMARY_SYSTEM, model=model,
            context="assistant-compact",
        )
        text = (response.get("content") if isinstance(response, dict) else str(response or "")) or ""
        if not text.strip():
            raise ValueError("压缩没有产出内容")
        summary = clip_text(text.strip(), SUMMARY_LIMIT)
    return summary
