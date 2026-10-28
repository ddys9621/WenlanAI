"""共创室团队（参考岚笺 creative-team）：一本书一个创作团队，作者在同一段对话里和团队交流。

- 主编默认发言：澄清目标、统筹分工，按创作顺序（作品信息 → 世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 →
  卷纲 → 章纲 → 正文）推进；可以 delegate 把一件事交给某位成员
- 作者也可以 @成员 直接找人（「@人物设计师 …」），这一轮由该成员发言
- 每位成员只开放与职责相符的工具，可分别指定模型（AssistantTeamSetting；空 = 跟随项目模型）；每位成员都能查、能读全书
- 要 AI 构思、撰写的内容走生成工具（复用页面上原来的 AI 生成逻辑，参考自动带齐）；propose_* 只记作者口述的内容和小修改
- 成员的产出都是候选 / 草稿，作者在对话卡片或谋篇页确认后才算定稿
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

READ_TOOLS = ("story_progress", "search_project", "list_fields", "read_field", "read_chapter", "kb_search", "kb_read")
WORLD_GEN = ("generate_world", "generate_world_rules", "generate_setting_entries")
CAST_GEN = ("generate_cast", "generate_relationships")
PLANNING_TOOLS = ("plan_volumes", "detail_volume", "plan_chapters")
WRITING_TOOLS = ("write_chapter", "write_chapters", "manuscript")
WORLD_TOOLS = ("propose_world_rule", "propose_setting_entry")
CAST_TOOLS = ("propose_character", "propose_organization")
RELATION_TOOLS = ("propose_relationship", "propose_membership")
CREATIVE_ORDER = "作品信息 → 世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 → 卷纲 → 章纲 → 正文"


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    initials: str
    color: str
    responsibility: str
    tools: tuple[str, ...]
    guidance: str


MEMBERS: tuple[Member, ...] = (
    Member(
        "editor", "主编", "编", "jade", "澄清创作目标，统筹成员分工，把握故事方向与推进顺序",
        (*READ_TOOLS, "fill_basics", *WORLD_GEN, *CAST_GEN, "generate_outline", *PLANNING_TOOLS, *WRITING_TOOLS,
         "propose_edit", *WORLD_TOOLS, *CAST_TOOLS, *RELATION_TOOLS, "project_status", "open_page", "ask_author", "delegate"),
        "先弄清作者想写什么，再按 作品信息 → 世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 → 分卷 → 细化卷纲 → "
        "单元章纲 → 确认 → 写正文 → 审校 的顺序推进：作品信息你用 fill_basics 定（书名 / 简介 / 主题 / 类型出候选让作者选）；"
        "世界交给世界观设定师，人物和关系交给人物设计师，总纲和分卷交给总纲策划师，细化和章纲交给章节策划师，正文交给正文作者"
        "（delegate 时写明用哪个生成工具、生成什么，把作者的原话带上）；重要的选择用 ask_author 让作者拍板；每轮结束告诉作者下一步是什么。",
    ),
    Member(
        "world", "世界观设定师", "世", "blue", "设计世界设定、世界规则、设定条目与势力（力量 / 职业体系、地点、组织）",
        (*READ_TOOLS, *WORLD_GEN, "generate_cast", "propose_edit", *WORLD_TOOLS, "propose_organization"),
        "按 世界设定四栏 → 世界规则 → 设定条目 → 势力 的顺序：generate_world 生成时代背景 / 地点设定 / 氛围基调 / 世界规则四栏，"
        "generate_world_rules 按题材生成修炼境界 / 装备 / 地图位置，generate_setting_entries 生成术语 / 铁律 / 规则等条目，"
        "势力 / 组织用 generate_cast（character_count=0，organization_count 写要几个）；这些工具会自动带齐参考，作者的原话放进 requirements。"
        "作者口述的具体设定才用 propose_edit / propose_world_rule / propose_setting_entry / propose_organization 记下。"
        "不适合境界体系或金手指的题材不要硬塞；不凭空声称素材里没有的事实。",
    ),
    Member(
        "character", "人物设计师", "人", "rose", "设计人物动机、关系、组织归属、说话方式与成长轨迹",
        (*READ_TOOLS, *CAST_GEN, "propose_edit", "propose_character", *RELATION_TOOLS),
        "用 generate_cast 生成人物（主角和主要人物在前；会连带关系卡和组织成员卡），人物定下来后用 generate_relationships 理关系、"
        "记组织成员；这些工具会自动带齐世界观和已有人物，作者的原话放进 requirements。人物要有想要的东西、害怕的东西和会让他改变的事，"
        "说话方式要能一耳朵听出是谁。作者口述的具体人物 / 关系才用 propose_character / propose_relationship / propose_membership 记下，"
        "已有人物的小改用 propose_edit。",
    ),
    Member(
        "outline", "总纲策划师", "纲", "amber", "打磨总纲与分卷：全书主线因果连贯，每卷一个新局面",
        (*READ_TOOLS, "generate_outline", "plan_volumes", "propose_edit"),
        "用 generate_outline 生成总纲各栏（梗概 / 全书主线 / 核心卖点 / 成长路线 / 终极目标 / 开篇钩子…，会自动带齐世界观、人物和对标书），"
        "总纲确认后用 plan_volumes 分卷；单项小改用 propose_edit（本书还没有总纲时目标是 new）。总纲不要写进作品设定的主题或简介；"
        "每卷换一个新局面（舞台、对手或目标），赌注逐卷抬高。",
    ),
    Member(
        "chapter", "章节策划师", "章", "violet", "把卷纲细化成剧情单元，再把单元展开为章纲",
        (*READ_TOOLS, "detail_volume", "plan_chapters", "propose_edit"),
        "分卷草案确认后用 detail_volume 把一卷细化成剧情单元，剧情单元确认后用 plan_chapters 展开章纲；剧情单元是一件完整的事，"
        "长短按事件大小定（已有单元的标题 / 经过 / 结束时用 propose_edit 改，不必重新细化）；章纲按实际事件和场景分章，"
        "不为凑章数拆小事；上级规划有缺口时先指出并建议修正上级，不在章纲里偷偷发明重要事实。",
    ),
    Member(
        "writer", "正文作者", "文", "orange", "依据已确认的章纲写正文：整章生成、续写、改写、润色或批量写作",
        (*READ_TOOLS, *WRITING_TOOLS),
        "只按作者确认过的章纲写：一章用 write_chapter（按章节页「AI 生成」的原逻辑出候选稿），几章用 write_chapters（后台批量）；"
        "续写 / 改写 / 润色用 manuscript，改写 / 润色前先 read_chapter 读原文，用 quote 逐字引用要改的那段；"
        "正文结果都是候选稿，作者采用后才写进书里。",
    ),
    Member(
        "reviewer", "审校编辑", "审", "slate", "核对因果、人物声音、设定与跨章一致性",
        (*READ_TOOLS, "project_status", "manuscript"),
        "先 read_chapter 读原文，对照世界设定、人物、关系和章纲找问题；指出具体问题、出处（引原句）和影响，再给出可执行的修改建议；"
        "没有证据的问题不要报。",
    ),
)
_BY_ID = {m.id: m for m in MEMBERS}
_BY_NAME = {m.name: m for m in MEMBERS}
DEFAULT_MEMBER = "editor"

STARTERS: tuple[dict[str, str], ...] = (
    {"id": "idea", "label": "从一个灵感开始", "hint": "让团队帮你找到故事的起点",
     "message": "我有一个灵感：（写下你的点子）。请先帮我把作品信息（书名、简介、主题、类型）定下来，再和我讨论故事方向"
                "（先聊世界，再聊人物，最后聊故事），需要我拍板的地方直接问我。"},
    {"id": "organize", "label": "一起梳理已有想法", "hint": "作品信息、世界、人物、关系和总纲逐层清晰",
     "message": "我已有一个小说想法，请先问我必要的问题，然后按 作品信息 → 世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 "
                "的顺序分工整理，每一层落成卡片给我确认。"},
    {"id": "plan", "label": "规划分卷与卷纲", "hint": "总纲 → 分卷 → 剧情单元",
     "message": "请看看创作进度，按总纲把全书分卷，并把第一卷细化成剧情单元，给我看看再确认。"},
    {"id": "write", "label": "接着往下写", "hint": "生成章纲、写正文",
     "message": "请看看创作进度，把接下来该写的章节准备好（缺章纲就先生成章纲给我确认），然后开始写。"},
    {"id": "review", "label": "检查前文问题", "hint": "因果、人物、设定一致性",
     "message": "@审校编辑 请检查最近写的几章有没有因果、人物或设定上的问题，按严重程度列出来。"},
)


def member(member_id: Optional[str]) -> Member:
    return _BY_ID.get(member_id or "", _BY_ID[DEFAULT_MEMBER])


def resolve_member(raw: Optional[str]) -> Optional[Member]:
    text = (raw or "").strip().lstrip("@")
    return _BY_ID.get(text) or _BY_NAME.get(text)


_MENTION = re.compile(r"^\s*@(\S+?)[\s，,:：]+(.*)$", re.S)


def parse_mention(message: str) -> tuple[Optional[Member], str]:
    """开头的「@成员」→ (成员, 去掉提及的正文)；没有或不认识 → (None, 原文)。"""
    match = _MENTION.match(message or "")
    if not match:
        return None, message
    found = resolve_member(match.group(1))
    return (found, match.group(2).strip()) if found else (None, message)


def member_view(m: Member, model: Optional[str] = None) -> dict:
    return {"id": m.id, "name": m.name, "initials": m.initials, "color": m.color,
            "responsibility": m.responsibility, "model": model or None}
