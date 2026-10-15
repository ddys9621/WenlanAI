"""行内补全（编辑器里像写代码的 Copilot）：作者停笔时，按光标前后的正文给一小段灰色建议，Tab 采用。

- 只读：不建候选稿、不写正文、不进后台任务；读到段尾 / 字数上限、或浏览器断开，就关掉上游流，不白烧 token
- 上下文从轻（补全要快）：光标前 ≤PREFIX_CHARS 字 + 光标后 ≤SUFFIX_CHARS 字、本章章纲契约、项目默认文风（截断）、
  本书人物（光标附近出现的排前面并带说话风格）、本章刚开头时附上一章结尾
- 长度：sentence 一句 / paragraph 补完当前段（段首则写一段）；max_tokens 仍取用户设置，靠提示词 + 主动停流控制
"""
from __future__ import annotations

import re
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.project_default_style import ProjectDefaultStyle
from app.models.writing_style import WritingStyle
from app.services.writing_assistant_service import contract_text
from app.utils.prompt_safety import UNTRUSTED_DATA_RULE, quote_untrusted

CURSOR = "⟨光标⟩"
PREFIX_CHARS = 1500
SUFFIX_CHARS = 300
CONTRACT_CHARS = 600
STYLE_CHARS = 300
PREVIOUS_TAIL_CHARS = 400
SHORT_PREFIX_CHARS = 200  # 本章写了不到这么多字时附上一章结尾
MAX_CHARACTERS = 12
VOICE_CHARS = 40
MIN_ECHO = 4  # 与光标前结尾重叠至少这么多字才算模型在复述
MIN_EMIT_CHARS = 16  # 攒够这么多字再发第一版，回声判断才有依据
LIMITS = {"sentence": 60, "paragraph": 220}

SENTENCE_ENDS = "。！？!?…"
CLAUSE_ENDS = "，,、；;：:" + SENTENCE_ENDS
CLOSERS = "”’」』）)》】\"'"
OPENERS = "“‘「『（(《【"
_INDENT = " \t\u3000"
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")
_THINK = re.compile(r"<think>.*?</think>", re.S)

COMPLETION_SYSTEM = (
    "你是小说作者的写作搭档，正在帮作者补全正在写的句子或段落——像输入法联想一样，只给一小段，供作者参考取舍。\n"
    "- 只输出要插在光标处的正文：不要重复光标前已经写了的字，不要解释、不要加引号或标题，不要输出光标标记。\n"
    "- 和前后文严丝合缝：人称、视角、时态、语气、人物称呼与设定保持一致；光标后已有正文时，补的内容要能顺接上后文。\n"
    "- 用具体的动作、细节、对话往前推一小步，不要总结、不要空泛抒情，不要一口气写到本章结尾。\n\n"
    + UNTRUSTED_DATA_RULE
)

LENGTH_RULES = {
    "sentence": "只写一句话（写到句号、问号或感叹号为止），不超过 40 字。",
    "paragraph": "补完光标所在的这一段，写到这一段自然结束就停，不要另起新段，不超过 150 字。",
}
PARAGRAPH_START_RULES = {
    "sentence": "光标在段首：另起一段，只写这一段的第一句，不超过 40 字。",
    "paragraph": "光标在段首：另起一段，写一整段（60-150 字），写完这一段就停。",
}


def current_line(prefix: str) -> str:
    return prefix[prefix.rfind("\n") + 1:]


def at_paragraph_start(prefix: str) -> bool:
    """光标所在行（光标前的部分）只有空白 = 段首：要另起一段，而不是接着上一句。"""
    return not current_line(prefix).strip(_INDENT)


def _paragraph_indent(prefix: str) -> str:
    """作者上一段开头的缩进（全角空格 / 空格）；不用缩进返回空串。"""
    for line in reversed(prefix.split("\n")[:-1]):
        if line.strip(_INDENT):
            return line[: len(line) - len(line.lstrip(_INDENT))]
    return ""


