"""V4.3 槽位 builder 函数（Phase 1 骨架版本）。

每个 builder 接收 (db, ctx) → 返回该槽位的字符串内容（或空字符串表示跳过）。

设计原则：
- builder 函数纯异步、纯查表/纯字符串拼接，不调用 LLM
- 失败时返回空字符串（被 assembler 标 skipped）
- required 槽位空返回 → assembler 抛 ValueError
- 拆书 builder（dissect_*）直接 SELECT ReferencePack 预压缩字段（V4.4 K5 三档）

Phase 1 骨架版本：
- 业务必填槽位（system_role / chapter_outline / project_skeleton / output_spec）实现最小可用版
- 拆书槽位实现 SELECT 预压缩字段的查询逻辑
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


async def build_dissect_style(db: AsyncSession, ctx: Any) -> str:
    """拆书文风指令（项目级缓存）。

    实现：SELECT 项目挂载的第一个 ReferencePack 的 style_<strength> 字段。
    """
    pack = await _get_first_attached_pack(db, ctx.project_id)
    if not pack:
        return ""
    strength = _get_strength_for(ctx, "style")
    text = pack.get_precompressed("style", strength)
    if not text:
        return ""
    book_title = getattr(pack, "source_book_title", "") or ""
    return f"**拆书参考文风（来源：《{book_title}》）：**\n{text}"


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


async def build_plot_lines_with_beats(db: AsyncSession, ctx: Any) -> str:
    """主线节点 + 桥段配额（由 bridge_slot_planner 确定）+ 副线节点概览。

    供 bridge_planning 场景填充桥段时了解全书骨架。前置不满足（无唯一主线 / 无节点）返回空串。
    配额与章号完全来自 compute_bridge_slots，与骨架建表用同一算法，保证 prompt 与 DB 一致。
    """
    from app.models.plot_line import PlotLine
    from app.services.bridge_slot_planner import (
        BridgePlanningPreconditionError,
        compute_bridge_slots,
        parse_plot_line,
    )

    result = await db.execute(
        select(PlotLine).where(PlotLine.project_id == ctx.project_id).order_by(PlotLine.order_index)
    )
    lines = [parse_plot_line(l) for l in result.scalars().all()]
    try:
        plan = compute_bridge_slots(lines)
    except BridgePlanningPreconditionError:
        return ""

    main = next(l for l in lines if l.id == plan.main_line_id)
    chunks: list[str] = ["【📈 全书骨架：主线节点 → 桥段配额】"]
    chunks.append(
        f"总桥段数：{plan.total_bridges}；总章数：{plan.total_chapters}；每桥段 4 章，配额由系统按节点权重确定。"
    )
    chunks.append(f"\n▼ 主线：{main.title}")
    for beat in main.beats:
        quota = plan.beat_quotas.get(beat.index, 0)
        beat_slots = [s for s in plan.slots if s.beat_index == beat.index]
        c_start = beat_slots[0].chapter_start if beat_slots else 0
        c_end = beat_slots[-1].chapter_end if beat_slots else 0
        desc_part = f"｜{beat.description[:60]}" if beat.description else ""
        chunks.append(
            f"  [节点 {beat.index}] {beat.title}  权重 {beat.weight:.0%}  → {quota} 个桥段（第 {c_start}-{c_end} 章）{desc_part}"
        )

    label = {"sub": "支线", "character": "角色线"}
    mode_label = {"companion": "伴生", "inserted": "插入", "converge": "汇流"}
    budgets = {b.plot_line_id: b for b in plan.line_budgets}
    for line in lines:
        if line.line_type == "main" or not line.beats:
            continue
        budget = budgets.get(line.id)
        if budget is not None and budget.anchored:
            head = (
                f"{mode_label.get(line.mode or '', line.mode)}型，锚定主线节点 {line.anchor_start_beat}-{line.anchor_end_beat}，"
                f"预算 {line.estimated_chapters} 章 ≈ 主推 {budget.primary_quota} 个桥段"
                f"（实际主推 {budget.primary_bridges}，保温 {budget.mention_bridges}）"
            )
        else:
            head = "未锚定，按进度比例挂到主线桥段"
        chunks.append(f"\n▼ {label.get(line.line_type, '其他')}：{line.title}（{head}）")
        for beat in line.beats:
            desc_part = f"｜{beat.description[:60]}" if beat.description else ""
            anchor_part = ""
            if beat.anchor_beat is not None:
                anchor_part = f"  → 主线节点 {beat.anchor_beat}{'（汇流）' if beat.relation == 'merge' else ''}"
            chunks.append(f"  [节点 {beat.index}] {beat.title}  权重 {beat.weight:.0%}{anchor_part}{desc_part}")
    return "\n".join(chunks)

async def build_bridge_position(db: AsyncSession, ctx: Any) -> str:
    """K2 桥段位置约束（章节级，不缓存）。

    Phase 2 完整版：使用 bridge_position_prompts 的 4 套 prompt 模板。
    """
    if not ctx.bridge_position or not ctx.bridge_context:
        return ""

    from app.services.reference_pack.bridge_position_prompts import (
        format_position_constraint,
    )

    text = format_position_constraint(
        position=ctx.bridge_position,
        bridge_title=ctx.bridge_context.get("title", "未命名桥段"),
        bridge_goal=ctx.bridge_context.get("goal", ""),
        bridge_showoff=ctx.bridge_context.get("showoff_point", ""),
        target_word_count=ctx.target_word_count or 3000,
        next_bridge_goal=ctx.bridge_context.get(
            "next_bridge_goal", "（下一桥段未设定）"
        ),
        template=ctx.bridge_context.get("template") or "showoff",
        opening=ctx.bridge_context.get("opening"),
        prev_bridge_hook=ctx.bridge_context.get("prev_bridge_hook") or "",
        shape=ctx.bridge_context.get("shape") or "standard",
        c3_hook_style=ctx.bridge_context.get("c3_hook_style") or "none",
    )
    primary_secondary = ctx.bridge_context.get("primary_secondary")
    if text and primary_secondary:
        text += (
            f"\n\n【🧵 本桥段主 B 线】{primary_secondary}\n"
            "本章可用 1-2 个场景推进这条支线（放在不与上面位置语义冲突的位置），不得让它抢走本章主线重心。"
        )
    return text


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
# 拆书 user 段 builder（统一查 ReferencePack 预压缩字段）
# ============================================================

def _make_dissect_builder(dimension: str) -> Callable[[AsyncSession, Any], Awaitable[str]]:
    """工厂：生成读取指定维度预压缩字段的 builder。

    优先级（V4.4 K5 三档预压缩生效后）：
    1. 优先返回预压缩字段（pack.<dim>_<strength>）→ 由拆书时一次性生成 + 写 DB
    2. fallback：实时调 dimension_compressor 从 _json 字段计算（首次访问）
       - 比之前的"粗暴 substring 截断"质量高得多
       - 性能：纯字典遍历 + 字符串拼接，几毫秒级
       - 对 204 章已有拆书数据无需迁移
    """
    async def _builder(db: AsyncSession, ctx: Any) -> str:
        pack = await _get_first_attached_pack(db, ctx.project_id)
        if not pack:
            return ""
        strength = _get_strength_for(ctx, dimension)
        # 1. 优先取已写 DB 的预压缩
        text = pack.get_precompressed(dimension, strength)
        if text:
            return text
        # 2. fallback：实时调 compressor
        json_text = getattr(pack, f"{dimension}_json", None)
        if not json_text:
            return ""
        from app.services.reference_pack.dimension_compressor import compress_dimension
        try:
            return compress_dimension(
                json_text, dimension, strength,
                pipeline_version=int(getattr(pack, "pipeline_version", None) or 2),
            ) or ""
        except Exception as exc:  # pragma: no cover - 防御性
            logger.warning(
                "compressor 失败 dim=%s strength=%s err=%s", dimension, strength, exc
            )
            # 极端情况降级：粗暴 substring（旧 fallback）
            max_chars = {"light": 130, "medium": 400, "deep": 1000}.get(strength, 400)
            return json_text[:max_chars] + ("…(截断)" if len(json_text) > max_chars else "")

    _builder.__name__ = f"build_dissect_{dimension}"
    return _builder


build_dissect_methodology = _make_dissect_builder("methodology")
build_dissect_structure = _make_dissect_builder("structure")
build_dissect_synopsis = _make_dissect_builder("synopsis")
build_dissect_bridges = _make_dissect_builder("bridges")
build_dissect_char_arch = _make_dissect_builder("character_archive")


async def build_dissect_corpus(db: AsyncSession, ctx: Any) -> str:
    """corpus 走 BM25 动态检索（不读预压缩）。

    Phase 1 骨架：先返回空。
    完整版（V4.4 K6 P2 Contextual Retrieval）会调 HybridCorpusRetriever。
    """
    return ""


# ============================================================
# helpers
# ============================================================

async def _get_first_attached_pack(db: AsyncSession, project_id: str):
    """SELECT 项目挂载的第一个 ReferencePack（按 attached_at 排序）。"""
    if not project_id:
        return None
    try:
        from app.models.reference_pack import ReferencePack
        from app.models.project_reference_pack import ProjectReferencePack
    except ImportError:
        return None

    result = await db.execute(
        select(ReferencePack)
        .join(ProjectReferencePack, ProjectReferencePack.pack_id == ReferencePack.id)
        .where(ProjectReferencePack.project_id == project_id)
        .order_by(ProjectReferencePack.attached_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


def _get_strength_for(ctx: Any, dimension: str) -> str:
    """查 (scene, tier) → policy → strength。"""
    from app.services.reference_pack.policy_tables import get_policy
    policy = get_policy(ctx.scene, ctx.model_name)
    return policy.get(dimension, "off")


# ============================================================
# builder 注册表（assembler 按 slot.name 查找）
# ============================================================

SLOT_BUILDERS: dict[str, Callable[[AsyncSession, Any], Awaitable[str]]] = {
    # system 段
    "system_role":            build_system_role,
    "system_base_style":      build_system_base_style,
    "dissect_style":          build_dissect_style,
    # user 段 - 必填业务
    "project_skeleton":       build_project_skeleton,
    "chapter_outline":        build_chapter_outline,
    "output_spec":            build_output_spec,
    # user 段 - 业务
    "bridge_position":        build_bridge_position,
    "plot_lines_with_beats":  build_plot_lines_with_beats,  # V4.1 方案 C
    "project_characters":     build_project_characters,     # 评审问题 A：本书角色
    "world_rules_table":      build_world_rules_table,      # 评审问题 A：世界规则表
    "history_full":           build_history_full,
    "history_normal":         build_history_normal,
    "history_brief":          build_history_brief,
    "memory_topk":            build_memory_topk,
    # user 段 - 拆书 V5 维度（synopsis / methodology / structure / bridges / character_archive / corpus）
    "dissect_methodology":    build_dissect_methodology,
    "dissect_structure":      build_dissect_structure,
    "dissect_synopsis":       build_dissect_synopsis,
    "dissect_corpus":         build_dissect_corpus,
    "dissect_bridges":        build_dissect_bridges,
    "dissect_character_archive": build_dissect_char_arch,
}


# 供 bridge_planning_service 生成 provenance 时取参考包标题
get_first_attached_pack = _get_first_attached_pack
