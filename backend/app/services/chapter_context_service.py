"""正文生成的上下文装配（读库部分，供单章生成与服务端批量共用）。

- build_outline_window：本段章纲窗口——挂了剧情单元的给本单元各章（已写 / 本章 / 待写）+ 下一章只作钩子方向；
  线性模式给前 1 章 + 本章 + 后 2 章。取代"全书章纲全量注入"（长篇里几十万字，且含未来章节会让模型抢跑）。
  章末钩子策略见 volume_context.hook_policy（单元收束章半钩、其余留钩）。
- build_character_context：本章相关角色（章纲涉及 / 文中点名 / 视角 / 主角 / 近期出场 / 与视角有关系）的状态卡、
  相关势力、死亡 / 失踪名单、故事时间。
- build_query_text：检索用的精简语句（标题 + 关键事件 + 出场人物），嵌入模型只吃得下一百多字。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.services import character_state_service as css
from app.services.context_budget import clip_text

CHARACTER_CARD_LIMIT = 12
LINEAR_WINDOW_BEFORE = 1
LINEAR_WINDOW_AFTER = 2


def parse_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(x).strip() for x in data if str(x).strip()] if isinstance(data, list) else []


def build_query_text(outline: Any, involved: Iterable[str]) -> str:
    events = parse_json_list(getattr(outline, "key_events", None))
    parts = [
        getattr(outline, "title", "") or "",
        " ".join(events[:4]),
        " ".join(list(involved)[:5]),
        (getattr(outline, "plot_points", None) or getattr(outline, "summary", None) or "")[:120],
    ]
    return clip_text(" ".join(p for p in parts if p).strip(), 300)


async def _written_numbers(db: AsyncSession, project_id: str, numbers: list[int]) -> set[int]:
    if not numbers:
        return set()
    rows = await db.execute(
        select(Chapter.chapter_number).where(
            Chapter.project_id == project_id,
            Chapter.chapter_number.in_(numbers),
            Chapter.content.isnot(None),
            Chapter.content != "",
        )
    )
    return set(rows.scalars().all())


def _outline_line(o: ChapterOutline, status: str, plot_chars: int) -> str:
    plot = clip_text(o.plot_points or o.summary or "", plot_chars)
    return f"- 第{o.chapter_number}章《{o.title}》（{status}）" + (f"：{plot}" if plot and plot_chars else "")


async def build_outline_window(db: AsyncSession, project_id: str, outline: ChapterOutline) -> str:
    current = outline.chapter_number
    in_unit = bool(outline.volume_id and outline.unit_index)
    if in_unit:
        members = list((await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.volume_id == outline.volume_id, ChapterOutline.unit_index == outline.unit_index,
            ).order_by(ChapterOutline.chapter_number)
        )).scalars().all())
    else:
        members = list((await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.project_id == project_id,
                ChapterOutline.chapter_number.between(current - LINEAR_WINDOW_BEFORE, current + LINEAR_WINDOW_AFTER),
            ).order_by(ChapterOutline.chapter_number)
        )).scalars().all())
    written = await _written_numbers(db, project_id, [o.chapter_number for o in members])
    lines: list[str] = []
    for o in members:
        if o.chapter_number == current:
            lines.append(f"- 第{o.chapter_number}章《{o.title}》（本章）")
        elif o.chapter_number < current or o.chapter_number in written:
            lines.append(_outline_line(o, "已写", 60))
        else:
            lines.append(_outline_line(o, "待写", 150))
    if in_unit:
        last = max((o.chapter_number for o in members), default=current)
        nxt = (await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.chapter_number == last + 1)
        )).scalar_one_or_none()
        if nxt is not None:
            lines.append(
                f"- 第{nxt.chapter_number}章《{nxt.title}》（下一段开头，只用于把本段收尾的钩子指向它，本章不要写到）："
                f"{clip_text(nxt.plot_points or nxt.summary or '', 80)}"
            )
    return "\n".join(lines)


@dataclass
class CharacterContext:
    selected: list[Any] = field(default_factory=list)
    cards_text: str = ""
    organizations_text: str = ""
    absent_text: str = ""
    story_time_text: str = ""
    involved: list[str] = field(default_factory=list)
    pov_name: Optional[str] = None

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.selected]


def _mentioned(characters: Iterable[Any], text: str) -> list[str]:
    """章纲文本里点到名的角色（章纲 characters_involved 漏写时兜底）。名字至少 2 个字才算，避免单字误命中。"""
    return [c.name for c in characters if c.name and len(c.name) >= 2 and c.name in text]


async def build_character_context(
    db: AsyncSession, project_id: str, chapter_number: int, outline: Any,
    characters: Optional[list[Any]] = None, limit: int = CHARACTER_CARD_LIMIT,
) -> CharacterContext:
    characters = characters if characters is not None else await css.load_characters(db, project_id)
    people = [c for c in characters if not getattr(c, "is_organization", False)]
    orgs = [c for c in characters if getattr(c, "is_organization", False)]
    outline_text = " ".join(
        str(x or "") for x in (
            getattr(outline, "title", ""), getattr(outline, "plot_points", ""), getattr(outline, "summary", ""),
            getattr(outline, "scene", ""), " ".join(parse_json_list(getattr(outline, "key_events", None))),
        )
    )
    involved = list(dict.fromkeys(parse_json_list(getattr(outline, "characters_involved", None)) + _mentioned(people, outline_text)))
    protagonist = next((c for c in people if (c.role_type or "").lower() == "protagonist"), None)
    pov_name = (getattr(outline, "pov", None) or "").strip() or (protagonist.name if protagonist else None)
    pov = next((c for c in people if c.name == pov_name), None)

    recent = await css.recent_presence(db, project_id, chapter_number, window=3)
    related = await css.load_related_ids(db, project_id, pov.id if pov else None, before_chapter=chapter_number)
    selected = css.select_relevant_characters(people, involved=involved, pov=pov_name, recent=recent,
                                              related_ids=related, limit=limit)
    names = [c.name for c in selected] + [a for c in selected for a in css._aliases(c)]
    states = await css.load_character_states(db, project_id, chapter_number, names=names)
    relations = await css.load_protagonist_relations(db, project_id, protagonist, selected, before_chapter=chapter_number)
    absent_states = await css.load_absent_states(db, project_id, chapter_number)
    story_time = await css.latest_story_time(db, project_id, chapter_number)

    org_list = css.select_relevant_organizations(orgs, outline_text, involved)
    org_text = "\n".join(
        f"- {o.name}" + (f"（{o.organization_type}）" if getattr(o, "organization_type", None) else "")
        + (f"：{clip_text(o.personality, 60)}" if getattr(o, "personality", None) else "")
        for o in org_list
    )
    return CharacterContext(
        selected=selected,
        cards_text=css.render_character_cards(selected, states, relations),
        organizations_text=org_text,
        absent_text=css.render_absent_list(absent_states, involved, chapter_number),
        story_time_text=f"{story_time[0]}（第{story_time[1]}章）" if story_time else "",
        involved=involved,
        pov_name=pov_name,
    )
