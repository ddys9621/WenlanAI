"""V4.3 槽位 builder 函数（Phase 1 骨架版本）。

每个 builder 接收 (db, ctx) → 返回该槽位的字符串内容（或空字符串表示跳过）。

设计原则：
- builder 函数纯异步、纯查表/纯字符串拼接，不调用 LLM
- 失败时返回空字符串（被 assembler 标 skipped）
- required 槽位空返回 → assembler 抛 ValueError

Phase 1 骨架版本：
- 业务必填槽位（system_role / chapter_outline / project_skeleton / output_spec）实现最小可用版
- 历史接续/记忆/桥段位置等先返回基础占位，留 TODO 给后续完善
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ============================================================
# system 段 builder
# ============================================================

async def build_system_role(db: AsyncSession, ctx: Any) -> str:
    """系统角色定位（全局静态，可缓存）。"""
    genre = (ctx.genre or "网文").strip()
    return (
        f"你是一个在起点、番茄写了几百万字的网文老作者，主写{genre}。\n"
        "你必须严格遵守用户给出的所有创作约束。"
    )


async def build_system_base_style(db: AsyncSession, ctx: Any) -> str:
    """基础叙事原则（全局静态，跨项目复用，可缓存）。与 prompt_service.CHAPTER_STYLE_RULES 同一套口径的短版。"""
    perspective = ctx.narrative_perspective or "第三人称"
    return f"""**基础叙事原则（网文大白话）：**
