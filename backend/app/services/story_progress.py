"""创作进度：总纲 / 卷纲 / 章纲 / 正文各到哪一步，以及下一步该做什么（共创室主编靠它推进，作者也能一眼看清）。

下一步的顺序：完善总纲 → 分卷 → 细化覆盖下一章的卷 → 生成该单元章纲 → 确认章纲 → 写正文；全书写完为 done。
只读，不写库。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.services.volume_planning import loads_units, unit_at
from app.services.volume_service import list_volumes, story_fields


def _unconfirmed(outline: Any) -> bool:
    return outline.review_status == "draft" or bool(outline.upstream_stale)


async def progress_snapshot(db: AsyncSession, project_id: str) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    total = int(getattr(project, "chapter_count", 0) or 0)
    fields = await story_fields(db, project_id)
    volumes = await list_volumes(db, project_id)
    outlines = {o.chapter_number: o for o in (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id)
    )).scalars().all()}
    written = set((await db.execute(
        select(Chapter.chapter_number).where(
            Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "",
        )
    )).scalars().all())

    lines = [f"总纲：梗概{'已写' if fields['premise'] else '缺'}，全书主线{'已写' if fields['main_plot'] else '缺'}"]
    if volumes:
        confirmed = sum(1 for v in volumes if (v.review_status or "confirmed") == "confirmed" and not v.upstream_stale)
        detailed = sum(1 for v in volumes if loads_units(v.units))
        lines.append(f"卷纲：共 {len(volumes)} 卷（已确认 {confirmed}，已细化剧情单元 {detailed}）")
        for v in volumes[:8]:
            state = "草稿" if v.review_status == "draft" else ("上游已改" if v.upstream_stale else "已确认")
            lines.append(f"  - 第{v.volume_number}卷《{v.title}》第 {v.chapter_start}-{v.chapter_end} 章（{state}，"
                         f"剧情单元 {len(loads_units(v.units))} 个）")
    else:
        lines.append("卷纲：还没有分卷")
    drafts = sum(1 for o in outlines.values() if _unconfirmed(o))
    lines.append(f"章纲：共 {len(outlines)} 章（待确认 / 上游已改 {drafts}）")
    lines.append(f"正文：已写 {len(written)} 章" + (f"，最远到第 {max(written)} 章" if written else "")
                 + (f"；全书计划 {total} 章" if total else ""))

    step = _next_step(fields, volumes, outlines, written, total)
    lines.append(f"下一步：{step['label']}")
    return {"text": "\n".join(lines), "next_step": step}


def _next_step(fields: dict, volumes: list, outlines: dict, written: set, total: int) -> dict[str, Any]:
    if not (fields.get("premise") and fields.get("main_plot")):
        return {"action": "story_outline", "label": "完善总纲（梗概与全书主线），作者确认后再分卷"}
    if not volumes:
        return {"action": "plan_volumes", "label": "按总纲把全书分卷"}
    planned_end = max(v.chapter_end for v in volumes)
    target = next((n for n in range(1, max(planned_end, total) + 1) if n not in written), None)
    if target is None:
        return {"action": "done", "label": "全书已经写完，可以做整体审校"}
    volume = next((v for v in volumes if v.chapter_start <= target <= v.chapter_end), None)
    if volume is None:
        return {"action": "plan_volumes", "label": f"第 {target} 章以后还没有卷纲，继续分卷"}
    units = loads_units(volume.units)
    if not units:
        return {"action": "detail_volume", "volume_number": volume.volume_number,
                "label": f"把第{volume.volume_number}卷《{volume.title}》细化为剧情单元"}
    unit = unit_at(units, target)
    if unit is None:
        return {"action": "detail_volume", "volume_number": volume.volume_number,
                "label": f"第{volume.volume_number}卷的剧情单元没覆盖第 {target} 章，重新细化本卷"}
    end = int(unit["chapter_end"])
    if target not in outlines:
        return {"action": "plan_chapters", "volume_number": volume.volume_number, "unit_index": int(unit["index"]),
                "label": f"把第{volume.volume_number}卷剧情单元《{unit.get('title')}》展开为章纲"}
    pending = [n for n in range(target, end + 1) if n in outlines and _unconfirmed(outlines[n])]
    if pending:
        return {"action": "confirm_outlines", "chapters": pending,
                "label": f"请作者确认第 {pending[0]}-{pending[-1]} 章的章纲（AI 草拟或上游已改）"}
    last = target
    while last + 1 <= end and last + 1 in outlines and last + 1 not in written:
        last += 1
    return {"action": "write_chapters", "from_chapter": target, "to_chapter": last,
            "label": f"写第 {target}-{last} 章正文"}
