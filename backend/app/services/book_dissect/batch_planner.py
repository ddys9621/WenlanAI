"""拆书：分批抽取规划器

把"逐章一次请求"与"整本一次请求"统一为"每批 N 章一次请求"：
- 上下文预算：模型上下文窗口 × SAFE_INPUT_RATIO，扣掉 prompt 模板 / 字典 / 前文摘要开销后，
  按章节字数贪心装箱，保证单批输入不超预算
- 输出预算：每章 ChapterFact JSON 约 EST_OUTPUT_TOKENS_PER_CHAPTER tokens，
  用户设置的 Max Tokens 决定单批最多几章（超出会被截断 → 整批 JSON 失效）
- 用户可指定 chapters_per_request 覆盖自动值（模型上下文已知时仍受其预算约束；
  上下文未知时以用户指定为准，不拿 32k 兜底预算去否决；输出预算只给提示）
- chapter_limit 截取前 N 章，配合 sampling_mode 做二次采样

规划只依赖每章字数，不读正文，因此 API 预估端点可直接用 chapters_meta 里的 word_count 复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.services.book_dissect.long_context_router import (
    PROMPT_TEMPLATE_OVERHEAD_TOKENS,
    SAFE_INPUT_RATIO,
    TOKENS_PER_CN_CHAR,
    _lookup_context_window,
)

# 模型不在上下文窗口表里时的保守兜底：32k 几乎是现代模型的下限，
# 得到的批次虽小（2-4 章）但仍比逐章省请求
DEFAULT_CONTEXT_WINDOW_FALLBACK = 32_000

# 每章拆书卡 JSON 的输出 token 估算（章纲 300-500 字 + 标签字段，英文 key 有额外开销）
EST_OUTPUT_TOKENS_PER_CHAPTER = 900

# 分批模式额外注入的字典 / 前文摘要上下文开销（字典 top50 ≈ 1k + 摘要 1500 字 ≈ 2k）
BATCH_CONTEXT_OVERHEAD_TOKENS = 3_000

# 单批章节数硬上限：再大 LLM 输出对齐（章号 / 顺序）出错率明显上升
MAX_CHAPTERS_PER_BATCH_HARD_CAP = 60

# ---- 情节单元识别（S2）的滚动窗口：喂的是压缩拆书卡，不是正文 ----
# 每张压缩卡（章纲 ≤400 字 + 标签 / 钩子 / 爽点 / 主角变化，英文 key）约 350 tokens
EST_INPUT_TOKENS_PER_CARD = 350
# 每个单元的 JSON（十几个叙述字段）约 450 tokens；单元平均 4 章 → 折算每章约 110 tokens 输出
EST_OUTPUT_TOKENS_PER_ARC = 450
AVG_CHAPTERS_PER_ARC = 4
# 输出预算只用 80%：窗口里还有上轮 carry 过来的卡，单元数会比 window_new / 4 略多
ARC_OUTPUT_SAFETY_RATIO = 0.8
# 系统提示 + 模板 + 词表 + 输出示例
ARC_PROMPT_OVERHEAD_TOKENS = 2_000
# 窗口下限 = 原固定值（小模型 / 低 Max Tokens 时退回老行为）；上限：一轮要对齐几十个单元的边界，再大出错率上升、单次输出过长
ARC_WINDOW_MIN = 8
ARC_WINDOW_HARD_CAP = 60


@dataclass
class BatchPlan:
    """分批规划结果。batches 里存的是目标章节列表的下标，与 target 顺序一致。"""

    batches: list[list[int]]
    mode: str                          # single / batched / one_shot
    model: str
    context_window: int                # 0 表示模型未知（已用 fallback 规划）
    context_known: bool
    input_budget_tokens: int           # 单批输入预算
    output_budget_tokens: int          # 用户 Max Tokens
    max_chapters_by_output: int        # 输出预算允许的单批章数
    chapters_per_request: int          # 实际生效的单批章数上限（0 = 仅按 token 装箱）
    warnings: list[str] = field(default_factory=list)

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    @property
    def target_count(self) -> int:
        return sum(len(b) for b in self.batches)


def select_target_indices(
    total: int,
    sampling_mode: str,
    sampling_param: int,
    chapter_limit: int = 0,
) -> list[int]:
    """先按 chapter_limit 截取前 N 章，再按 sampling_mode 采样，返回原列表下标。"""
    if total <= 0:
        return []
    n = total if chapter_limit <= 0 else min(total, chapter_limit)
    indices = list(range(n))
    if sampling_mode == "every_n":
        step = max(1, sampling_param or 1)
        return indices[::step]
    if sampling_mode == "key_only":
        k = max(1, n // 20)
        mid_start = max(0, n // 2 - k // 2)
        picked = indices[:k] + indices[mid_start:mid_start + k] + indices[-k:]
        return sorted(set(picked))
    return indices


def estimate_chapter_tokens(char_count: int) -> int:
    return int(max(0, char_count) * TOKENS_PER_CN_CHAR)


def plan_batches(
    char_counts: Sequence[int],
    *,
    model: Optional[str],
    max_tokens: Optional[int],
    extraction_engine: str = "auto",
    chapters_per_request: int = 0,
) -> BatchPlan:
    """按引擎模式 + 预算把目标章节切成若干批。

    Args:
        char_counts: 目标章节（已采样）的正文字数，顺序即抽取顺序
        model: 模型名，用于查上下文窗口
        max_tokens: 用户 Max Tokens 设置（输出预算）
        extraction_engine: auto / chunked / long_context
        chapters_per_request: 用户指定的单批章数；0 = 自动
    """
    n = len(char_counts)
    model_str = (model or "").strip()
    engine = (extraction_engine or "auto").lower()
    ctx_known = _lookup_context_window(model_str)
    ctx = ctx_known or DEFAULT_CONTEXT_WINDOW_FALLBACK
    output_budget = int(max_tokens or 0)
    input_budget = max(
        1_000,
        int(ctx * SAFE_INPUT_RATIO) - PROMPT_TEMPLATE_OVERHEAD_TOKENS - BATCH_CONTEXT_OVERHEAD_TOKENS,
    )
    max_by_output = (
        max(1, output_budget // EST_OUTPUT_TOKENS_PER_CHAPTER) if output_budget > 0
        else MAX_CHAPTERS_PER_BATCH_HARD_CAP
    )
    warnings: list[str] = []

    def _plan(batches: list[list[int]], mode: str, cap: int) -> BatchPlan:
        return BatchPlan(
            batches=batches, mode=mode, model=model_str,
            context_window=ctx_known, context_known=bool(ctx_known),
            input_budget_tokens=input_budget, output_budget_tokens=output_budget,
            max_chapters_by_output=max_by_output, chapters_per_request=cap,
            warnings=warnings,
        )

    if n == 0:
        return _plan([], "single", 0)

    if engine == "chunked":
        return _plan([[i] for i in range(n)], "single", 1)

    if engine == "long_context":
        total_tokens = sum(estimate_chapter_tokens(c) for c in char_counts)
        if total_tokens > input_budget:
            warnings.append(
                f"全书估算 {total_tokens} tokens 超过单批输入预算 {input_budget}，"
                "整本一次很可能被模型拒绝或截断"
            )
        if n > max_by_output:
            warnings.append(
                f"按当前 Max Tokens（{output_budget}）估算单次最多输出约 {max_by_output} 章，"
                f"{n} 章整本一次输出很可能被截断"
            )
        return _plan([list(range(n))], "one_shot" if n > 1 else "single", n)

    # auto / 自定义批大小
    if chapters_per_request > 0:
        cap = min(chapters_per_request, MAX_CHAPTERS_PER_BATCH_HARD_CAP)
        if not ctx_known:
            warnings.append(
                f"模型「{model_str or '未设置'}」不在上下文窗口表中，无法校验每批 {cap} 章是否超出上下文，"
                "已按指定章数分批；超出时该批会自动拆半重试"
            )
        if cap > max_by_output:
            warnings.append(
                f"按当前 Max Tokens（{output_budget}）估算单次最多稳定输出约 {max_by_output} 章，"
                f"每批 {cap} 章可能被截断（截断的批次会自动拆半重试）"
            )
    else:
        cap = min(max_by_output, MAX_CHAPTERS_PER_BATCH_HARD_CAP)
        if not ctx_known:
            warnings.append(
                f"模型「{model_str or '未设置'}」不在上下文窗口表中，按 {DEFAULT_CONTEXT_WINDOW_FALLBACK // 1000}k 保守规划；"
                "可手动指定每批章节数覆盖"
            )
        if output_budget > 0 and max_by_output < 3:
            warnings.append(
                f"当前 Max Tokens（{output_budget}）偏低，自动模式每批仅 {max_by_output} 章；"
                "在设置中调高 Max Tokens 可减少请求次数"
            )

    pack_budget = input_budget if ctx_known or chapters_per_request <= 0 else None
    batches = _pack_by_budget(char_counts, input_budget=pack_budget, cap=cap)
    if len(batches) == 1 and n > 1:
        mode = "one_shot"
    elif all(len(b) == 1 for b in batches):
        mode = "single"
    else:
        mode = "batched"
    return _plan(batches, mode, cap)


def _pack_by_budget(
    char_counts: Sequence[int],
    *,
    input_budget: Optional[int],
    cap: int,
) -> list[list[int]]:
    """顺序贪心装箱：章数到 cap 或 token 到预算就开新批；单章超预算独占一批（单章路径会再分段）。

    input_budget=None 表示不按 token 预算切（上下文未知且用户显式指定了每批章数时，只按 cap 切）。
    """
    batches: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for idx, chars in enumerate(char_counts):
        tokens = estimate_chapter_tokens(chars)
        over_budget = input_budget is not None and current_tokens + tokens > input_budget
        if current and (len(current) >= cap or over_budget):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(idx)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def split_batch(indices: list[int]) -> list[list[int]]:
    """对半拆分一批（用于失败重试），长度 ≤1 时原样返回。"""
    if len(indices) <= 1:
        return [indices]
    mid = len(indices) // 2
    return [indices[:mid], indices[mid:]]


@dataclass
class ArcWindowPlan:
    """情节单元识别的滚动窗口规划：每轮新进多少张拆书卡。"""

    window_new: int                    # 每轮新进卡数（已夹在 ARC_WINDOW_MIN..ARC_WINDOW_HARD_CAP）
    max_by_input: int                  # 输入预算允许的卡数
    max_by_output: int                 # 输出预算允许的卡数（Max Tokens 未知时 = 硬上限）
    model: str
    context_window: int                # 0 表示模型未知（已用 fallback 规划）
    context_known: bool
    output_budget_tokens: int

    def window_count(self, card_count: int) -> int:
        """按卡数估算需要几轮 LLM（不含失败减半重试 / carry 造成的额外轮次）。"""
        return -(-max(0, card_count) // self.window_new)


def plan_arc_window(card_count: int, *, model: Optional[str], max_tokens: Optional[int]) -> ArcWindowPlan:
    """按模型上下文 / Max Tokens 决定情节单元识别每轮喂多少张拆书卡。

    输入侧：上下文 × SAFE_INPUT_RATIO 扣掉提示词开销，按每卡 EST_INPUT_TOKENS_PER_CARD 折算；
    输出侧：Max Tokens × 安全系数 能容纳几个单元 JSON，再乘平均单元长度换算成卡数。
    两者取小，再夹在 [ARC_WINDOW_MIN, ARC_WINDOW_HARD_CAP]；上下文未知按 32k 兜底。
    """
    model_str = (model or "").strip()
    ctx_known = _lookup_context_window(model_str)
    ctx = ctx_known or DEFAULT_CONTEXT_WINDOW_FALLBACK
    output_budget = int(max_tokens or 0)
    input_budget = max(1_000, int(ctx * SAFE_INPUT_RATIO) - ARC_PROMPT_OVERHEAD_TOKENS)
    max_by_input = max(1, input_budget // EST_INPUT_TOKENS_PER_CARD)
    if output_budget > 0:
        arcs_fit = int(output_budget * ARC_OUTPUT_SAFETY_RATIO) // EST_OUTPUT_TOKENS_PER_ARC
        max_by_output = max(1, arcs_fit * AVG_CHAPTERS_PER_ARC)
    else:
        max_by_output = ARC_WINDOW_HARD_CAP
    window_new = min(max(min(max_by_input, max_by_output), ARC_WINDOW_MIN), ARC_WINDOW_HARD_CAP)
    return ArcWindowPlan(
        window_new=window_new, max_by_input=max_by_input, max_by_output=max_by_output,
        model=model_str, context_window=ctx_known, context_known=bool(ctx_known),
        output_budget_tokens=output_budget,
    )