- 必须使用{perspective}视角稳稳讲故事
- 段落短（一段最多三句）、对话多、叙述贴着主角的口气走，读起来像手机上的连载，不是文学散文
- 短句为主，长短错开，别连续三句一样长，不排比
- 情绪先写人做了什么，再直接点名（"他慌了"）；胸口发紧、心跳加速这类身体渲染一章最多一两处
- 书面词换成嘴上会说的：随即→然后、些许→有点、眸→眼、宛如→像
- ❌ 不用"道心坚定""一往无前""天地本质"等套路语，不用"为了天下苍生""更大的使命"等宏大主题，不用排比总结主角心理
- ✅ 结尾停在具体动作、一句话或一个声音上，最好是钩子"""


# ============================================================
# user 段 业务 builder
# ============================================================

async def build_project_skeleton(db: AsyncSession, ctx: Any) -> str:
    """项目基本信息（项目级缓存）。"""
    from app.models.project import Project

    result = await db.execute(select(Project).where(Project.id == ctx.project_id))
    project = result.scalar_one_or_none()
    if not project:
        # 兜底：用 ctx 中的元数据
        title = ctx.title or "未命名"
        return f"【项目信息】\n书名：{title}"

    lines = [
        "【项目信息】",
        f"书名：{project.title or ctx.title or '未命名'}",
        f"主题：{project.theme or ctx.theme or '未设定'}",
        f"类型：{project.genre or ctx.genre or '网文'}",
        f"视角：{project.narrative_perspective or ctx.narrative_perspective or '第三人称'}",
        "",
        "【世界观】",
        f"时间：{project.world_time_period or '未设定'}",
        f"地点：{project.world_location or '未设定'}",
        f"氛围：{project.world_atmosphere or '未设定'}",
    ]
    if project.world_rules:
        lines.append(f"规则：{project.world_rules[:600]}")
    return "\n".join(lines)


async def build_chapter_outline(db: AsyncSession, ctx: Any) -> str:
    """本章信息（章节级动态，不缓存）。"""
    if not ctx.chapter_outline_id:
        return ""
    from app.models.chapter_outline import ChapterOutline

    result = await db.execute(
        select(ChapterOutline).where(ChapterOutline.id == ctx.chapter_outline_id)
    )
    co = result.scalar_one_or_none()
    if not co:
        return ""

    lines = [
        f"第{co.chapter_number}章：{co.title}",
    ]
    if co.scene:
        lines.append(f"- 场景：{co.scene}")
    if co.pov:
        lines.append(f"- 视角：{co.pov}")
    if co.plot_points:
        lines.append(f"- 剧情要点：{co.plot_points}")
    if co.key_events:
        lines.append(f"- 关键事件：{co.key_events}")
    if co.characters_involved:
        lines.append(f"- 涉及角色：{co.characters_involved}")
    lines.append(f"- 目标字数：{ctx.target_word_count}")
    return "\n".join(lines)


def _clip(value: Any, limit: int) -> str:
    """单行化 + 截断：换行压成空格，供角色/规则表一行一条。"""
    text = " ".join(str(value or "").split())
    return text[:limit]


_ROLE_LABEL = {"protagonist": "主角", "antagonist": "反派", "supporting": "配角"}
_ROLE_ORDER = {"protagonist": 0, "antagonist": 1, "supporting": 2}


async def build_project_characters(db: AsyncSession, ctx: Any) -> str:
    """【👥 本书角色】项目自有角色与组织（项目级缓存）。

    评审问题 A：没有这段时 LLM 只能从节点描述里捞名字，捞不到就自己编，跨批次人名漂移。
    主角 → 反派 → 配角 → 组织；人物最多 12 个、组织最多 6 个，一行一条。
    """
    from app.models.character import Character

    result = await db.execute(
        select(Character)
        .where(Character.project_id == ctx.project_id)
        .order_by(Character.created_at, Character.id)
    )
    rows = [c for c in result.scalars().all() if (c.name or "").strip()]
    if not rows:
        return ""

    people = sorted(
        (c for c in rows if not c.is_organization),
        key=lambda c: _ROLE_ORDER.get(c.role_type or "", 3),
    )[:12]
    orgs = [c for c in rows if c.is_organization][:6]

    lines = ["【👥 本书角色（人名/称呼必须与此一致，不得另起新名）】"]
    for c in people:
        meta = "·".join(x for x in (_ROLE_LABEL.get(c.role_type or "", c.role_type or ""), c.gender or "", c.age or "") if x)
        desc = "｜".join(x for x in (_clip(c.personality, 60), _clip(c.background, 60)) if x)
        head = f"- {c.name}（{meta}）" if meta else f"- {c.name}"
        lines.append(f"{head}：{desc}" if desc else head)
    if orgs:
        lines.append("组织/势力：")
        for o in orgs:
            desc = "｜".join(x for x in (_clip(o.organization_type, 30), _clip(o.organization_purpose, 60)) if x)
            lines.append(f"- {o.name}：{desc}" if desc else f"- {o.name}")
    return "\n".join(lines)


_RULE_CATEGORY_LABEL = {
    "cultivation_realm": "能力/地位层级",
    "equipment_template": "资源/载体系统",
    "map_location": "地图/地点",
}
_LADDER_CATEGORIES = {"cultivation_realm"}


async def build_world_rules_table(db: AsyncSession, ctx: Any) -> str:
    """【📜 世界规则表】WorldRule 按分类汇总（项目级缓存）。

    层级类（境界/等级）按 order_index 串成阶梯，供桥段规划把升级节奏铺在正确位置；
    其余分类一行列出 name（summary）。
    """
    from app.models.world_rule import WorldRule

    result = await db.execute(
        select(WorldRule)
        .where(WorldRule.project_id == ctx.project_id)
        .order_by(WorldRule.category, WorldRule.order_index, WorldRule.name)
    )
    rules = result.scalars().all()
    if not rules:
        return ""

    by_cat: dict[str, list[Any]] = {}
    for r in rules:
        by_cat.setdefault(r.category, []).append(r)

    lines = ["【📜 世界规则表（设定硬约束，不得违背）】"]
    for cat, items in by_cat.items():
        label = _RULE_CATEGORY_LABEL.get(cat, cat)
        if cat in _LADDER_CATEGORIES:
            lines.append(f"- {label}：{' → '.join(r.name for r in items[:12])}")
            continue
        parts = [f"{r.name}（{_clip(r.summary, 40)}）" if r.summary else r.name for r in items[:8]]
        lines.append(f"- {label}：{'；'.join(parts)}")
    return "\n".join(lines)


async def build_world_map(db: AsyncSession, ctx: Any) -> str:
    """【🗺 世界地图】作者在地图上摆好的地点布局（项目级缓存）：章纲展开 / 桥段规划按它安排场景与行程。"""
    from app.services.world_map_context import map_overview

    overview = await map_overview(db, ctx.project_id)
    return f"【🗺 世界地图】\n{overview}" if overview else ""


async def build_history_full(db: AsyncSession, ctx: Any) -> str:
    """最近 N 章的完整摘要（按 HISTORICAL_CONTEXT_TABLE.full_count）。

    Phase 1 骨架：先返回空（等 V4.4 P2 Chapter summary_full 字段就绪后补全）。
    """
    return ""


async def build_history_normal(db: AsyncSession, ctx: Any) -> str:
    """中段章节摘要。Phase 1 骨架版返回空。"""
    return ""


async def build_history_brief(db: AsyncSession, ctx: Any) -> str:
    """早段章节摘要。Phase 1 骨架版返回空。"""
    return ""


async def build_memory_topk(db: AsyncSession, ctx: Any) -> str:
    """智能记忆 top-K（依赖现有 memory_service）。

    Phase 1 骨架：先返回空，待整合现有 MemoryService.search_memories。
    """
    return ""


async def build_output_spec(db: AsyncSession, ctx: Any) -> str:
    """输出要求（章节级，但内容稳定）。"""
    if ctx.scene == "chapter_content":
        word_count = ctx.target_word_count or 3000
        soft_low = int(word_count * 0.9)
        soft_high = int(word_count * 1.1)
        return (
            f"请直接输出正文，不要章节标题。\n"
            f"目标字数：{word_count}（允许范围 {soft_low}-{soft_high}）"
        )
    return "请按 JSON 格式输出结果，不要任何 markdown 标记。"


# ============================================================
# builder 注册表（assembler 按 slot.name 查找）
# ============================================================

SLOT_BUILDERS: dict[str, Callable[[AsyncSession, Any], Awaitable[str]]] = {
    # system 段
    "system_role":            build_system_role,
    "system_base_style":      build_system_base_style,
    # user 段 - 必填业务
    "project_skeleton":       build_project_skeleton,
    "chapter_outline":        build_chapter_outline,
    "output_spec":            build_output_spec,
    # user 段 - 业务
    "project_characters":     build_project_characters,     # 评审问题 A：本书角色
    "world_rules_table":      build_world_rules_table,      # 评审问题 A：世界规则表
    "world_map":              build_world_map,              # 世界地图：地点方位远近
    "history_full":           build_history_full,
    "history_normal":         build_history_normal,
    "history_brief":          build_history_brief,
    "memory_topk":            build_memory_topk,
}

