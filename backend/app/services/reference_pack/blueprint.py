"""V4.3 Prompt Blueprint 装配单（详见 v4_design.md §10.2.4）。

核心原则：
- 每个 (scene, tier) 对应一份『槽位 + max_tokens』装配单
- 装配单在模块加载时一次性生成（启动期计算）
- 运行时只做 SELECT + 截断，零 if/else 分支
- 总长度可静态算、CI 验证、上下文窗口永不超

设计：
- Slot：单个 prompt 槽位（含 max_tokens 硬上限）
- SCENE_BUSINESS_TEMPLATES：7 场景的"槽位顺序模板"（不含 max_tokens）
- BUSINESS_SLOT_TOKENS：业务槽位的固定 token 上限
- PROMPT_BLUEPRINT：最终生成的 28 份装配单 dict[(scene, tier)] -> list[Slot]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.reference_pack.policy_tables import ModelTier


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

# 业务槽位（非拆书）的固定 token 上限（按档位）
# 注：所有 4 档基础占用大致一致，XL 档放宽 project_skeleton 等
BUSINESS_SLOT_TOKENS: dict[ModelTier, dict[str, int]] = {
    "S": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 600, "chapter_outline": 400,
        "project_characters": 400, "world_rules_table": 300,
        "world_map": 120,
        "history_full": 400, "history_normal": 200, "history_brief": 160,
        "memory_topk": 400,
        "output_spec": 150,
    },
    "M": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 1200, "chapter_outline": 500,
        "project_characters": 600, "world_rules_table": 400, "world_map": 400,
        "history_full": 400, "history_normal": 400, "history_brief": 240,
        "memory_topk": 1000,
        "output_spec": 150,
    },
    "L": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 1500, "chapter_outline": 500,
        "project_characters": 800, "world_rules_table": 600, "world_map": 600,
        "history_full": 400, "history_normal": 400, "history_brief": 560,
        "memory_topk": 1500,
        "output_spec": 150,
    },
    "XL": {
        "system_role": 100, "system_base_style": 700,
        "project_skeleton": 2000, "chapter_outline": 500,
        "project_characters": 1200, "world_rules_table": 800, "world_map": 800,
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
OUTPUT_RESERVE: dict[str, int] = {
    "chapter_content":    4500,
    "chapter_regenerate": 4500,
    "chapter_outline":    3000,  # 批量生成 N 个章纲
    "story_outline":      2000,
    "volume_planning":    6000,  # 全书分卷 / 一卷的剧情单元 JSON
    "character":          2000,
    "world_building":     1500,
}

# 场景 + 档位组合的输出预留覆盖（精细控制，覆盖 OUTPUT_RESERVE）
OUTPUT_RESERVE_BY_TIER: dict[tuple[str, ModelTier], int] = {
    ("volume_planning", "S"): 4000,
    ("volume_planning", "M"): 5000,
}


# CI 单测的安全比率：装配单总占用不超过窗口的 60%
SAFETY_RATIO = 0.6


# ============================================================
# 场景定义：每个场景需要哪些"业务槽位"（按出现顺序）
# ============================================================

# 7 场景的业务槽位模板（system 段在前、user 段在后，按出现顺序）。

SCENE_BUSINESS_TEMPLATES: dict[str, list[str]] = {
    "chapter_content": [
        # system 段：基础规则 → 拆书 style
        "system_role", "system_base_style",
        # user 段：业务必填 → 历史接续 → 输出要求
        "project_skeleton", "chapter_outline",
        "history_full", "history_normal", "history_brief", "memory_topk",
        "output_spec",
    ],
    "chapter_outline": [
        "system_role", "system_base_style",
        "project_skeleton", "project_characters", "world_rules_table", "world_map", "output_spec",
    ],
    "story_outline": [
        "system_role", "system_base_style",
        "project_skeleton", "output_spec",
    ],
    "volume_planning": [
        # system 段：基础规则
        "system_role", "system_base_style",
        # user 段：项目骨架 → 本书角色 → 世界规则表 → 世界地图 → 输出要求（总纲 / 卷纲由卷纲服务拼在后面）
        "project_skeleton", "project_characters", "world_rules_table", "world_map", "output_spec",
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
    if slot_name in ("project_characters", "world_rules_table", "world_map"):
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


def _compose_blueprint(scene: str, tier: ModelTier) -> list[Slot]:
    """启动期：按 SCENE_BUSINESS_TEMPLATES 组合一份装配单（system 段在前、user 段在后）。"""
    slots = [_make_business_slot(name, tier) for name in SCENE_BUSINESS_TEMPLATES.get(scene, [])]
    return [s for s in slots if s.section == "system"] + [s for s in slots if s.section == "user"]


# 启动期一次性生成 28 份装配单（4 档 × 7 场景）
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
