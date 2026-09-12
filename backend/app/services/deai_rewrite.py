"""去 AI 味重写的提示词：只带用户勾选的提示词 + 本章原文（作者要求上下文最简，不带章纲 / 前文 / 设定 / 文风规则）。

首次生成不注入任何去 AI 味规则；这里是 deai_prompts 唯一的消费点。
"""
from __future__ import annotations

OUTPUT_RULES = "直接输出改写后的完整正文：不要章节标题，不要任何说明、注释或前后缀。"


def build_rewrite_prompt(prompt_texts: list[str], content: str) -> str:
    """按用户勾选顺序拼接提示词，再附原文与输出格式要求。空提示词 / 空正文抛 ValueError。"""
    texts = [t.strip() for t in prompt_texts if t and t.strip()]
    if not texts:
        raise ValueError("至少需要一条去 AI 味提示词")
    body = (content or "").strip()
    if not body:
        raise ValueError("章节正文为空，无法重写")
    return "\n\n".join(texts) + f"\n\n【原文】\n{body}\n\n{OUTPUT_RULES}"
