"""共创室的生成工具：复用页面上原来的 AI 生成逻辑（同一套上下文组装、提示词与解析），只是把「直接写进库」改成「出卡片」，
作者在卡片上确认才写入；每张卡的说明写明按哪个原入口生成、参考了什么。

- 世界设定：世界设定页「重新生成」（wizard_stream.world_building_prompt），出四栏修改卡；补缺时只出空着的栏
- 世界规则：建项目时自动生成世界规则（world_rule_service.generate_rules_data），出新建卡；已有规则时只补没有的
- 设定条目：原来没有 AI 生成，新写：作品信息 + 世界设定 + 世界规则明细 + 已有条目 + 对标书全书骨架 + 最终提示词
- 角色与组织：角色页「AI 批量生成」（character_batch_service.draft_cast），出人物 / 组织卡，连带关系卡、成员卡
- 人物关系：单独补关系是新写：作品信息 + 世界设定 + 人物 / 组织 + 已有关系与成员 + 对标书人物功能谱 + 最终提示词
- 总纲：谋篇页「AI 生成」（wizard_stream.outline_prompt），出总纲各栏修改卡（本书还没有总纲时目标是 new）
- 单章正文：章节页「AI 生成」（chapters.start_chapter_job），后台出候选稿
生成器只读已经写进书里的内容（待确认的卡片不算）；前置由生成总入口 run_target 先查好。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.models.assistant import AssistantEntityCandidate, AssistantMessage
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.project import Project
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.setting_entry import SETTING_CATEGORIES, SettingEntry
from app.models.world_rule import WorldRule
from app.schemas.character import CharacterBatchGenerateRequest
from app.services import assistant_entity_candidate_service as entities
from app.services import assistant_fields as fields
from app.services import creation_readiness as readiness
from app.services import story_progress as sp
from app.services.assistant_tools import (
    ToolContext, ToolError, ToolOutcome, _detail_volume, _int_arg, _member_ai, _plan_chapters, _plan_volumes, _propose_one,
    _text, create_field_card, default_style_id,
)
from app.services.knowledge.kb_context import traced_kb_context
from app.services.planning_context import clip
from app.services.prompt_service import prompt_service
from app.services.world_setting_context import build_world_context, world_query
from app.utils.json_cleaner import clean_and_parse_json
from app.utils.role_type import normalize_role_type

CARD_NOTE = "这些是候选卡：作者在卡片上点「应用 / 建档」才写进书里（回答提问不会写入），现在还没写入，不要说已经好了。"
WORLD_DATA_KEYS = {"world_time_period": "time_period", "world_location": "location", "world_atmosphere": "atmosphere",
                   "world_rules": "rules"}
WORLD_LABELS = dict(sp.WORLD_FIELDS)
RULE_ORDER = ("cultivation_realm", "equipment_template", "map_location")
OUTLINE_KEYS = ("premise", "main_plot", "golden_finger", "selling_points", "power_system", "main_tropes", "ultimate_goal",
                "opening_hook")
LIST_LIMIT = 40


def _plain(value: Any) -> str:
    return "" if value is None or isinstance(value, (dict, list)) else str(value).strip()


def _clamp(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _count(args: dict, key: str, default: int, high: int) -> int:
    return _clamp(args.get(key) if args.get(key) not in (None, "") else default, default, 0, high)


def _requirements(args: dict) -> str:
    return _text(args, "requirements", 2000, required=False)


def _reason(origin: str, refs: list[str], requirements: str = "") -> str:
    text = f"按{origin}的原逻辑生成；参考了：{'、'.join(r for r in refs if r) or '作品信息'}"
    return (text + (f"；作者要求：{requirements}" if requirements else ""))[:1000]


async def _project(ctx: ToolContext) -> Project:
    project = await ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ToolError("找不到本书")
    return project


async def _stream_text(ai: Any, prompt: str) -> str:
    text = ""
    async for chunk in ai.generate_text_stream(prompt=prompt):
        text += chunk
    return text


async def _collect_text(ai: Any, prompt: str, what: str) -> str:
    resp = await ai.generate_text_stream_collect(prompt=prompt, context=what) or {}
    content = resp.get("content") or ""
    if resp.get("finish_reason") == "length":
        raise ToolError(f"{what}：输出被 Max Tokens 截断（已输出 {len(content)} 字），请在「设置」中调大 Max Tokens 后重试")
    if not content.strip():
        raise ToolError(f"{what}：模型没有返回内容")
    return content


def _parse(text: str, expected: str, what: str) -> Any:
    try:
        return clean_and_parse_json(text, expected_type=expected, log_prefix=f"[共创室·{what}]")
    except ValueError as exc:
        raise ToolError(f"模型返回的{what}不是合法 JSON，可以再试一次") from exc


def _rows(data: Any) -> list[dict]:
    """模型偶尔把数组包在对象里：取第一个列表；只留对象。"""
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [data])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _finish(what: str, made: list[str], failed: list[str], refs: list[str], extra: str = "") -> ToolOutcome:
    if not made:
        raise ToolError(f"{what}一张卡也没出成" + (f"：{'；'.join(failed[:5])}" if failed else "（模型没给出可用的内容）"))
    shown = "、".join(made[:6]) + ("…" if len(made) > 6 else "")
    summary = f"{what}：出了 {len(made)} 张卡（{shown}）"
    lines = [summary, CARD_NOTE, f"参考了：{'、'.join(refs)}", *([extra] if extra else []),  # 模型只看得到 data
             *([f"没出成的：{'；'.join(failed[:8])}"] if failed else [])]
    return ToolOutcome(True, summary, "\n".join(lines))


async def parse_world_data(text: str, ai: Any) -> dict:
    """解析世界观输出（与向导同一套：本地清理，不行再请模型只修格式）；仍解析不了抛 ToolError，不拿占位文本出卡。"""
    from app.utils.json_cleaner import repair_json_with_llm

    try:
        data = clean_and_parse_json(text, expected_type="object", log_prefix="[共创室·世界观]")
    except ValueError:
        try:
            data = await repair_json_with_llm(text, user_ai_service=ai, expected_type="object", provider=None, model=None,
                                              schema_hint="time_period, location, atmosphere, rules",
                                              log_prefix="[共创室·世界观]")
        except Exception as exc:  # noqa: BLE001
            raise ToolError("模型返回的世界观格式不对（自动修复后仍解析不了），可以再试一次") from exc
    if not isinstance(data, dict):
        raise ToolError("模型返回的世界观格式不对，可以再试一次")
    return data


def _world_keys(project: Project, args: dict) -> list[str]:
    asked = [k for k in (args.get("fields") or []) if k in WORLD_DATA_KEYS]
    if asked:
        return asked
    empty = [k for k in WORLD_DATA_KEYS if not (getattr(project, k, None) or "").strip()]
    return empty or list(WORLD_DATA_KEYS)


async def generate_world(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.api.wizard_stream import world_building_prompt  # 原逻辑：世界设定页「重新生成」

    project, requirements = await _project(ctx), _requirements(args)
    title = project.title or "未命名项目"
    prompt, kb = await world_building_prompt(
        ctx.db, project_id=project.id, title=title, theme=project.theme or title, genre=project.genre or "通用",
        generation_prompt=project.generation_prompt, description=project.description or "", requirements=requirements,
    )
    ai = _member_ai(ctx)
    data = await parse_world_data(await _stream_text(ai, prompt), ai)
    refs = ["书名、主题、类型、简介", *([f"对标书《{kb.source_title}》全书骨架"] if kb.text else []),
            *(["最终提示词"] if (project.generation_prompt or "").strip() else [])]
    reason = _reason("世界设定页「重新生成」", refs, requirements)
    made, failed = [], []
    for key in _world_keys(project, args):
        value = _plain(data.get(WORLD_DATA_KEYS[key]))
        if not value:
            continue
        try:
            await create_field_card(ctx, f"project.{key}", project.id, value, reason)
            made.append(WORLD_LABELS[key])
        except (ToolError, fields.FieldError) as exc:
            failed.append(f"{WORLD_LABELS[key]}：{exc}")
    return _finish("世界设定", made, failed, refs)


def _order(row: dict) -> int:
    return _clamp(row.get("order_index"), 0, 0, 10_000)


async def generate_world_rules(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.services.world_rule_service import world_rule_service  # 原逻辑：建项目时自动生成世界规则

    project, requirements = await _project(ctx), _requirements(args)
    existing = list((await ctx.db.execute(select(WorldRule).where(WorldRule.project_id == project.id))).scalars())
    data = await world_rule_service.generate_rules_data(ctx.db, project, _member_ai(ctx), existing=existing,
                                                        requirements=requirements)
    if not isinstance(data, dict):
        raise ToolError("模型返回的世界规则格式不对（自动修复后仍解析不了），可以再试一次")
    refs = ["作品信息", "世界设定四栏", "主要人物与组织", *([f"已有规则 {len(existing)} 条（只补没有的）"] if existing else [])]
    reason = _reason("建项目时自动生成世界规则", refs, requirements)
    made, failed = [], []
    for category in RULE_ORDER:
        rows = [r for r in _rows(data.get(category) or []) if _plain(r.get("name"))]
        for row in sorted(rows, key=_order):
            payload = {"category": category, "name": _plain(row.get("name")), "summary": _plain(row.get("summary")),
                       "details": _plain(row.get("details")), "reason": reason}
            try:
                made.append((await _propose_one(ctx, payload, "world_rule"))["name"])
            except (ToolError, entities.EntityError) as exc:
                failed.append(f"「{payload['name']}」：{exc}")
    return _finish("世界规则", made, failed, refs)


SETTING_ENTRIES_PROMPT = """你是一位资深的小说世界观设计师。请为下面这部小说补充{count}条世界设定条目（术语 / 铁律 / 势力 / 规则等零散设定），补进已有的设定里，不要另起炉灶，也不要和已有条目重复。

