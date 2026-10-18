"""全局智能助笔 · 全书工具（参考岚笺：工具随打开的作品开放，当前页面不是权限边界；只开放受控工具）。

没有任意文件 / 数据库 / 删除 / 保存工具：修改只能 propose_edit 生成候选（作者应用才写入），
正文只能交给 manuscript（产出章节候选稿）或 write_chapters（后台批量写已确认的章纲），提问用 ask_author 暂停等待作者回答。
共创室：每位成员只能用自己职责内的工具（cocreation_team.Member.tools）；规划工具（分卷 / 细化 / 单元章纲）只产出草稿，
并推送「草案卡片」让作者确认。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate, AssistantFieldCandidate
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.knowledge import KbSource
from app.models.project import Project
from app.models.story_outline import StoryOutline
from app.models.world_map import WorldMapLocation
from app.models.volume import Volume
from app.services import assistant_candidate_service as cands
from app.services import assistant_entity_candidate_service as entities
from app.services import assistant_fields as fields
from app.services import cocreation_team as team
from app.services import volume_service as volumes
from app.services.assistant_checks_service import project_checks
from app.services.assistant_persistence import PersistError, write_verified
from app.services.knowledge import kb_query
from app.services.knowledge.entry_types import ENTRY_TYPES, entry_label
from app.services.planning_context import clip
from app.services.story_progress import progress_snapshot
from app.services.writing_assistant_service import SELECTION_SKILLS, SKILL_LABELS, execute_skill

PAGES = {
    "world-setting": "世界设定", "world-rules": "世界规则", "setting-entries": "世界设定条目", "world-map": "世界地图",
    "characters": "角色与组织", "relationships": "关系管理", "outline": "谋篇（总纲 / 卷纲 / 章纲）",
    "chapter-analysis": "章节写作", "writing-styles": "写作风格", "memories": "故事账本",
}

TOOLS: dict[str, tuple[str, str, str]] = {
    "search_project": ("查找资料", "在本书的章节正文、章纲、人物、设定、地点里按关键词找资料（返回出处与摘录）",
                       '{"query": "关键词（多个用空格分开）"}'),
    "list_fields": ("定位内容", "列出可以修改的内容项：字段 ID、目标 ID、名称与当前内容摘要；可按人物名 / 章号 / 字段名筛选",
                    '{"query": "可选，例如 林尘 性格"}'),
    "read_field": ("读取内容", "读取某一项的当前完整内容（修改前必须先读取这一项）", '{"field_id": "...", "target_id": "..."}'),
    "propose_edit": ("准备修改候选", "为某一项生成修改候选：value 是完整的新内容（列表类字段给字符串数组），作者确认后才写入",
                     '{"field_id": "...", "target_id": "...", "value": "完整新内容", "reason": "为什么这样改"}'),
    "propose_character": ("新建角色", "为本书新建一个角色（人物）生成候选，作者在对话里确认后才真正建档；name 必填，其余可留空",
                          '{"name": "角色名", "role_type": "protagonist|supporting|antagonist（可选）", "age": "可选", '
                          '"gender": "可选", "personality": "性格（可选）", "background": "背景故事（可选）", '
                          '"appearance": "外貌（可选）", "speech_style": "说话风格（可选）", "reason": "为什么加（可选）"}'),
    "propose_organization": ("新建组织", "为本书新建一个组织 / 势力生成候选，作者确认后才真正建档；name 必填，其余可留空",
                             '{"name": "组织名", "organization_type": "类型（可选）", "organization_purpose": "宗旨（可选）", '
                             '"personality": "组织特性（可选）", "background": "背景（可选）", "reason": "为什么加（可选）"}'),
    "propose_setting_entry": ("新建设定条目", "为本书新建一条世界设定（术语 / 铁律 / 势力 / 规则等，不属于境界·装备·地图三类）"
                              "生成候选，作者确认后才建档；分条存、各自独立容量，别再往「世界规则」单字段里堆。title 必填",
                              '{"title": "条目名", "category": "term|law|faction|rule|other（可选）", '
                              '"summary": "一句话简述（可选）", "content": "详细设定（可选）", "reason": "为什么加（可选）"}'),
    "manuscript": ("处理正文", "处理某一章的正文：continue 续写 / rewrite 改写选段 / polish 润色选段 / review 核对本章 / query 查前文；"
                              "改写、润色只能处理作者在该章正文里选中的那段；修改类结果是候选稿",
                   '{"chapter_number": 1, "skill": "continue", "instruction": "具体要求"}'),
    "open_page": ("打开页面", "打开某个页面给作者看", '{"page": "' + "|".join(PAGES) + '"}'),
    "project_status": ("查看待办", "查看本书需要注意的事项：待确认章纲、未分析 / 分析过期的章节、待审候选稿、一致性问题", "{}"),
    "ask_author": ("向作者提问", "需要作者做决定、选方案或补充信息时提问并等待回答（最多 3 个问题；单选 / 多选至少 2 个选项）",
                   '{"questions": [{"id": "q1", "prompt": "问题", "mode": "single|multiple|text", '
                   '"options": [{"id": "a", "label": "选项", "recommended": true}]}]}'),
    "story_progress": ("查看创作进度", "总纲 / 卷纲 / 章纲 / 正文各到哪一步，以及建议的下一步", "{}"),
    "kb_search": ("查知识库", "在作者的知识库（拆过的书）里按关键词找条目：多个词用空格分开、都要命中；可按类型筛选"
                             "（chapter 章卡 / arc 剧情单元 / volume 分卷 / synopsis 全书骨架 / characters 人物功能谱 / "
                             "methodology 写法手册 / structure 结构统计 / style 文风 / excerpt 片段）",
                  '{"query": "关键词", "type": "可选，条目类型"}'),
    "kb_read": ("读知识库条目", "读一条知识库条目（先 kb_search 拿到 entry_id）：默认去名版（人名换成功能位，适合学结构）；"
                             "view=named 看原名版。只学结构、节奏和写法，不照搬人物、设定与情节",
                '{"entry_id": "...", "view": "denamed|named"}'),
    "plan_volumes": ("按总纲分卷", "按总纲把全书（已写章纲之后的部分）分卷，产出卷纲草稿（已有章纲的卷保留）",
                     '{"chapter_count": 可选全书章数, "volume_count": 可选卷数, "instruction": "可选，作者对分卷的要求"}'),
    "detail_volume": ("细化卷纲", "把某一卷拆成剧情单元并编排线索，产出草稿（本卷已有章纲时不能重拆）",
                      '{"volume_number": 1, "instruction": "可选要求"}'),
    "plan_chapters": ("生成单元章纲", "把某卷的某个剧情单元展开为章纲（只补缺的章），产出待确认的章纲",
                      '{"volume_number": 1, "unit_index": 1, "instruction": "可选要求"}'),
    "write_chapters": ("写正文", "在后台批量写一段章节的正文（只写作者已确认的章纲，遇到未确认的会停下）",
                       '{"from_chapter": 1, "to_chapter": 3}'),
    "delegate": ("交给成员", "把一件具体的事交给某位成员处理，拿到他的结果后再决定下一步（只有主编能用）",
                 '{"member": "world|character|outline|chapter|writer|reviewer", "task": "要他做的事，写清楚范围和要求"}'),
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
    user_id: Optional[str] = None
    member_id: str = team.DEFAULT_MEMBER
    model: Optional[str] = None
    plans: list = field(default_factory=list)
    entity_candidates: list = field(default_factory=list)


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


async def _propose_entity(ctx: ToolContext, args: dict, entity_type: str) -> ToolOutcome:
    reason = _text(args, "reason", 1000, required=False)
    made: list = []

    async def write() -> None:
        for stale in made:  # 上次提交被别的请求回滚了：丢掉旧对象，重建一份
            if stale in ctx.db:
                ctx.db.expunge(stale)
        made.append(await entities.create_entity_candidate(
            ctx.db, project_id=ctx.project_id, session_id=ctx.session_id, run_id=ctx.run_id,
            entity_type=entity_type, payload=args, reason=reason,
        ))

    async def verify() -> bool:
        return bool(await ctx.db.scalar(
            select(AssistantEntityCandidate.id).where(AssistantEntityCandidate.id == made[-1].id)))

    try:
        await write_verified(ctx.db, write, verify, "新建对象候选")
    except PersistError as exc:
        raise ToolError(str(exc))
    view = entities.entity_candidate_view(made[-1])
    ctx.entity_candidates.append(view)
    ctx.emit({"type": "entity_candidate", "candidate": view})
    return ToolOutcome(True, f"为「{view['label']}」准备了新建候选",
                       "新建候选已生成，正在等作者在对话里确认后才真正建档；现在还没有建，不要说已经建好了。")


async def _propose_character(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "character")


async def _propose_organization(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "organization")


async def _propose_setting_entry(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "setting_entry")


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


# ---------------- 共创：进度与规划 ----------------

DRAFT_NOTE = "这些是草稿：作者在对话里的草案卡片或谋篇页确认后才算定稿，现在不要说已经定好了。"


def _int_arg(args: dict, key: str, required: bool = True) -> Optional[int]:
    value = args.get(key)
    if value in (None, ""):
        if required:
            raise ToolError(f"缺少参数 {key}")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"参数 {key} 应是整数")
    if number < 1:
        raise ToolError(f"参数 {key} 应大于 0")
    return number


def _emit_plan(ctx: ToolContext, plan: dict) -> None:
    ctx.plans.append(plan)
    ctx.emit({"type": "plan", "plan": plan})


def _volume_card(v: dict) -> dict:
    return {"id": v["id"], "volume_number": v["volume_number"], "title": v["title"], "chapter_start": v["chapter_start"],
            "chapter_end": v["chapter_end"], "summary": clip(v["summary"], 160), "unit_count": len(v["units"])}


async def _volume_by_number(ctx: ToolContext, number: int) -> Volume:
    volume = (await ctx.db.execute(
        select(Volume).where(Volume.project_id == ctx.project_id, Volume.volume_number == number)
    )).scalars().first()
    if volume is None:
        raise ToolError(f"本书还没有第 {number} 卷：先用 story_progress 看看现有的卷")
    return volume


async def _story_progress(ctx: ToolContext, _args: dict) -> ToolOutcome:
    snapshot = await progress_snapshot(ctx.db, ctx.project_id)
    return ToolOutcome(True, f"下一步：{snapshot['next_step']['label']}", snapshot["text"])


KB_SEARCH_LIMIT = 8
KB_BOUNDARY = "（知识库里是拆过的书：只学结构、节奏和写法，不照搬人物、设定与情节）"


async def _kb_user(ctx: ToolContext) -> str:
    if ctx.user_id:
        return ctx.user_id
    project = await ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ToolError("找不到本书")
    return project.user_id


async def _kb_search(ctx: ToolContext, args: dict) -> ToolOutcome:
    query = _text(args, "query", 200)
    entry_type = str(args.get("type") or "").strip() or None
    if entry_type is not None and entry_type not in ENTRY_TYPES:
        raise ToolError("type 只能是 " + " / ".join(ENTRY_TYPES))
    user_id = await _kb_user(ctx)
    rows, total = await kb_query.search_entries(ctx.db, user_id, query, entry_type=entry_type, limit=KB_SEARCH_LIMIT)
    if not rows:
        return ToolOutcome(True, "知识库里没有找到", f"知识库里没有找到同时包含「{query}」的条目；可以换个说法或少用几个词。")
    titles = {s.id: s.title for s in await kb_query.list_sources(ctx.db, user_id)}
    lines = [f"- [{e.id}] 《{titles.get(e.source_id, '')}》{e.title}（{entry_label(e.entry_type)}）：{clip(e.summary, 80)}"
             for e in rows]
    more = f"\n（共 {total} 条，只列前 {len(rows)} 条；要看全文用 kb_read）" if total > len(rows) else "\n（要看全文用 kb_read）"
    return ToolOutcome(True, f"知识库里找到 {total} 条", "\n".join(lines) + more)


async def _kb_read(ctx: ToolContext, args: dict) -> ToolOutcome:
    entry_id = _text(args, "entry_id", 64)
    named = str(args.get("view") or "denamed").strip() == "named"
    entry = await kb_query.get_entry(ctx.db, await _kb_user(ctx), entry_id)
    if entry is None:
        raise ToolError("知识库里没有这条：先用 kb_search 查到 entry_id")
    source = await ctx.db.get(KbSource, entry.source_id)
    ctx.read_targets.add(f"kb:{entry.id}:{entry.revision or 1}")
    head = (f"《{source.title if source else ''}》{entry.title}｜{entry_label(entry.entry_type)}｜修订 {entry.revision or 1}｜"
            f"{'原名版' if named else '去名版'}")
    body = (entry.body if named else entry.denamed_body) or entry.body or ""
    return ToolOutcome(True, f"读了《{entry.title}》", clip(f"{head}\n{KB_BOUNDARY}\n\n{body}", DATA_LIMIT))


async def _plan_volumes(ctx: ToolContext, args: dict) -> ToolOutcome:
    created = await volumes.generate_skeleton(
        ctx.db, ctx.project_id, ctx.ai_service, total_chapters=_int_arg(args, "chapter_count", False),
        volume_count=_int_arg(args, "volume_count", False), instruction=_text(args, "instruction", 2000, False),
        model=ctx.model,
    )
    cards = [_volume_card(volumes.volume_to_dict(v)) for v in created]
    _emit_plan(ctx, {"kind": "volumes", "title": f"分卷草案：{len(cards)} 卷", "volumes": cards})
    lines = [f"- 第{c['volume_number']}卷《{c['title']}》第 {c['chapter_start']}-{c['chapter_end']} 章：{c['summary']}" for c in cards]
    return ToolOutcome(True, f"分了 {len(cards)} 卷（草稿）", "\n".join([*lines, DRAFT_NOTE]))


async def _detail_volume(ctx: ToolContext, args: dict) -> ToolOutcome:
    volume = await _volume_by_number(ctx, _int_arg(args, "volume_number"))
    volume = await volumes.detail_volume(ctx.db, volume.id, ctx.ai_service,
                                         instruction=_text(args, "instruction", 2000, False), model=ctx.model)
    view = volumes.volume_to_dict(volume)
    units = [{"index": u["index"], "title": u["title"], "chapter_start": u["chapter_start"],
              "chapter_end": u["chapter_end"], "story": clip(u.get("story"), 140)} for u in view["units"]]
    _emit_plan(ctx, {"kind": "units", "title": f"第{view['volume_number']}卷《{view['title']}》剧情单元草案",
                     "volume": {**_volume_card(view), "units": units, "threads": view["threads"]}})
    lines = [f"- 单元 {u['index']}《{u['title']}》第 {u['chapter_start']}-{u['chapter_end']} 章：{u['story']}" for u in units]
    return ToolOutcome(True, f"第{view['volume_number']}卷拆成 {len(units)} 个剧情单元（草稿）", "\n".join([*lines, DRAFT_NOTE]))


async def _plan_chapters(ctx: ToolContext, args: dict) -> ToolOutcome:
    volume = await _volume_by_number(ctx, _int_arg(args, "volume_number"))
    unit_index = _int_arg(args, "unit_index")
    created = await volumes.generate_unit_outlines(ctx.db, volume.id, unit_index, ctx.ai_service,
                                                   instruction=_text(args, "instruction", 2000, False), model=ctx.model)
    chapters = [{"id": o.id, "chapter_number": o.chapter_number, "title": o.title, "plot_points": clip(o.plot_points, 120)}
                for o in created]
    _emit_plan(ctx, {"kind": "outlines", "title": f"第{volume.volume_number}卷单元 {unit_index} 章纲草案（{len(chapters)} 章）",
                     "volume_id": volume.id, "unit_index": unit_index, "chapters": chapters})
    lines = [f"- 第{c['chapter_number']}章《{c['title']}》：{c['plot_points']}" for c in chapters]
    return ToolOutcome(True, f"生成了 {len(chapters)} 章章纲（待确认）", "\n".join([*lines, DRAFT_NOTE]))


async def _write_chapters(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.api.chapters import start_batch_job
    from app.services.ai_jobs import AIJobConflictError
    from app.services.chapter_batch_service import BatchOptions

    start, end = _int_arg(args, "from_chapter"), _int_arg(args, "to_chapter")
    if end < start:
        raise ToolError("to_chapter 不能小于 from_chapter")
    if end - start + 1 > 50:
        raise ToolError("一次最多写 50 章，分几次来")
    if not ctx.user_id:
        raise ToolError("没有登录信息，不能启动后台写作")
    try:
        job = await start_batch_job(project_id=ctx.project_id, user_id=ctx.user_id, ai_service=ctx.ai_service,
                                    options=BatchOptions(from_chapter=start, to_chapter=end, require_confirmed_outline=True))
    except AIJobConflictError as exc:
        raise ToolError(f"本书已有正文任务在运行：{exc}")
    ctx.emit({"type": "job", "job": {"id": job.id, "title": job.title, "kind": job.kind}})
    return ToolOutcome(True, f"开始在后台写第 {start}-{end} 章",
                       "后台批量写作已开始：只写已确认的章纲，写完的章节会自动采用并分析；进度在右下角任务托盘。"
                       "现在正文还没写完，不要说已经写好了。")


HANDLERS = {
    "search_project": _search_project, "list_fields": _list_fields, "read_field": _read_field,
    "propose_edit": _propose_edit, "propose_character": _propose_character,
    "propose_organization": _propose_organization, "propose_setting_entry": _propose_setting_entry,
    "manuscript": _manuscript, "open_page": _open_page,
    "project_status": _project_status, "ask_author": _ask_author, "story_progress": _story_progress,
    "kb_search": _kb_search, "kb_read": _kb_read,
    "plan_volumes": _plan_volumes, "detail_volume": _detail_volume, "plan_chapters": _plan_chapters,
    "write_chapters": _write_chapters,
}


async def execute_tool(ctx: ToolContext, name: str, args: Any) -> ToolOutcome:
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolOutcome(False, f"没有这个工具：{name}", f"没有这个工具：{name}。只能用：{'、'.join(HANDLERS)}。")
    speaker = team.member(ctx.member_id)
    if name not in speaker.tools:
        return ToolOutcome(False, f"{speaker.name}不能用「{tool_label(name)}」",
                           f"这件事不在{speaker.name}的职责内（你能用：{'、'.join(speaker.tools)}）；请直接回复，建议作者找主编或对应成员。")
    if not isinstance(args, dict):
        return ToolOutcome(False, f"{tool_label(name)}：参数格式不对", "args 应是 JSON 对象。")
    try:
        outcome = await handler(ctx, args)
    except (ToolError, fields.FieldError, entities.EntityError, ValueError, volumes.VolumeConflictError) as exc:
        return ToolOutcome(False, f"{tool_label(name)}：{exc}", f"这一步没有成功：{exc}")
    outcome.data = outcome.data[:DATA_LIMIT]
    return outcome


def tool_catalog_text(allowed: Optional[tuple[str, ...]] = None) -> str:
    return "\n".join(
        f"- {name}：{desc}\n  参数：{schema}"
        for name, (_label, desc, schema) in TOOLS.items() if allowed is None or name in allowed
    )
