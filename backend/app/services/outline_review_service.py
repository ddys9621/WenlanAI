"""章纲确认与上游过期（参考岚笺「保存 ≠ 确认；上游改了，确认失效」）。

- review_status：draft = AI 草拟待确认（桥段展开 / 自动规划产出）；confirmed 或空 = 已确认（作者手建 / 旧数据）
- upstream_stale：所属桥段 / 剧情线 / 故事大纲的内容被改过，建议核对；确认后清除
只做提醒（生成前预检 / 列表标记 / 批量可选「只写已确认章纲」），不阻断单章生成。
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_candidate import utcnow
from app.models.chapter_outline import ChapterOutline
from app.models.chapter_outline_plot_line_link import ChapterOutlinePlotLineLink
from app.models.plot_bridge import PlotBridge

DRAFT = "draft"
CONFIRMED = "confirmed"

BRIDGE_CONTENT_FIELDS = (
    "title", "goal", "showoff_point", "golden_finger_usage", "c1_intro", "c2_build", "c3_payoff", "c4_aftermath",
    "next_bridge_hook",
)
PLOT_LINE_CONTENT_FIELDS = ("title", "description", "timeline_data", "estimated_chapters")


def is_unconfirmed(outline: Any) -> bool:
    return getattr(outline, "review_status", None) == DRAFT


def confirm(outline: ChapterOutline) -> None:
    outline.review_status = CONFIRMED
    outline.confirmed_at = utcnow()
    outline.upstream_stale = False
    outline.upstream_reason = None


async def confirm_project(db: AsyncSession, project_id: str) -> int:
    rows = (await db.execute(
        select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            or_(ChapterOutline.review_status == DRAFT, ChapterOutline.upstream_stale.is_(True)),
        )
    )).scalars().all()
    for outline in rows:
        confirm(outline)
    return len(rows)


def _merge_reason(current: str | None, reason: str) -> str:
    parts = [p for p in (current or "").split("；") if p]
    if reason not in parts:
        parts.append(reason)
    return "；".join(parts[-3:])


async def mark_stale(db: AsyncSession, outline_ids: Iterable[str], reason: str) -> int:
    ids = list({i for i in outline_ids if i})
    if not ids:
        return 0
    rows = (await db.execute(select(ChapterOutline).where(ChapterOutline.id.in_(ids)))).scalars().all()
    for outline in rows:
        outline.upstream_stale = True
        outline.upstream_reason = _merge_reason(outline.upstream_reason, reason)
    return len(rows)


def content_changed(obj: Any, updates: dict[str, Any], fields: Iterable[str]) -> bool:
    """更新里有没有真正改动内容字段（值相同 / 只改状态不算）。"""
    for field in fields:
        if field in updates and updates[field] is not None and updates[field] != getattr(obj, field, None):
            return True
    return False


async def mark_bridge_outlines(db: AsyncSession, bridge: PlotBridge) -> int:
    ids = (await db.execute(select(ChapterOutline.id).where(ChapterOutline.bridge_id == bridge.id))).scalars().all()
    return await mark_stale(db, ids, f"所属桥段《{bridge.title}》已修改")


async def mark_plot_line_outlines(db: AsyncSession, plot_line: Any) -> int:
    linked = (await db.execute(
        select(ChapterOutlinePlotLineLink.chapter_outline_id).where(ChapterOutlinePlotLineLink.plot_line_id == plot_line.id)
    )).scalars().all()
    via_bridge = (await db.execute(
        select(ChapterOutline.id)
        .join(PlotBridge, PlotBridge.id == ChapterOutline.bridge_id)
        .where(PlotBridge.plot_line_id == plot_line.id)
    )).scalars().all()
    return await mark_stale(db, [*linked, *via_bridge], f"所属剧情线《{plot_line.title}》已修改")


async def mark_project_outlines(db: AsyncSession, project_id: str, reason: str) -> int:
    ids = (await db.execute(select(ChapterOutline.id).where(ChapterOutline.project_id == project_id))).scalars().all()
    return await mark_stale(db, ids, reason)


def outline_warnings(outline: Any) -> list[str]:
    warnings = []
    if is_unconfirmed(outline):
        warnings.append("本章章纲是 AI 草拟的，尚未确认")
    if getattr(outline, "upstream_stale", False):
        reason = getattr(outline, "upstream_reason", None) or "上游规划已修改"
        warnings.append(f"本章章纲的上游已改动（{reason}），建议先核对章纲")
    return warnings