def strip_echo(prefix: str, text: str) -> str:
    """去掉模型开头复述的光标前文字：当前行已写的半句整段重复，或与光标前结尾重叠 ≥ MIN_ECHO 字。"""
    line = current_line(prefix).strip(_INDENT)
    if len(line) >= 2 and text.startswith(line):
        return text[len(line):]
    tail = prefix.rstrip()[-40:]
    for k in range(min(len(tail), len(text)), MIN_ECHO - 1, -1):
        if tail.endswith(text[:k]):
            return text[k:]
    return text


def clean_completion(raw: str, *, prefix: str) -> str:
    """模型原文 → 可直接插在光标处的文字：去思考块 / 围栏 / 光标标记 / 开头复述；段首按作者习惯补缩进，段中去掉前导换行。"""
    text = _THINK.sub("", raw or "")
    if "<think>" in text:  # 思考块还没结束：正文还没开始
        return ""
    text = _FENCE.sub("", text.replace(CURSOR, ""))
    if not at_paragraph_start(prefix):
        return strip_echo(prefix, text.lstrip("\r\n"))
    text = strip_echo(prefix, text.lstrip("\r\n" + _INDENT)).lstrip("\r\n" + _INDENT)
    if text and not current_line(prefix):
        text = _paragraph_indent(prefix) + text
    return text


def _sentence_end(text: str) -> int:
    """第一处句末（连同连续的句末标点与后引号 / 括号）之后的位置；对话引号后接着「他问。」之类的仍算同一句。没有返回 -1。"""
    i = 0
    while i < len(text):
        if text[i] in SENTENCE_ENDS:
            j = i + 1
            while j < len(text) and text[j] in SENTENCE_ENDS:
                j += 1
            k = j
            while k < len(text) and text[k] in CLOSERS:
                k += 1
            if k > j and k < len(text) and not text[k].isspace() and text[k] not in OPENERS:
                i = k  # “你来了？”他问。—— 引号后接说明语，句子还没完
                continue
            return k
        i += 1
    return -1


def _last_end(text: str, marks: str) -> int:
    """text 里最后一个 marks 标点（连同后引号）之后的位置；没有返回 -1。"""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in marks:
            j = i + 1
            while j < len(text) and text[j] in CLOSERS:
                j += 1
            return j
    return -1


def _cap(text: str, limit: int, marks: str) -> str:
    """超过字数上限：尽量在上限内最后一个 marks 标点处截断（至少保留四成），否则硬截。"""
    cut = _last_end(text[:limit], marks)
    return text[:cut] if cut >= limit * 0.4 else text[:limit]


def cut_completion(text: str, length: str, *, final: bool = False) -> tuple[str, bool]:
    """按长度截断：返回 (保留的文字, 是否已经够了)。够了 = 段尾 / 句尾（sentence）/ 字数上限 / 流已结束（final）。"""
    limit = LIMITS.get(length, LIMITS["paragraph"])
    body = len(text) - len(text.lstrip(_INDENT))
    newline = text.find("\n", body)
    ended = newline != -1
    part = text[:newline].rstrip() if ended else text
    if length == "sentence":
        end = _sentence_end(part)
        if end != -1 and (end < len(part) or final or ended):
            return part[:end], True
        if len(part) >= limit:
            return _cap(part, limit, CLAUSE_ENDS), True
    elif len(part) >= limit:
        return _cap(part, limit, SENTENCE_ENDS), True
    if ended or final:
        return part.rstrip(), True
    return part, False


@dataclass
class CompletionContext:
    outline: Optional[ChapterOutline] = None
    style_text: str = ""
    characters: list[tuple[str, str]] = field(default_factory=list)  # (名字, 说话风格；不在光标附近的为空)
    previous_tail: str = ""


