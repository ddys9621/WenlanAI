"""C3 兑现章末尾风格（项目级开关 Project.c3_hook_style）。

- none（默认）：C3 章末不留钩子——爽感带着读者进下一章（付费文 / 2026-09 评审决定的现状）
- soft：收束场景 + 一个不解释的小异样（半钩，≤2 句）——免费平台每章末钩子决定留存时用

三处 prompt 用同一份文案：填充方法论（bridge_templates.methodology 的「不留钩子」替换）、
章纲展开（C3 位置语义）、写作位置约束（PAYOFF 模板的「章末留任何钩子」禁令替换）。
"""
from __future__ import annotations

from typing import Any

C3_HOOK_NONE = "none"
C3_HOOK_SOFT = "soft"
VALID_C3_HOOK_STYLES: tuple[str, ...] = (C3_HOOK_NONE, C3_HOOK_SOFT)

# 填充方法论里被替换的原词（四个题材模板的 methodology 都含它）
METHODOLOGY_NO_HOOK = "**不留钩子**"
METHODOLOGY_SOFT_HOOK = "**章末只留半钩：收束场景 + 一个不解释的小异样（≤2 句），不得展开新事件**"

# 章纲展开 C3 位置语义括注
EXPANSION_C3_NONE = "章末不留钩子"
EXPANSION_C3_SOFT = "章末半钩：收束场景后留一个不解释的小异样，不得展开新事件"

# 写作位置约束（PAYOFF）：被替换的禁令 + 追加段
WRITING_NO_HOOK_BAN = "章末留任何钩子"
WRITING_SOFT_HOOK_BAN = "章末写明确的悬念预告或开启新事件（半钩只许一个不解释的小异样）"
WRITING_SOFT_HOOK_BLOCK = (
    "【🪝 半钩模式】章末处理改为：收束场景之后，再落一个不解释的小异样——一句反常的台词 / 一件不该出现的物件 / "
    "一个与刚才兑现相悖的细节，≤ 2 句，不解释、不预告、不开启新事件。"
)


def normalize_c3_hook_style(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return text if text in VALID_C3_HOOK_STYLES else C3_HOOK_NONE


def methodology_for(methodology: str, style: str) -> str:
    return methodology.replace(METHODOLOGY_NO_HOOK, METHODOLOGY_SOFT_HOOK) if style == C3_HOOK_SOFT else methodology


def expansion_c3_rule(style: str) -> str:
    return EXPANSION_C3_SOFT if style == C3_HOOK_SOFT else EXPANSION_C3_NONE


def apply_writing_payoff_style(text: str, style: str) -> str:
    if style != C3_HOOK_SOFT or not text:
        return text
    return f"{text.replace(WRITING_NO_HOOK_BAN, WRITING_SOFT_HOOK_BAN)}\n{WRITING_SOFT_HOOK_BLOCK}\n"
