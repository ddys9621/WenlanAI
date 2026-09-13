"""V4.3 适配器：让现有 prompt_service 调用链路无缝接入 V4 PromptAssembler。

设计原则（零破坏）：
- 不动 prompt_service.get_chapter_generation_*（旧 prompt 模板保持原样）
- 提供 build_v4_dissect_segment() → 返回"拆书 + 桥段约束"的字符串
- 现有调用方把它塞入 mcp_references 参数即可

这样 8 个挂载点（chapters / scene_generation / chapter_regenerator / wizard_stream
worldbuilding/character/outline/bridge_planning）都可以用一行代码接入 V4，
不需要重写任何现有 prompt 拼装逻辑。

后续 Phase 4 V4.4 K5 Prompt Caching 完成后，再把这层逐步替换为完整 PromptAssembler 调用。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reference_pack.assembler import (
    AssembledPrompt,
    AssemblyContext,
    PromptAssembler,
)

logger = logging.getLogger(__name__)


# 这些标签代表"拆书产物"+"K2 桥段约束"段，应被纳入 V4 注入返回值
DISSECT_LABELS = (
    "【📚", "【🏗️", "【👤", "【🌍", "【🌉", "【👥", "【📖", "【💡",
    "【🎯",  # K2 桥段位置约束
    "**拆书参考文风",  # system 段的拆书 style
)

# 这些是"项目业务"段，现有 prompt 已经包含，V4 适配器不重复
BUSINESS_LABELS = ("【项目信息】", "【世界观】", "【本章信息】", "【🧠 智能记忆")


async def build_v4_dissect_segment(
    db: AsyncSession,
    project_id: str,
    scene: str,
    model_name: str = "deepseek-v3",
    *,
    chapter_outline_id: Optional[str] = None,
    target_word_count: int = 3000,
    bridge_position: Optional[str] = None,
    bridge_context: Optional[dict[str, Any]] = None,
    **extra,
) -> str:
    """V4 适配器：返回拼好的"拆书参考 + K2 桥段约束"段，可直接塞入 mcp_references 字段。

    Args:
        db: 数据库会话
        project_id: 项目 ID（必须有挂载的 ReferencePack 才有产出）
        scene: 'chapter_content' / 'scene_generation' / 'character' / ...
        model_name: 用于查 model tier（默认 deepseek-v3 = L 档）
        chapter_outline_id: 章纲 ID（用于 chapter_content 场景）
        target_word_count: 本章目标字数（影响桥段约束的字数计算）
        bridge_position: K2 桥段位置 'intro/build/payoff/aftermath'
        bridge_context: K2 桥段上下文 {title, goal, showoff_point, next_bridge_goal}
        extra: 透传到 AssemblyContext.extra

    Returns:
        拆书内容字符串。如果项目没挂载参考包/场景未在策略表 → 返回 ""（自然降级）

    Examples:
        >>> v4_seg = await build_v4_dissect_segment(
        ...     db, project_id="abc",
        ...     scene="chapter_content",
        ...     model_name="deepseek-v3",
        ...     chapter_outline_id=co.id,
        ...     bridge_position="intro",
        ...     bridge_context={"title": "拜师", "goal": "...", "showoff_point": "..."},
        ... )
        >>> # 现有 prompt 调用：
        >>> prompt = prompt_service.get_chapter_generation_with_context_prompt(
        ...     ...,
        ...     mcp_references=f"{mcp_refs}\\n\\n{v4_seg}" if v4_seg else mcp_refs,
        ... )
    """
    try:
        ctx = AssemblyContext(
            scene=scene,
            model_name=model_name,
            project_id=project_id,
            chapter_outline_id=chapter_outline_id,
            target_word_count=target_word_count,
            bridge_position=bridge_position,
            bridge_context=bridge_context,
            extra=extra,
        )
        prompt = await PromptAssembler().assemble(db, ctx)
    except ValueError as exc:
        logger.warning(
            "[v4_compat] 装配失败（场景未在策略表？）：scene=%s err=%s",
            scene, exc,
        )
        return ""
    except Exception as exc:
        logger.error(
            "[v4_compat] 装配异常: scene=%s err=%s", scene, exc, exc_info=True,
        )
        return ""

    return _extract_dissect_only(prompt)


def _extract_dissect_only(prompt: AssembledPrompt) -> str:
    """从 AssembledPrompt 中只取拆书+桥段约束相关段，跳过业务段和系统段。

    业务段（项目骨架/章纲/输出要求/记忆）已经在现有 prompt 模板里有，不重复。
    系统段（角色设定/基础文风）也已在现有 system_prompt 里。
    """
    out: list[str] = []
    # 从 user_blocks 中筛选拆书 + 桥段
    for block in prompt.user_blocks:
        text = block.get("text", "")
        if any(text.lstrip().startswith(lbl) for lbl in DISSECT_LABELS):
            out.append(text)

    # 从 system_blocks 中只取拆书 style（其他都已重复）
    for block in prompt.system_blocks:
        text = block.get("text", "")
        if text.lstrip().startswith("**拆书参考文风"):
            out.append(text)

    if not out:
        return ""

    return "\n\n".join(out)


async def build_v4_bridge_constraint_only(
    db: AsyncSession,
    project_id: str,
    scene: str = "chapter_content",
    model_name: str = "deepseek-v3",
    *,
    bridge_position: Optional[str] = None,
    bridge_context: Optional[dict[str, Any]] = None,
    chapter_outline_id: Optional[str] = None,
    target_word_count: int = 3000,
) -> str:
    """V4 K2 桥段位置约束适配器 — 仅返回桥段约束块，不返回拆书维度。

    使用场景：现有挂载点已经在用 v3 ReferencePackInjector（cherry-pick 恢复），
    职责分工：
    - v3 ReferencePackInjector 负责拆书维度（methodology / style / structure / ...）
    - V4 此函数负责 K2 桥段位置约束（C1/C2/C3/C4 模板）

    Returns:
        K2 桥段约束字符串。无桥段（bridge_position 为空）→ ""
    """
    if not bridge_position or not bridge_context:
        return ""

    try:
        ctx = AssemblyContext(
            scene=scene,
            model_name=model_name,
            project_id=project_id,
            chapter_outline_id=chapter_outline_id,
            target_word_count=target_word_count,
            bridge_position=bridge_position,
            bridge_context=bridge_context,
        )
        prompt = await PromptAssembler().assemble(db, ctx)
    except Exception as exc:
        logger.warning(
            "[v4_compat] 桥段约束装配失败: scene=%s position=%s err=%s",
            scene, bridge_position, exc,
        )
        return ""

    # 只取以【🎯 开头的桥段约束段
    out: list[str] = []
    for block in prompt.user_blocks:
        text = block.get("text", "")
        if text.lstrip().startswith("【🎯"):
            out.append(text)

    return "\n\n".join(out)


async def fetch_bridge_context(
    db: AsyncSession, chapter_outline: Any
) -> Optional[dict[str, Any]]:
    """根据 ChapterOutline 取出桥段上下文（含 next_bridge_goal 与题材模板 template）。

    Args:
        chapter_outline: ChapterOutline ORM 对象（含 bridge_id）

    Returns:
        bridge_context dict，或 None（章纲无 bridge_id / 桥段不存在）
    """
    if not chapter_outline or not getattr(chapter_outline, "bridge_id", None):
        return None

    try:
        from sqlalchemy import select
        from app.models.plot_bridge import PlotBridge

        bridge = (await db.execute(
            select(PlotBridge).where(PlotBridge.id == chapter_outline.bridge_id)
        )).scalar_one_or_none()
        if not bridge:
            return None

        # 查上下桥段：下桥段目标给 C4 引子，上桥段钩子给非开篇 C1 承接
        neighbours = (await db.execute(
            select(PlotBridge)
            .where(PlotBridge.project_id == bridge.project_id)
            .where(PlotBridge.bridge_number.in_([bridge.bridge_number - 1, bridge.bridge_number + 1]))
        )).scalars().all()
        next_bridge = next((b for b in neighbours if b.bridge_number == bridge.bridge_number + 1), None)
        prev_bridge = next((b for b in neighbours if b.bridge_number == bridge.bridge_number - 1), None)

        # 题材模板：优先桥段填充时记录的 generation_meta.template，否则按项目 genre 解析
        import json

        from app.models.project import Project
        from app.services.bridge_hook_style import normalize_c3_hook_style
        from app.services.bridge_templates import resolve_template

        recorded = None
        if getattr(bridge, "generation_meta", None):
            try:
                recorded = (json.loads(bridge.generation_meta) or {}).get("template")
            except (json.JSONDecodeError, TypeError, AttributeError):
                recorded = None
        project = (await db.execute(
            select(Project).where(Project.id == bridge.project_id)
        )).scalar_one_or_none()
        template_key = resolve_template(getattr(project, "genre", None), explicit_key=recorded).key

        try:
            secondary = json.loads(bridge.secondary_beats) if bridge.secondary_beats else []
        except (json.JSONDecodeError, TypeError):
            secondary = []
        primary_secondary = "；".join(
            f"{t.get('line_type')}《{t.get('line_title')}》[节点 {t.get('beat_index')}] {t.get('beat_title')}"
            + (f"：{str(t['beat_description'])[:100]}" if t.get("beat_description") else "")
            for t in secondary
            if isinstance(t, dict) and t.get("role", "primary") != "mention"
        )

        # 桥段形态：节点收官 / 全书高潮节点收官（需要主线节点权重定位高潮节点）
        from app.services.bridge_shapes import SHAPE_STANDARD, bridge_shape, climax_beat_index
        from app.services.bridge_slot_planner import parse_plot_line

        shape = SHAPE_STANDARD
        if bridge.plot_line_id and bridge.beat_index is not None:
            from app.models.plot_line import PlotLine

            line = (await db.execute(select(PlotLine).where(PlotLine.id == bridge.plot_line_id))).scalar_one_or_none()
            climax = climax_beat_index(parse_plot_line(line)) if line is not None else None
            shape = bridge_shape(bridge.beat_coverage_end, bridge.beat_index, climax)

        return {
            "title": bridge.title,
            "goal": bridge.goal,
            "showoff_point": bridge.showoff_point,
            "next_bridge_goal": next_bridge.goal if next_bridge else "（下一桥段未设定）",
            "template": template_key,
            "primary_secondary": primary_secondary,
            "opening": bridge.bridge_number == 1,
            "prev_bridge_hook": (prev_bridge.next_bridge_hook or "") if prev_bridge else "",
            "shape": shape,
            "c3_hook_style": normalize_c3_hook_style(getattr(project, "c3_hook_style", None)),
        }
    except Exception as exc:
        logger.warning("[v4_compat] fetch_bridge_context 失败: %s", exc)
        return None
