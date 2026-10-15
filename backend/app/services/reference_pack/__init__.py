"""V4.2/V4.3 拆书参考包注入子系统（V4 设计书 §10）。

本子系统的职责：
- policy_tables：硬编码的『场景×模型 → 维度策略』查表
- blueprint：每个 (scene, tier) 的 prompt 装配单（槽位 + max_tokens）
- assembler：按 blueprint 遍历填充 + 硬截断 → 输出可发送给 LLM 的 prompt
- slot_builders：19 个槽位的内容构造函数

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
    POLICY_TABLE,
    CORPUS_TOPK,
    HISTORICAL_CONTEXT_TABLE,
    MEMORY_TOPK_TABLE,
    get_model_tier,
    get_policy,
    get_corpus_top_k,
)
from app.services.reference_pack.v4_compat import build_v4_dissect_segment

__all__ = [
    "AssemblyContext",
    "AssembledPrompt",
    "PromptAssembler",
    "Slot",
    "PROMPT_BLUEPRINT",
    "MODEL_TIERS",
    "POLICY_TABLE",
    "CORPUS_TOPK",
    "HISTORICAL_CONTEXT_TABLE",
    "MEMORY_TOPK_TABLE",
    "get_model_tier",
    "get_policy",
    "get_corpus_top_k",
    "build_v4_dissect_segment",
]
