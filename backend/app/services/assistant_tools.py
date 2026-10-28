"""全局智能助笔 · 全书工具（参考岚笺：工具随打开的作品开放，当前页面不是权限边界；只开放受控工具）。

没有任意文件 / 数据库 / 删除 / 保存工具：要 AI 构思、撰写的内容走生成工具（fill_basics / generate_* / 规划 / write_chapter，
见 assistant_generators：复用页面上原来的 AI 生成逻辑，先查前置，只出卡片或草稿）；作者口述的内容与小改用 propose_edit /
propose_* 生成候选（作者应用 / 建档才写入）；正文交给 manuscript（产出章节候选稿）或 write_chapters（后台批量写已确认的章纲），
提问用 ask_author 暂停等待作者回答。工具目录、查找结果、可修改内容都按创作顺序排（作品信息 → 世界设定 → 世界规则 → 设定条目 →
角色与组织 → 关系 → 总纲 → 卷纲 → 章纲 → 正文），每一层都查得到（search_project）、看得到（read_field / read_chapter）、
改得了（propose_edit / manuscript）。共创室：每位成员只能用自己职责内的工具（cocreation_team.Member.tools）；规划工具
（分卷 / 细化 / 单元章纲）只产出草稿，并推送「草案卡片」让作者确认。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantEntityCandidate, AssistantFieldCandidate
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.knowledge import KbSource
from app.models.project import Project
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.setting_entry import SETTING_CATEGORY_LABELS, SettingEntry
from app.models.story_outline import StoryOutline
from app.models.world_map import WorldMapLocation
from app.models.world_rule import WorldRule
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
from app.services.volume_planning import loads_threads, loads_units
from app.services.writing_assistant_service import SELECTION_SKILLS, SKILL_LABELS, execute_skill
from app.utils.character_names import parse_aliases
from app.utils.story_outline_fields import parse_story_outline_fields

PAGES = {
    "world-setting": "世界设定", "world-rules": "世界规则", "setting-entries": "世界设定条目", "world-map": "世界地图",
    "characters": "角色与组织", "relationships": "关系管理", "organizations": "组织与成员",
    "outline": "谋篇（总纲 / 卷纲 / 章纲）", "chapter-analysis": "章节写作", "writing-styles": "写作风格", "memories": "故事账本",
}

BATCH_LIMIT = 8
_BATCH_HINT = f"；一次可以提多条：{{\"items\": [{{...}}, {{...}}]}}（每条的参数同单条，最多 {BATCH_LIMIT} 条）"

FORCE_HINT = "；会先查前置，缺必需的上游会先补上游卡片再挂起这件事；作者明确说不补、直接做时才加 \"force\": true"

# 顺序 = 给模型看的目录顺序：先查看类，再是按创作顺序排的生成工具（作品信息 → 世界 → 人物 → 关系 → 总纲 → 卷纲 → 章纲 →
# 正文），最后是记录作者口述内容 / 小改用的 propose_*（同样按创作顺序）
TOOLS: dict[str, tuple[str, str, str]] = {
    "story_progress": ("查看创作进度", "作品信息 → 世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 → 卷纲 → 章纲 → 正文 各到哪一步，"
                                       "以及按这个顺序建议的下一步（每轮开头的【创作进度】就是它；作者处理过卡片后可以再看一次）", "{}"),
    "search_project": ("查找资料", "在本书的世界设定、世界规则、设定条目、地点、人物与组织、人物关系、组织成员、总纲、卷纲（含剧情单元）、"
                                   "章纲、章节正文里按关键词找资料（返回出处与摘录，按创作顺序列）",
                       '{"query": "关键词（多个用空格分开）"}'),
    "list_fields": ("定位内容", "列出可以修改的内容项（按创作顺序：作品设定 / 世界规则 / 设定条目 / 地点 / 人物 / 组织 / 人物关系 / "
                                "组织成员 / 总纲 / 卷纲 / 剧情单元 / 章纲）：字段 ID、目标 ID、名称与当前内容摘要；可按人物名 / 章号 / "
                                "卷号 / 字段名筛选（本书还没有总纲时，总纲各字段的目标是 new，照常 propose_edit，作者应用时新建总纲）",
                    '{"query": "可选，例如 林尘 性格"}'),
    "read_field": ("读取内容", "读取某一项的当前完整内容（选项字段会列出能填的值）", '{"field_id": "...", "target_id": "..."}'),
    "read_chapter": ("读正文", "读某一章的正文原文（长章分段读：offset 是从第几个字开始，每次最多约 5000 字，结果里会说下一段从哪读）；"
                               "改写 / 润色前先读原文，引用要逐字",
                     '{"chapter_number": 1, "offset": 0}'),
    "kb_search": ("查知识库", "在作者的知识库（拆过的书）里按关键词找条目：多个词用空格分开、都要命中；可按类型筛选"
                             "（chapter 章卡 / arc 剧情单元 / volume 分卷 / synopsis 全书骨架 / characters 人物功能谱 / "
                             "methodology 写法手册 / structure 结构统计 / style 文风 / excerpt 片段）",
                  '{"query": "关键词", "type": "可选，条目类型"}'),
    "kb_read": ("读知识库条目", "读一条知识库条目（先 kb_search 拿到 entry_id）：默认去名版（人名换成功能位，适合学结构）；"
                             "view=named 看原名版。只学结构、节奏和写法，不照搬人物、设定与情节",
                '{"entry_id": "...", "view": "denamed|named"}'),
    "fill_basics": ("补作品信息", "按灵感模式补书名 / 简介 / 主题 / 类型（每项出 6 个候选，作者在提问卡里选，选定直接写入），"
                                 "或问作者全书章数 / 叙事视角 / 目标字数；不传 fields 就补第一项缺的",
                    '{"fields": ["description"]（可选：title / description / theme / genre / chapter_count / '
                    'narrative_perspective / target_words）, "hint": "可选，作者对这一项的要求"}'),
    "generate_world": ("生成世界设定", "按世界设定页「重新生成」的原逻辑生成时代背景 / 地点设定 / 氛围基调 / 世界规则四栏的修改卡"
                                       "（参考书名、主题、类型、对标书、最终提示词，自动带齐）；不传 fields 就只生成空着的栏" + FORCE_HINT,
                       '{"fields": ["world_time_period", "world_location", "world_atmosphere", "world_rules"]（可选）, '
                       '"requirements": "可选，作者的原话"}'),
    "generate_world_rules": ("生成世界规则", "按建项目时自动生成世界规则的原逻辑（按题材出修炼境界 / 装备 / 地图，或地位层级 / "
                                             "资源 / 地点）生成新建卡；已有规则时只补没有的" + FORCE_HINT,
                             '{"requirements": "可选，作者的原话"}'),
    "generate_setting_entries": ("生成设定条目", "生成术语 / 铁律 / 势力 / 规则等设定条目的新建卡（参考作品信息、世界设定、"
                                                 "世界规则、已有条目、对标书）" + FORCE_HINT,
                                 '{"count": 5, "requirements": "可选，作者的原话"}'),
    "generate_cast": ("生成角色与组织", "按角色页「AI 批量生成」的原逻辑生成人物 / 组织新建卡，连带关系卡和组织成员卡（参考作品信息、"
                                         "世界设定、已有角色组织、世界规则与设定条目、对标书人物功能谱）；只要组织时 character_count=0"
                      + FORCE_HINT,
                      '{"character_count": 3, "organization_count": 0, "requirements": "作者的原话，如 主角的师父，亦正亦邪"}'),
    "generate_relationships": ("生成人物关系", "给书里已有的人物理关系、记组织成员，产出关系卡和成员卡（参考人物、组织、已有关系、"
                                               "世界设定、对标书）" + FORCE_HINT,
                               '{"requirements": "可选，作者的原话"}'),
    "generate_outline": ("生成总纲", "按谋篇页「AI 生成总纲」的原逻辑生成总纲各栏的修改卡（参考作品信息、章数 / 视角 / 字数、"
                                     "世界观、主角与其他角色、对标书、项目提示词、最终提示词）" + FORCE_HINT,
                         '{"requirements": "可选，作者的原话"}'),
    "plan_volumes": ("按总纲分卷", "按总纲把全书（已写章纲之后的部分）分卷，产出卷纲草稿（已有章纲的卷保留）" + FORCE_HINT,
                     '{"chapter_count": 可选全书章数, "volume_count": 可选卷数, "instruction": "可选，作者对分卷的要求"}'),
    "detail_volume": ("细化卷纲", "把某一卷拆成剧情单元并编排线索，产出草稿（分卷草案要先确认；本卷已有章纲时不能重拆；"
                                  "已有单元的文字用 propose_edit 改）" + FORCE_HINT,
                      '{"volume_number": 1, "instruction": "可选要求"}'),
    "plan_chapters": ("生成单元章纲", "把某卷的某个剧情单元展开为章纲（剧情单元草案要先确认；只补缺的章），产出待确认的章纲" + FORCE_HINT,
                      '{"volume_number": 1, "unit_index": 1, "instruction": "可选要求"}'),
    "write_chapter": ("写一章正文", "按章节页「AI 生成」的原逻辑在后台生成这一章的候选稿（全量上下文；章纲要已确认、前面的章要写完；"
                                    "作者在章节写作页审阅采用）" + FORCE_HINT,
                      '{"chapter_number": 1}'),
    "write_chapters": ("写正文", "在后台批量写一段章节的正文（只写作者已确认的章纲，遇到未确认的会停下）",
                       '{"from_chapter": 1, "to_chapter": 3}'),
    "manuscript": ("处理正文", "处理某一章的正文：continue 续写 / rewrite 改写 / polish 润色 / review 核对本章 / query 查前文；"
                              "改写、润色要指明哪一段：作者在该章正文里选中的那段，或用 quote 逐字引用要改的原文（先 read_chapter 读原文，"
                              "引用要在本章里只出现一次）；修改类结果是候选稿",
                   '{"chapter_number": 1, "skill": "continue", "instruction": "具体要求", "quote": "改写 / 润色时要改的原文（可选）"}'),
    "propose_edit": ("准备修改候选", "为已有的某一项生成修改候选：value 是完整的新内容（列表类字段给字符串数组，数字字段给整数），"
                                     "作者在卡片上点「应用」才写入；这一项已有内容而你还没读过时，会先把现有内容给你，按它给出完整新值再提一次；"
                                     f"一次可以改多项：{{\"items\": [{{\"field_id\": ..., \"target_id\": ..., \"value\": ..., "
                                     f"\"reason\": ...}}, ...]}}（最多 {BATCH_LIMIT} 项）",
                     '{"field_id": "...", "target_id": "...", "value": "完整新内容", "reason": "为什么这样改"}'),
    "propose_world_rule": ("新建世界规则", "为本书新建一条世界规则（世界规则页的三类：cultivation_realm 修炼境界 / equipment_template "
                           "装备模板 / map_location 地图位置；地图位置建档后会出现在世界地图上）生成候选，作者在卡片上点「建档」才建档；"
                           "同一分类已有同名的改用 propose_edit。境界按从低到高的顺序提" + _BATCH_HINT,
                           '{"category": "cultivation_realm|equipment_template|map_location", "name": "名称", '
                           '"summary": "一句话简述（可选）", "details": "详细设定：突破条件 / 战力范围 / 用途 / 地理关系等（可选）", '
                           '"reason": "为什么加（可选）"}'),
    "propose_setting_entry": ("新建设定条目", "为本书新建一条世界设定条目（术语 / 铁律 / 势力 / 规则等；修炼境界、装备、地图位置三类"
                              "用 propose_world_rule）生成候选，作者在卡片上点「建档」才建档；本书已有同名的改用 propose_edit；"
                              "分条存、各自独立容量，别再往「世界规则」单字段里堆。title 必填" + _BATCH_HINT,
                              '{"title": "条目名", "category": "term|law|faction|rule|other（可选）", '
                              '"summary": "一句话简述（可选）", "content": "详细设定（可选）", "reason": "为什么加（可选）"}'),
    "propose_character": ("新建角色", "为本书新建一个角色（人物）生成候选，作者在卡片上点「建档」才真正建档；本书已有同名的改用 propose_edit；"
                                      "name 必填，其余可留空" + _BATCH_HINT,
                          '{"name": "角色名", "role_type": "protagonist|supporting|antagonist|mentor|ally|extra（可选）", '
                          '"age": "可选", "gender": "可选", "personality": "性格（可选）", "background": "背景故事（可选）", '
                          '"appearance": "外貌（可选）", "speech_style": "说话风格（可选）", "reason": "为什么加（可选）"}'),
    "propose_organization": ("新建组织", "为本书新建一个组织 / 势力生成候选，作者在卡片上点「建档」才真正建档；本书已有同名的改用 "
                                         "propose_edit；name 必填，其余可留空" + _BATCH_HINT,
                             '{"name": "组织名", "organization_type": "类型（可选）", "organization_purpose": "宗旨（可选）", '
                             '"location": "所在地（可选）", "motto": "座右铭 / 口号（可选）", '
                             '"personality": "组织特性（可选）", "background": "背景（可选）", "reason": "为什么加（可选）"}'),
    "propose_relationship": ("新建关系", "为两个人物新建一条关系（关系页）生成候选，作者在卡片上点「建档」才建档；from_name / to_name 填人物名"
                                         "（书里已有的，或本段对话里刚提的人物候选），这一对已经有关系的改用 propose_edit" + _BATCH_HINT,
                             '{"from_name": "角色A", "to_name": "角色B", "relationship_name": "关系，如 师徒 / 宿敌 / 青梅竹马", '
                             '"intimacy_level": "亲密度，-100（敌对）到 100（亲密），可选", '
                             '"status": "active 进行中|broken 已破裂|past 已结束|complicated 复杂（可选）", '
                             '"description": "关系描述（可选）", "reason": "为什么加（可选）"}'),
    "propose_membership": ("加入组织", "把一个人物记成某个组织的成员（组织页的成员列表）生成候选，作者在卡片上点「建档」才写入；"
                                       "character_name 填人物名、organization_name 填组织名（书里已有的，或本段对话里刚提的候选），"
                                       "已经是成员的改用 propose_edit" + _BATCH_HINT,
                           '{"character_name": "人物", "organization_name": "组织", "position": "职位，如 掌门 / 外门弟子", '
                           '"rank": "职位等级 0-100（可选）", "loyalty": "忠诚度 0-100（可选）", '
                           '"status": "active 在职|retired 已退出|expelled 被逐出|deceased 已故（可选）", "reason": "为什么加（可选）"}'),
    "project_status": ("查看待办", "查看本书需要注意的事项：待确认章纲、未分析 / 分析过期的章节、待审候选稿、一致性问题", "{}"),
    "open_page": ("打开页面", "打开某个页面给作者看", '{"page": "' + "|".join(PAGES) + '"}'),
    "ask_author": ("向作者提问", "需要作者做决定、选方案或补充信息时提问并等待回答（最多 3 个问题；单选 / 多选至少 2 个选项）",
                   '{"questions": [{"id": "q1", "prompt": "问题", "mode": "single|multiple|text", '
                   '"options": [{"id": "a", "label": "选项", "recommended": true}]}]}'),
    "delegate": ("交给成员", "把一件具体的事交给某位成员处理，拿到他的结果后再决定下一步（只有主编能用）",
                 '{"member": "world|character|outline|chapter|writer|reviewer", "task": "要他做的事，写清楚范围和要求"}'),
}
SEARCH_LIMIT = 12
EXCERPT = 60
DATA_LIMIT = 6000
CHAPTER_PAGE = 5000  # read_chapter 一次最多读这么多字（结果整体还要过 DATA_LIMIT）
TARGET_ID_LIMIT = 64  # 剧情单元的目标是「卷 id:单元序号」，比 uuid 长


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
    deferred: Optional[dict] = None  # 生成总入口挂起的要求：等作者处理完上游卡片自动接着做
    declined: set = field(default_factory=set)  # 作者没采用的层 / 这一轮跳过的作品信息字段：不再自动补
    origin_goal: str = ""  # 作者最初那句要求（续跑时也是它）


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


def _member_ai(ctx: ToolContext) -> Any:
    """发言成员设了自己的模型：处理正文 / 批量写作也用它（复制一份改默认模型，不动共享实例）。"""
    if not ctx.model or getattr(ctx.ai_service, "default_model", None) == ctx.model:
        return ctx.ai_service
    svc = copy.copy(ctx.ai_service)
    svc.default_model = ctx.model
    return svc


def _emit_card(ctx: ToolContext, kind: str, payload: dict) -> None:
    """推一张卡片给前端：带上是哪位成员提的，运行中就能挂到他的发言下。"""
    ctx.emit({"type": kind, **payload, "member_id": ctx.member_id})


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


def _join(*parts: Any) -> str:
    return "\n".join(str(p) for p in parts if p)


# 总纲各栏（谋篇页的名字）：查找资料时按栏目读，不读一串 JSON
_OUTLINE_KEYS = tuple((spec.json_key, spec.name) for spec in fields.FIELD_SPECS.values()
                      if spec.entity == "story_outline" and spec.json_key)


def _outline_text(content: Optional[str]) -> str:
    data = parse_story_outline_fields(content)
    return _join(*(f"{name}：{'、'.join(value) if isinstance(value, list) else value}"
                   for key, name in _OUTLINE_KEYS if (value := data.get(key))))


def _volume_text(v: Volume) -> str:
    units = [_join(f"单元 {u.get('index')}《{u.get('title') or ''}》", u.get("story"), u.get("turn"))
             for u in loads_units(v.units)]
    return _join(v.title, v.goal, v.summary, v.climax, v.ending_hook, "；".join(loads_threads(v.threads)), *units)


async def _search_sources(db: AsyncSession, project_id: str,
                          terms: Optional[list[str]] = None) -> list[tuple[str, str, str, str]]:
    """(类别, 出处名称, 页面, 文本)，按创作顺序：作品设定 → 世界规则 → 设定条目 → 地点 → 人物 / 组织 → 人物关系 → 组织成员 →
    总纲 → 卷纲（含剧情单元）→ 章纲 → 正文。给了 terms 就只把含关键词的章节正文读进来（长篇不必每次读全书正文）。"""
    sources: list[tuple[str, str, str, str]] = []
    project = await db.get(Project, project_id)
    if project:
        sources.append(("设定", "作品设定", "world-setting", _join(
            project.title, project.genre, project.description, project.theme, project.world_time_period,
            project.world_location, project.world_atmosphere, project.world_rules, project.generation_prompt)))
    for rule in (await db.execute(
        select(WorldRule).where(WorldRule.project_id == project_id).order_by(WorldRule.category, WorldRule.order_index)
    )).scalars():
        sources.append(("世界规则", f"{fields.WORLD_RULE_LABELS.get(rule.category, '世界规则')}「{rule.name}」", "world-rules",
                        _join(rule.name, rule.summary, rule.details)))
    for entry in (await db.execute(
        select(SettingEntry).where(SettingEntry.project_id == project_id).order_by(SettingEntry.order_index)
    )).scalars():
        sources.append(("设定条目", entry.title, "setting-entries", _join(
            entry.title, SETTING_CATEGORY_LABELS.get(entry.category, entry.category), entry.summary, entry.content)))
    for loc in (await db.execute(select(WorldMapLocation).where(WorldMapLocation.project_id == project_id))).scalars():
        sources.append(("地点", loc.name, "world-map", _join(loc.name, loc.region, loc.description)))

    cast = list((await db.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    )).scalars())
    names = {c.id: c.name for c in cast}
    orgs = {o.id: o for o in (await db.execute(select(Organization).where(Organization.project_id == project_id))).scalars()}
    details = {o.character_id: o for o in orgs.values()}
    for c in cast:
        detail = details.get(c.id)
        sources.append(("组织" if c.is_organization else "人物", c.name, "characters", _join(
            c.name, "、".join(parse_aliases(c.aliases)), fields.ROLE_LABELS.get(c.role_type or "", ""), c.age, c.gender,
            c.organization_type, c.organization_purpose, getattr(detail, "location", None), getattr(detail, "motto", None),
            c.personality, c.speech_style, c.appearance, c.background)))
    for r in (await db.execute(
        select(CharacterRelationship).where(CharacterRelationship.project_id == project_id)
        .order_by(CharacterRelationship.created_at)
    )).scalars():
        a, b = names.get(r.character_from_id, fields.UNKNOWN_CAST), names.get(r.character_to_id, fields.UNKNOWN_CAST)
        sources.append(("关系", f"{a} → {b}", "relationships", _join(
            a, b, r.relationship_name, fields.RELATIONSHIP_STATUS_LABELS.get(r.status or "", ""), r.description)))
    members = (await db.execute(
        select(OrganizationMember).where(OrganizationMember.organization_id.in_(list(orgs)))
        .order_by(OrganizationMember.created_at)
    )).scalars() if orgs else []
    for m in members:
        org_name = names.get(orgs[m.organization_id].character_id, fields.UNKNOWN_CAST)
        person = names.get(m.character_id, fields.UNKNOWN_CAST)
        sources.append(("组织成员", f"{org_name} · {person}", "organizations", _join(
            org_name, person, m.position, fields.MEMBER_STATUS_LABELS.get(m.status or "", ""), m.notes)))

    for so in (await db.execute(
        select(StoryOutline).where(StoryOutline.project_id == project_id)
        .order_by(StoryOutline.is_active.desc(), StoryOutline.version.desc())
    )).scalars():
        sources.append(("总纲", f"总纲《{so.title}》" + ("" if so.is_active else "（旧版本）"), "outline", _outline_text(so.content)))
    for v in (await db.execute(
        select(Volume).where(Volume.project_id == project_id).order_by(Volume.volume_number)
    )).scalars():
        sources.append(("卷纲", f"第{v.volume_number}卷《{v.title}》", "outline", _volume_text(v)))
    for o in (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id).order_by(ChapterOutline.chapter_number)
    )).scalars():
        sources.append(("章纲", f"第{o.chapter_number}章章纲《{o.title}》", "outline",
                        _join(o.title, o.plot_points, o.key_events, o.entry_state, o.exit_state, o.scene)))
    chapters = select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number)
    if terms:
        chapters = chapters.where(or_(*(Chapter.content.contains(t, autoescape=True) for t in terms)))
    for ch in (await db.execute(chapters)).scalars():
        sources.append(("正文", f"第{ch.chapter_number}章《{ch.title}》", "chapter-analysis", ch.content or ""))
    return sources


async def _search_project(ctx: ToolContext, args: dict) -> ToolOutcome:
    query = _text(args, "query", 100)
    terms = [t for t in re.split(r"[\s,，、；;]+", query) if t] or [query]
    hits = []
    for kind, title, page, text in await _search_sources(ctx.db, ctx.project_id, terms):
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
    rows, total, loose = await fields.find_fields(ctx.db, ctx.project_id, query)
    if not rows:
        return ToolOutcome(True, "没有匹配的内容项", f"没有和「{query}」匹配的可修改内容；换个说法或不带 query 再列。")
    notes = []
    if loose:
        notes.append("（没有同时包含全部关键词的内容项，下面按任一关键词列出，命中多的在前）")
    if total > len(rows):
        notes.append(f"（共 {total} 项，只列了前 {len(rows)} 项；加上人物名、章号或字段名再筛选）")
    data = "\n".join([*notes, *(
        f"- {r['label']}｜field_id={r['field_id']}｜target_id={r['target_id']}｜当前：{r['preview']}" for r in rows
    )])
    more = f"（共 {total} 项）" if total > len(rows) else ""
    return ToolOutcome(True, f"列出 {len(rows)} 项{('「' + query + '」') if query else ''}{more}", data)


def _field_text(got: dict) -> str:
    spec = fields.FIELD_SPECS.get(got["field_id"])
    value = json.dumps(got["value"], ensure_ascii=False) if got["kind"] == "list" else (got["value"] or "（空白）")
    if got["kind"] == "number" and spec is not None:
        shape = f"整数，{spec.min_value} 到 {spec.max_value}"
    else:
        shape = f"{'列表' if got['kind'] == 'list' else '文字'}，上限 {got['max_length']} 字"
    meaning = fields.display_value(spec, got["value"])
    shown = f"{value}（{meaning}）" if meaning and meaning != value else value
    allowed = f"\n只能填：{fields.choice_text(spec)}" if spec is not None and spec.choices else ""
    return f"{got['label']}（{shape}）：\n{shown}{allowed}"


async def _read_field(ctx: ToolContext, args: dict) -> ToolOutcome:
    got = await fields.read_field(ctx.db, ctx.project_id, _text(args, "field_id", 80),
                                  _text(args, "target_id", TARGET_ID_LIMIT))
    ctx.read_targets.add((got["field_id"], got["target_id"]))
    return ToolOutcome(True, f"读取「{got['label']}」", _field_text(got))


class _NeedsRead(Exception):
    """这一项已有内容、模型还没读过：已替它读好，带着现有内容退回去重提。"""

    def __init__(self, got: dict):
        super().__init__(got["label"])
        self.got = got


async def _propose_edit(ctx: ToolContext, args: dict) -> ToolOutcome:
    items = args.get("items")
    if items is None:
        try:
            view = await _propose_one_edit(ctx, args)
        except _NeedsRead as need:
            return ToolOutcome(False, f"修改前先读了「{need.got['label']}」的现有内容",
                               "这一项已经有内容（下面是现有内容，已替你读取）：在它的基础上给出完整的新值，"
                               f"再调用 propose_edit。\n{_field_text(need.got)}")
        return ToolOutcome(True, f"为{view['label']}准备了修改候选", _EDIT_NOTE)
    if not isinstance(items, list) or not items:
        raise ToolError("items 应是一组对象（每项一个 {field_id, target_id, value, reason}）；只改一项就直接给参数")
    if len(items) > BATCH_LIMIT:
        raise ToolError(f"一次最多改 {BATCH_LIMIT} 项，分几次来")
    made, reads, failed = [], [], []
    for item in items:  # 一项一项提：前面的已经落库；没读过的有内容项退回现有内容，其余照提
        try:
            if not isinstance(item, dict):
                raise ToolError("每项应是一个对象")
            made.append(await _propose_one_edit(ctx, item))
        except _NeedsRead as need:
            reads.append(need.got)
        except (ToolError, fields.FieldError) as exc:
            failed.append(f"{item.get('field_id') if isinstance(item, dict) else '（格式不对）'}：{exc}")
    lines = []
    if reads:
        lines.append("这几项已经有内容（已替你读取，下面是现有内容）：在它的基础上给出完整的新值，再用 propose_edit 提：")
        lines += [_field_text(got) for got in reads]
    if failed:
        lines.append("没提成的：\n" + "\n".join(f"- {f}" for f in failed))
    if not made:
        return ToolOutcome(False, f"修改前先读了 {len(reads)} 项现有内容" if reads and not failed else "一项都没提成",
                           "\n".join(lines))
    rest = f"（另有 {len(reads) + len(failed)} 项没提成）" if reads or failed else ""
    return ToolOutcome(True, f"为{'、'.join(v['label'] for v in made)}准备了修改候选{rest}", "\n".join([_EDIT_NOTE, *lines]))


_EDIT_NOTE = "修改候选已生成：作者在卡片上比较后点「应用」才写入（回答提问不会写入）；现在还没有写入，不要说已经改好了。"


async def _propose_one_edit(ctx: ToolContext, args: dict) -> dict:
    """提一项修改候选（没读过、已有内容的先替模型读好退回去）→ 落候选表 → 推卡片，返回卡片内容。"""
    field_id, target_id = _text(args, "field_id", 80), _text(args, "target_id", TARGET_ID_LIMIT)
    if (field_id, target_id) not in ctx.read_targets:
        # 没读过就提修改：替它读一遍。空白的直接照提（没有可冲掉的）；有内容的先交给它看，按现有内容给完整新值再提
        got = await fields.read_field(ctx.db, ctx.project_id, field_id, target_id)
        ctx.read_targets.add((got["field_id"], got["target_id"]))
        if got["value"] not in ("", []):
            raise _NeedsRead(got)
    if "value" not in args:
        raise ToolError("缺少参数 value（完整的新内容）")
    return await create_field_card(ctx, field_id, target_id, args["value"], _text(args, "reason", 1000, required=False))


async def create_field_card(ctx: ToolContext, field_id: str, target_id: str, value: Any, reason: str) -> dict:
    """落一张修改候选并推卡片（写入后读回核对），返回卡片内容；修改前要不要先读，由调用方决定。"""
    made: list = []

    async def write() -> None:
        for stale in made:  # 上次提交被别的请求回滚了：丢掉会话里的旧对象，重新生成一份
            if stale in ctx.db:
                ctx.db.expunge(stale)
        made.append(await cands.create_field_candidate(
            ctx.db, project_id=ctx.project_id, session_id=ctx.session_id, run_id=ctx.run_id,
            field_id=field_id, target_id=target_id, value=value, reason=reason,
        ))

    async def verify() -> bool:
        return bool(await ctx.db.scalar(select(AssistantFieldCandidate.id).where(AssistantFieldCandidate.id == made[-1].id)))

    try:
        await write_verified(ctx.db, write, verify, "修改候选")
    except PersistError as exc:
        raise ToolError(str(exc))
    view = cands.candidate_view(made[-1])
    ctx.candidates.append(view)
    _emit_card(ctx, "candidate", {"candidate": view})
    return view


async def default_style_id(db: AsyncSession, project_id: str) -> Optional[int]:
    """项目在「写作风格」页设的默认风格：共创室写正文时带上（没设就不用风格）。"""
    from app.models.project_default_style import ProjectDefaultStyle

    return await db.scalar(select(ProjectDefaultStyle.style_id).where(ProjectDefaultStyle.project_id == project_id))


_ENTITY_NOTE = "新建候选已生成：作者要在卡片上点「建档」才真正建档（回答提问不会建档）；现在还没有建，不要说已经建好了。"


async def _propose_one(ctx: ToolContext, args: dict, entity_type: str) -> dict:
    """提一条新建候选（校验 → 查同名 → 落候选表 → 推卡片），返回规整后的字段。"""
    reason = _text(args, "reason", 1000, required=False)
    payload = entities.normalize_entity_payload(entity_type, args)
    clash = await entities.same_name_conflict(ctx.db, ctx.project_id, ctx.session_id, entity_type, payload)
    if clash:
        raise ToolError(clash)
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
    _emit_card(ctx, "entity_candidate", {"candidate": view})
    return payload


async def _propose_entity(ctx: ToolContext, args: dict, entity_type: str) -> ToolOutcome:
    items = args.get("items")
    if items is None:
        payload = await _propose_one(ctx, args, entity_type)
        return ToolOutcome(True, f"为{entities.kind_label(entity_type, payload)}「{entities.display_name(entity_type, payload)}」"
                                 "准备了新建候选", _ENTITY_NOTE)
    if not isinstance(items, list) or not items:
        raise ToolError("items 应是一组对象（每条一个 {...}）；只提一条就直接给参数")
    if len(items) > BATCH_LIMIT:
        raise ToolError(f"一次最多提 {BATCH_LIMIT} 条，分几次来")
    made: list[dict] = []
    failed: list[str] = []
    for item in items:  # 一条一条提：前面的已经落库，同一批里重名的会被同名查重挡下
        name = (entities.display_name(entity_type, item) or "（没写名字）") if isinstance(item, dict) else "（格式不对）"
        try:
            if not isinstance(item, dict):
                raise ToolError("每条应是一个对象")
            made.append(await _propose_one(ctx, item, entity_type))
        except (ToolError, entities.EntityError) as exc:
            failed.append(f"「{name}」：{exc}")
    if not made:
        raise ToolError("一条都没提成——" + "；".join(failed))
    kinds = {entities.kind_label(entity_type, p) for p in made}
    kind = kinds.pop() if len(kinds) == 1 else entities.ENTITY_LABEL[entity_type]
    names = "、".join(f"「{entities.display_name(entity_type, p)}」" for p in made)
    note = f"（另有 {len(failed)} 条没提成）" if failed else ""
    return ToolOutcome(True, f"为{kind}{names}准备了新建候选{note}",
                       _ENTITY_NOTE + ("\n没提成的：\n" + "\n".join(f"- {f}" for f in failed) if failed else ""))


async def _propose_character(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "character")


async def _propose_organization(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "organization")


async def _propose_setting_entry(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "setting_entry")


async def _propose_world_rule(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "world_rule")


async def _propose_relationship(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "relationship")


async def _propose_membership(ctx: ToolContext, args: dict) -> ToolOutcome:
    return await _propose_entity(ctx, args, "membership")


async def _chapter_by_number(ctx: ToolContext, args: dict) -> Chapter:
    try:
        number = int(args.get("chapter_number"))
    except (TypeError, ValueError):
        raise ToolError("chapter_number 应是章号（整数）")
    chapter = (await ctx.db.execute(
        select(Chapter).where(Chapter.project_id == ctx.project_id, Chapter.chapter_number == number)
    )).scalars().first()
    if chapter is None:
        raise ToolError(f"本书没有第 {number} 章")
    return chapter


async def _read_chapter(ctx: ToolContext, args: dict) -> ToolOutcome:
    chapter = await _chapter_by_number(ctx, args)
    content = chapter.content or ""
    head = f"第{chapter.chapter_number}章《{chapter.title}》"
    if not content.strip():
        return ToolOutcome(True, f"{head}还没有正文", f"{head}还没有正文（可以用 manuscript 续写或 write_chapters 后台写）。")
    try:
        start = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        raise ToolError("offset 应是整数（从第几个字开始读）")
    if start >= len(content):
        raise ToolError(f"{head}一共 {len(content)} 字，offset 超出了")
    end = min(len(content), start + CHAPTER_PAGE)
    tail = (f"\n（这一章还有 {len(content) - end} 字没读：read_chapter 带 offset={end} 接着读）" if end < len(content)
            else "\n（读完了）")
    return ToolOutcome(True, f"读了{head}第 {start + 1}-{end} 字",
                       f"{head}｜共 {len(content)} 字｜这次读第 {start + 1}-{end} 字\n{content[start:end]}{tail}")


def _quoted_selection(chapter: Chapter, quote: str) -> dict:
    """按逐字引用在本章正文里定位要改的那段（只能出现一次），当作选中的选区。"""
    content = chapter.content or ""
    count = content.count(quote)
    if count == 0:
        raise ToolError(f"第 {chapter.chapter_number} 章正文里没有找到这段原文：引用要逐字（先用 read_chapter 读原文再复制）")
    if count > 1:
        raise ToolError(f"这段原文在第 {chapter.chapter_number} 章出现了 {count} 次：多引几个字，让它只出现一次")
    start = content.index(quote)
    return {"start": start, "end": start + len(quote), "text": quote}


async def _manuscript(ctx: ToolContext, args: dict) -> ToolOutcome:
    chapter = await _chapter_by_number(ctx, args)
    number = chapter.chapter_number
    skill = _text(args, "skill", 20)
    if skill not in SKILL_LABELS:
        raise ToolError(f"skill 只能是 {'/'.join(SKILL_LABELS)}")
    instruction = _text(args, "instruction", 2000, required=False) or SKILL_LABELS[skill]
    selection = None
    if skill in SELECTION_SKILLS:
        quote = args.get("quote")
        page_sel = ctx.page.get("selection") if ctx.page.get("chapter_id") == chapter.id else None
        if isinstance(quote, str) and quote.strip():
            selection = _quoted_selection(chapter, quote)
        elif page_sel:
            selection = page_sel
        else:
            raise ToolError(f"{SKILL_LABELS[skill]}要指明第 {number} 章的哪一段：用 quote 逐字引用要改的原文"
                            "（先 read_chapter 读原文），或请作者在章节写作页选中那段")
    result = await execute_skill(ctx.db, chapter, ai_service=_member_ai(ctx), message=instruction, skill=skill,
                                 selection=selection)
    label = f"第 {number} 章 · {SKILL_LABELS[skill]}"
    candidate = result.get("candidate")
    if candidate and not await ctx.db.scalar(select(ChapterCandidate.id).where(ChapterCandidate.id == candidate["id"])):
        raise ToolError("候选稿没能写进数据库（被同时进行的其他操作打断），请再说一次")
    if candidate:
        summary = {**candidate, "chapter_number": number, "chapter_title": chapter.title}
        ctx.chapter_candidates.append(summary)
        _emit_card(ctx, "chapter_candidate", {"candidate": summary})
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
        return ToolOutcome(True, "没有需要注意的事项", "本书目前没有待确认的卷纲 / 章纲、过期分析、待审候选稿或一致性问题。")
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
    _emit_card(ctx, "plan", {"plan": plan})


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
    story = await volumes.story_fields(ctx.db, ctx.project_id)
    if not (story.get("premise") or story.get("main_plot")):  # 分卷读的是已经应用的总纲：拿空总纲去分卷只会凭空编
        raise ToolError("本书还没有总纲（或总纲的修改还在待确认）：先完善总纲的梗概和全书主线、请作者在卡片上应用，再分卷")
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
        job = await start_batch_job(project_id=ctx.project_id, user_id=ctx.user_id, ai_service=_member_ai(ctx),
                                    options=BatchOptions(from_chapter=start, to_chapter=end, require_confirmed_outline=True,
                                                         style_id=await default_style_id(ctx.db, ctx.project_id)))
    except AIJobConflictError as exc:
        raise ToolError(f"本书已有正文任务在运行：{exc}")
    ctx.emit({"type": "job", "job": {"id": job.id, "title": job.title, "kind": job.kind}})
    return ToolOutcome(True, f"开始在后台写第 {start}-{end} 章",
                       "后台批量写作已开始：只写已确认的章纲，写完的章节会自动采用并分析；进度在右下角任务托盘。"
                       "现在正文还没写完，不要说已经写好了。")


async def _fill_basics(ctx: ToolContext, args: dict) -> ToolOutcome:
    from app.services import assistant_generators as gens  # 延迟导入：生成器要用本模块的卡片工具

    return await gens.fill_basics(ctx, args)


def _target(target: str) -> Callable[[ToolContext, dict], Any]:
    """生成类工具：都经生成总入口（先查前置、缺上游先补并挂起，齐了才按原逻辑生成）。"""
    async def handler(ctx: ToolContext, args: dict) -> ToolOutcome:
        from app.services import assistant_generators as gens  # 延迟导入：生成器要用本模块的卡片工具

        return await gens.run_target(ctx, target, args)

    return handler


HANDLERS = {
    "fill_basics": _fill_basics,
    "generate_world": _target("world"), "generate_world_rules": _target("world_rules"),
    "generate_setting_entries": _target("setting_entries"), "generate_cast": _target("cast"),
    "generate_relationships": _target("relationships"), "generate_outline": _target("outline"),
    "plan_volumes": _target("volumes"), "detail_volume": _target("detail"), "plan_chapters": _target("outlines"),
    "write_chapter": _target("chapter"),
    "search_project": _search_project, "list_fields": _list_fields, "read_field": _read_field,
    "read_chapter": _read_chapter, "propose_edit": _propose_edit, "propose_world_rule": _propose_world_rule,
    "propose_setting_entry": _propose_setting_entry, "propose_character": _propose_character,
    "propose_organization": _propose_organization, "propose_relationship": _propose_relationship,
    "propose_membership": _propose_membership,
    "manuscript": _manuscript, "open_page": _open_page,
    "project_status": _project_status, "ask_author": _ask_author, "story_progress": _story_progress,
    "kb_search": _kb_search, "kb_read": _kb_read,
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
