"""卷纲服务：总纲 → 分卷 → 细化剧情单元 → 单元章纲（LLM + DB）。

- generate_skeleton：按总纲把全书（或已写章纲之后的部分）分成若干卷，产出 draft 卷；已有章纲的卷保留不动
- detail_volume：把一卷拆成剧情单元（单元长短由模型按事件定）+ 线索编排；本卷已有章纲时拒绝（避免与章纲脱节）
- generate_unit_outlines：把一个剧情单元展开为章纲（只补缺的章；超过 CHAPTER_BATCH 章分段续写）
- update_volume：内容改动 → 本卷章纲标「上游已改」；confirm_volume：作者确认
- ensure_outline_for_chapter：批量写作缺章纲时自动规划（未细化先细化 → 生成覆盖该章的单元章纲）
所有规划结果都是 draft，作者确认后才算定稿（参考岚笺「保存 ≠ 确认」）。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter_candidate import utcnow
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.story_outline import StoryOutline
from app.models.volume import Volume
from app.services import outline_review_service as outline_review
from app.services import volume_planning as vp
from app.services.narrative_tasks import has_tasks, normalize_narrative_tasks
from app.services.planning_context import (
    actual_progress_block,
    clip,
    open_promises_block,
    pov_line,
    story_core_lines,
    written_upto,
)
from app.services.knowledge import kb_refs
from app.services.knowledge.kb_context import traced_kb_context
from app.services.platform_presets import default_chapter_words
from app.services.reference_pack import AssemblyContext, PromptAssembler
from app.utils.story_outline_fields import parse_story_outline_fields

logger = get_logger(__name__)

VOLUME_SCENE = "volume_planning"
OUTLINE_SCENE = "chapter_outline"
DRAFT, CONFIRMED = "draft", "confirmed"
TEXT_FIELDS = ("title", "summary", "goal", "climax", "ending_hook", "review_note")


class VolumePlanningError(ValueError):
    """前置条件不满足 / 模型输出不可用（API 层映射为 400）。"""


class VolumeConflictError(RuntimeError):
    """与已有章纲冲突（API 层映射为 409）。"""


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def volume_to_dict(v: Volume, outline_count: int = 0) -> dict[str, Any]:
    return {
        "id": v.id, "project_id": v.project_id, "volume_number": v.volume_number, "title": v.title or "",
        "chapter_start": v.chapter_start, "chapter_end": v.chapter_end,
        "summary": v.summary or "", "goal": v.goal or "", "climax": v.climax or "", "ending_hook": v.ending_hook or "",
        "units": vp.loads_units(v.units), "threads": vp.loads_threads(v.threads), "review_note": v.review_note or "",
        "review_status": v.review_status or CONFIRMED, "confirmed_at": _iso(v.confirmed_at),
        "upstream_stale": bool(v.upstream_stale), "upstream_reason": v.upstream_reason or "",
        "outline_count": outline_count, "created_at": _iso(v.created_at), "updated_at": _iso(v.updated_at),
    }


async def list_volumes(db: AsyncSession, project_id: str) -> list[Volume]:
    return list((await db.execute(
        select(Volume).where(Volume.project_id == project_id).order_by(Volume.volume_number)
    )).scalars().all())


async def outline_counts(db: AsyncSession, project_id: str) -> dict[str, int]:
    rows = await db.execute(
        select(ChapterOutline.volume_id, func.count(ChapterOutline.id))
        .where(ChapterOutline.project_id == project_id, ChapterOutline.volume_id.isnot(None))
        .group_by(ChapterOutline.volume_id)
    )
    return dict(rows.all())


async def volume_for_chapter(db: AsyncSession, project_id: str, chapter_number: int) -> Optional[Volume]:
    return (await db.execute(
        select(Volume).where(
            Volume.project_id == project_id, Volume.chapter_start <= chapter_number, Volume.chapter_end >= chapter_number,
        ).order_by(Volume.volume_number)
    )).scalars().first()


async def story_fields(db: AsyncSession, project_id: str) -> dict[str, Any]:
    outline = (await db.execute(
        select(StoryOutline)
        .where(StoryOutline.project_id == project_id, StoryOutline.is_active == True)  # noqa: E712
        .order_by(StoryOutline.version.desc())
    )).scalars().first()
    return parse_story_outline_fields(outline.content if outline else None)


async def _require_project(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise VolumePlanningError("项目不存在")
    return project


async def _assemble(db: AsyncSession, project_id: str, scene: str, model: str) -> Any:
    return await PromptAssembler().assemble(db, AssemblyContext(scene=scene, model_name=model, project_id=project_id))


def _model(ai: Any, model: Optional[str]) -> str:
    return model or getattr(ai, "default_model", None) or ""


async def _collect(ai: Any, *, prompt: str, system_prompt: str, model: Optional[str], what: str) -> str:
    kwargs = {"model": model} if model else {}
    resp = await ai.generate_text_stream_collect(
        prompt=prompt, system_prompt=system_prompt, temperature=0.7, context=what, **kwargs,
    )
    content = (resp or {}).get("content") or ""
    if (resp or {}).get("finish_reason") == "length":
        raise VolumePlanningError(f"{what}：输出被 Max Tokens 截断（已输出 {len(content)} 字），请在「设置」中调大 Max Tokens 后重试")
    if not content.strip():
        raise VolumePlanningError(f"{what}：模型没有返回内容")
    return content


def _instruction(text: str) -> str:
    return f"【作者本次的要求（优先满足）】\n{text.strip()}" if text and text.strip() else ""


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _volume_block(v: Volume, heading: str, *, full: bool = True) -> str:
    lines = [heading, f"- 第{v.volume_number}卷《{v.title}》（第 {v.chapter_start}-{v.chapter_end} 章）"]
    if v.goal:
        lines.append(f"- 目标与冲突：{clip(v.goal, 300)}")
    if v.summary:
        lines.append(f"- 本卷故事：{clip(v.summary, 1500 if full else 300)}")
    if full and v.climax:
        lines.append(f"- 卷末高潮：{clip(v.climax, 200)}")
    if v.ending_hook:
        lines.append(f"- 卷末钩子：{clip(v.ending_hook, 200)}")
    threads = vp.loads_threads(v.threads)
    if full and threads:
        lines.append("- 线索编排：" + "；".join(clip(t, 120) for t in threads[:8]))
    if full and v.review_note:
        lines.append(f"- 上一卷复盘修正（按它调整）：{clip(v.review_note, 300)}")
    return "\n".join(lines)


# ---------------- 分卷 ----------------

async def generate_skeleton(
    db: AsyncSession, project_id: str, ai: Any, *, total_chapters: Optional[int] = None,
    volume_count: Optional[int] = None, instruction: str = "", model: Optional[str] = None,
) -> list[Volume]:
    project = await _require_project(db, project_id)
    total = int(total_chapters or project.chapter_count or 0)
    if total < 1:
        raise VolumePlanningError("请先在世界设定里填写全书章数")
    volumes = await list_volumes(db, project_id)
    counts = await outline_counts(db, project_id)
    locked = max((i for i, v in enumerate(volumes) if counts.get(v.id)), default=-1)
    kept, replaced = volumes[: locked + 1], volumes[locked + 1:]
    start = kept[-1].chapter_end + 1 if kept else 1
    if start > total:
        raise VolumePlanningError(f"前 {len(kept)} 卷已覆盖到第 {start - 1} 章，全书只有 {total} 章：要继续规划请先调大全书章数")
    fixed = "\n".join(
        f"- 第{v.volume_number}卷《{v.title}》第 {v.chapter_start}-{v.chapter_end} 章：{clip(v.summary, 200)}" for v in kept
    )
    effective = _model(ai, model)
    prompt = await _assemble(db, project_id, VOLUME_SCENE, effective)
    progress = await actual_progress_block(db, project_id, before_chapter=start) if await written_upto(db, project_id) else ""
    task = vp.render_skeleton_task(
        total_chapters=total, start_chapter=start, volume_count=volume_count or vp.suggest_volume_count(total - start + 1),
        fixed_text=fixed,
    )
    kb = await traced_kb_context(db, project_id, "volume_skeleton")
    content = await _collect(
        ai, prompt=_join(prompt.user_prompt, "\n".join(story_core_lines(await story_fields(db, project_id))), progress,
                         kb.text, _instruction(instruction), task, kb.ref_instruction),
        system_prompt=prompt.system_prompt, model=model, what="分卷",
    )
    rows = vp.parse_skeleton(content, start_chapter=start, end_chapter=total, first_number=len(kept) + 1)
    refs = [row.pop("ref", "") for row in rows]
    for v in replaced:
        await db.delete(v)
    await db.flush()
    created = [Volume(project_id=project_id, review_status=DRAFT, **row) for row in rows]
    db.add_all(created)
    await db.flush()
    await kb_refs.save_citations(db, project_id, kb.refs, kb.scene, "volume", [(v.id, ref) for v, ref in zip(created, refs)])
    await db.commit()
    for v in created:
        await db.refresh(v)
    logger.info("[卷纲] project=%s 分卷 %d 卷（保留 %d 卷，第 %d-%d 章）", project_id, len(created), len(kept), start, total)
    return created


# ---------------- 细化卷纲 ----------------

async def _neighbour(db: AsyncSession, volume: Volume, offset: int) -> Optional[Volume]:
    return (await db.execute(
        select(Volume).where(Volume.project_id == volume.project_id, Volume.volume_number == volume.volume_number + offset)
    )).scalars().first()


async def _require_volume(db: AsyncSession, volume_id: str) -> Volume:
    volume = await db.get(Volume, volume_id)
    if volume is None:
        raise VolumePlanningError("卷纲不存在")
    return volume


async def detail_volume(
    db: AsyncSession, volume_id: str, ai: Any, *, instruction: str = "", model: Optional[str] = None,
) -> Volume:
    volume = await _require_volume(db, volume_id)
    if (await outline_counts(db, volume.project_id)).get(volume.id):
        raise VolumeConflictError(f"第{volume.volume_number}卷已有章纲：先删除本卷章纲再重新细化，或直接修改剧情单元")
    prev, nxt = await _neighbour(db, volume, -1), await _neighbour(db, volume, 1)
    promises, _ids, _items = await open_promises_block(db, volume.project_id, before_chapter=volume.chapter_start, limit=10)
    prompt = await _assemble(db, volume.project_id, VOLUME_SCENE, _model(ai, model))
    kb = await traced_kb_context(db, volume.project_id, "volume_detail", volume=volume)
    content = await _collect(
        ai, prompt=_join(
            prompt.user_prompt,
            "\n".join(story_core_lines(await story_fields(db, volume.project_id))),
            _volume_block(prev, "【⬅ 上一卷（已收尾，本卷开头要接住它的结尾）】", full=False) if prev else "",
            _volume_block(volume, "【📍 本卷】"),
            _volume_block(nxt, "【➡ 下一卷（本卷结尾要把局面交给它）】", full=False) if nxt else "",
            await actual_progress_block(db, volume.project_id, before_chapter=volume.chapter_start),
            promises, kb.text, _instruction(instruction),
            vp.render_detail_task({"volume_number": volume.volume_number, "title": volume.title,
                                   "chapter_start": volume.chapter_start, "chapter_end": volume.chapter_end}),
            kb.ref_instruction,
        ),
        system_prompt=prompt.system_prompt, model=model, what=f"细化第{volume.volume_number}卷",
    )
    detail = vp.parse_detail(content, {"chapter_start": volume.chapter_start, "chapter_end": volume.chapter_end})
    volume.units = json.dumps(detail["units"], ensure_ascii=False)
    volume.threads = json.dumps(detail["threads"], ensure_ascii=False)
    if detail["summary"]:
        volume.summary = detail["summary"]
    volume.review_status = DRAFT
    await kb_refs.clear_citations(db, volume.project_id, "unit", prefix=f"{volume.id}:")
    await kb_refs.save_citations(db, volume.project_id, kb.refs, kb.scene, "unit",
                                 [(f"{volume.id}:{u['index']}", ref) for u, ref in zip(detail["units"], detail["refs"])])
    await db.commit()
    await db.refresh(volume)
    logger.info("[卷纲] 第%d卷细化为 %d 个剧情单元", volume.volume_number, len(detail["units"]))
    return volume


# ---------------- 单元章纲 ----------------

def _map_task_ids(raw: Any, mapping: dict[str, str]) -> Any:
    """章纲 narrative_tasks 里的短编号（P3）→ 真实承诺 id；其余原样（normalize 时按未回收清单过滤）。"""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    for kind in ("resolve", "advance"):
        out[kind] = [
            {**item, "promise_id": mapping.get(str(item.get("promise_id") or "").strip().upper(), item.get("promise_id"))}
            for item in raw.get(kind) or [] if isinstance(item, dict)
        ]
    return out


def _batches(numbers: list[int]) -> list[list[int]]:
    """缺章号 → 连续段，每段再按 CHAPTER_BATCH 切开。"""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1 and len(runs[-1]) < vp.CHAPTER_BATCH:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


async def _previous_chapter_block(db: AsyncSession, project_id: str, chapter_number: int) -> str:
    if chapter_number <= 1:
        return ""
    prev = (await db.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.chapter_number == chapter_number - 1)
    )).scalars().first()
    if prev is None:
        return ""
    lines = [f"【⛓ 上一章结尾（第 {chapter_number} 章从这里接，不要重述）】", f"- 第{prev.chapter_number}章《{prev.title}》"]
    if prev.exit_state:
        lines.append(f"- 停在：{clip(prev.exit_state, 300)}")
    if prev.plot_points:
        lines.append(f"- 经过：{clip(prev.plot_points, 300)}")
    return "\n".join(lines)


def _unit_block(unit: dict, units: list[dict], next_volume: Optional[Volume]) -> str:
    lines = [f"【🧩 剧情单元 {unit['index']}/{len(units)}《{unit['title']}》（第 {unit['chapter_start']}-{unit['chapter_end']} 章）】"]
    if unit.get("story"):
        lines.append(f"- 经过：{clip(unit['story'], 1500)}")
    if unit.get("turn"):
        lines.append(f"- 结束时的变化：{clip(unit['turn'], 300)}")
    following = next((u for u in units if u["index"] == unit["index"] + 1), None)
    if following:
        lines.append(f"- 下一件事：《{following['title']}》{clip(following.get('story'), 120)}")
    elif next_volume is not None:
        lines.append(f"- 本单元是本卷最后一件事，之后进入第{next_volume.volume_number}卷《{next_volume.title}》")
    return "\n".join(lines)


def _json_list(items: list[str]) -> Optional[str]:
    return json.dumps(items, ensure_ascii=False) if items else None


async def generate_unit_outlines(
    db: AsyncSession, volume_id: str, unit_index: int, ai: Any, *, instruction: str = "", model: Optional[str] = None,
    on_batch: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> list[ChapterOutline]:
    volume = await _require_volume(db, volume_id)
    units = vp.loads_units(volume.units)
    unit = next((u for u in units if int(u.get("index") or 0) == unit_index), None)
    if unit is None:
        raise VolumePlanningError(f"第{volume.volume_number}卷没有剧情单元 {unit_index}：请先细化卷纲")
    start, end = int(unit["chapter_start"]), int(unit["chapter_end"])
    existing = set((await db.execute(
        select(ChapterOutline.chapter_number).where(
            ChapterOutline.project_id == volume.project_id, ChapterOutline.chapter_number.between(start, end),
        )
    )).scalars().all())
    missing = [n for n in range(start, end + 1) if n not in existing]
    if not missing:
        raise VolumeConflictError(f"剧情单元《{unit['title']}》第 {start}-{end} 章的章纲都已存在")
    project = await _require_project(db, volume.project_id)
    fields = await story_fields(db, volume.project_id)
    prompt = await _assemble(db, volume.project_id, OUTLINE_SCENE, _model(ai, model))
    words = default_chapter_words(getattr(project, "platform_preset", None))
    next_volume = await _neighbour(db, volume, 1)
    kb = await traced_kb_context(db, volume.project_id, "unit_outline", volume=volume, unit=unit)
    created: list[ChapterOutline] = []
    for batch in _batches(missing):
        b_start, b_end = batch[0], batch[-1]
        promise_text, promise_ids, open_promises = await open_promises_block(
            db, volume.project_id, before_chapter=b_start, limit=15, with_ids=True,
        )
        content = await _collect(
            ai, prompt=_join(
                prompt.user_prompt,
                "\n".join(story_core_lines(fields)[:4]),
                _volume_block(volume, "【📍 所属卷】"),
                _unit_block(unit, units, next_volume),
                await _previous_chapter_block(db, volume.project_id, b_start),
                await actual_progress_block(db, volume.project_id, before_chapter=b_start),
                promise_text, kb.text, _instruction(instruction),
                vp.render_chapters_task(unit, b_start, b_end, pov_line(project.narrative_perspective), words),
                kb.ref_instruction,
            ),
            system_prompt=prompt.system_prompt, model=model, what=f"第 {b_start}-{b_end} 章章纲",
        )
        batch_refs: list[tuple[ChapterOutline, str]] = []
        for row in vp.parse_chapter_outlines(content, b_start, b_end):
            tasks = normalize_narrative_tasks(_map_task_ids(row["narrative_tasks"], promise_ids), open_promises)
            outline = ChapterOutline(
                project_id=volume.project_id, chapter_number=row["chapter_number"], title=row["title"],
                scene=row["scene"], pov=row["pov"], plot_points=row["plot_points"],
                key_events=json.dumps(row["key_events"], ensure_ascii=False),
                characters_involved=json.dumps(row["characters_involved"], ensure_ascii=False),
                entry_state=row["entry_state"], exit_state=row["exit_state"], forbidden=_json_list(row["forbidden"]),
                narrative_tasks=json.dumps(tasks, ensure_ascii=False) if has_tasks(tasks) else None,
                target_word_count=row["target_word_count"] or words, order_index=row["chapter_number"],
                volume_id=volume.id, unit_index=unit_index, review_status=DRAFT,
            )
            db.add(outline)
            created.append(outline)
            batch_refs.append((outline, row["ref"]))
        await db.flush()
        await kb_refs.save_citations(db, volume.project_id, kb.refs, kb.scene, "chapter_outline",
                                     [(o.id, ref) for o, ref in batch_refs])
        await db.commit()
        if on_batch is not None:
            await on_batch(b_start, b_end)
    for outline in created:
        await db.refresh(outline)
    logger.info("[卷纲] 第%d卷单元 %d 生成章纲 %d 章", volume.volume_number, unit_index, len(created))
    return created


# ---------------- 编辑 / 确认 / 删除 ----------------

def _normalized_updates(volume: Volume, updates: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(updates[k]) for k in TEXT_FIELDS if updates.get(k) is not None}
    start = int(updates.get("chapter_start") or volume.chapter_start)
    end = int(updates.get("chapter_end") or volume.chapter_end)
    if end < start:
        raise VolumePlanningError("结束章号不能小于起始章号")
    out["chapter_start"], out["chapter_end"] = start, end
    units = updates.get("units")
    if units is not None:
        out["units"] = json.dumps(vp.normalize_units(units, start, end), ensure_ascii=False) if units else None
    elif (start, end) != (volume.chapter_start, volume.chapter_end) and volume.units:
        out["units"] = json.dumps(vp.normalize_units(vp.loads_units(volume.units), start, end), ensure_ascii=False)
    threads = updates.get("threads")
    if threads is not None:
        out["threads"] = json.dumps([str(t).strip() for t in threads if str(t).strip()], ensure_ascii=False)
    return out


async def update_volume(db: AsyncSession, volume: Volume, updates: dict[str, Any]) -> Volume:
    """保存作者的修改（保存 ≠ 确认）；内容真的变了 → 本卷章纲标「上游已改」。"""
    values = _normalized_updates(volume, updates)
    changed = any(getattr(volume, k) != v for k, v in values.items() if k != "review_note")
    for key, value in values.items():
        setattr(volume, key, value)
    if changed:
        ids = (await db.execute(select(ChapterOutline.id).where(ChapterOutline.volume_id == volume.id))).scalars().all()
        await outline_review.mark_stale(db, ids, f"所属卷纲《{volume.title}》已修改")
    await db.flush()
    return volume


def confirm_volume(volume: Volume) -> None:
    volume.review_status = CONFIRMED
    volume.confirmed_at = utcnow()
    volume.upstream_stale = False
    volume.upstream_reason = None


async def delete_volume(db: AsyncSession, volume: Volume) -> None:
    if (await outline_counts(db, volume.project_id)).get(volume.id):
        raise VolumeConflictError(f"第{volume.volume_number}卷已有章纲，先删除这些章纲再删卷")
    await db.delete(volume)


async def create_volume(db: AsyncSession, project_id: str, data: dict[str, Any]) -> Volume:
    """手建一卷：默认接在最后一卷之后。"""
    volumes = await list_volumes(db, project_id)
    last = volumes[-1] if volumes else None
    start = int(data.get("chapter_start") or (last.chapter_end + 1 if last else 1))
    end = int(data.get("chapter_end") or start + vp.CHAPTERS_PER_VOLUME - 1)
    volume = Volume(project_id=project_id, volume_number=(last.volume_number + 1) if last else 1,
                    title=str(data.get("title") or "新的一卷"), chapter_start=start, chapter_end=max(start, end),
                    review_status=CONFIRMED)
    db.add(volume)
    await db.flush()
    await update_volume(db, volume, data)
    return volume


# ---------------- 批量写作的自动规划 ----------------

async def ensure_outline_for_chapter(db: AsyncSession, project_id: str, chapter_number: int, ai: Any) -> bool:
    """缺章纲时：找覆盖本章的卷 → 未细化先细化 → 生成覆盖本章的单元章纲。找不到卷返回 False。"""
    volume = await volume_for_chapter(db, project_id, chapter_number)
    if volume is None:
        return False
    if not vp.loads_units(volume.units):
        volume = await detail_volume(db, volume.id, ai)
    unit = vp.unit_at(vp.loads_units(volume.units), chapter_number)
    if unit is None:
        return False
    has_outline = await db.scalar(select(ChapterOutline.id).where(
        ChapterOutline.project_id == project_id, ChapterOutline.chapter_number == chapter_number,
    ))
    if not has_outline:
        await generate_unit_outlines(db, volume.id, int(unit["index"]), ai)
    return True
