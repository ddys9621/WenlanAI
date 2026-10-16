"""正文提示词（长篇版）。

旧模板的问题：全书章纲（含未来章节）每章全量注入、本章任务夹在中段后面跟几十万字参考资料、桥段结构约束被塞进
「MCP 参考资料」、收尾一律"停在钩子上"与兑现章"不留钩子"冲突、多处"最高优先级 / 禁止自由发挥"互相打架。

这里：
- system：人设 + 视角 / 类型指导 + 文风 + 平台写法 + 项目风格 + 写作优先级（只说一次）+ 输出要求——跨章稳定，
  可命中各家的前缀缓存
- user：作品设定 → 前情脉络（层级摘要）→ 近期剧情 → 相关旧事 → 出场角色与状态 → 地图与方位 → 叙事账本 → 参考资料 →
  上一章正文 → 本段章纲 → 本章任务（章纲 / 叙事任务 / 结构要求 / 字数 / 用户微调）→ 收尾
- 全部上下文过预算器（context_budget），本章任务与收尾永不裁剪
- 「视角人物知道什么」是写作优先级第 1 条的硬约束：放进「出场角色与状态」，不跟叙事账本一起被截掉；
  账本按 伏笔清单 → 因果 → 时间轴 → 关系 → 归属 的顺序（排在后面的先被裁）
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.services.context_budget import ContextSection, budget_report, clip_text, fit_sections, render_sections
from app.services.prompt_service import CHAPTER_OUTPUT_INSTRUCTION, CHAPTER_STYLE_RULES, PromptService
from app.utils.prompt_safety import UNTRUSTED_DATA_RULE, quote_untrusted

DEFAULT_BUDGET_CHARS = 36_000
CONTINUATION_TAIL_CHARS = 1500

SYSTEM_PERSONA = (
    "你是一个在起点、番茄这类平台写了几百万字的网文老作者，习惯日更，写出来的东西读者在手机上刷着看不费劲。"
    "用户会给你这本书的设定、前情和本章任务，你照着写这一章。"
)

PRIORITY_RULES = """## 写作优先级（冲突时按这个顺序取舍，只在这里说一次）
1. 已经发生的事实不能违背：死亡 / 失踪名单、境界与实力、持有物品、故事时间、视角人物知道什么
2. 本章章纲里的大事件必须发生，顺序可以按逻辑微调；不提前写后面章节的事
3. 本章的结构要求（几成铺垫几成兑现、章末留不留钩子）
4. 叙事与文风要求
对话、动作、小插曲这类细节可以自由发挥，让人物活起来；但不要新增章纲外的大事件、新的重要角色或新的设定。
前情只用来保持连贯：不要复述上一章已经写过的内容，开头直接接着上一章结尾往下写。"""

CLOSING_HEAD = "落笔前再看一眼：段落短、对话多、叙述用主角的口气、环境两句带过、书面词换成嘴上的词、"
IMITATION_CLOSING_HEAD = "落笔前再看一眼：句式、段落和对话比例按参考文风来，人名、地名和设定都用本书的，不照抄参考里的句子、"
IMITATION_STYLE_TITLE = "## 参考文风（仿写参考开启：文风以这里为准，下面「网文大白话」里和它冲突的条目以参考文风为准）"
CLOSING_TAILS = {
    "hook": "结尾停在钩子上。",
    "none": "结尾收在一个具体的收束场景上，不留钩子、不预告后事。",
    "soft": "结尾先收束，再留一个不解释的小异样（不超过两句），不开启新事件。",
}

LEDGER_ORDER: tuple[str, ...] = (
    "narrative_promises", "causal_chains", "timeline_events", "relationship_dynamics", "affiliation_dynamics",
)


@dataclass
class ChapterPromptInput:
    title: str
    theme: str
    genre: str
    narrative_perspective: str
    time_period: str
    location: str
    atmosphere: str
    world_rules: str
    chapter_number: int
    chapter_title: str
    chapter_outline_text: str
    outline_window: str = ""
    narrative_tasks: str = ""
    structure_requirements: str = ""
    hook_policy: str = "hook"
    story_so_far: str = ""
    recent_summaries: str = ""
    relevant_history: str = ""
    recent_full: str = ""
    character_cards: str = ""
    pov_knowledge: str = ""
    absent_characters: str = ""
    organizations: str = ""
    story_time: str = ""
    world_map: str = ""
    ledger_blocks: dict[str, str] = field(default_factory=dict)
    references: str = ""
    imitation: str = ""
    imitation_style: str = ""
    style_content: str = ""
    platform_block: str = ""
    generation_prompt: str = ""
    target_word_count: int = 3000
    word_soft_range: float = 0.10
    budget_chars: int = DEFAULT_BUDGET_CHARS


@dataclass
class ChapterPrompt:
    system: str
    user: str
    task: str
    closing: str
    report: dict[str, Any]


def build_chapter_closing(hook_policy: str, imitation_style: bool = False) -> str:
    tail = CLOSING_TAILS.get(hook_policy or "hook", CLOSING_TAILS["hook"])
    head = IMITATION_CLOSING_HEAD if imitation_style else CLOSING_HEAD
    return f"{head}{tail}\n\n{CHAPTER_OUTPUT_INSTRUCTION}"


def _system_prompt(inp: ChapterPromptInput) -> str:
    perspective = (inp.narrative_perspective or "").strip() or "第三人称"
    style_rules = CHAPTER_STYLE_RULES.format(
        narrative_perspective=perspective,
        perspective_boundary_clause=PromptService._build_perspective_boundary_clause(perspective),
    )
    # 首行原文是"（重点，和章纲同等重要）"——与写作优先级冲突，system 里换成干净的标题
    style_body = style_rules.strip().split("\n", 1)[1] if "\n" in style_rules.strip() else ""
    imitation_style = (inp.imitation_style or "").strip()
    parts = [
        SYSTEM_PERSONA,
        PromptService._resolve_perspective_guide(perspective).strip(),
        PromptService._resolve_genre_guide(inp.genre or "").strip(),
        f"{IMITATION_STYLE_TITLE}\n{imitation_style}" if imitation_style else "",
        "## 叙事与文风要求：网文大白话\n" + style_body,
        inp.platform_block.strip(),
        inp.style_content.strip(),
        PRIORITY_RULES,
        UNTRUSTED_DATA_RULE,
        f"## 输出\n{CHAPTER_OUTPUT_INSTRUCTION}",
    ]
    return "\n\n".join(p for p in parts if p)


def _setting_text(inp: ChapterPromptInput) -> str:
    lines = [
        f"- 书名：{inp.title}｜类型：{inp.genre or '未设定'}｜主题：{clip_text(inp.theme or '未设定', 200)}",
        f"- 叙事视角：{inp.narrative_perspective or '第三人称'}",
        f"- 时代背景：{inp.time_period or '未设定'}｜主要地点：{inp.location or '未设定'}｜氛围：{inp.atmosphere or '未设定'}",
    ]
    if (inp.world_rules or "").strip():
        lines.append(f"- 世界规则：\n{inp.world_rules.strip()}")
    return "\n".join(lines)


def _characters_text(inp: ChapterPromptInput) -> str:
    parts = []
    if inp.story_time.strip():
        parts.append(f"故事时间：上一章结束于 {inp.story_time.strip()}")
    if inp.character_cards.strip():
        parts.append(inp.character_cards.strip())
    pov = (inp.pov_knowledge or "").strip()
    if pov and "暂无" not in pov.splitlines()[-1] and "未指定 POV" not in pov:
        parts.append("视角信息边界：" + pov.removeprefix("【视角信息边界】").strip())
    if inp.organizations.strip():
        parts.append("相关势力：\n" + inp.organizations.strip())
    if inp.absent_characters.strip():
        parts.append("已死亡 / 失踪（不能以活人身份出场）：\n" + inp.absent_characters.strip())
    return "\n\n".join(parts)


def _ledger_text(inp: ChapterPromptInput) -> str:
    blocks = [(inp.ledger_blocks or {}).get(key, "") for key in LEDGER_ORDER]
    useful = [b.strip() for b in blocks if b and b.strip() and "暂无" not in b.strip().splitlines()[-1]]
    return "\n\n".join(useful)


def _task_text(inp: ChapterPromptInput, closing: str) -> str:
    low = int(inp.target_word_count * (1 - inp.word_soft_range))
    high = int(inp.target_word_count * (1 + inp.word_soft_range))
    parts = [f"写第{inp.chapter_number}章《{inp.chapter_title}》。", "本章章纲：\n" + inp.chapter_outline_text.strip()]
    if inp.narrative_tasks.strip():
        parts.append("本章叙事任务（伏笔 / 承诺）：\n" + inp.narrative_tasks.strip())
    if inp.structure_requirements.strip():
        parts.append("本章结构要求：\n" + inp.structure_requirements.strip())
    parts.append(
        f"字数：目标 {inp.target_word_count} 字（{low}–{high} 字）。接近 {high} 字就收尾，不展开新情节；"
        "篇幅不够时先压缩环境和过渡，保留冲突、转折和结果；不要为凑字数重复描写。"
    )
    if (inp.generation_prompt or "").strip():
        parts.append(
            "作者补充要求（优先于通用写作偏好；与输出格式冲突时仍按格式要求）：\n" + inp.generation_prompt.strip()
        )
    parts.append(closing)
    return "\n\n".join(parts)


QUOTED_SECTIONS = {"references": "参考资料", "imitation": "仿写参考"}


def _quote_reference_section(sections: list[ContextSection]) -> list[ContextSection]:
    """参考资料 / 仿写参考过完预算器再包起止标记：裁剪不会把结束标记裁掉，区块总是闭合的。"""
    return [replace(s, text=quote_untrusted(s.text, QUOTED_SECTIONS[s.key])) if s.key in QUOTED_SECTIONS else s
            for s in sections]


def build_chapter_prompt(inp: ChapterPromptInput) -> ChapterPrompt:
    closing = build_chapter_closing(inp.hook_policy, imitation_style=bool((inp.imitation_style or "").strip()))
    task = _task_text(inp, closing)
    budget = max(inp.budget_chars - len(task), 4_000)
    sections = fit_sections([
        ContextSection("setting", "作品设定", _setting_text(inp), priority=8, max_chars=3_500, min_chars=600),
        ContextSection("story_so_far", "前情脉络", inp.story_so_far, priority=6, max_chars=4_500, min_chars=800, keep="tail"),
        ContextSection("recent_summaries", "近期剧情", inp.recent_summaries, priority=7, max_chars=3_500, min_chars=600, keep="tail"),
        ContextSection("relevant_history", "相关旧事", inp.relevant_history, priority=4, max_chars=2_500, min_chars=500),
        ContextSection("characters", "出场角色与状态", _characters_text(inp), priority=9, max_chars=5_000, min_chars=1_500),
        ContextSection("world_map", "地图与方位", inp.world_map, priority=4, max_chars=1_200, min_chars=300),
        ContextSection("ledger", "叙事账本", _ledger_text(inp), priority=5, max_chars=3_500, min_chars=800),
        ContextSection("imitation", "仿写参考", inp.imitation, priority=3, max_chars=2_600, min_chars=600),
        ContextSection("references", "参考资料", inp.references, priority=1, max_chars=3_000),
        ContextSection("recent_full", "上一章正文", inp.recent_full, priority=8, max_chars=7_000, min_chars=1_500, keep="tail"),
        ContextSection("outline_window", "本段章纲", inp.outline_window, priority=7, max_chars=2_000, min_chars=400),
    ], total_chars=budget)
    report = budget_report(sections)
    sections = _quote_reference_section(sections)
    user = render_sections([*sections, ContextSection("task", "本章任务", task, priority=10, max_chars=0, required=True)])
    report["task"] = {"chars": len(task), "trimmed": False}
    return ChapterPrompt(system=_system_prompt(inp), user=user, task=task, closing=closing, report=report)


def build_continuation_prompt(
    prompt: ChapterPrompt, written: str, target_word_count: int, chapter_number: int,
) -> str:
    """正文被 Max Tokens 截断后的续写提示词（system 沿用原提示词）。"""
    remain = max(target_word_count - len(written), 300)
    tail = written[-CONTINUATION_TAIL_CHARS:]
    task = prompt.task
    outline = task[: task.index(prompt.closing)].strip() if prompt.closing in task else task
    return (
        f"【本章已写正文（结尾部分）】\n{tail}\n\n"
        f"上面是第{chapter_number}章已经写出的正文，因为长度限制在中途断开了。请紧接着最后一个字往下写，"
        f"把本章写完（大约还差 {remain} 字）。不要重复已写内容，不要加任何说明或标题。\n\n"
        f"【本章任务（复述）】\n{clip_text(outline, 2_500)}\n\n{prompt.closing}"
    )
