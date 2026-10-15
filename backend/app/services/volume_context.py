"""正文生成时「本章在卷纲中的位置」：卷 → 剧情单元 → 本章是这件事的第几章。

只给软指导（单元开场 / 推进 / 收束），不规定字数比例、不要求每章兑现爽点；
钩子策略：单元收束章半钩（收住这件事、轻轻指向下一件），其余章留钩。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.volume import Volume
from app.services.planning_context import clip
from app.services.volume_planning import loads_units, position_guidance, unit_at, unit_position


@dataclass
class VolumeContext:
    volume_id: str
    volume_number: int
    volume_title: str
    volume_goal: str
    unit: Optional[dict[str, Any]] = None
    unit_count: int = 0
    index: int = 0
    size: int = 0
    next_title: Optional[str] = None

    @property
    def unit_end(self) -> bool:
        return self.unit is not None and self.index == self.size


async def fetch_volume_context(db: AsyncSession, outline: Any) -> Optional[VolumeContext]:
    """章纲 → 所属卷与剧情单元（作者手建、没挂卷的章纲按章号找卷；找不到卷返回 None）。"""
    from app.services.volume_service import volume_for_chapter

    number = int(getattr(outline, "chapter_number", 0) or 0)
    volume_id = getattr(outline, "volume_id", None)
    volume = await db.get(Volume, volume_id) if volume_id else await volume_for_chapter(db, outline.project_id, number)
    if volume is None:
        return None
    units = loads_units(volume.units)
    unit_index = getattr(outline, "unit_index", None)
    unit = next((u for u in units if unit_index and int(u.get("index") or 0) == unit_index), None) or unit_at(units, number)
    ctx = VolumeContext(volume.id, volume.volume_number, volume.title or "", volume.goal or "", unit_count=len(units))
    if unit is None or not int(unit["chapter_start"]) <= number <= int(unit["chapter_end"]):
        return ctx
    ctx.unit = unit
    ctx.index, ctx.size = unit_position(unit, number)
    following = next((u for u in units if int(u.get("index") or 0) == int(unit.get("index") or 0) + 1), None)
    if following is not None:
        ctx.next_title = str(following.get("title") or "")
    else:
        from sqlalchemy import select

        nxt = (await db.execute(select(Volume).where(
            Volume.project_id == volume.project_id, Volume.volume_number == volume.volume_number + 1,
        ))).scalars().first()
        ctx.next_title = f"第{nxt.volume_number}卷《{nxt.title}》" if nxt is not None else None
    return ctx


def render_structure(ctx: Optional[VolumeContext]) -> str:
    if ctx is None:
        return ""
    head = f"- 第{ctx.volume_number}卷《{ctx.volume_title}》" + (f"：{clip(ctx.volume_goal, 150)}" if ctx.volume_goal else "")
    lines = ["【📍 本章在卷纲中的位置】", head]
    unit = ctx.unit
    if unit is not None:
        lines.append(
            f"- 剧情单元 {unit.get('index')}/{ctx.unit_count}《{unit.get('title')}》（第 {unit['chapter_start']}-{unit['chapter_end']} 章），"
            f"本章是这件事的第 {ctx.index}/{ctx.size} 章"
        )
        if unit.get("story"):
            lines.append(f"- 这件事的经过：{clip(unit['story'], 400)}")
        if unit.get("turn"):
            lines.append(f"- 这件事结束时的变化：{clip(unit['turn'], 150)}")
        lines.append(f"- {position_guidance(ctx.index, ctx.size, ctx.next_title)}")
    return "\n".join(lines)


def hook_policy(ctx: Optional[VolumeContext]) -> str:
    return "soft" if ctx is not None and ctx.unit_end else "hook"
