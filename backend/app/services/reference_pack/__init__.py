"""规划场景的提示词装配：项目自有资料的槽位（骨架 / 角色 / 规则 / 地图 / 输出要求）+ 硬截断。

原来的拆书参考包维度槽位已下线：仿写参考改由 services/knowledge/kb_context 按场景组装。

本子系统的职责：
- policy_tables：模型分档与历史接续 / 记忆条数查表
- blueprint：每个 (scene, tier) 的 prompt 装配单（槽位 + max_tokens）
- assembler：按 blueprint 遍历填充 + 硬截断 → 输出可发送给 LLM 的 prompt
- slot_builders：各槽位的内容构造函数

调用方约定：
    from app.services.reference_pack import PromptAssembler, AssemblyContext

    assembler = PromptAssembler()
    prompt = await assembler.assemble(db, AssemblyContext(
        scene='chapter_content',
        model_name='deepseek-v3',
        project_id=...,
        chapter_id=...,
    ))
    # prompt.system_prompt 和 prompt.user_prompt 直接喂给 AI service
"""
from app.services.reference_pack.assembler import (
    AssemblyContext,
    AssembledPrompt,
    PromptAssembler,
)
from app.services.reference_pack.blueprint import (
    Slot,
    PROMPT_BLUEPRINT,
)
from app.services.reference_pack.policy_tables import (
    MODEL_TIERS,
    HISTORICAL_CONTEXT_TABLE,
    MEMORY_TOPK_TABLE,
    get_model_tier,
)

__all__ = [
    "AssemblyContext",
    "AssembledPrompt",
    "PromptAssembler",
    "Slot",
    "PROMPT_BLUEPRINT",
    "MODEL_TIERS",
    "HISTORICAL_CONTEXT_TABLE",
    "MEMORY_TOPK_TABLE",
    "get_model_tier",
]
