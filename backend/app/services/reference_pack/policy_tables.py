"""V4.2 查表架构：4 张完全硬编码的策略查表（详见 v4_design.md §10.3）。

核心原则：**Injector 内零计算、零 if/else、零 fallback**。
所有"哪个场景注入什么档位、放多长、放多少条"全在这里写死。

4 张表：
1. MODEL_TIERS    模型分档（S/M/L/XL）按上下文窗口大小
2. POLICY_TABLE   场景×档位 → 维度策略（8 场景 × 4 档 = 32 entry）
3. CORPUS_TOPK    corpus 检索 top-K 查表
4. HISTORICAL_CONTEXT_TABLE  历史接续摘要数量查表
5. MEMORY_TOPK_TABLE         智能记忆 top-K 查表

新增模型只动 MODEL_TIERS；新增场景只动 POLICY_TABLE；零 Injector 代码改动。
"""
from __future__ import annotations

from typing import Literal


ModelTier = Literal["S", "M", "L", "XL"]
# S  = ≤16K   小模型兜底（Qwen-Plus / Yi-Lite / 老款 GPT-3.5）
# M  = 32K    主流（Qwen-Max / 豆包 Pro 32K / Yi-Large 32K）
# L  = 64K    大窗口（DeepSeek V3 / GLM-4 64K）
# XL = 128K+  旗舰（Claude Sonnet 4.5 / GPT-4o / Gemini 2.0 / Moonshot K2 / GLM-4.5）

Strength = Literal["off", "light", "medium", "deep"]
# off    = 0 token，完全不注入
# light  = ≤200 token
# medium = ≤600 token
# deep   = ≤1500 token


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
# 表 B：场景 × 模型档位 → 维度策略（核心交付物）
# ============================================================
# 每个 (scene, tier) entry 明确写死每个维度的 strength
# strength: 'off' / 'light' / 'medium' / 'deep'
#
# V5（book_dissect_v5_design.md §5）维度集合收敛为 7 维：
#   synopsis（全书骨架）/ bridges（桥段库）/ style（文风指纹）/ character_archive（人物功能谱）
#   / methodology（写法手册）/ structure（结构统计）/ corpus（拆书卡检索）
# archetypes / worldbuilding / entities / relations / events 随实体图谱抽取一并删除。

V5_DIMENSIONS: tuple[str, ...] = (
    "synopsis", "bridges", "style", "character_archive", "methodology", "structure", "corpus",
)

