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
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reference_pack.assembler import (
    AssembledPrompt,
    AssemblyContext,
    PromptAssembler,
)

logger = logging.getLogger(__name__)


# 这些标签代表"拆书产物"段，应被纳入 V4 注入返回值
DISSECT_LABELS = (
    "【📚", "【🏗️", "【👤", "【🌍", "【🌉", "【👥", "【📖", "【💡",
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
    **extra,
) -> str:
    """V4 适配器：返回拼好的"拆书参考"段，可直接塞入 mcp_references 字段。

    Args:
        db: 数据库会话
        project_id: 项目 ID（必须有挂载的 ReferencePack 才有产出）
        scene: 'chapter_content' / 'scene_generation' / 'character' / ...
        model_name: 用于查 model tier（默认 deepseek-v3 = L 档）
        chapter_outline_id: 章纲 ID（用于 chapter_content 场景）
        target_word_count: 本章目标字数
        extra: 透传到 AssemblyContext.extra

    Returns:
        拆书内容字符串。如果项目没挂载参考包/场景未在策略表 → 返回 ""（自然降级）

    Examples:
        >>> v4_seg = await build_v4_dissect_segment(
        ...     db, project_id="abc",
        ...     scene="chapter_content",
        ...     model_name="deepseek-v3",
        ...     chapter_outline_id=co.id,
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
