"""卷纲 / 章纲规划共用的业务上下文（只读 DB，不写）。

与 reference_pack 槽位的分工：槽位管「项目常量」（骨架 / 角色 / 规则 / 地图 / 拆书维度），
这里管随规划位置变化的部分：总纲核心字段、已写正文的实际进展、未回收伏笔、视角规则。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_NO_ABILITY = {"", "无", "没有", "暂无", "none", "无金手指", "不适用"}


def clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def story_core_lines(fields: dict[str, Any]) -> list[str]:
    """【📖 总纲】梗概 / 全书主线 / 主角特殊能力（可选）/ 卖点 / 套路 / 升级路线 / 终极目标（空字段跳过）。"""
    lines = ["【📖 总纲】"]
    if fields.get("premise"):
        lines.append(f"- 梗概：{clip(fields['premise'], 400)}")
    if fields.get("main_plot"):
        lines.append(f"- 全书主线：{clip(fields['main_plot'], 1500)}")
    ability = clip(fields.get("golden_finger"), 200)
    if ability.lower() not in _NO_ABILITY:
        lines.append(f"- 主角特殊能力：{ability}（设定的一部分，只在故事需要时出现）")
    if fields.get("selling_points"):
        lines.append(f"- 核心卖点：{'、'.join(str(x) for x in fields['selling_points'][:6])}")
    if fields.get("main_tropes"):
        lines.append(f"- 主要套路：{'、'.join(str(x) for x in fields['main_tropes'][:6])}")
    if fields.get("power_system"):
        lines.append(f"- 成长路线：{clip(fields['power_system'], 200)}")
    if fields.get("ultimate_goal"):
        lines.append(f"- 终极目标：{clip(fields['ultimate_goal'], 200)}")
    return lines


async def written_upto(db: AsyncSession, project_id: str) -> int:
    """已写到第几章（有正文的最大章号；没有正文为 0）。"""
    from app.models.chapter import Chapter

    value = (await db.execute(
        select(func.max(Chapter.chapter_number)).where(
            Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "",
        )
    )).scalar_one_or_none()
    return int(value or 0)


async def actual_progress_block(
    db: AsyncSession, project_id: str, before_chapter: int, *, recent: int = 5, budget: int = 2_400,
) -> str:
    """【📈 实际剧情进展】已写章节的层级摘要 + 最近几章档案摘要；规划以它为准修正，避免越写越偏。"""
    from app.models.chapter import Chapter
    from app.models.chapter_digest import ChapterDigest
    from app.services.arc_summary_service import render_story_so_far

    if before_chapter <= 1:
        return ""
    story, _covered = await render_story_so_far(db, project_id, before_chapter, budget_chars=budget // 2)
    rows = (await db.execute(
        select(Chapter.chapter_number, Chapter.title, ChapterDigest.summary)
        .join(ChapterDigest, ChapterDigest.chapter_id == Chapter.id)
        .where(
            Chapter.project_id == project_id,
            Chapter.chapter_number < before_chapter,
            ChapterDigest.summary != "",
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(recent)
    )).all()
    if not story and not rows:
        return ""
    lines = ["【📈 实际剧情进展（以已写正文为准：计划与它冲突时顺着实际写，不要推翻已发生的事）】"]
    if story:
        lines.append(story)
    if rows:
        lines.append("最近几章：")
        lines += [f"- 第{number}章《{clip(title, 20)}》：{clip(content, 160)}" for number, title, content in reversed(rows)]
    return "\n".join(lines)[:budget]


async def open_promises_block(
    db: AsyncSession, project_id: str, before_chapter: int, *, limit: int = 12, with_ids: bool = False,
) -> tuple[str, dict[str, str], list[Any]]:
    """【🎣 当前未回收的伏笔】with_ids → 带短编号 P1…，返回 (文本, 短编号→真实 id, 承诺列表)。"""
    from app.services.narrative_state_service import narrative_state_service

    promises = await narrative_state_service._get_active_promises(db, project_id, max(before_chapter, 1), limit=limit)
    if not promises:
        return "", {}, []
    lines = ["【🎣 当前未回收的伏笔 / 承诺】"]
    mapping: dict[str, str] = {}
    for i, p in enumerate(promises, start=1):
        flag = narrative_state_service._promise_flag(p, before_chapter).strip()
        head = f"P{i} " if with_ids else ""
        if with_ids:
            mapping[f"P{i}"] = p.id
        lines.append(
            f"- {head}[{p.promise_type}/{p.priority}] {clip(p.title, 40)}（第{p.source_chapter_number}章起）"
            f"{' ' + flag if flag else ''}：{clip(p.content, 60)}"
        )
    return "\n".join(lines), mapping, list(promises)


def pov_line(narrative_perspective: str | None) -> str:
    perspective = (narrative_perspective or "").strip() or "第三人称"
    if "第一" in perspective:
        return "叙事视角：第一人称（“我”= 主角；章纲 pov 字段固定填主角名，章纲用第三人称记录）"
    return f"叙事视角：{perspective}"
