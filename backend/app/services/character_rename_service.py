"""角色改名级联。

Character.name 在若干表里以「名字快照」形式存在：组织成员名单 JSON、章纲视角/涉及角色、
连续性信号、一致性问题、作者的人物状态修正、章节分析的角色状态。这些字段都是整值比对的结构化名字，
改名时做精确等值替换是安全的；自由文本（章节正文、剧情要点等）不在此处理。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter_consistency_issue import ChapterConsistencyIssue
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.ledger_override import AuthorStateSignal
from app.models.memory import PlotAnalysis

logger = get_logger(__name__)


def _rename_in_name_list(raw: str | None, old_name: str, new_name: str) -> str | None:
    """JSON 名字数组里等于 old_name 的元素（字符串或 {"name": ...}）改为 new_name；无命中返回 None。"""
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    changed = False
    for idx, item in enumerate(items):
        if isinstance(item, str):
            if item.strip() == old_name:
                items[idx] = new_name
                changed = True
        elif isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip() == old_name:
            item["name"] = new_name
            changed = True
    return json.dumps(items, ensure_ascii=False) if changed else None


def _rename_in_character_states(states: Any, old_name: str, new_name: str) -> list | None:
    """PlotAnalysis.character_states 里 character_name 等于 old_name 的条目改名；无命中返回 None。"""
    if not isinstance(states, list):
        return None
    changed = False
    renamed = []
    for state in states:
        if isinstance(state, dict) and (state.get("character_name") or "").strip() == old_name:
            state = {**state, "character_name": new_name}
            changed = True
        renamed.append(state)
    return renamed if changed else None


async def propagate_character_rename(
    db: AsyncSession,
    project_id: str,
    old_name: str,
    new_name: str,
) -> dict[str, int]:
    """在 project 内把结构化名字字段里的 old_name 精确替换为 new_name，返回各处命中数。

    只 flush 不 commit，由调用方与角色本身的改名放在同一事务里提交。
    """
    old_key = (old_name or "").strip()
    if not old_key or not (new_name or "").strip() or old_key == new_name.strip():
        return {}

    counts: dict[str, int] = {}

    def _hit(key: str, n: int = 1) -> None:
        if n:
            counts[key] = counts.get(key, 0) + n

    # 1. 组织成员名单快照
    orgs = await db.execute(
        select(Character).where(
            Character.project_id == project_id,
            Character.is_organization == True,  # noqa: E712
            Character.organization_members.is_not(None),
        )
    )
    for org in orgs.scalars():
        updated = _rename_in_name_list(org.organization_members, old_key, new_name)
        if updated is not None:
            org.organization_members = updated
            _hit("organization_members")

    # 2. 章纲视角
    result = await db.execute(
        update(ChapterOutline)
        .where(ChapterOutline.project_id == project_id, func.trim(ChapterOutline.pov) == old_key)
        .values(pov=new_name)
    )
    _hit("chapter_outline_pov", result.rowcount)

    # 3. 章纲涉及角色
    outlines = await db.execute(
        select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            ChapterOutline.characters_involved.is_not(None),
        )
    )
    for outline in outlines.scalars():
        updated = _rename_in_name_list(outline.characters_involved, old_key, new_name)
        if updated is not None:
            outline.characters_involved = updated
            _hit("chapter_outline_characters_involved")

    # 4. 连续性信号 / 一致性问题（按名字串链的硬规则审计）/ 作者的人物状态修正（同样按名字回放）
    for model, key in (
        (ChapterContinuitySignal, "continuity_signals"),
        (ChapterConsistencyIssue, "consistency_issues"),
        (AuthorStateSignal, "author_state_signals"),
    ):
        result = await db.execute(
            update(model)
            .where(model.project_id == project_id, func.trim(model.character_name) == old_key)
            .values(character_name=new_name)
        )
        _hit(key, result.rowcount)

    # 5. 章节分析的角色状态快照
    analyses = await db.execute(
        select(PlotAnalysis).where(PlotAnalysis.project_id == project_id, PlotAnalysis.character_states.is_not(None))
    )
    for analysis in analyses.scalars():
        renamed = _rename_in_character_states(analysis.character_states, old_key, new_name)
        if renamed is not None:
            analysis.character_states = renamed  # 整体重新赋值，JSON 列才会被标记为脏
            _hit("plot_analysis_character_states")

    await db.flush()
    logger.info("🔁 角色改名级联 %s → %s: %s", old_key, new_name, counts or "无需更新")
    return counts
