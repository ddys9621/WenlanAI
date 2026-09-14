"""V4.3 Prompt Blueprint 装配单（详见 v4_design.md §10.2.4）。

核心原则：
- 每个 (scene, tier) 对应一份『槽位 + max_tokens』装配单
- 装配单在模块加载时一次性生成（启动期计算）
- 运行时只做 SELECT + 截断，零 if/else 分支
- 总长度可静态算、CI 验证、上下文窗口永不超

设计：
- Slot：单个 prompt 槽位（含 max_tokens 硬上限）
- BLUEPRINT_TEMPLATES：8 场景的"槽位顺序模板"（不含 max_tokens）
- STRENGTH_BUDGET：strength 档位 → token 预算映射
- BUSINESS_SLOT_TOKENS：业务槽位（非拆书）的固定 token 上限
- PROMPT_BLUEPRINT：最终生成的 32 份装配单 dict[(scene, tier)] -> list[Slot]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.reference_pack.policy_tables import (
    POLICY_TABLE,
    ModelTier,
    Strength,
)


# ============================================================
# Slot 数据结构
# ============================================================

CacheTier = Literal["global", "project", "chapter", "none"]


@dataclass(frozen=True)
class Slot:
    """单个 prompt 槽位（V4.3 装配单的基本单元）。"""
    name: str                              # 槽位名（如 'dissect_style'）
    max_tokens: int                        # 硬上限（截断到此）
    section: Literal["system", "user"]     # 放在 system 还是 user 段
    label: str = ""                        # prompt 标签（如 '【📚 写作方法论参考】'）
    required: bool = False                 # True=必出现（缺失抛 ValueError）

    # V4.4 K5 Prompt Caching 标注
    cacheable: bool = False                # True = 可缓存（项目级或全局静态）
    cache_tier: CacheTier = "none"
    # global  = 全局静态（角色设定/基础文风）→ 跨项目复用
    # project = 项目级静态（项目骨架/拆书参考）→ 同项目所有章节复用
    # chapter = 章节级动态（章纲/桥段约束/历史）→ 不缓存


# ============================================================
# 配置常量
# ============================================================

# strength → max_tokens 映射
STRENGTH_BUDGET: dict[Strength, int] = {
    "off": 0,
    "light": 200,
    "medium": 600,
    "deep": 1500,
}


# 业务槽位（非拆书）的固定 token 上限（按档位）
# 注：所有 4 档基础占用大致一致，XL 档放宽 project_skeleton 等
BUSINESS_SLOT_TOKENS: dict[ModelTier, dict[str, int]] = {
    "S": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 600, "chapter_outline": 400,
        "project_characters": 400, "world_rules_table": 300,
        "bridge_position": 500,
        "plot_lines_with_beats": 1200,  # V4.1 方案 C：主线+节点+配额，S 档紧
        "history_full": 400, "history_normal": 200, "history_brief": 160,
        "memory_topk": 400,
        "output_spec": 150,
    },
    "M": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 1200, "chapter_outline": 500,
        "project_characters": 600, "world_rules_table": 400,
        "bridge_position": 600,
        "plot_lines_with_beats": 1800,  # V4.1 方案 C：M 档允许多节点展开
        "history_full": 400, "history_normal": 400, "history_brief": 240,
        "memory_topk": 1000,
        "output_spec": 150,
    },
    "L": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 1500, "chapter_outline": 500,
        "project_characters": 800, "world_rules_table": 600,
        "bridge_position": 600,
        "plot_lines_with_beats": 2500,  # V4.1 方案 C：L 档可装完整其他主个节点描述
        "history_full": 400, "history_normal": 400, "history_brief": 560,
        "memory_topk": 1500,
        "output_spec": 150,
    },
    "XL": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 2000, "chapter_outline": 500,
        "project_characters": 1200, "world_rules_table": 800,
        "bridge_position": 600,
        "plot_lines_with_beats": 3500,  # V4.1 方案 C：XL 档全量装入节点描述 + 附加上下文
        "history_full": 800, "history_normal": 1000, "history_brief": 800,
        "memory_topk": 2500,
        "output_spec": 150,
    },
}


# 模型窗口大小（用于 CI 单测验证 sum ≤ window × 60%）
MODEL_WINDOW: dict[ModelTier, int] = {
    "S": 16_000,
    "M": 32_000,
    "L": 64_000,
    "XL": 128_000,
}


# 输出预留（每章节生成约 4500 token 输出）
# bridge_planning 用 (scene, tier) 二维 key 是因为 S 档模型应该生成更少的桥段
OUTPUT_RESERVE: dict[str, int] = {
    "chapter_content":    4500,
    "scene_generation":   2000,
    "chapter_regenerate": 4500,
    "chapter_outline":    3000,  # 批量生成 N 个章纲
    "story_outline":      2000,
    "bridge_planning":    8000,  # 75 个桥段 JSON（默认/L/XL）
    "character":          2000,
    "world_building":     1500,
}

# 场景 + 档位组合的输出预留覆盖（精细控制，覆盖 OUTPUT_RESERVE）
OUTPUT_RESERVE_BY_TIER: dict[tuple[str, ModelTier], int] = {
    # S 档窗口小，bridge_planning 只生成 ~25 个桥段
    ("bridge_planning", "S"): 5000,
    ("bridge_planning", "M"): 6000,
}


# CI 单测的安全比率：装配单总占用不超过窗口的 60%
SAFETY_RATIO = 0.6


# ============================================================
# 拆书维度的 prompt 标签（K1 决策表）
# ============================================================

DISSECT_LABELS: dict[str, str] = {
    "methodology":       "【📚 原书写法手册】",
    "structure":         "【🏗️ 原书结构统计】",
    "synopsis":          "【📖 原书全书骨架】",
    "corpus":            "【💡 原书相关拆书卡】",
    "bridges":           "【🌉 原书情节单元（桥段库）】",
    "character_archive": "【👥 原书人物功能谱】",
    # style 走 system 段，标签由 builder 在 system 段内自行打印
}


# ============================================================
# 场景定义：每个场景需要哪些"业务槽位"（按出现顺序）
# ============================================================

# 8 场景的业务槽位模板。拆书槽位由 POLICY_TABLE 动态决定。
# 注：拆书槽位在 prompt 中的插入位置由本模块的 _compose_slots 决定（synopsis 靠前，corpus 末尾）

SCENE_BUSINESS_TEMPLATES: dict[str, list[str]] = {
    "chapter_content": [
        # system 段：基础规则 → 拆书 style
        "system_role", "system_base_style",
        # user 段：业务必填 → 桥段约束 → 历史接续 → 输出要求
        "project_skeleton", "chapter_outline", "bridge_position",
        "history_full", "history_normal", "history_brief", "memory_topk",
        "output_spec",
    ],
    "chapter_outline": [
        "system_role", "system_base_style",
        "project_skeleton", "project_characters", "world_rules_table", "output_spec",
    ],
    "story_outline": [
        "system_role", "system_base_style",
        "project_skeleton", "output_spec",
    ],
    "bridge_planning": [
        # system 段：基础规则
        "system_role", "system_base_style",
        # user 段：项目骨架 → 本书角色 → 世界规则表 → V4.1 方案 C 剩情线节点配额 → 输出要求
        "project_skeleton", "project_characters", "world_rules_table",
        "plot_lines_with_beats", "output_spec",
    ],
    "scene_generation": [
        "system_role", "system_base_style",
        "project_skeleton", "chapter_outline", "history_full",
        "output_spec",
    ],
    "chapter_regenerate": [
        "system_role", "system_base_style",
        "project_skeleton", "chapter_outline", "history_full", "history_normal",
        "output_spec",
    ],
    "character": [
        "system_role", "system_base_style",
        "project_skeleton", "output_spec",
    ],
    "world_building": [
        "system_role", "system_base_style",
        "project_skeleton", "output_spec",
    ],
}


# ============================================================
# 启动期生成 PROMPT_BLUEPRINT
# ============================================================

def _make_business_slot(slot_name: str, tier: ModelTier) -> Slot:
    """根据 slot_name + tier 构造业务槽位。"""
    max_tokens = BUSINESS_SLOT_TOKENS[tier].get(slot_name, 200)

    if slot_name == "system_role":
        return Slot(slot_name, max_tokens, "system", required=True,
                    cacheable=True, cache_tier="global")
    if slot_name == "system_base_style":
        return Slot(slot_name, max_tokens, "system", required=True,
                    cacheable=True, cache_tier="global")
    if slot_name == "project_skeleton":
        return Slot(slot_name, max_tokens, "user", required=True,
                    cacheable=True, cache_tier="project")
    if slot_name == "chapter_outline":
        return Slot(slot_name, max_tokens, "user", "【本章信息】",
                    required=True, cacheable=False, cache_tier="chapter")
    if slot_name == "bridge_position":
        return Slot(slot_name, max_tokens, "user", "【🎯 桥段位置约束】",
                    cacheable=False, cache_tier="chapter")
    if slot_name == "plot_lines_with_beats":
        # V4.1 方案 C：项目级缓存（同一项目 bridge_planning 调用间剩情线不变）
        return Slot(slot_name, max_tokens, "user",
                    cacheable=True, cache_tier="project")
    if slot_name in ("project_characters", "world_rules_table"):
        # 项目自有资料：同一项目内不变 → 项目级缓存；空表 → 跳过
        return Slot(slot_name, max_tokens, "user",
                    cacheable=True, cache_tier="project")
    if slot_name == "history_full":
        return Slot(slot_name, max_tokens, "user", "【前置章节（完整摘要）】",
                    cacheable=False, cache_tier="chapter")
    if slot_name == "history_normal":
        return Slot(slot_name, max_tokens, "user", cacheable=False,
                    cache_tier="chapter")
    if slot_name == "history_brief":
        return Slot(slot_name, max_tokens, "user", cacheable=False,
                    cache_tier="chapter")
    if slot_name == "memory_topk":
        return Slot(slot_name, max_tokens, "user", "【🧠 智能记忆】",
                    cacheable=False, cache_tier="chapter")
    if slot_name == "output_spec":
        return Slot(slot_name, max_tokens, "user", required=True,
                    cacheable=False, cache_tier="chapter")

    # 未知 business slot 兜底
    return Slot(slot_name, max_tokens, "user")


def _make_dissect_slot(dim: str, strength: Strength) -> Slot:
    """根据维度名 + strength 构造拆书槽位。"""
    max_tokens = STRENGTH_BUDGET[strength]

    if dim == "style":
        # style 走 system 段（全局基调）
        return Slot(f"dissect_{dim}", max_tokens, "system",
                    label="**拆书参考文风**",
                    cacheable=True, cache_tier="project")
    if dim == "corpus":
        # corpus 动态检索，不缓存
        return Slot(f"dissect_{dim}", max_tokens, "user",
                    label=DISSECT_LABELS.get(dim, ""),
                    cacheable=False, cache_tier="chapter")
    if dim in ("bridges", "character_archive"):
        # 桥段范本和角色档案按章节动态选（基于 bridge_position）
        # bridges 在章节场景按位置选不缓存；其他场景缓存
        # 简化：均设为 chapter 不缓存
        return Slot(f"dissect_{dim}", max_tokens, "user",
                    label=DISSECT_LABELS.get(dim, ""),
                    cacheable=False, cache_tier="chapter")

    # methodology / structure / synopsis = 项目级缓存
    return Slot(f"dissect_{dim}", max_tokens, "user",
                label=DISSECT_LABELS.get(dim, ""),
                cacheable=True, cache_tier="project")


# 拆书槽位在 prompt 中的优先级（user 段内的插入顺序）
# 注：style 会被 _make_dissect_slot 放到 system 段，但仍需列在这里才会被 _compose_blueprint 处理
DISSECT_SLOT_ORDER = (
    "style",             # 文风指令 - 由 _make_dissect_slot 放到 system 段
    "synopsis",          # 全书骨架 - 靠前
    "methodology",
    "structure",
    "bridges",
    "character_archive",
    "corpus",            # 拆书卡片段 - 末尾
)


def _compose_blueprint(scene: str, tier: ModelTier) -> list[Slot]:
    """启动期：根据 SCENE_BUSINESS_TEMPLATES + POLICY_TABLE 组合一份装配单。

    顺序规则：
    1. system 段：system_role → system_base_style → dissect_style（如启用）
    2. user 段：project_skeleton → [synopsis 靠前] → chapter_outline → bridge_position
                → 其他拆书维度 → history → memory → [corpus 末尾] → output_spec
    """
    business_slots = [
        _make_business_slot(name, tier)
        for name in SCENE_BUSINESS_TEMPLATES.get(scene, [])
    ]

    # 取出该场景的拆书策略
    policy = POLICY_TABLE.get((scene, tier), {})
    dissect_slots = [
        _make_dissect_slot(dim, strength)
        for dim in DISSECT_SLOT_ORDER
        for strength in [policy.get(dim, "off")]
        if strength != "off"
    ]

    # ---- 按区域组合 ----
    system_business = [s for s in business_slots if s.section == "system"]
    user_business = [s for s in business_slots if s.section == "user"]
    system_dissect = [s for s in dissect_slots if s.section == "system"]
    user_dissect = [s for s in dissect_slots if s.section == "user"]

    # 在 user_business 中找各关键槽位的位置
    def find_idx(slots: list[Slot], name: str) -> int | None:
        for i, s in enumerate(slots):
            if s.name == name:
                return i
        return None

    # 把 synopsis 插在 project_skeleton 之后（如启用）
    user_combined = list(user_business)
    synopsis_slot = next(
        (s for s in user_dissect if s.name == "dissect_synopsis"), None
    )
    if synopsis_slot:
        idx = find_idx(user_combined, "project_skeleton")
        if idx is not None:
            user_combined.insert(idx + 1, synopsis_slot)
        else:
            user_combined.insert(0, synopsis_slot)

    # 其他拆书维度插在 bridge_position 之后（如没 bridge_position，则在 chapter_outline 之后）
    other_dissect = [s for s in user_dissect
                     if s.name not in ("dissect_synopsis", "dissect_corpus")]
    if other_dissect:
        anchor = find_idx(user_combined, "bridge_position")
        if anchor is None:
            anchor = find_idx(user_combined, "chapter_outline")
        if anchor is None:
            anchor = find_idx(user_combined, "project_skeleton")
        if anchor is None:
            anchor = 0
        for offset, s in enumerate(other_dissect):
            user_combined.insert(anchor + 1 + offset, s)

    # corpus 插在 memory_topk 之前（最末尾位置）
    corpus_slot = next(
        (s for s in user_dissect if s.name == "dissect_corpus"), None
    )
    if corpus_slot:
        anchor = find_idx(user_combined, "memory_topk")
        if anchor is None:
            anchor = find_idx(user_combined, "history_brief")
        if anchor is None:
            anchor = find_idx(user_combined, "output_spec")
        if anchor is not None:
            user_combined.insert(anchor, corpus_slot)
        else:
            user_combined.append(corpus_slot)

    # 最终：system_business + system_dissect + user_combined
    return system_business + system_dissect + user_combined


# 启动期一次性生成 32 份装配单（4 档 × 8 场景）
PROMPT_BLUEPRINT: dict[tuple[str, ModelTier], list[Slot]] = {
    (scene, tier): _compose_blueprint(scene, tier)
    for scene in SCENE_BUSINESS_TEMPLATES.keys()
    for tier in ("S", "M", "L", "XL")
}


# ============================================================
# CI 验证辅助函数
# ============================================================

def calc_blueprint_total(scene: str, tier: ModelTier) -> int:
    """计算一个 blueprint 的所有槽位 max_tokens 之和（输入 token）。"""
    slots = PROMPT_BLUEPRINT.get((scene, tier), [])
    return sum(s.max_tokens for s in slots)


def calc_total_with_output(scene: str, tier: ModelTier) -> int:
    """输入 + 输出预留的总占用（优先用 OUTPUT_RESERVE_BY_TIER）。"""
    output = OUTPUT_RESERVE_BY_TIER.get(
        (scene, tier),
        OUTPUT_RESERVE.get(scene, 4500),
    )
    return calc_blueprint_total(scene, tier) + output
