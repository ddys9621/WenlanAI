"""项目自定义提示词：只开放最影响成稿的写作指导，输出格式、作品资料、字段规则留在代码里自动拼接。

- 每条有固定 key、默认文本（就是生成器里的原文）与可用变量；项目只存改过的条目，没改过的跟随系统默认
- 类型 / 视角指导的默认值按项目当前的类型 / 视角选取：项目换了类型，没改过的条目跟着换
- 生成时由调用方 load_overrides 后交给生成器（ChapterPromptInput.prompt_overrides、volume_planning 的 guide 参数等）
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_candidate import utcnow
from app.models.project_prompt import ProjectPromptOverride
from app.services import volume_planning as vp
from app.services.chapter_prompt_builder import chapter_prompt_defaults
from app.services.prompt_service import PromptService
from app.utils.prompt_template import unknown_variables

MAX_PROMPT_CHARS = 20_000


@dataclass(frozen=True)
class PromptGroup:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class PromptVariable:
    name: str
    label: str


@dataclass(frozen=True)
class PromptContext:
    genre: str = ""
    narrative_perspective: str = ""

    @classmethod
    def of(cls, project: Any) -> "PromptContext":
        return cls(genre=project.genre or "", narrative_perspective=project.narrative_perspective or "")


@dataclass(frozen=True)
class PromptSpec:
    key: str
    group: str
    title: str
    description: str
    default: Callable[[PromptContext], str]
    variables: tuple[PromptVariable, ...] = ()


def _chapter(key: str) -> Callable[[PromptContext], str]:
    return lambda ctx: chapter_prompt_defaults(ctx.genre, ctx.narrative_perspective)[key]


PROMPT_GROUPS: tuple[PromptGroup, ...] = (
    PromptGroup("chapter", "正文写作", "单章与批量写作时给 AI 的写作指导。"),
    PromptGroup("planning", "规划（总纲 → 卷纲 → 章纲）", "生成总纲、分卷、细化卷纲、单元章纲时的写法；输出哪些字段由系统固定。"),
)

PROMPT_SPECS: tuple[PromptSpec, ...] = (
    PromptSpec(
        "chapter_persona", "chapter", "写作人设",
        "正文提示词的开头：AI 以什么身份、给什么样的读者写这本书。",
        _chapter("chapter_persona"),
    ),
    PromptSpec(
        "chapter_style", "chapter", "文风规则",
        "决定成稿的段落、对话、口吻和用词，对正文影响最大。换成别的文风时记得同步改「落笔提醒」；"
        "开启仿写参考时，参考文风排在它前面，冲突的地方以参考文风为准。",
        _chapter("chapter_style"),
        (PromptVariable("narrative_perspective", "本书叙事视角"),
         PromptVariable("perspective_boundary_clause", "视角信息边界（按本书视角自动生成的一条约束）")),
    ),
    PromptSpec(
        "chapter_closing", "chapter", "落笔提醒",
        "放在本章任务最后的一句提醒，后面自动接上本章的收尾要求（如「结尾停在钩子上。」）；开启仿写参考时改用参考文风的提醒。",
        _chapter("chapter_closing"),
    ),
    PromptSpec(
        "chapter_priority", "chapter", "写作优先级",
        "正文和章纲、前情冲突时怎么取舍，也决定 AI 能在章纲之外自由发挥到什么程度。",
        _chapter("chapter_priority"),
    ),
    PromptSpec(
        "genre_guide", "chapter", "本书类型指导",
        "按本书类型自动选取（多个类型会合并），写正文和生成总纲时都会带上；没改过的话，项目换了类型会跟着换。",
        _chapter("genre_guide"),
    ),
    PromptSpec(
        "perspective_guide", "chapter", "叙事视角指导",
        "按本书叙事视角自动选取，写正文时带上；写群像、多视角轮换时可以在这里放宽。",
        _chapter("perspective_guide"),
    ),
    PromptSpec(
        "outline_elements", "planning", "总纲写法",
        "生成总纲时每一项怎么写；总纲输出哪 8 个字段由系统固定。",
        lambda ctx: PromptService.OUTLINE_ELEMENTS,
    ),
    PromptSpec(
        "volume_skeleton", "planning", "分卷写法",
        "把全书分成若干卷时的写法（谋篇页分卷、共创室规划分卷都用它）。",
        lambda ctx: vp.SKELETON_GUIDE,
    ),
    PromptSpec(
        "volume_detail", "planning", "卷纲细化写法",
        "把一卷拆成剧情单元、编排线索时的写法。",
        lambda ctx: vp.DETAIL_GUIDE,
        (PromptVariable("start", "本卷起始章号"), PromptVariable("end", "本卷结束章号")),
    ),
    PromptSpec(
        "chapter_outlines", "planning", "章纲写法",
        "把剧情单元展开成章纲时的写法（批量写作缺章纲时自动规划也用它）；视角、人名、章节契约、伏笔编号这些字段规则由系统固定。",
        lambda ctx: vp.CHAPTERS_GUIDE,
    ),
)

_BY_KEY = {s.key: s for s in PROMPT_SPECS}


def spec(key: str) -> PromptSpec:
    return _BY_KEY[key]


def default_text(key: str, ctx: PromptContext) -> str:
    return spec(key).default(ctx)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def validate(key: str, content: str) -> list[str]:
    s = spec(key)
    errors = []
    if len(content) > MAX_PROMPT_CHARS:
        errors.append(f"太长了：最多 {MAX_PROMPT_CHARS} 字")
    unknown = unknown_variables(content, [v.name for v in s.variables])
    if unknown:
        allowed = "这一条可用 " + "、".join(f"{{{v.name}}}" for v in s.variables) if s.variables else "这一条没有可用变量"
        errors.append(f"不认识的变量 {'、'.join(f'{{{name}}}' for name in unknown)}：{allowed}")
    return errors


def prompt_view(s: PromptSpec, ctx: PromptContext, row: Optional[ProjectPromptOverride]) -> dict[str, Any]:
    default = s.default(ctx)
    return {
        "key": s.key,
        "group": s.group,
        "title": s.title,
        "description": s.description,
        "variables": [{"name": v.name, "label": v.label} for v in s.variables],
        "default_content": default,
        "content": row.content if row is not None else default,
        "customized": row is not None,
        "default_changed": bool(row is not None and row.default_hash and row.default_hash != text_hash(default)),
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


async def override_rows(db: AsyncSession, project_id: str) -> dict[str, ProjectPromptOverride]:
    rows = (await db.execute(
        select(ProjectPromptOverride).where(ProjectPromptOverride.project_id == project_id)
    )).scalars().all()
    return {r.prompt_key: r for r in rows if r.prompt_key in _BY_KEY}


async def load_overrides(db: AsyncSession, project_id: str) -> dict[str, str]:
    return {key: row.content for key, row in (await override_rows(db, project_id)).items()}


async def save_override(db: AsyncSession, project: Any, key: str, content: str) -> Optional[ProjectPromptOverride]:
    """存一条自定义（content 已去首尾空白、已校验）；和系统默认一字不差就删掉自定义，返回 None。"""
    default = default_text(key, PromptContext.of(project))
    row = await db.get(ProjectPromptOverride, (project.id, key))
    if content == default:
        if row is not None:
            await db.delete(row)
        return None
    if row is None:
        row = ProjectPromptOverride(project_id=project.id, prompt_key=key)
        db.add(row)
    row.content = content
    row.default_hash = text_hash(default)
    row.updated_at = utcnow()
    return row


async def reset_overrides(db: AsyncSession, project_id: str, keys: Optional[Iterable[str]] = None) -> int:
    stmt = delete(ProjectPromptOverride).where(ProjectPromptOverride.project_id == project_id)
    if keys is not None:
        stmt = stmt.where(ProjectPromptOverride.prompt_key.in_(list(keys)))
    return (await db.execute(stmt)).rowcount or 0
