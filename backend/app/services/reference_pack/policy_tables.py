"""查表：模型分档与按档位的条数（全部硬编码）。

1. MODEL_TIERS    模型分档（S/M/L/XL）按上下文窗口大小
2. HISTORICAL_CONTEXT_TABLE  历史接续摘要数量查表
3. MEMORY_TOPK_TABLE         智能记忆 top-K 查表

新增模型只动 MODEL_TIERS。
"""
from __future__ import annotations

from typing import Literal


ModelTier = Literal["S", "M", "L", "XL"]
# S  = ≤16K   小模型兜底（Qwen-Plus / Yi-Lite / 老款 GPT-3.5）
# M  = 32K    主流（Qwen-Max / 豆包 Pro 32K / Yi-Large 32K）
# L  = 64K    大窗口（DeepSeek V3 / GLM-4 64K）
# XL = 128K+  旗舰（Claude Sonnet 4.5 / GPT-4o / Gemini 2.0 / Moonshot K2 / GLM-4.5）


# ============================================================
# 表 A：模型分档表（按窗口大小硬编码）
# ============================================================

MODEL_TIERS: dict[str, ModelTier] = {
    # === XL 旗舰 ===
    "deepseek-v4":            "XL",   # V4 Flash/Pro：上下文 1M（HF 模型卡），前缀覆盖 -flash / -pro
    "deepseek-v3.2":          "XL",   # 128K；必须排在 L 段 "deepseek-v3" 之前，否则被前缀吞掉
    "claude-sonnet-4":        "XL",   # 200K，前缀覆盖 4 / 4-5 / 4-6
    "gpt-4.1":                "XL",   # 1M
    "gpt-5":                  "XL",
    "gemini-2.5":             "XL",   # 1M
    "claude-sonnet-4-5":      "XL",
    "claude-opus-4":          "XL",
    "claude-3-5-sonnet":      "XL",
    "claude-3-opus":          "XL",
    "gpt-4o":                 "XL",
    "gpt-4-turbo":            "XL",
    "gemini-2.0-flash":       "XL",
    "gemini-1.5-pro":         "XL",
    "moonshot-v1-128k":       "XL",
    "glm-4.5":                "XL",
    "glm-4-plus":             "XL",

    # === L 大窗口 ===
    "deepseek-v3":            "L",
    "deepseek-v3.1":          "L",
    "deepseek-r1":            "L",
    "deepseek-chat":          "L",
    "glm-4":                  "L",
    "moonshot-v1-64k":        "L",

    # === M 主流 ===
    "qwen-max":               "M",
    "qwen-turbo-32k":         "M",
    "qwen3-max":              "M",
    "qwen-plus-32k":          "M",
    "doubao-pro-32k":         "M",
    "doubao-lite-32k":        "M",
    "yi-large":               "M",
    "yi-large-rag":           "M",
    "moonshot-v1-32k":        "M",
    "ernie-bot-4":            "M",

    # === S 兜底 ===
    "qwen-plus":              "S",
    "qwen-turbo":             "S",
    "yi-lite":                "S",
    "gpt-3.5-turbo":          "S",
    "gpt-3.5-turbo-16k":      "S",
    "moonshot-v1-8k":         "S",
    "ernie-bot":              "S",

    # === 默认（未知模型按 M 处理）===
    "_default": "M",
}


def normalize_model_name(model_name: str) -> str:
    """归一化模型名用于查表：小写 + 去掉 'vendor/' 路由前缀。

    网关（SiliconFlow / OpenRouter / 火山）返回的模型名常带厂商前缀，如
    'deepseek-ai/DeepSeek-V4-Flash'；直接前缀匹配会全部落到 _default（M 档），
    旗舰模型只拿到 32K 档的槽位预算（2026-09 桥段评审问题 B）。
    """
    name = (model_name or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name


def get_model_tier(model_name: str) -> ModelTier:
    """查表获取模型档位（零计算）。

    Args:
        model_name: 模型名（如 'deepseek-v3'、'deepseek-ai/DeepSeek-V4-Flash'）

    Returns:
        S / M / L / XL 之一
    """
    name = normalize_model_name(model_name)
    if not name:
        return MODEL_TIERS["_default"]
    # 先精确匹配
    if name in MODEL_TIERS:
        return MODEL_TIERS[name]
    # 再做前缀匹配（兼容带版本后缀的模型名，如 'deepseek-v3-0324'）
    for key, tier in MODEL_TIERS.items():
        if key != "_default" and name.startswith(key):
            return tier
    return MODEL_TIERS["_default"]


# ============================================================
# 表 D：历史接续摘要数量查表（替代"填充到预算"）
# ============================================================

HISTORICAL_CONTEXT_TABLE: dict[ModelTier, dict[str, int]] = {
    "S":  {"full_count": 1, "normal_count": 1, "brief_count": 2},   # 共 4 章
    "M":  {"full_count": 1, "normal_count": 2, "brief_count": 3},   # 共 6 章
    "L":  {"full_count": 1, "normal_count": 2, "brief_count": 7},   # 共 10 章
    "XL": {"full_count": 2, "normal_count": 5, "brief_count": 10},  # 共 17 章
}


# ============================================================
# 表 E：智能记忆 top-K 查表
# ============================================================

MEMORY_TOPK_TABLE: dict[ModelTier, int] = {
    "S":  3,
    "M":  5,
    "L":  8,
    "XL": 15,
}
