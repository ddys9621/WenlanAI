"""智能助笔（参考岚笺 Writing Agent）：当前章的对话式助手。

- 技能固定：continue 续写 / rewrite 改写 / polish 润色 / review 核对 / query 提问
- 判定：显式选择优先；问句优先于顺带出现的改写类动词；普通讨论落到只读的 query
- 工具全是只读投影（不接受前端传路径 / 任意工具）：本章正文、章纲契约、前文证据（只取本章之前的章节）、一致性问题、
  出场人物与世界观要点（续写 / 改写 / 润色时带上，人物和设定别走样）
- 修改类结果只是候选稿：改写 / 润色 = 替换选区（replace_range），续写 = 接在末尾（append）；采用走候选稿接口
- 提问 / 核对只回答，不产生候选稿、不动正文
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.project import Project
from app.services.chapter_candidate_service import candidate_summary, create_candidate
from app.services.chapter_context_service import parse_json_list
from app.services.chapter_version_service import content_hash
from app.services.narrative_tasks import render_narrative_tasks
from app.services.outline_contract import forbidden_items
from app.services.planning_context import clip
from app.utils.prompt_safety import UNTRUSTED_DATA_RULE, quote_untrusted

SKILL_LABELS = {"continue": "续写", "rewrite": "改写", "polish": "润色", "review": "核对", "query": "提问"}
MODIFYING_SKILLS = {"continue", "rewrite", "polish"}
SELECTION_SKILLS = {"rewrite", "polish"}

# 以核对类动词开头的是祈使句（「检查一下有没有吃书」），先于问句判断
_REVIEW_LEAD = re.compile(r"^(请|帮我|麻烦|你)?(检查|核对|审校|校对|挑错|挑挑|挑毛病|查查|查一下|审一下|校一下|找找问题)")
# 问句看句式：问号、句末吗/呢、问句开头、或问出处；不因为句中顺带一个「改写」就当成改写
_QUESTION = re.compile(
    r"[？?]|[吗呢][。！!…]*$|^(前文|之前|前面|有没有|是不是|是否|为什么|为何|谁|哪|怎么|几|多少)|依据|出处|提过|说过"
)
_REVIEW = re.compile(r"检查|核对|审校|校对|挑错|毛病|哪里不对|有没有问题|一致性|吃书|矛盾|硬伤|bug|漏洞", re.IGNORECASE)
_POLISH = re.compile(r"润色|顺一下|通顺|优化文笔|改得?更?自然|修饰|打磨")
_REWRITE = re.compile(r"改写|重写|换个写法|换种写法|改成|改为|扩写|缩写|精简|删减|改得|改一下|改改")
_CONTINUE = re.compile(r"续写|接着写|往下写|写下去|继续写|接下来写|后面写")

_STOPWORDS = (
    "前文", "前面", "之前", "以前", "有没有", "是不是", "是否", "提过", "说过", "写过", "出现过", "出现", "哪一章", "哪章",
    "哪里", "哪儿", "什么", "怎么", "为什么", "为何", "这里", "那里", "这个", "那个", "这幅", "那幅", "这段", "那段",
    "这句", "这些", "那些", "一下", "依据", "出处", "请问", "帮我", "看看", "我们", "他们", "你们", "就是", "还是",
    "可以", "改写", "核对", "检查",
)
EVIDENCE_EXCERPT = 60
CURRENT_CONTEXT_CHARS = 6000
CONTINUE_TAIL_CHARS = 1800
REWRITE_MARGIN_CHARS = 300
CAST_LIMIT = 8
WORLD_LIMIT = 600

ASSISTANT_SYSTEM = (
    "你是这本小说作者的写作助手，只围绕当前这一章工作。只依据给出的资料作答：引用正文必须逐字复制；"
    "前文资料里找不到依据就直说「前文没有找到依据」，不要编造之前发生过的事。不要擅自改动作者没让你改的内容。\n\n"
    + UNTRUSTED_DATA_RULE
)


def resolve_skill(message: str, *, has_selection: bool, preferred: Optional[str] = None) -> str:
    if preferred in SKILL_LABELS:
        return preferred
    text = (message or "").strip()
    if _REVIEW_LEAD.search(text):
        return "review"
    if _QUESTION.search(text):
        return "query"
    if _REVIEW.search(text):
        return "review"
    if _POLISH.search(text):
        return "polish"
    if _REWRITE.search(text):
        return "rewrite"
    if _CONTINUE.search(text):
        return "continue"
    return "query"


def _question_terms(question: str) -> list[str]:
    text = question or ""
    for word in _STOPWORDS:
        text = text.replace(word, " ")
    terms: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text):
        for size in range(min(len(chunk), 6), 1, -1):
            for i in range(0, len(chunk) - size + 1):
                term = chunk[i:i + size]
                if term not in terms:
                    terms.append(term)
    return terms


def search_prior_evidence(chapters: Iterable[Any], question: str, limit: int = 6) -> list[dict]:
    """在本章之前的章节里按问句关键词找证据摘录（关键词命中，不是完备的语义检索）。"""
    terms = _question_terms(question)
    if not terms:
        return []
    scored = []
    for chapter in chapters:
        content = chapter.content or ""
        hits = [t for t in terms if t in content]
        if not hits:
            continue
        best = max(hits, key=len)
        pos = content.index(best)
        start, end = max(0, pos - EVIDENCE_EXCERPT), min(len(content), pos + len(best) + EVIDENCE_EXCERPT)
        scored.append((sum(len(t) for t in hits), chapter.chapter_number, {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "excerpt": content[start:end].strip(),
        }))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def contract_text(outline: Optional[ChapterOutline]) -> str:
    if outline is None:
        return "（本章没有关联章纲）"
    lines = [f"标题：{outline.title}"]
    if (outline.entry_state or "").strip():
        lines.append(f"进入状态：{outline.entry_state.strip()}")
    if (outline.plot_points or "").strip():
        lines.append(f"剧情要点：{outline.plot_points.strip()}")
    events = parse_json_list(outline.key_events)
    if events:
        lines.append("关键事件：" + "、".join(events) + "（最后一条是章末落点）")
    if (outline.exit_state or "").strip():
        lines.append(f"退出状态：{outline.exit_state.strip()}")
    forbidden = forbidden_items(outline.forbidden)
    if forbidden:
        lines.append("禁止事项：" + "；".join(forbidden))
    tasks = render_narrative_tasks(outline.narrative_tasks, outline.chapter_number) if outline.narrative_tasks else ""
    if tasks.strip():
        lines.append(f"叙事任务：\n{tasks.strip()}")
    return "\n".join(lines)


def _clip_around(content: str, start: int, end: int, limit: int) -> str:
    if len(content) <= limit:
        return content
    margin = max((limit - (end - start)) // 2, 0)
    lo, hi = max(0, start - margin), min(len(content), end + margin)
    return ("…" if lo > 0 else "") + content[lo:hi] + ("…" if hi < len(content) else "")


def cast_text(cast: list) -> str:
    """本章出场人物（章纲里的涉及角色）：性格 + 说话方式，续写 / 改写时人物别走样。"""
    lines = []
    for c in cast[:CAST_LIMIT]:
        brief = "｜".join(p for p in (clip(c.personality, 60), f"说话：{clip(c.speech_style, 40)}" if c.speech_style else "") if p)
        lines.append(f"- {c.name}：{brief}" if brief else f"- {c.name}")
    return "\n".join(lines)


def world_text(project: Any) -> str:
    """世界观要点：时代 / 地点 / 规则（截短），续写 / 改写时别违背设定。"""
    if project is None:
        return ""
    parts = (f"时代：{clip(project.world_time_period, 120)}" if project.world_time_period else "",
             f"地点：{clip(project.world_location, 120)}" if project.world_location else "",
             f"规则：{clip(project.world_rules, WORLD_LIMIT)}" if project.world_rules else "")
    return "\n".join(p for p in parts if p)


def build_prompt(
    skill: str,
    *,
    message: str,
    chapter: Chapter,
    outline: Optional[ChapterOutline],
    selection: Optional[dict] = None,
    evidence: Optional[list[dict]] = None,
    issues: Optional[list[str]] = None,
    cast: str = "",
    world: str = "",
) -> str:
    content = chapter.content or ""
    header = f"当前是第{chapter.chapter_number}章《{chapter.title}》。\n作者的指令：{message.strip()}"
    contract = f"【本章章纲】\n{contract_text(outline)}"
    background = [b for b in (f"【出场人物】\n{cast}" if cast else "", f"【世界观要点】\n{world}" if world else "") if b]
    sel_start, sel_end = (selection["start"], selection["end"]) if selection else (0, 0)

    if skill == "query":
        evidence_text = "\n".join(
            f"- 第{e['chapter_number']}章《{e['title']}》：{e['excerpt']}" for e in (evidence or [])
        ) or "（前文没有找到与问题相关的段落）"
        parts = [header]
        if selection:
            parts.append("作者选中的这段是待核对的说法，不是它自己的证据：\n" + quote_untrusted(selection["text"], "选中段落"))
        parts += [
            "前文证据（只取本章之前的章节，按关键词找到，不保证完备）：\n" + quote_untrusted(evidence_text, "前文证据"),
            "本章正文：\n" + quote_untrusted(_clip_around(content, sel_start, sel_end, CURRENT_CONTEXT_CHARS), "本章正文"),
            contract,
            "回答要求：说明出自第几章、引用原句；分清人物亲身做的事和人物嘴上说的话；证据不足就说「前文没有找到依据」。",
        ]
        return "\n\n".join(parts)

    if skill == "review":
        target = selection["text"] if selection else _clip_around(content, 0, 0, CURRENT_CONTEXT_CHARS)
        issue_text = "\n".join(f"- {i}" for i in (issues or [])) or "（暂无已登记的一致性问题）"
        return "\n\n".join([
            header,
            contract,
            "已登记的一致性问题：\n" + issue_text,
            ("要核对的段落：\n" if selection else "本章正文：\n") + quote_untrusted(target, "待核对正文"),
            "核对要求：逐项对照章纲（关键事件、退出状态、禁止事项、叙事任务）与已知问题，指出问题并引用原句；"
            "没有问题就直说没问题。只给意见，不要改写正文。",
        ])

    if skill in SELECTION_SKILLS:
        before = content[max(0, sel_start - REWRITE_MARGIN_CHARS):sel_start]
        after = content[sel_end:sel_end + REWRITE_MARGIN_CHARS]
        verb = "润色（只改措辞与通顺度，不改情节和信息）" if skill == "polish" else "按指令改写"
        return "\n\n".join([
            header,
            contract,
            *background,
            "选段前文：\n" + quote_untrusted(before, "前文"),
            "要处理的选段：\n" + quote_untrusted(selection["text"], "选段"),
            "选段后文：\n" + quote_untrusted(after, "后文"),
            f"请{verb}这段，和前后文自然衔接，人名、称呼、设定不变。只输出替换后的这段正文，不要解释、不要加引号或标题。",
        ])

    tail = content[-CONTINUE_TAIL_CHARS:]
    return "\n\n".join([
        header,
        contract,
        *background,
        "本章已写正文（结尾部分）：\n" + quote_untrusted(tail, "已写正文"),
        "请紧接着最后一个字往下写 600-1200 字：照章纲推进还没写到的关键事件，写到退出状态就停，不写禁止事项里的事；"
        "不要重复已写内容，只输出新写的正文，不要解释、不要加标题。",
    ])


def clean_model_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    if len(cleaned) >= 2 and cleaned[0] in "“\"「" and cleaned[-1] in "”\"」":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def selection_matches(content: str, selection: Optional[dict]) -> bool:
    if not selection:
        return False
    start, end = selection["start"], selection["end"]
    return 0 <= start < end <= len(content) and content[start:end] == selection["text"]


async def load_tools(db: AsyncSession, chapter: Chapter) -> dict:
    """只读投影：章纲、本章之前的章节、本章未解决的一致性问题、出场人物与世界观要点（文字）。"""
    outline = await db.get(ChapterOutline, chapter.chapter_outline_id) if chapter.chapter_outline_id else None
    prior = list((await db.execute(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id, Chapter.chapter_number < chapter.chapter_number)
        .order_by(Chapter.chapter_number)
    )).scalars().all())
    issue_rows = (await db.execute(
        select(ChapterConsistencyIssue).where(ChapterConsistencyIssue.chapter_id == chapter.id)
    )).scalars().all()
    issues = [f"[{i.severity}] {i.title}：{i.details or ''}".rstrip("：") for i in issue_rows]
    project = await db.get(Project, chapter.project_id)
    names = parse_json_list(outline.characters_involved) if outline is not None else []
    cast = list((await db.execute(select(Character).where(
        Character.project_id == chapter.project_id, Character.name.in_(names),
    ))).scalars().all()) if names else []
    return {"outline": outline, "prior": prior, "issues": issues, "cast": cast_text(cast), "world": world_text(project)}


async def execute_skill(
    db: AsyncSession, chapter: Chapter, *, ai_service: Any, message: str, skill: str, selection: Optional[dict],
    on_tool: Optional[Callable[[str, str], None]] = None, on_chunk: Optional[Callable[[str], None]] = None,
) -> dict:
    """对一章执行一个技能（单章助笔与全局助笔的 manuscript 工具共用）；修改类结果存成候选稿，不改正文。"""
    content = chapter.content or ""
    if skill in SELECTION_SKILLS and not selection:
        return {"skill": skill, "answer": f"请先在正文里选中要{SKILL_LABELS[skill]}的那段，再让我处理。", "candidate": None}
    if selection and not selection_matches(content, selection):
        raise ValueError("正文在你选中之后被改过，选区对不上了；请重新选中再试")
    notify = on_tool or (lambda _name, _detail: None)

    tools = await load_tools(db, chapter)
    notify("currentChapter", f"本章正文 {len(content)} 字")
    notify("chapterContract", "已读取章纲契约" if tools["outline"] else "本章没有章纲")
    evidence: list[dict] = []
    if skill == "query":
        question = f"{message}\n{selection['text'] if selection else ''}"
        evidence = search_prior_evidence(tools["prior"], question)
        notify("contextFacts", f"前文证据 {len(evidence)} 段（只取本章之前）")
    if skill == "review":
        notify("consistencyGate", f"一致性问题 {len(tools['issues'])} 条")

    prompt = build_prompt(skill, message=message, chapter=chapter, outline=tools["outline"], selection=selection,
                          evidence=evidence, issues=tools["issues"], cast=tools["cast"], world=tools["world"])
    full = ""
    async for chunk in ai_service.generate_text_stream(
        prompt=prompt, system_prompt=ASSISTANT_SYSTEM, creative=skill in MODIFYING_SKILLS,
    ):
        full += chunk
        if on_chunk:
            on_chunk(chunk)

    if skill not in MODIFYING_SKILLS:
        return {"skill": skill, "answer": full.strip(), "candidate": None, "evidence": evidence}
    text = clean_model_text(full)
    if not text:
        raise ValueError("模型没有返回内容，没有产生候选稿")
    base = content_hash(content)
    candidate = await create_candidate(
        db, chapter,
        content=text,
        source="assistant",
        base_hash=base,
        mode="append" if skill == "continue" else "replace_range",
        range_start=selection["start"] if selection else None,
        range_end=selection["end"] if selection else None,
        original_text=selection["text"] if selection else None,
        meta={"skill": skill, "instruction": message[:200]},
    )
    await db.commit()
    return {
        "skill": skill,
        "answer": f"已生成{SKILL_LABELS[skill]}候选稿（{candidate.word_count} 字），确认后再采用写入正文。",
        "candidate": candidate_summary(candidate, base),
    }


async def run_assistant(job: Any, *, session_factory: Any, chapter_id: str, ai_service: Any, message: str,
                        skill: str, selection: Optional[dict]) -> dict:
    async with session_factory() as db:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is None:
            raise ValueError("章节不存在")
        job.progress(f"{SKILL_LABELS[skill]}中…", 20)
        return await execute_skill(
            db, chapter, ai_service=ai_service, message=message, skill=skill, selection=selection,
            on_tool=lambda name, detail: job.publish({"type": "tool", "name": name, "detail": detail}),
            on_chunk=lambda chunk: job.publish({"type": "content", "content": chunk}),
        )