POLICY_TABLE: dict[tuple[str, ModelTier], dict[str, Strength]] = {

    # ============ 1. 世界观生成 ============
    ("world_building", "S"):  {"synopsis": "medium"},
    ("world_building", "M"):  {"synopsis": "deep"},
    ("world_building", "L"):  {"synopsis": "deep"},
    ("world_building", "XL"): {"synopsis": "deep"},

    # ============ 2. 角色生成 ============
    ("character", "S"):  {"character_archive": "medium", "synopsis": "light"},
    ("character", "M"):  {"character_archive": "deep", "synopsis": "medium", "corpus": "light"},
    ("character", "L"):  {"character_archive": "deep", "synopsis": "medium", "corpus": "light"},
    ("character", "XL"): {"character_archive": "deep", "synopsis": "medium", "corpus": "medium"},

    # ============ 3. 故事大纲 ============
    ("story_outline", "S"):  {"synopsis": "medium", "methodology": "medium", "structure": "light"},
    ("story_outline", "M"):  {"synopsis": "deep", "methodology": "deep", "bridges": "medium", "structure": "medium"},
    ("story_outline", "L"):  {"synopsis": "deep", "methodology": "deep", "bridges": "medium", "structure": "medium"},
    ("story_outline", "XL"): {"synopsis": "deep", "methodology": "deep", "bridges": "deep", "structure": "deep"},

    # ============ 3.5 桥段规划（K2 核心场景）============
    ("bridge_planning", "S"):  {"bridges": "medium", "synopsis": "light", "methodology": "light"},
    ("bridge_planning", "M"):  {"bridges": "deep", "methodology": "deep", "synopsis": "medium",
                                "structure": "medium", "character_archive": "medium"},
    ("bridge_planning", "L"):  {"bridges": "deep", "methodology": "deep", "synopsis": "medium",
                                "structure": "medium", "character_archive": "medium"},
    ("bridge_planning", "XL"): {"bridges": "deep", "methodology": "deep", "synopsis": "deep",
                                "structure": "deep", "character_archive": "deep"},

    # ============ 4. 章纲（批量）============
    ("chapter_outline", "S"):  {"methodology": "medium", "structure": "medium", "synopsis": "light"},
    ("chapter_outline", "M"):  {"methodology": "deep", "structure": "deep", "bridges": "medium",
                                "synopsis": "medium", "corpus": "medium"},
    ("chapter_outline", "L"):  {"methodology": "deep", "structure": "deep", "bridges": "medium",
                                "synopsis": "medium", "corpus": "medium"},
    ("chapter_outline", "XL"): {"methodology": "deep", "structure": "deep", "bridges": "deep",
                                "synopsis": "deep", "corpus": "deep"},

    # ============ 5a. 章节正文（每章触发，最高频）============
    ("chapter_content", "S"):  {"style": "medium", "corpus": "light", "methodology": "light"},
    ("chapter_content", "M"):  {"style": "deep", "corpus": "medium", "methodology": "medium",
                                "bridges": "light", "structure": "light", "synopsis": "light"},
    ("chapter_content", "L"):  {"style": "deep", "corpus": "deep", "methodology": "medium",
                                "bridges": "light", "structure": "medium", "synopsis": "light"},
    ("chapter_content", "XL"): {"style": "deep", "corpus": "deep", "methodology": "deep",
                                "bridges": "medium", "structure": "deep", "synopsis": "medium",
                                "character_archive": "medium"},

    # ============ 5b. 场景生成（卡片）============
    ("scene_generation", "S"):  {"style": "medium", "corpus": "light"},
    ("scene_generation", "M"):  {"style": "deep", "corpus": "medium"},
    ("scene_generation", "L"):  {"style": "deep", "corpus": "deep", "structure": "light"},
    ("scene_generation", "XL"): {"style": "deep", "corpus": "deep", "structure": "medium"},

    # ============ 5c. 章节重生成 ============
    ("chapter_regenerate", "S"):  {"style": "medium", "corpus": "light"},
    ("chapter_regenerate", "M"):  {"style": "deep", "corpus": "medium", "methodology": "medium"},
    ("chapter_regenerate", "L"):  {"style": "deep", "corpus": "medium", "methodology": "medium"},
    ("chapter_regenerate", "XL"): {"style": "deep", "corpus": "deep", "methodology": "deep"},
}


def get_policy(scene: str, model_name: str) -> dict[str, Strength]:
    """查表入口：返回 (scene, tier) 对应的维度策略。

    Returns:
        dict[dimension_name, strength]，未在表中的场景返回空 dict（兜底白名单）
    """
    tier = get_model_tier(model_name)
    return POLICY_TABLE.get((scene, tier), {})


# ============================================================
# 表 C：corpus 检索 top-K 查表
# ============================================================
# 不再用公式反算，每个 (scene, tier) 写死 K

CORPUS_TOPK: dict[tuple[str, ModelTier], int] = {
    ("chapter_content", "S"):  1,
    ("chapter_content", "M"):  3,
    ("chapter_content", "L"):  5,
    ("chapter_content", "XL"): 5,

    ("chapter_outline", "S"):  0,
    ("chapter_outline", "M"):  2,
    ("chapter_outline", "L"):  3,
    ("chapter_outline", "XL"): 5,

    ("scene_generation", "S"):  1,
    ("scene_generation", "M"):  2,
    ("scene_generation", "L"):  3,
    ("scene_generation", "XL"): 3,

    ("chapter_regenerate", "S"):  1,
    ("chapter_regenerate", "M"):  2,
    ("chapter_regenerate", "L"):  3,
    ("chapter_regenerate", "XL"): 5,

    ("character", "S"):  0,
    ("character", "M"):  1,
    ("character", "L"):  2,
    ("character", "XL"): 3,
}


def get_corpus_top_k(scene: str, model_name: str) -> int:
    """查表获取 corpus 检索 top-K（零计算）。"""
    return CORPUS_TOPK.get((scene, get_model_tier(model_name)), 0)


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