作品信息：
- 书名：{title}
- 主题：{theme}
- 类型：{genre}
- 简介：{description}

世界设定：
- 时间背景：{time_period}
- 地理位置：{location}
- 氛围基调：{atmosphere}
- 世界规则：{rules}

{rules_detail}

【已有设定条目】（名字不能重复）
{existing}

【作者要求】
{requirements}

要求：
- 每条只写一件事：title 简短（2-12 字），summary 一句话说清是什么，content 写清含义、边界与代价、在故事里怎么用（100-300 字）
- category 只能是 term（术语）/ law（铁律）/ faction（势力）/ rule（规则）/ other（其他）
- 修炼境界、装备、地图地点不写成条目（它们在世界规则里），人物和组织也不写成条目（它们在角色与组织里）
- 和上面的世界设定一致，不推翻已有设定

只返回 JSON 数组，不要任何其他文字：
[{{"title": "条目名", "category": "term", "summary": "一句话简述", "content": "详细设定"}}]"""


async def generate_setting_entries(ctx: ToolContext, args: dict) -> ToolOutcome:
    project, requirements = await _project(ctx), _requirements(args)
    count = _clamp(args.get("count"), 5, 1, 8)
    existing = list((await ctx.db.execute(
        select(SettingEntry).where(SettingEntry.project_id == project.id)
        .order_by(SettingEntry.order_index, SettingEntry.created_at)
    )).scalars())
    world = await build_world_context(ctx.db, project, world_query(project, "术语 铁律 势力 规则"), scene="共创室设定条目")
    kb = await traced_kb_context(ctx.db, project.id, "worldview")
    prompt = SETTING_ENTRIES_PROMPT.format(
        count=count, title=project.title, theme=project.theme or "未设定", genre=project.genre or "通用",
        description=project.description or "未设定", time_period=project.world_time_period or "未设定",
        location=project.world_location or "未设定", atmosphere=project.world_atmosphere or "未设定",
        rules=project.world_rules or "未设定", rules_detail=world.rules or "（还没有世界规则明细）",
        existing="\n".join(f"- {e.title}：{clip(e.summary or e.content, 40)}" for e in existing[:LIST_LIMIT]) or "（暂无）",
        requirements=requirements or "无特殊要求",
    )
    if kb.text:
        prompt = f"{prompt}\n\n{kb.text}"
    prompt = prompt_service.apply_project_generation_prompt(prompt, project.generation_prompt or "")
    rows = _rows(_parse(await _collect_text(_member_ai(ctx), prompt, "生成设定条目"), "array", "设定条目"))
    refs = [r for r in ("作品信息", "世界设定四栏", "世界规则明细" if world.rules else "",
                        f"已有条目 {len(existing)} 条" if existing else "",
                        f"对标书《{kb.source_title}》全书骨架" if kb.text else "") if r]
    reason = _reason("共创室「生成设定条目」（复用世界观组装）", refs, requirements)
    made, failed = [], []
    for row in rows[:count]:
        category = _plain(row.get("category"))
        payload = {"title": _plain(row.get("title")), "category": category if category in SETTING_CATEGORIES else "other",
                   "summary": _plain(row.get("summary")), "content": _plain(row.get("content")), "reason": reason}
        try:
            made.append((await _propose_one(ctx, payload, "setting_entry"))["title"])
        except (ToolError, entities.EntityError) as exc:
            failed.append(f"「{payload['title'] or '没写名字'}」：{exc}")
    return _finish("设定条目", made, failed, refs)


def _is_org(data: dict) -> bool:
    return str(data.get("is_organization")).strip().lower() in ("true", "1", "yes")


def _person_payload(data: dict) -> dict:
    payload = {key: _plain(data.get(key)) for key in
               ("name", "age", "gender", "personality", "background", "appearance", "speech_style")}
    return {**payload, "role_type": normalize_role_type(_plain(data.get("role_type")), "supporting")}  # 与角色页同一口径


def _org_payload(data: dict) -> dict:
    return {key: _plain(data.get(key)) for key in
            ("name", "organization_type", "organization_purpose", "location", "motto", "personality", "background")}


def _links(data: dict) -> list[tuple[str, dict]]:
    """批量角色里带出的关系与组织成员（和角色页一样：关系只连人物，成员只挂组织）。"""
    name = data["name"]
    rels = data.get("relationships_array")
    rels = rels if isinstance(rels, list) else data.get("relationships") if isinstance(data.get("relationships"), list) else []
    out = [("relationship", {
        "from_name": name, "to_name": _plain(r.get("target_character_name")),
        "relationship_name": _plain(r.get("relationship_type")) or "关系",
        "intimacy_level": _clamp(r.get("intimacy_level"), 50, -100, 100), "description": _plain(r.get("description")),
    }) for r in rels if isinstance(r, dict) and _plain(r.get("target_character_name"))]
    out += [("membership", {
        "character_name": name, "organization_name": _plain(m.get("organization_name")),
        "position": _plain(m.get("position")) or "成员", "rank": _clamp(m.get("rank"), 0, 0, 100),
        "loyalty": _clamp(m.get("loyalty"), 50, 0, 100),
    }) for m in data.get("organization_memberships") or [] if isinstance(m, dict) and _plain(m.get("organization_name"))]
    return out


async def _pending_cast_names(ctx: ToolContext) -> list[str]:
    rows = (await ctx.db.execute(select(AssistantEntityCandidate.payload_json).where(
        AssistantEntityCandidate.session_id == ctx.session_id, AssistantEntityCandidate.status == "candidate",
        AssistantEntityCandidate.entity_type.in_(("character", "organization")),
    ))).scalars().all()
    return [str(json.loads(raw or "{}").get("name") or "") for raw in rows]


async def generate_cast(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.services.character_batch_service import draft_cast  # 原逻辑：角色页「AI 批量生成」

    project, requirements = await _project(ctx), _requirements(args)
    request = CharacterBatchGenerateRequest(
        project_id=project.id, character_count=_count(args, "character_count", 3, 10),
        organization_count=_count(args, "organization_count", 0, 5), requirements=requirements or None,
    )
    try:
        draft = await draft_cast(ctx.db, ai_service=_member_ai(ctx), project=project, request=request,
                                 taken=await _pending_cast_names(ctx))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    reason = _reason("角色页「AI 批量生成」", draft.refs, requirements)
    made, failed, people = [], [], []
    for data in draft.entities:
        org = _is_org(data)
        payload = _org_payload(data) if org else _person_payload(data)
        try:
            await _propose_one(ctx, {**payload, "reason": reason}, "organization" if org else "character")
            made.append(payload["name"])
            if not org:
                people.append(data)
        except (ToolError, entities.EntityError) as exc:
            failed.append(f"「{payload['name']}」：{exc}")
    links = 0
    for data in people:
        for entity_type, payload in _links(data):
            try:
                await _propose_one(ctx, {**payload, "reason": reason}, entity_type)
                links += 1
            except (ToolError, entities.EntityError):
                continue  # 连到不存在的人 / 组织或重复的：和角色页一样丢掉
    extra = "\n".join(line for line in (
        f"另有关系 / 组织成员卡 {links} 张" if links else "",
        f"重名跳过：{'、'.join(draft.skipped)}" if draft.skipped else "",
        f"后面的批次没生成成：{draft.error}" if draft.error else "",
    ) if line)
    return _finish("角色与组织", made, failed, draft.refs, extra)


RELATIONSHIPS_PROMPT = """你是一位专业的角色关系设计师。请为这部小说的人物理清关系：人物两两之间是什么关系，谁属于哪个组织、什么职位。关系要有张力、为故事服务，不要为凑数硬连。

