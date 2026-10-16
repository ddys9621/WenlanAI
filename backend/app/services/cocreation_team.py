"""共创室团队（参考岚笺 creative-team）：一本书一个创作团队，作者在同一段对话里和团队交流。

- 主编默认发言：澄清目标、统筹分工、决定推进顺序；可以 delegate 把一件事交给某位成员
- 作者也可以 @成员 直接找人（「@人物设计师 …」），这一轮由该成员发言
- 每位成员只开放与职责相符的工具，可分别指定模型（AssistantTeamSetting；空 = 跟随项目模型）
- 成员的产出都是候选 / 草稿，作者在对话卡片或谋篇页确认后才算定稿
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

READ_TOOLS = ("search_project", "list_fields", "read_field", "story_progress", "kb_search", "kb_read")
PLANNING_TOOLS = ("plan_volumes", "detail_volume", "plan_chapters")


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
        (*READ_TOOLS, "propose_edit", *PLANNING_TOOLS, "manuscript", "write_chapters", "project_status",
         "open_page", "ask_author", "delegate"),
        "先弄清作者想写什么，再按 总纲 → 分卷 → 细化卷纲 → 单元章纲 → 确认 → 写正文 → 审校 的顺序推进；"
        "专业的事交给对应成员（delegate），重要的选择用 ask_author 让作者拍板；每轮结束告诉作者下一步是什么。",
    ),
    Member(
        "world", "世界观设定师", "世", "blue", "设计世界规则、地点、势力与力量 / 职业体系",
        (*READ_TOOLS, "propose_edit"),
        "写清时代、空间、秩序、核心冲突和不可违反的规则；力量体系说明能力边界、代价和突破条件。"
        "不适合境界体系或金手指的题材不要硬塞；不凭空声称素材里没有的事实。",
    ),
    Member(
        "character", "人物设计师", "人", "rose", "设计人物动机、关系、说话方式与成长轨迹",
        (*READ_TOOLS, "propose_edit"),
        "人物要有想要的东西、害怕的东西和会让他改变的事；关系要有张力；说话方式要能一耳朵听出是谁。",
    ),
    Member(
        "outline", "总纲策划师", "纲", "amber", "打磨总纲与分卷：全书主线因果连贯，每卷一个新局面",
        (*READ_TOOLS, "propose_edit", "plan_volumes"),
        "先想清从开始到结局发生了什么、人物为何这样选择、结果为何引出下一件事，再写连贯的自然段；"
        "每卷换一个新局面（舞台、对手或目标），赌注逐卷抬高。",
    ),
    Member(
        "chapter", "章节策划师", "章", "violet", "把卷纲细化成剧情单元，再把单元展开为章纲",
        (*READ_TOOLS, "propose_edit", "detail_volume", "plan_chapters"),
        "剧情单元是一件完整的事，长短按事件大小定；章纲按实际事件和场景分章，不为凑章数拆小事；"
        "上级规划有缺口时先指出并建议修正上级，不在章纲里偷偷发明重要事实。",
    ),
    Member(
        "writer", "正文作者", "文", "orange", "依据已确认的章纲写正文：续写、改写、润色或批量写作",
        (*READ_TOOLS, "manuscript", "write_chapters"),
        "只按作者确认过的章纲写；正文结果都是候选稿，作者采用后才写进书里。",
    ),
    Member(
        "reviewer", "审校编辑", "审", "slate", "核对因果、人物声音、设定与跨章一致性",
        (*READ_TOOLS, "project_status", "manuscript"),
        "指出具体问题、出处和影响，再给出可执行的修改建议；没有证据的问题不要报。",
    ),
)
_BY_ID = {m.id: m for m in MEMBERS}
_BY_NAME = {m.name: m for m in MEMBERS}
DEFAULT_MEMBER = "editor"

STARTERS: tuple[dict[str, str], ...] = (
    {"id": "idea", "label": "从一个灵感开始", "hint": "让团队帮你找到故事的起点",
     "message": "我有一个灵感：（写下你的点子）。请先读一下本书现有设定，和我讨论故事方向，需要我拍板的地方直接问我。"},
    {"id": "organize", "label": "一起梳理已有想法", "hint": "人物、世界和总纲逐渐清晰",
     "message": "我已有一个小说想法，请先问我必要的问题，然后分工整理世界、人物与完整的故事总纲。"},
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
