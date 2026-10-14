"""全局智能助笔 · 全书工具（参考岚笺：工具随打开的作品开放，当前页面不是权限边界；只开放受控工具）。

没有任意文件 / 数据库 / 删除 / 保存工具：修改只能 propose_edit 生成候选（作者应用才写入），
正文只能交给 manuscript（产出章节候选稿），提问用 ask_author 暂停等待作者回答。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantFieldCandidate
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.project import Project
from app.models.story_outline import StoryOutline
from app.models.world_map import WorldMapLocation
from app.services import assistant_candidate_service as cands
from app.services import assistant_fields as fields
from app.services.assistant_checks_service import project_checks
from app.services.assistant_persistence import PersistError, write_verified
from app.services.writing_assistant_service import SELECTION_SKILLS, SKILL_LABELS, execute_skill

PAGES = {
    "world-setting": "世界设定", "world-rules": "世界规则", "world-map": "世界地图", "characters": "角色与组织",
    "relationships": "关系管理", "outline": "故事大纲", "plot-bridges": "桥段规划", "chapter-analysis": "章节写作",
    "writing-styles": "写作风格", "memories": "记忆系统",
}

TOOLS: dict[str, tuple[str, str, str]] = {
    "search_project": ("查找资料", "在本书的章节正文、章纲、人物、设定、地点里按关键词找资料（返回出处与摘录）",
                       '{"query": "关键词（多个用空格分开）"}'),
    "list_fields": ("定位内容", "列出可以修改的内容项：字段 ID、目标 ID、名称与当前内容摘要；可按人物名 / 章号 / 字段名筛选",
                    '{"query": "可选，例如 林尘 性格"}'),
    "read_field": ("读取内容", "读取某一项的当前完整内容（修改前必须先读取这一项）", '{"field_id": "...", "target_id": "..."}'),
    "propose_edit": ("准备修改候选", "为某一项生成修改候选：value 是完整的新内容（列表类字段给字符串数组），作者确认后才写入",
                     '{"field_id": "...", "target_id": "...", "value": "完整新内容", "reason": "为什么这样改"}'),
    "manuscript": ("处理正文", "处理某一章的正文：continue 续写 / rewrite 改写选段 / polish 润色选段 / review 核对本章 / query 查前文；"
                              "改写、润色只能处理作者在该章正文里选中的那段；修改类结果是候选稿",
                   '{"chapter_number": 1, "skill": "continue", "instruction": "具体要求"}'),
    "open_page": ("打开页面", "打开某个页面给作者看", '{"page": "' + "|".join(PAGES) + '"}'),
    "project_status": ("查看待办", "查看本书需要注意的事项：待确认章纲、未分析 / 分析过期的章节、待审候选稿、一致性问题", "{}"),
    "ask_author": ("向作者提问", "需要作者做决定、选方案或补充信息时提问并等待回答（最多 3 个问题；单选 / 多选至少 2 个选项）",
                   '{"questions": [{"id": "q1", "prompt": "问题", "mode": "single|multiple|text", '
                   '"options": [{"id": "a", "label": "选项", "recommended": true}]}]}'),
}
SEARCH_LIMIT = 8
EXCERPT = 60
DATA_LIMIT = 6000


@dataclass
class ToolContext:
    db: AsyncSession
    project_id: str
    session_id: str
    run_id: str
    page: dict
    ai_service: Any
    emit: Callable[[dict], None]
    read_targets: set = field(default_factory=set)
    candidates: list = field(default_factory=list)
    chapter_candidates: list = field(default_factory=list)


@dataclass
class ToolOutcome:
    ok: bool
    summary: str
    data: str = ""
    question: Optional[dict] = None


class ToolError(Exception):
    pass


def tool_label(name: str) -> str:
    return TOOLS[name][0] if name in TOOLS else name


def _text(args: dict, key: str, limit: int = 2000, required: bool = True) -> str:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolError(f"缺少参数 {key}")
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ToolError(f"参数 {key} 应是文字")
    return str(value).strip()[:limit]


def _excerpt(text: str, term: str) -> str:
    pos = text.find(term)
    start, end = max(0, pos - EXCERPT), min(len(text), pos + len(term) + EXCERPT)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


async def _search_sources(db: AsyncSession, project_id: str) -> list[tuple[str, str, str, str]]:
    """(类别, 出处名称, 页面, 文本)"""
    sources: list[tuple[str, str, str, str]] = []
    project = await db.get(Project, project_id)
    if project:
        setting = "\n".join(filter(None, [project.description, project.theme, project.world_time_period,
                                          project.world_location, project.world_atmosphere, project.world_rules]))
        sources.append(("设定", "作品设定", "world-setting", setting))
    for so in (await db.execute(select(StoryOutline).where(StoryOutline.project_id == project_id))).scalars():
        sources.append(("大纲", f"故事大纲《{so.title}》", "outline", so.content or ""))
    for c in (await db.execute(select(Character).where(Character.project_id == project_id))).scalars():
        text = "\n".join(filter(None, [c.name, c.personality, c.background, c.appearance, c.organization_purpose]))
        sources.append(("组织" if c.is_organization else "人物", c.name, "characters", text))
    for o in (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id).order_by(ChapterOutline.chapter_number)
    )).scalars():
        text = "\n".join(filter(None, [o.title, o.plot_points, o.key_events, o.entry_state, o.exit_state, o.scene]))
        sources.append(("章纲", f"第{o.chapter_number}章章纲《{o.title}》", "outline", text))
    for ch in (await db.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number)
    )).scalars():
        sources.append(("正文", f"第{ch.chapter_number}章《{ch.title}》", "chapter-analysis", ch.content or ""))
    for loc in (await db.execute(select(WorldMapLocation).where(WorldMapLocation.project_id == project_id))).scalars():
        sources.append(("地点", loc.name, "world-map", "\n".join(filter(None, [loc.name, loc.region, loc.description]))))
    return sources


async def _search_project(ctx: ToolContext, args: dict) -> ToolOutcome:
    query = _text(args, "query", 100)
    terms = [t for t in re.split(r"[\s,，、；;]+", query) if t] or [query]
    hits = []
    for kind, title, page, text in await _search_sources(ctx.db, ctx.project_id):
        found = [t for t in terms if t in text]
        if found:
            best = max(found, key=len)
            hits.append((sum(len(t) for t in found), kind, title, page, _excerpt(text, best)))
    hits.sort(key=lambda h: -h[0])
    hits = hits[:SEARCH_LIMIT]
    if not hits:
        return ToolOutcome(True, f"没找到「{query}」", f"本书资料里没有找到「{query}」。")
    data = "\n".join(f"- [{kind}] {title}（页面 {page}）：{excerpt}" for _s, kind, title, page, excerpt in hits)
    return ToolOutcome(True, f"找到 {len(hits)} 处「{query}」", data)


async def _list_fields(ctx: ToolContext, args: dict) -> ToolOutcome:
    query = _text(args, "query", 100, required=False)
    rows = await fields.list_fields(ctx.db, ctx.project_id, query)
    if not rows:
        return ToolOutcome(True, "没有匹配的内容项", f"没有和「{query}」匹配的可修改内容；换个说法或不带 query 再列。")
    data = "\n".join(
        f"- {r['label']}｜field_id={r['field_id']}｜target_id={r['target_id']}｜当前：{r['preview']}" for r in rows
    )
    return ToolOutcome(True, f"列出 {len(rows)} 项{('「' + query + '」') if query else ''}", data)


async def _read_field(ctx: ToolContext, args: dict) -> ToolOutcome:
    got = await fields.read_field(ctx.db, ctx.project_id, _text(args, "field_id", 80), _text(args, "target_id", 36))
    ctx.read_targets.add((got["field_id"], got["target_id"]))
    value = json.dumps(got["value"], ensure_ascii=False) if got["kind"] == "list" else (got["value"] or "（空白）")
    return ToolOutcome(True, f"读取「{got['label']}」",
                       f"{got['label']}（{'列表' if got['kind'] == 'list' else '文字'}，上限 {got['max_length']} 字）：\n{value}")


async def _propose_edit(ctx: ToolContext, args: dict) -> ToolOutcome:
    field_id, target_id = _text(args, "field_id", 80), _text(args, "target_id", 36)
    if (field_id, target_id) not in ctx.read_targets:
        raise ToolError("修改前先用 read_field 读取这一项的当前内容，再按读到的内容给出完整的新值")
    if "value" not in args:
        raise ToolError("缺少参数 value（完整的新内容）")
    reason = _text(args, "reason", 1000, required=False)
    made: list = []

    async def write() -> None:
        for stale in made:  # 上次提交被别的请求回滚了：丢掉会话里的旧对象，重新生成一份
            if stale in ctx.db:
                ctx.db.expunge(stale)
        made.append(await cands.create_field_candidate(
            ctx.db, project_id=ctx.project_id, session_id=ctx.session_id, run_id=ctx.run_id,
            field_id=field_id, target_id=target_id, value=args["value"], reason=reason,
        ))

    async def verify() -> bool:
        return bool(await ctx.db.scalar(select(AssistantFieldCandidate.id).where(AssistantFieldCandidate.id == made[-1].id)))

    try:
        await write_verified(ctx.db, write, verify, "修改候选")
    except PersistError as exc:
        raise ToolError(str(exc))
    candidate = made[-1]
    view = cands.candidate_view(candidate)
    ctx.candidates.append(view)
    ctx.emit({"type": "candidate", "candidate": view})
    return ToolOutcome(True, f"为「{view['label']}」准备了修改候选",
                       "修改候选已生成，正在等作者在对话里比较后决定是否应用；现在还没有写入，不要说已经改好了。")


async def _manuscript(ctx: ToolContext, args: dict) -> ToolOutcome:
    try:
        number = int(args.get("chapter_number"))
    except (TypeError, ValueError):
        raise ToolError("chapter_number 应是章号（整数）")
    skill = _text(args, "skill", 20)
    if skill not in SKILL_LABELS:
        raise ToolError(f"skill 只能是 {'/'.join(SKILL_LABELS)}")
    instruction = _text(args, "instruction", 2000, required=False) or SKILL_LABELS[skill]
    chapter = (await ctx.db.execute(
        select(Chapter).where(Chapter.project_id == ctx.project_id, Chapter.chapter_number == number)
    )).scalar_one_or_none()
    if chapter is None:
        raise ToolError(f"本书没有第 {number} 章")
    selection = None
    if skill in SELECTION_SKILLS:
        page_sel = ctx.page.get("selection")
        if not page_sel or ctx.page.get("chapter_id") != chapter.id:
            raise ToolError(f"{SKILL_LABELS[skill]}只能处理作者在第 {number} 章正文里选中的那段：请作者在章节写作页选中后再说")
        selection = page_sel
    result = await execute_skill(ctx.db, chapter, ai_service=ctx.ai_service, message=instruction, skill=skill,
                                 selection=selection)
    label = f"第 {number} 章 · {SKILL_LABELS[skill]}"
    candidate = result.get("candidate")
    if candidate and not await ctx.db.scalar(select(ChapterCandidate.id).where(ChapterCandidate.id == candidate["id"])):
        raise ToolError("候选稿没能写进数据库（被同时进行的其他操作打断），请再说一次")
    if candidate:
        summary = {**candidate, "chapter_number": number, "chapter_title": chapter.title}
        ctx.chapter_candidates.append(summary)
        ctx.emit({"type": "chapter_candidate", "candidate": summary})
        return ToolOutcome(True, f"{label}：候选稿 {candidate.get('word_count', 0)} 字",
                           f"{result['answer']}\n候选稿开头：{candidate.get('preview', '')}\n"
                           "作者要在章节写作页的候选稿里审阅后采用，现在正文还没变。")
    return ToolOutcome(True, label, result.get("answer") or "（没有结果）")


async def _open_page(ctx: ToolContext, args: dict) -> ToolOutcome:
    page = _text(args, "page", 40)
    if page not in PAGES:
        raise ToolError(f"没有这个页面：{page}；可用：{'、'.join(PAGES)}")
    ctx.emit({"type": "navigate", "page": page, "label": PAGES[page]})
    return ToolOutcome(True, f"打开「{PAGES[page]}」", f"已为作者打开「{PAGES[page]}」页面。")


async def _project_status(ctx: ToolContext, _args: dict) -> ToolOutcome:
    checks = await project_checks(ctx.db, ctx.project_id)
    items = checks["items"]
    if not items:
        return ToolOutcome(True, "没有需要注意的事项", "本书目前没有待确认章纲、过期分析、待审候选稿或一致性问题。")
    data = "\n".join(f"- [{i['kind']}] {i['title']}：{i['detail']}" for i in items[:30])
    return ToolOutcome(True, f"需要注意 {len(items)} 项", data)


def validate_questions(raw: Any) -> dict:
    questions = raw.get("questions") if isinstance(raw, dict) else None
    if not isinstance(questions, list) or not 1 <= len(questions) <= 3:
        raise ToolError("questions 应是 1-3 个问题")
    out, ids = [], set()
    for q in questions:
        if not isinstance(q, dict):
            raise ToolError("每个问题应是对象")
        qid = str(q.get("id") or f"q{len(out) + 1}")[:40]
        prompt = str(q.get("prompt") or "").strip()[:1000]
        mode = q.get("mode") if q.get("mode") in ("single", "multiple", "text") else "text"
        options = []
        for o in q.get("options") or []:
            if isinstance(o, dict) and str(o.get("label") or "").strip():
                options.append({"id": str(o.get("id") or f"o{len(options) + 1}")[:40], "label": str(o["label"]).strip()[:120],
                                "description": str(o.get("description") or "")[:500], "recommended": bool(o.get("recommended"))})
        options = options[:8]
        if not prompt or qid in ids:
            raise ToolError("问题缺少 prompt 或 id 重复")
        if mode != "text" and len(options) < 2:
            raise ToolError("单选 / 多选问题至少要有 2 个选项")
        if len({o["id"] for o in options}) != len(options):
            raise ToolError("选项 id 重复")
        ids.add(qid)
        out.append({"id": qid, "prompt": prompt, "mode": mode, "options": options if mode != "text" else []})
    return {"questions": out}


async def _ask_author(_ctx: ToolContext, args: dict) -> ToolOutcome:
    question = validate_questions(args)
    return ToolOutcome(True, f"向作者提问 {len(question['questions'])} 个问题", "等待作者回答。", question=question)


HANDLERS = {
    "search_project": _search_project, "list_fields": _list_fields, "read_field": _read_field,
    "propose_edit": _propose_edit, "manuscript": _manuscript, "open_page": _open_page,
    "project_status": _project_status, "ask_author": _ask_author,
}


async def execute_tool(ctx: ToolContext, name: str, args: Any) -> ToolOutcome:
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolOutcome(False, f"没有这个工具：{name}", f"没有这个工具：{name}。只能用：{'、'.join(HANDLERS)}。")
    if not isinstance(args, dict):
        return ToolOutcome(False, f"{tool_label(name)}：参数格式不对", "args 应是 JSON 对象。")
    try:
        outcome = await handler(ctx, args)
    except (ToolError, fields.FieldError, ValueError) as exc:
        return ToolOutcome(False, f"{tool_label(name)}：{exc}", f"这一步没有成功：{exc}")
    outcome.data = outcome.data[:DATA_LIMIT]
    return outcome


def tool_catalog_text() -> str:
    return "\n".join(f"- {name}：{desc}\n  参数：{schema}" for name, (_label, desc, schema) in TOOLS.items())