作品信息：
- 书名：{title}
- 主题：{theme}
- 类型：{genre}
- 时间背景：{time_period}
- 地理位置：{location}
- 世界规则：{rules}

【人物】（关系两头只能用这些名字）
{people}

【组织】（成员只能挂在这些组织）
{orgs}

【已有关系】（不要重复）
{existing_relations}

【已有组织成员】（不要重复）
{existing_members}

【作者要求】
{requirements}

要求：
- relationship_type 优先从 父亲/母亲/兄弟/姐妹/子女/配偶/恋人/师父/徒弟/朋友/同学/邻居/知己/上司/下属/同事/合作伙伴/敌人/仇人/竞争对手/宿敌 里选，都不合适就写一个 2-6 字的短词
- intimacy_level 从 -100（死敌）到 100（至亲），description 写清这段关系的来由和张力（30-80 字）
- 每个人物最多挂一个主要组织；position 写具体职位，rank / loyalty 是 0-100 的整数
- 已有的关系和成员不要再写

只返回 JSON 对象，不要任何其他文字：
{{"relationships": [{{"from": "人物A", "to": "人物B", "relationship_type": "师父", "intimacy_level": 60, "description": "关系描述"}}],
 "memberships": [{{"character": "人物", "organization": "组织", "position": "职位", "rank": 50, "loyalty": 80}}]}}"""


async def generate_relationships(ctx: ToolContext, args: dict) -> ToolOutcome:
    project, requirements = await _project(ctx), _requirements(args)
    cast = list((await ctx.db.execute(
        select(Character).where(Character.project_id == project.id).order_by(Character.created_at))).scalars())
    names = {c.id: c.name for c in cast}
    people, orgs = [c for c in cast if not c.is_organization], [c for c in cast if c.is_organization]
    relations = (await ctx.db.execute(
        select(CharacterRelationship).where(CharacterRelationship.project_id == project.id))).scalars().all()
    details = {o.id: o for o in (await ctx.db.execute(
        select(Organization).where(Organization.project_id == project.id))).scalars()}
    members = (await ctx.db.execute(select(OrganizationMember).where(
        OrganizationMember.organization_id.in_(list(details))))).scalars().all() if details else []
    kb = await traced_kb_context(ctx.db, project.id, "characters")
    prompt = RELATIONSHIPS_PROMPT.format(
        title=project.title, theme=project.theme or "未设定", genre=project.genre or "通用",
        time_period=project.world_time_period or "未设定", location=project.world_location or "未设定",
        rules=clip(project.world_rules, 600) or "未设定",
        people="\n".join(f"- {c.name}（{c.role_type or 'supporting'}）：{clip(c.personality or c.background, 60)}"
                         for c in people[:LIST_LIMIT]) or "（暂无）",
        orgs="\n".join(f"- {c.name}［{c.organization_type or '势力'}］：{clip(c.organization_purpose or c.background, 60)}"
                       for c in orgs[:LIST_LIMIT]) or "（暂无）",
        existing_relations="\n".join(f"- {names.get(r.character_from_id, '?')} → {names.get(r.character_to_id, '?')}："
                                     f"{r.relationship_name or '关系'}" for r in relations[:LIST_LIMIT]) or "（暂无）",
        existing_members="\n".join(f"- {names.get(m.character_id, '?')} · {names.get(details[m.organization_id].character_id, '?')}"
                                   f"（{m.position or '成员'}）" for m in members[:LIST_LIMIT]) or "（暂无）",
        requirements=requirements or "无特殊要求",
    )
    if kb.text:
        prompt = f"{prompt}\n\n{kb.text}"
    prompt = prompt_service.apply_project_generation_prompt(prompt, project.generation_prompt or "")
    data = _parse(await _collect_text(_member_ai(ctx), prompt, "生成人物关系"), "object", "人物关系")
    data = data if isinstance(data, dict) else {}
    refs = [r for r in ("作品信息", "世界设定", f"人物 {len(people)} 个、组织 {len(orgs)} 个",
                        f"已有关系 {len(relations)} 条、成员 {len(members)} 条" if relations or members else "",
                        f"对标书《{kb.source_title}》人物功能谱" if kb.text else "") if r]
    reason = _reason("共创室「生成人物关系」（复用人物组装）", refs, requirements)
    cards = [("relationship", {
        "from_name": _plain(r.get("from")), "to_name": _plain(r.get("to")),
        "relationship_name": _plain(r.get("relationship_type")) or "关系",
        "intimacy_level": _clamp(r.get("intimacy_level"), 50, -100, 100), "description": _plain(r.get("description")),
    }) for r in _rows(data.get("relationships") or [])]
    cards += [("membership", {
        "character_name": _plain(m.get("character")), "organization_name": _plain(m.get("organization")),
        "position": _plain(m.get("position")) or "成员", "rank": _clamp(m.get("rank"), 0, 0, 100),
        "loyalty": _clamp(m.get("loyalty"), 50, 0, 100),
    }) for m in _rows(data.get("memberships") or [])]
    made, failed = [], []
    for entity_type, payload in cards:
        title = entities.display_name(entity_type, payload)
        try:
            await _propose_one(ctx, {**payload, "reason": reason}, entity_type)
            made.append(title)
        except (ToolError, entities.EntityError) as exc:
            failed.append(f"「{title}」：{exc}")
    return _finish("人物关系", made, failed, refs)


def parse_outline_data(text: str) -> Any:
    """与谋篇页同一口径：解析不出梗概和主线就不算（不拿半截原文出卡）。"""
    try:
        data = clean_and_parse_json(text, expected_type="object", log_prefix="[共创室·总纲]")
    except ValueError:
        return None
    return data if isinstance(data, dict) and (data.get("premise") or data.get("main_plot")) else None


async def generate_outline(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.api.wizard_stream import outline_cast_info, outline_prompt  # 原逻辑：谋篇页「AI 生成总纲」

    project, requirements = await _project(ctx), _requirements(args)
    chapter_count, target_words = project.chapter_count or 10, project.target_words or 100000
    heroes, others, cast_count, hero_count = await outline_cast_info(ctx.db, project.id)
    prompt, world, kb = await outline_prompt(
        ctx.db, project, narrative_perspective=project.narrative_perspective, target_words=target_words,
        chapter_count=chapter_count, requirements=requirements, protagonists_info=heroes, characters_info=others,
    )
    data = parse_outline_data(await _stream_text(_member_ai(ctx), prompt))
    if data is None:
        raise ToolError("模型返回的总纲解析不出梗概和主线，可以再试一次")
    target = (await fields.load_target(ctx.db, project.id, fields.spec_of("story_outline.premise"), fields.NEW_OUTLINE)).id
    refs = [r for r in (
        "作品信息", f"全书 {chapter_count} 章 / {project.narrative_perspective or '第三人称'} / {target_words} 字",
        "世界设定（总述 + 规则 + 条目）" if world.detail or (project.world_rules or "").strip() else "世界设定四栏",
        f"主角 {hero_count} 个、其他角色 {cast_count - hero_count} 个",
        "人物关系与组织归属" if "【🔗 人物关系与组织归属】" in others else "", f"对标书《{kb.source_title}》" if kb.text else "",
        "最终提示词" if (project.generation_prompt or "").strip() else "",
    ) if r]
    reason = _reason("谋篇页「AI 生成总纲」", refs, requirements)
    made, failed = [], []
    for key in OUTLINE_KEYS:
        value = data.get(key)
        if key in ("selling_points", "main_tropes"):
            value = ([_plain(x) for x in value if _plain(x)] if isinstance(value, list)
                     else ([_plain(value)] if _plain(value) else []))
        else:
            value = _plain(value)
        if not value:
            continue
        spec = fields.spec_of(f"story_outline.{key}")
        try:
            await create_field_card(ctx, spec.id, target, value, reason)
            made.append(spec.name)
        except (ToolError, fields.FieldError) as exc:
            failed.append(f"{spec.name}：{exc}")
    return _finish("总纲", made, failed, refs)


async def write_chapter(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.api.chapters import ChapterGenerateOptions, check_prerequisites, start_chapter_job  # 原逻辑：章节页「AI 生成」
    from app.services.ai_jobs import AIJobConflictError
    from app.services.chapter_batch_service import sync_chapters_from_outlines

    number = _int_arg(args, "chapter_number")
    if not ctx.user_id:
        raise ToolError("没有登录信息，不能启动后台写作")
    await sync_chapters_from_outlines(ctx.db, ctx.project_id)
    chapter = (await ctx.db.execute(
        select(Chapter).where(Chapter.project_id == ctx.project_id, Chapter.chapter_number == number))).scalars().first()
    if chapter is None:
        raise ToolError(f"第 {number} 章还没有章节：先生成并确认这一章的章纲")
    ok, message, _previous = await check_prerequisites(ctx.db, chapter)
    if not ok:
        raise ToolError(message)
    options = ChapterGenerateOptions(style_id=await default_style_id(ctx.db, ctx.project_id), enable_mcp=False)
    try:
        job = await start_chapter_job(chapter=chapter, user_id=ctx.user_id, ai_service=_member_ai(ctx), options=options)
    except AIJobConflictError as exc:
        raise ToolError(f"本书已有正文任务在运行：{exc}") from exc
    ctx.emit({"type": "job", "job": {"id": job.id, "title": job.title, "kind": job.kind}})
    return ToolOutcome(True, f"开始在后台生成第 {number} 章", (
        "已按章节页「AI 生成」的原逻辑在后台生成这一章（全量上下文：前情、出场人物状态、视角边界、世界观、仿写参考、写作风格…），"
        "结果是候选稿：作者在章节写作页审阅后采用才写进正文。进度在右下角任务托盘。现在正文还没变，不要说已经写好了。"))


BASIC_LABELS = {"title": "书名", "description": "简介", "theme": "主题", "genre": "类型"}
SETTING_CHOICES = {
    "chapter_count": ("全书大概写多少章？", (("100", "100 章"), ("200", "200 章"), ("300", "300 章"), ("500", "500 章")), "300"),
    "narrative_perspective": ("用什么叙事视角？", (("第三人称", "第三人称"), ("第一人称", "第一人称"), ("全知视角", "全知视角")),
                              "第三人称"),
    "target_words": ("全书目标多少字？", (("300000", "30 万字"), ("600000", "60 万字"), ("1000000", "100 万字"),
                                           ("2000000", "200 万字")), "1000000"),
}
WRITE_NOTE = "选定后直接写进作品设定（改动里可以撤销）；都不满意就在下面写你想要的，会用你写的。"
IDEA_LIMIT = 1500


async def _idea(ctx: ToolContext, project: Project) -> str:
    """灵感模式的「原始灵感」：作者在这段对话里最近说的话（不含提问卡回答和系统代发的）+ 现有简介。"""
    rows = (await ctx.db.execute(
        select(AssistantMessage.content, AssistantMessage.meta_json)
        .where(AssistantMessage.session_id == ctx.session_id, AssistantMessage.role == "user")
        .order_by(AssistantMessage.created_at.desc()).limit(8)
    )).all()
    said = [content for content, meta in rows if not ({"answer", "auto"} & set(json.loads(meta or "{}")))][:3]
    return clip("；".join(p.strip() for p in [*reversed(said), project.description or ""] if p and p.strip()), IDEA_LIMIT)


async def ask_basics(ctx: ToolContext, field: str, hint: str = "") -> ToolOutcome:
    from app.api.inspiration import _generate_options_impl  # 原逻辑：灵感模式的候选生成

    project = await _project(ctx)
    label = BASIC_LABELS[field]
    result = await _generate_options_impl({
        "step": field, "hint": hint,
        "context": {"original_idea": await _idea(ctx, project), "title": project.title or "",
                    "description": project.description or "", "theme": project.theme or ""},
    }, _member_ai(ctx))
    options = [o.strip() for o in result.get("options") or [] if isinstance(o, str) and o.strip()][:8]
    if result.get("error") or len(options) < 3:
        raise ToolError(f"{label}的候选没生成出来（{result.get('error') or '候选太少'}），可以再试一次，或请作者直接说")
    prompt = (result.get("prompt") or f"选一个{label}").strip().rstrip("：:")  # 回答气泡写成「问题：答案」
    question = {"note": WRITE_NOTE, "questions": [{
        "id": field, "prompt": prompt, "mode": "multiple" if field == "genre" else "single",
        "options": [{"id": f"o{i}", "label": text[:500], "description": "", "recommended": False}
                    for i, text in enumerate(options, 1)],
        "write": {"field_id": f"project.{field}", "target_id": project.id, "join": "、" if field == "genre" else ""},
    }]}
    return ToolOutcome(True, f"请作者选{label}（灵感模式出了 {len(options)} 个候选）",
                       f"等作者在提问卡里选{label}；选定直接写入作品设定。", question=question)


def settings_question(project_id: str, keys) -> dict:
    return {"note": WRITE_NOTE, "questions": [{
        "id": key, "prompt": prompt, "mode": "single",
        "options": [{"id": value, "label": label, "value": value, "description": "", "recommended": value == best}
                    for value, label in choices],
        "write": {"field_id": f"project.{key}", "target_id": project_id, "join": ""},
    } for key in keys for prompt, choices, best in (SETTING_CHOICES[key],)]}


async def fill_basics(ctx: ToolContext, args: dict) -> ToolOutcome:
    project = await _project(ctx)
    asked = [f for f in (args.get("fields") or []) if f in BASIC_LABELS or f in SETTING_CHOICES]
    if not asked:
        asked = [k for k, _label in sp.missing_basics(project)][:1] or [k for k, _label in sp.missing_settings(project)]
    if not asked:
        return ToolOutcome(True, "作品信息都已定好", "书名、简介、主题、类型、全书章数、叙事视角、目标字数都已写；"
                                                     "要重新挑哪一项，带 fields 再调用 fill_basics。")
    basics = [f for f in asked if f in BASIC_LABELS]
    if basics:
        return await ask_basics(ctx, basics[0], _text(args, "hint", 500, required=False))
    settings = [f for f in asked if f in SETTING_CHOICES][:3]
    labels = "、".join(dict(sp.SETTING_FIELDS)[k] for k in settings)
    return ToolOutcome(True, f"请作者定：{labels}", "等作者在提问卡里选；选定直接写入作品设定。",
                       question=settings_question(project.id, settings))


GENERATORS = {
    "world": generate_world, "world_rules": generate_world_rules, "setting_entries": generate_setting_entries,
    "cast": generate_cast, "relationships": generate_relationships, "outline": generate_outline,
    "volumes": _plan_volumes, "detail": _detail_volume, "outlines": _plan_chapters, "chapter": write_chapter,
}
TOOL_OF = {"world": "generate_world", "world_rules": "generate_world_rules", "setting_entries": "generate_setting_entries",
           "cast": "generate_cast", "relationships": "generate_relationships", "outline": "generate_outline",
           "volumes": "plan_volumes", "detail": "detail_volume", "outlines": "plan_chapters", "chapter": "write_chapter"}
PARAM_KEYS = {"detail": ("volume_number",), "outlines": ("volume_number", "unit_index"), "chapter": ("chapter_number",)}
MAX_UPSTREAM = 8
WAIT_NOTE = ("{what}：要作者先在待确认栏处理这些卡片。这一轮不要再调用生成工具，回复里告诉作者先确认哪些、确认后会接着{label}"
             "（作者处理完，系统会自动接着做）。")
DEFER_NOTE = ("上游还没有，已先按原逻辑生成了上游卡片：这一轮不要再调用生成工具；回复里告诉作者先在待确认栏确认这些卡片，"
              "确认后会自动接着{label}。")
DECLINED_NOTE = ("{what}，而上一轮生成的{layer}卡片作者没采用：不要再自动生成。用 ask_author 问作者：重新生成{layer}"
                 "（可以补充想法），还是不补、直接{label}（再调用时带 force=true）。")


def _params(target: str, args: dict) -> dict:
    return {key: _int_arg(args, key) for key in PARAM_KEYS.get(target, ())}


def target_label(target: str, args: dict) -> str:
    if target == "cast":
        people, orgs = _count(args, "character_count", 3, 10), _count(args, "organization_count", 0, 5)
        return "生成" + "、".join(p for p in (f"{people} 个人物" if people else "", f"{orgs} 个组织" if orgs else "") if p)
    if target == "detail":
        return f"细化第{args.get('volume_number')}卷"
    if target == "outlines":
        return f"生成第{args.get('volume_number')}卷单元 {args.get('unit_index')} 的章纲"
    if target == "chapter":
        return f"写第 {args.get('chapter_number')} 章正文"
    if target == "volumes":
        return "按总纲分卷"
    return f"生成{readiness.TARGET_LABELS[target]}"


def _deepest(checker: Any, need: Any) -> Any:
    """沿着「要先生成的上游」往上追，直到追到能直接处理的那一步（最上游的缺口）。"""
    for _ in range(MAX_UPSTREAM):
        if need is None or need.kind != "generate":
            return need
        inner = readiness.need_for(checker, need.layer, **_params(need.layer, need.args))
        if inner is None:
            return need
        need = inner
    return need


def _new_cards(ctx: ToolContext, marks: tuple[int, int, int]) -> dict:
    volume_ids, outline_ids = [], []
    for plan in ctx.plans[marks[2]:]:
        if plan.get("kind") == "volumes":
            volume_ids += [v["id"] for v in plan.get("volumes") or []]
        elif plan.get("kind") == "units" and plan.get("volume"):
            volume_ids.append(plan["volume"]["id"])
        else:
            outline_ids += [c["id"] for c in plan.get("chapters") or []]
    waiting = {"candidates": [c["id"] for c in ctx.candidates[marks[0]:]],
               "entity_candidates": [c["id"] for c in ctx.entity_candidates[marks[1]:]],
               "volume_ids": volume_ids, "outline_ids": outline_ids}
    return {key: ids for key, ids in waiting.items() if ids}


def _defer(ctx: ToolContext, target: str, args: dict, label: str, waiting: dict) -> None:
    ctx.deferred = {"goal": ctx.origin_goal, "label": label, "tool": TOOL_OF[target],
                    "args": {k: v for k, v in args.items() if k != "force"}, "waiting": waiting}


async def run_target(ctx: ToolContext, target: str, args: dict) -> ToolOutcome:
    """生成工具的总入口：先查前置；缺必需的上游就先按原逻辑补上游（出卡 / 提问）并挂起这件事，齐了才按原逻辑生成。
    作者明确说不补、直接做时带 force=true 跳过前置。"""
    params, label = _params(target, args), target_label(target, args)
    need = None
    if args.get("force") is not True:
        provided = {"project.chapter_count"} if target == "volumes" and args.get("chapter_count") else set()
        checker = await readiness.load_checker(ctx.db, ctx.project_id, ctx.session_id, ctx.declined | provided)
        need = _deepest(checker, readiness.need_for(checker, target, **params))
    if need is None:
        return await GENERATORS[target](ctx, args)
    if need.kind == "basics":
        return await ask_basics(ctx, need.fields[0])
    if need.kind == "settings":
        labels = "、".join(readiness.SETTING_LABELS[k] for k in need.fields)
        return ToolOutcome(True, f"{label}之前要作者先定：{labels}", "等作者在提问卡里选；选定直接写入作品设定，之后接着做。",
                           question=settings_question(ctx.project_id, need.fields))
    if need.kind == "blocked":
        return ToolOutcome(False, f"{label}：{need.label}", f"这一步现在做不了：{need.label}。如实告诉作者。")
    if need.kind == "confirm":
        _defer(ctx, target, args, label, need.waiting)
        return ToolOutcome(True, f"{label}：先等作者确认（{need.label}）", WAIT_NOTE.format(what=need.label, label=label))
    layer = readiness.TARGET_LABELS[need.layer]
    if need.layer in ctx.declined:
        return ToolOutcome(False, f"{label}：{need.label}（上一轮的{layer}卡片作者没采用）",
                           DECLINED_NOTE.format(what=need.label, layer=layer, label=label))
    marks = (len(ctx.candidates), len(ctx.entity_candidates), len(ctx.plans))
    upstream = await GENERATORS[need.layer](ctx, dict(need.args))
    waiting = _new_cards(ctx, marks)
    if not upstream.ok or not waiting:
        return ToolOutcome(False, f"{label}：{need.label}，先补{layer}也没成功", upstream.data or upstream.summary)
    _defer(ctx, target, args, label, waiting)
    return ToolOutcome(True, f"{need.label}：先按原逻辑生成了{layer}，作者确认后接着{label}",
                       f"{DEFER_NOTE.format(label=label)}\n{upstream.data}")  # 说明放前面：工具结果超长会从尾部截断