async def load_completion_context(db: AsyncSession, chapter: Chapter, *, prefix: str, suffix: str) -> CompletionContext:
    """只读：章纲、项目默认文风、人物名（光标附近出现的排前面）、本章刚开头时的上一章结尾。"""
    outline = await db.get(ChapterOutline, chapter.chapter_outline_id) if chapter.chapter_outline_id else None
    style = (await db.execute(
        select(WritingStyle.prompt_content)
        .join(ProjectDefaultStyle, ProjectDefaultStyle.style_id == WritingStyle.id)
        .where(ProjectDefaultStyle.project_id == chapter.project_id)
    )).scalars().first()
    rows = (await db.execute(
        select(Character.name, Character.speech_style)
        .where(Character.project_id == chapter.project_id, Character.is_organization.isnot(True))
        .order_by(Character.created_at)
    )).all()
    nearby = prefix[-PREFIX_CHARS:] + suffix[:SUFFIX_CHARS]
    present = [(name, (voice or "").strip()[:VOICE_CHARS]) for name, voice in rows if name and name in nearby]
    others = [(name, "") for name, _ in rows if name and name not in nearby]
    previous_tail = ""
    if len(prefix.strip()) < SHORT_PREFIX_CHARS and chapter.chapter_number > 1:
        previous = (await db.execute(
            select(Chapter.content)
            .where(Chapter.project_id == chapter.project_id, Chapter.chapter_number < chapter.chapter_number)
            .order_by(Chapter.chapter_number.desc())
            .limit(1)
        )).scalars().first()
        previous_tail = (previous or "").strip()[-PREVIOUS_TAIL_CHARS:]
    return CompletionContext(
        outline=outline,
        style_text=(style or "").strip()[:STYLE_CHARS],
        characters=(present + others)[:MAX_CHARACTERS],
        previous_tail=previous_tail,
    )


def build_completion_prompt(*, chapter: Chapter, prefix: str, suffix: str, length: str, ctx: CompletionContext) -> str:
    before, after = prefix[-PREFIX_CHARS:], suffix[:SUFFIX_CHARS]
    parts = [f"当前是第{chapter.chapter_number}章《{chapter.title}》。"]
    if ctx.outline is not None:
        parts.append("【本章章纲】（只作方向参考，这次只补一小段）\n" + contract_text(ctx.outline)[:CONTRACT_CHARS])
    if ctx.style_text:
        parts.append(f"【文风】\n{ctx.style_text}")
    if ctx.characters:
        parts.append("【本书人物】" + "、".join(f"{name}（{voice}）" if voice else name for name, voice in ctx.characters))
    if ctx.previous_tail:
        parts.append("上一章结尾：\n" + quote_untrusted(ctx.previous_tail, "上一章结尾"))
    parts.append(f"正文（{CURSOR} 是作者的光标位置）：\n" + quote_untrusted(f"{before}{CURSOR}{after}", "光标前后正文"))
    if at_paragraph_start(prefix):
        rule = PARAGRAPH_START_RULES[length]
    else:
        follow = "光标后还有正文，补的内容要能接上。" if after.strip() else ""
        rule = f"光标在段中：紧接着光标前的最后一个字往下写。{follow}{LENGTH_RULES[length]}"
    parts.append(f"要求：{rule}只输出要插在{CURSOR}处的文字。")
    return "\n\n".join(parts)


async def stream_completion(
    ai_service: Any, *, prompt: str, prefix: str, length: str, model: Optional[str] = None,
) -> AsyncIterator[str]:
    """逐次产出「截至目前、清洗并截断后的完整建议」（只在变化时产出）；够了就停掉上游流，不再读、不再计费。"""
    raw, last = "", ""
    stream = ai_service.generate_text_stream(prompt=prompt, system_prompt=COMPLETION_SYSTEM, model=model, creative=True)
    async with aclosing(stream):
        async for chunk in stream:
            raw += chunk or ""
            text, done = cut_completion(clean_completion(raw, prefix=prefix), length)
            if text and text != last and (done or len(raw) >= MIN_EMIT_CHARS):
                last = text
                yield text
            if done:
                return
    text, _ = cut_completion(clean_completion(raw, prefix=prefix), length, final=True)
    if text and text != last:
        yield text
