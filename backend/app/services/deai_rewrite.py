"""去 AI 味重写的提示词：只带用户勾选的提示词 + 本章原文（作者要求上下文最简，不带章纲 / 前文 / 设定 / 文风规则）。

首次生成不注入任何去 AI 味规则；这里是 deai_prompts 唯一的消费点。

两种模式：
- 全文重写（full）：提示词 + 原文；可附专有名词表——人名 / 地名 / 势力 / 功法原样保留，避免改写时把名字换掉
- 局部重写（local）：只把检测出 AI 味重的段落（ai_flavor_metrics.flagged_paragraph_indices）带编号交给模型，
  相邻段落只读供衔接；模型按「[P编号] 新段落」逐行输出，原位替换，其余段落一字不动
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

OUTPUT_RULES = "直接输出改写后的完整正文：不要章节标题，不要任何说明、注释或前后缀。"
LOCAL_OUTPUT_RULES = "输出格式：每个待改写段落一行，以「[P编号]」开头，后接改写后的整段；只输出这些行，不要任何说明。"
GLOSSARY_LIMIT = 80
_LOCAL_LINE = re.compile(r"^\s*\[P(\d+)\]\s*(.+?)\s*$")


def _clean_prompts(prompt_texts: Iterable[str]) -> list[str]:
    texts = [t.strip() for t in prompt_texts if t and t.strip()]
    if not texts:
        raise ValueError("至少需要一条去 AI 味提示词")
    return texts


def _glossary_block(glossary: Optional[Iterable[str]]) -> str:
    names = list(dict.fromkeys(n.strip() for n in (glossary or []) if n and n.strip()))[:GLOSSARY_LIMIT]
    if not names:
        return ""
    return "【专有名词（人名 / 地名 / 势力 / 功法 / 物品，原样保留，不得改写或替换）】\n" + "、".join(names)


def build_rewrite_prompt(prompt_texts: list[str], content: str, glossary: Optional[list[str]] = None) -> str:
    """按用户勾选顺序拼接提示词，再附（可选的专有名词表）原文与输出格式要求。空提示词 / 空正文抛 ValueError。"""
    texts = _clean_prompts(prompt_texts)
    body = (content or "").strip()
    if not body:
        raise ValueError("章节正文为空，无法重写")
    glossary_text = _glossary_block(glossary)
    head = "\n\n".join([*texts, glossary_text] if glossary_text else texts)
    return head + f"\n\n【原文】\n{body}\n\n{OUTPUT_RULES}"


def split_paragraph_lines(text: str) -> tuple[list[str], list[int]]:
    """原文按行切：返回 (所有行, 非空行的行号)。段落下标 i 对应 lines[para_lines[i]]。"""
    lines = (text or "").split("\n")
    return lines, [i for i, line in enumerate(lines) if line.strip()]


def build_local_rewrite_prompt(
    prompt_texts: list[str], paragraphs: list[str], targets: list[int], glossary: Optional[list[str]] = None,
) -> str:
    texts = _clean_prompts(prompt_texts)
    targets = sorted({i for i in targets if 0 <= i < len(paragraphs)})
    if not targets:
        raise ValueError("没有需要局部重写的段落")
    context = sorted({j for i in targets for j in (i - 1, i + 1) if 0 <= j < len(paragraphs)} - set(targets))
    parts = [*texts]
    glossary_text = _glossary_block(glossary)
    if glossary_text:
        parts.append(glossary_text)
    parts.append(
        f"下面是本章里 AI 味较重的 {len(targets)} 个段落（编号 = 段落序号）。只改写这些段落：保持原意、人物、事件、信息量不变，"
        "长度相近，换成大白话、短句、具体动作；不要新增情节，不要和上下文重复。"
    )
    parts.append("【待改写段落】\n" + "\n".join(f"[P{i + 1}] {paragraphs[i].strip()}" for i in targets))
    if context:
        parts.append("【上下文段落（只读，用来衔接，不要改写、不要输出）】\n"
                     + "\n".join(f"P{j + 1}：{paragraphs[j].strip()}" for j in context))
    parts.append(LOCAL_OUTPUT_RULES)
    return "\n\n".join(parts)


def parse_local_rewrite(text: str, targets: list[int]) -> dict[int, str]:
    """解析「[P编号] 新段落」；只认目标段落的编号（越界 / 非目标编号 / 说明文字一律丢弃）。"""
    wanted = set(targets)
    out: dict[int, str] = {}
    for line in (text or "").splitlines():
        match = _LOCAL_LINE.match(line)
        if not match:
            continue
        index = int(match.group(1)) - 1
        if index in wanted and match.group(2).strip():
            out[index] = match.group(2).strip()
    return out


def merge_paragraphs(text: str, replacements: dict[int, str]) -> str:
    """按段落下标原位替换，保留原文的空行 / 换行结构。"""
    lines, para_lines = split_paragraph_lines(text)
    for index, new_text in replacements.items():
        if 0 <= index < len(para_lines):
            lines[para_lines[index]] = new_text
    return "\n".join(lines)
