"""V4.3 PromptAssembler：按 blueprint 装配单遍历填充 + 硬截断（v4_design.md §10.5.1）。

核心原则：
- 唯一的 for 循环遍历 blueprint 槽位
- builder 产出超过 max_tokens → 硬截断
- 零 budget 计算、零 if/else 分支、零 fallback
- 同 (scene, model_name) + 同 ctx = 完全相同的 prompt（可复现）

公开 API：
    async with AsyncSession() as db:
        prompt = await PromptAssembler().assemble(db, AssemblyContext(
            scene='chapter_content',
            model_name='deepseek-v3',
            project_id='...',
            chapter_id='...',
        ))
        # prompt.system_prompt / prompt.user_prompt 可直接发给 AI service
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reference_pack.blueprint import (
    PROMPT_BLUEPRINT,
    Slot,
)
from app.services.reference_pack.policy_tables import (
    get_model_tier,
    normalize_model_name,
)
from app.services.reference_pack.slot_builders import SLOT_BUILDERS

logger = logging.getLogger(__name__)


# ============================================================
# 中文字符 → token 估算比（按模型族）
# ----------------------------------------------------------------
# 各家 tokenizer 对中文效率差异很大：DeepSeek/Qwen ≈ 0.6-0.75 token/字，
# GPT-4o(o200k) ≈ 1，Claude ≈ 1.3-1.5。统一按 1.5 估算会让国产模型的槽位
# 预算只剩一半（600 tokens 只装 400 字）。估算偏大只会少装内容，偏小才有
# 超窗风险，因此每族取公开数据的上沿。
# ============================================================

CHAR_TOKEN_RATIO_BY_FAMILY: tuple[tuple[str, float], ...] = (
    ("claude", 1.5),
    ("gpt", 1.0), ("o1", 1.0), ("o3", 1.0), ("o4", 1.0),
    ("gemini", 1.0),
    ("deepseek", 0.75), ("qwen", 0.75),
    ("glm", 0.8), ("doubao", 0.8), ("moonshot", 0.8), ("kimi", 0.8),
    ("yi-", 0.8), ("ernie", 0.8), ("hunyuan", 0.8), ("minimax", 0.8),
)
DEFAULT_CHAR_TOKEN_RATIO = 1.2


def char_token_ratio(model_name: str) -> float:
    """按模型族查中文字/token 比；未知模型族用保守默认值。"""
    name = normalize_model_name(model_name)
    for prefix, ratio in CHAR_TOKEN_RATIO_BY_FAMILY:
        if name.startswith(prefix):
            return ratio
    return DEFAULT_CHAR_TOKEN_RATIO


# ============================================================
# 数据结构
# ============================================================

@dataclass
class AssemblyContext:
    """所有生成场景的统一组装上下文。

    业务方根据场景填充必要字段，未用到的字段保持默认值。
    """
    scene: str                                # 必填：'chapter_content' / 'character' / ...
    model_name: str                           # 必填：用于查 model tier
    project_id: str                           # 必填

    # 章节相关（chapter_content / scene_generation / chapter_regenerate）
    chapter_id: Optional[str] = None
    chapter_outline_id: Optional[str] = None
    target_word_count: int = 3000

    # 场景生成
    plot_card_id: Optional[str] = None

    # 角色生成
    role_type: Optional[str] = None
    user_input: Optional[str] = None

    # 重生成
    modification_instructions: Optional[str] = None

    # 灵感 / 元数据（不依赖项目，部分场景用）
    title: Optional[str] = None
    description: Optional[str] = None
    theme: Optional[str] = None
    genre: Optional[str] = None
    narrative_perspective: Optional[str] = None

    # 任意业务字段透传（builder 可按需读取）
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssembledPrompt:
    """组装结果。"""
    system_prompt: str
    user_prompt: str

    # 可选：V4.4 K5 用于注入 cache_control 的多段 blocks
    system_blocks: list[dict[str, Any]] = field(default_factory=list)
    user_blocks: list[dict[str, Any]] = field(default_factory=list)

    # 审计字段
    slots_filled: list[str] = field(default_factory=list)
    slots_truncated: list[str] = field(default_factory=list)
    slots_skipped: list[str] = field(default_factory=list)
    actual_tokens_estimate: int = 0
    scene: str = ""
    model_tier: str = ""
    char_token_ratio: float = 1.5


# ============================================================
# 核心 Assembler
# ============================================================

class PromptAssembler:
    """V4.3 极简组装器：按 blueprint 遍历填充 + 截断。"""

    # 中文字符 1 字 ≈ 1.5 token，英文 4 字符 ≈ 1 token
    CN_CHAR_TO_TOKEN = 1.5

    async def assemble(
        self,
        db: AsyncSession,
        ctx: AssemblyContext,
    ) -> AssembledPrompt:
        """主入口：返回 AssembledPrompt。

        Raises:
            ValueError: 未知 scene + model_tier 组合；或 required slot 内容为空
        """
        tier = get_model_tier(ctx.model_name)
        ratio = char_token_ratio(ctx.model_name)
        blueprint = PROMPT_BLUEPRINT.get((ctx.scene, tier))
        if blueprint is None:
            raise ValueError(
                f"No blueprint for (scene={ctx.scene!r}, tier={tier!r}); "
                f"register it in SCENE_BUSINESS_TEMPLATES"
            )

        # 唯一的 for 循环
        system_parts: list[str] = []
        user_parts: list[str] = []
        system_blocks: list[dict[str, Any]] = []
        user_blocks: list[dict[str, Any]] = []
        slots_filled: list[str] = []
        slots_truncated: list[str] = []
        slots_skipped: list[str] = []

        for slot in blueprint:
            builder = SLOT_BUILDERS.get(slot.name)
            if builder is None:
                logger.warning(
                    "[Assembler] no builder for slot %r, skip", slot.name
                )
                slots_skipped.append(slot.name)
                continue

            try:
                content = await builder(db, ctx)
            except Exception as exc:
                logger.error(
                    "[Assembler] builder %r failed: %s", slot.name, exc,
                    exc_info=True,
                )
                if slot.required:
                    raise
                slots_skipped.append(slot.name)
                continue

            content = (content or "").strip()
            if not content:
                if slot.required:
                    raise ValueError(
                        f"Required slot {slot.name!r} returned empty content"
                    )
                slots_skipped.append(slot.name)
                continue

            # 加标签前缀
            if slot.label:
                content = f"{slot.label}\n{content}"

            # 截断（优先段落边界，见 _truncate）
            truncated = self._truncate(content, slot.max_tokens, ratio)
            if len(truncated) < len(content):
                slots_truncated.append(slot.name)

            # 放进对应段
            if slot.section == "system":
                system_parts.append(truncated)
                system_blocks.append(self._make_block(truncated, slot))
            else:
                user_parts.append(truncated)
                user_blocks.append(self._make_block(truncated, slot))

            slots_filled.append(slot.name)

        system_prompt = "\n\n".join(system_parts)
        user_prompt = "\n\n".join(user_parts)
        tokens = self._estimate_tokens(system_prompt + "\n" + user_prompt, ratio)

        logger.info(
            "[Assembler] scene=%s tier=%s ratio=%.2f filled=%d truncated=%d skipped=%d tokens≈%d",
            ctx.scene, tier, ratio, len(slots_filled),
            len(slots_truncated), len(slots_skipped), tokens,
        )

        return AssembledPrompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            slots_filled=slots_filled,
            slots_truncated=slots_truncated,
            slots_skipped=slots_skipped,
            actual_tokens_estimate=tokens,
            scene=ctx.scene,
            model_tier=tier,
            char_token_ratio=ratio,
        )

    # ---------------- internal helpers ----------------

    @classmethod
    def _truncate(cls, text: str, max_tokens: int, ratio: float | None = None) -> str:
        """截断到 max_tokens（按中文字符估算）。

        优先在段落 / 句子边界收口（至少保留 60% 预算），避免把世界规则这类
        整段设定切在半句；找不到边界才硬切。ratio 不传时沿用 CN_CHAR_TO_TOKEN。
        """
        if max_tokens <= 0:
            return ""
        max_chars = int(max_tokens / (ratio or cls.CN_CHAR_TO_TOKEN))
        if len(text) <= max_chars:
            return text
        head = text[:max_chars]
        floor = int(max_chars * 0.6)
        for sep in ("\n", "。", "；", "！", "？"):
            pos = head.rfind(sep)
            if pos >= floor:
                return head[: pos + 1].rstrip() + "\n…(截断)"
        return head + "…(截断)"

    @classmethod
    def _estimate_tokens(cls, text: str, ratio: float | None = None) -> int:
        """粗估 token 数（中文 1 字 ≈ ratio token，其他 4 字符 ≈ 1 token）。"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * (ratio or cls.CN_CHAR_TO_TOKEN) + other_chars / 4)

    @staticmethod
    def _make_block(text: str, slot: Slot) -> dict[str, Any]:
        """构造 V4.4 K5 风格的 block（含 cache_control 标记）。

        Provider 适配层会按 model_name 决定是否真的传 cache_control 给 API。
        """
        block: dict[str, Any] = {"type": "text", "text": text}
        if slot.cacheable and slot.cache_tier in ("global", "project"):
            # Anthropic 风格 cache_control
            block["cache_control"] = {"type": "ephemeral"}
        return block
