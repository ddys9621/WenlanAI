"""创作进度：世界设定 → 世界规则 → 设定条目 → 角色与组织 → 关系 → 总纲 → 卷纲 → 章纲 → 正文 各到哪一步，
以及下一步该做什么（共创室每轮都把它带进上下文，主编和成员照它推进；作者也能一眼看清）。

下一步按创作顺序找第一个没做完的层：
- 必需的层（世界设定 / 角色与组织 / 总纲）一点没写：先补它，后面写得再多也一样（地基没打）
- 必需的层写了一部分：分卷之前先补全（先把地基打完整再规划）；已经分卷 / 有章纲 / 有正文了就不再卡着，缺什么写在进度里
- 可选的层（世界规则 / 设定条目 / 关系）：后面的层都还没开始时提示（题材用不上可以跳过），后面开始了就算跳过
总纲之后：分卷 → 细化覆盖下一章的卷 → 生成该单元章纲 → 确认章纲 → 写正文；全书写完为 done。
只读，不写库。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.project import Project
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.setting_entry import SettingEntry
from app.models.world_rule import WorldRule
from app.services.volume_planning import loads_units, unit_at
from app.services.volume_service import list_volumes, story_fields

WORLD_FIELDS = (("world_time_period", "时代背景"), ("world_location", "地点设定"), ("world_atmosphere", "氛围基调"),
                ("world_rules", "世界规则"))
RULE_CATEGORIES = (("cultivation_realm", "修炼境界"), ("equipment_template", "装备模板"), ("map_location", "地图位置"))
HEROES_SHOWN = 3


@dataclass
class Layer:
    """创作链上的一层：done 做完了 / started 已经动笔 / required 必需（可选层后面开始了就算跳过）。"""
    line: str
    done: bool
    started: bool
    required: bool
    step: dict


def _unconfirmed(outline: Any) -> bool:
    return outline.review_status == "draft" or bool(outline.upstream_stale)


def _world_layer(project: Optional[Project]) -> Layer:
    filled = [label for key, label in WORLD_FIELDS if (getattr(project, key, None) or "").strip()]
    missing = [label for _key, label in WORLD_FIELDS if label not in filled]
    if not filled:
        line = "世界设定：时代背景 / 地点设定 / 氛围基调 / 世界规则四栏都还空着"
        step = {"action": "world_setting", "label": "完善世界设定：时代背景、地点设定、氛围基调、世界规则（世界设定页四栏）"}
    elif missing:
        line = f"世界设定：{'、'.join(filled)}已写；{'、'.join(missing)}还空着"
        step = {"action": "world_setting", "label": f"补全世界设定：还缺{'、'.join(missing)}"}
    else:
        line = "世界设定：时代背景、地点设定、氛围基调、世界规则四栏都已写"
        step = {"action": "world_setting", "label": "世界设定已完善"}
    return Layer(line, not missing, bool(filled), True, step)


async def _rules_layer(db: AsyncSession, project_id: str) -> Layer:
    counts = dict((await db.execute(
        select(WorldRule.category, func.count(WorldRule.id)).where(WorldRule.project_id == project_id)
        .group_by(WorldRule.category)
    )).all())
    total = sum(counts.values())
    have = [f"{label} {counts[key]} 条" for key, label in RULE_CATEGORIES if counts.get(key)]
    lack = [label for key, label in RULE_CATEGORIES if not counts.get(key)]
    line = (f"世界规则：{'、'.join(have) or f'{total} 条'}" + (f"；{'、'.join(lack)}还没有" if lack else "")
            if total else "世界规则：还没有（修炼境界 / 装备模板 / 地图位置）")
    step = {"action": "world_rules",
            "label": "建世界规则：修炼境界 / 装备模板 / 地图位置（题材用不上可以跳过，接着建设定条目）"}
    return Layer(line, bool(total), bool(total), False, step)


async def _entries_layer(db: AsyncSession, project_id: str) -> Layer:
    count = int(await db.scalar(select(func.count(SettingEntry.id)).where(SettingEntry.project_id == project_id)) or 0)
    line = f"设定条目：{count} 条" if count else "设定条目：还没有（术语 / 铁律 / 势力 / 规则等）"
    step = {"action": "setting_entries",
            "label": "建设定条目：术语 / 铁律 / 势力 / 规则等零散设定（用不上可以跳过，接着建角色与组织）"}
    return Layer(line, bool(count), bool(count), False, step)


async def _cast_and_relations(db: AsyncSession, project_id: str) -> tuple[Layer, Layer]:
    cast = (await db.execute(
        select(Character.name, Character.is_organization, Character.role_type)
        .where(Character.project_id == project_id).order_by(Character.created_at)
    )).all()
    people = [c for c in cast if not c.is_organization]
    orgs = [c for c in cast if c.is_organization]
    heroes = [c.name for c in people if c.role_type == "protagonist"]
    hero_text = (f"（主角：{'、'.join(heroes[:HEROES_SHOWN])}{'等' if len(heroes) > HEROES_SHOWN else ''}）" if heroes
                 else "（还没定主角）" if people else "")
    cast_layer = Layer(
        f"角色与组织：人物 {len(people)} 个{hero_text}，组织 {len(orgs)} 个" if cast else "角色与组织：还没有",
        bool(people), bool(cast), True,
        {"action": "characters", "label": "建角色与组织：先定主角和主要人物，再建门派 / 家族等势力"},
    )

    relationships = int(await db.scalar(
        select(func.count(CharacterRelationship.id)).where(CharacterRelationship.project_id == project_id)) or 0)
    members = int(await db.scalar(
        select(func.count(OrganizationMember.id))
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(Organization.project_id == project_id)) or 0)
    need_rel = len(people) >= 2 and not relationships
    need_member = bool(orgs) and bool(people) and not members
    label = ("理清关系：人物之间是什么关系，谁属于哪个组织、什么职位" if need_rel and need_member
             else "理清人物关系：谁和谁是什么关系" if need_rel else "理清组织归属：谁属于哪个组织、什么职位")
    relations_layer = Layer(f"关系：人物关系 {relationships} 条，组织成员 {members} 人",
                            not (need_rel or need_member), bool(relationships or members), False,
                            {"action": "relationships", "label": label})
    return cast_layer, relations_layer


def _outline_layer(fields: dict) -> Layer:
    return Layer(
        f"总纲：梗概{'已写' if fields['premise'] else '缺'}，全书主线{'已写' if fields['main_plot'] else '缺'}",
        bool(fields["premise"] and fields["main_plot"]), bool(fields["premise"] or fields["main_plot"]), True,
        {"action": "story_outline", "label": "完善总纲（梗概与全书主线），作者确认后再分卷"},
    )


def _foundation_step(layers: list[Layer], planning_started: bool) -> Optional[dict]:
    """总纲及之前的层：必需层一点没写就先补、写了一部分就在分卷之前补全；可选层只在后面的层都还没开始时提示。"""
    for i, layer in enumerate(layers):
        if layer.done:
            continue
        if layer.required:
            if not layer.started or not planning_started:
                return layer.step
        elif not (planning_started or any(other.started for other in layers[i + 1:])):
            return layer.step
    return None


async def progress_snapshot(db: AsyncSession, project_id: str) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    total = int(getattr(project, "chapter_count", 0) or 0)
    cast_layer, relations_layer = await _cast_and_relations(db, project_id)
    foundation = [_world_layer(project), await _rules_layer(db, project_id), await _entries_layer(db, project_id),
                  cast_layer, relations_layer, _outline_layer(await story_fields(db, project_id))]
    volumes = await list_volumes(db, project_id)
    outlines = {o.chapter_number: o for o in (await db.execute(
        select(ChapterOutline.chapter_number, ChapterOutline.review_status, ChapterOutline.upstream_stale)
        .where(ChapterOutline.project_id == project_id)
    )).all()}
    written = set((await db.execute(
        select(Chapter.chapter_number).where(
            Chapter.project_id == project_id, Chapter.content.isnot(None), Chapter.content != "",
        )
    )).scalars().all())

    lines = [layer.line for layer in foundation]
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

    step = (_foundation_step(foundation, bool(volumes or outlines or written))
            or _planning_step(volumes, outlines, written, total))
    lines.append(f"下一步：{step['label']}")
    return {"text": "\n".join(lines), "next_step": step}


def _planning_step(volumes: list, outlines: dict, written: set, total: int) -> dict[str, Any]:
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
