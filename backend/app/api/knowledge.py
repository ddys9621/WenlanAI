"""知识库 API：书架 / 条目浏览 / 关键词检索 / 作者修改与核对 / 恢复拆书版本 / 重新导入 / 删除；
项目的仿写参考：对标书与仿写方式 / 按场景预览注入内容 / 查询引用。

用户级、跨项目；所有端点 require_login 并按 user_id 隔离（越权一律 404）。
删除拆书来源 = 删除这本书：转给 book_dissect.delete_task（它会连带删知识库条目与项目对标关联）。
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_login
from app.database import get_db
from app.models.chapter_outline import ChapterOutline
from app.models.knowledge import KbEntry, KbProjectLink, KbSource
from app.models.project import Project
from app.models.volume import Volume
from app.schemas.knowledge import (
    KbCitationOut, KbEntryOut, KbEntrySummaryOut, KbEntryUpdate, KbPreviewIn, KbPreviewOut, KbProjectLinkIn,
    KbProjectLinkOut, KbProjectLinkView, KbRefOut, KbSearchHit, KbSearchOut, KbSourceOut, KbSourceUpdate, KbSourceVolume,
)
from app.services import volume_planning as vp
from app.services.knowledge import kb_query, kb_refs
from app.services.knowledge.kb_context import build_kb_context
from app.services.knowledge.kb_import import (
    delete_source_rows, ensure_dissect_sources, import_dissect_task, regenerate_entry,
)
from app.services.knowledge.kb_links import set_project_link
from app.user_manager import User

router = APIRouter(prefix="/knowledge", tags=["知识库"])
project_router = APIRouter(prefix="/projects/{project_id}/knowledge", tags=["项目仿写参考"])


def _loads(raw: Optional[str], default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _source_out(source: KbSource, counts: dict[str, int]) -> KbSourceOut:
    return KbSourceOut(
        id=source.id, kind=source.kind, title=source.title, author=source.author, genre=source.genre,
        dissect_task_id=source.dissect_task_id, chapter_count=source.chapter_count or 0,
        total_words=source.total_words or 0, notes=source.notes, entry_counts=counts,
        created_at=source.created_at, updated_at=source.updated_at,
    )


def _summary_fields(entry: KbEntry) -> dict[str, Any]:
    return dict(
        id=entry.id, source_id=entry.source_id, entry_key=entry.entry_key, entry_type=entry.entry_type,
        layer=entry.layer, title=entry.title, summary=entry.summary, chapter_start=entry.chapter_start,
        chapter_end=entry.chapter_end, volume_index=entry.volume_index, arc_index=entry.arc_index,
        origin=entry.origin, status=entry.status, upstream_changed=bool(entry.upstream_changed),
        revision=entry.revision or 1,
    )


def _entry_out(entry: KbEntry) -> KbEntryOut:
    return KbEntryOut(**_summary_fields(entry), body=entry.body or "", denamed_body=entry.denamed_body or "",
                      data=_loads(entry.data_json, {}), tags=_loads(entry.tags, []), position=entry.position)


async def _require_source(db: AsyncSession, user: User, source_id: str) -> KbSource:
    source = await kb_query.get_source(db, user.user_id, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="知识库来源不存在或无权访问")
    return source


async def _require_entry(db: AsyncSession, user: User, entry_id: str) -> KbEntry:
    entry = await kb_query.get_entry(db, user.user_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="知识库条目不存在或无权访问")
    return entry


async def _source_response(db: AsyncSession, source: KbSource) -> KbSourceOut:
    counts = await kb_query.entry_counts(db, [source.id])
    return _source_out(source, counts.get(source.id, {}))


@router.get("/sources", response_model=List[KbSourceOut], summary="书架：当前用户的全部来源（先补导已完成的拆书）")
async def list_sources(user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await ensure_dissect_sources(db, user.user_id)
    sources = await kb_query.list_sources(db, user.user_id)
    counts = await kb_query.entry_counts(db, [s.id for s in sources])
    return [_source_out(s, counts.get(s.id, {})) for s in sources]


@router.get("/sources/{source_id}", response_model=KbSourceOut)
async def get_source(source_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    return await _source_response(db, await _require_source(db, user, source_id))


@router.patch("/sources/{source_id}", response_model=KbSourceOut)
async def update_source(source_id: str, payload: KbSourceUpdate, user: User = Depends(require_login),
                        db: AsyncSession = Depends(get_db)):
    source = await _require_source(db, user, source_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    await db.commit()
    await db.refresh(source)
    return await _source_response(db, source)


@router.delete("/sources/{source_id}", summary="删除来源（拆书来源连同拆书任务一起删除）")
async def delete_source(source_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    source = await _require_source(db, user, source_id)
    if source.dissect_task_id:
        from app.api import book_dissect
        try:
            await book_dissect.delete_task(source.dissect_task_id, user=user, db=db)
            return {"deleted": source_id}
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    await delete_source_rows(db, [source.id])
    await db.commit()
    return {"deleted": source_id}


@router.post("/sources/{source_id}/reimport", response_model=KbSourceOut, summary="按最新拆书结果重新导入")
async def reimport_source(source_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    source = await _require_source(db, user, source_id)
    if not source.dissect_task_id:
        raise HTTPException(status_code=400, detail="这个来源不是拆书产出，没有可重新导入的拆书结果")
    if await import_dissect_task(db, source.dissect_task_id, user.user_id) is None:
        raise HTTPException(status_code=409, detail="拆书结果不存在或尚未完成")
    await db.refresh(source)
    return await _source_response(db, source)


@router.get("/sources/{source_id}/entries", response_model=List[KbEntrySummaryOut])
async def list_entries(source_id: str, entry_type: Optional[str] = Query(None), user: User = Depends(require_login),
                       db: AsyncSession = Depends(get_db)):
    await _require_source(db, user, source_id)
    return [KbEntrySummaryOut(**_summary_fields(e)) for e in await kb_query.list_entries(db, source_id, entry_type)]


@router.get("/entries/{entry_id}", response_model=KbEntryOut)
async def get_entry(entry_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    return _entry_out(await _require_entry(db, user, entry_id))


@router.patch("/entries/{entry_id}", response_model=KbEntryOut, summary="作者修改（保存为作者版本，重新拆书不覆盖）")
async def update_entry(entry_id: str, payload: KbEntryUpdate, user: User = Depends(require_login),
                       db: AsyncSession = Depends(get_db)):
    entry = await _require_entry(db, user, entry_id)
    if kb_query.update_entry(entry, **payload.model_dump(exclude_unset=True)):
        await db.commit()
    return _entry_out(entry)


@router.post("/entries/{entry_id}/confirm", response_model=KbEntryOut, summary="标记已核对")
async def confirm_entry(entry_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    entry = await _require_entry(db, user, entry_id)
    entry.status = "confirmed"
    await db.commit()
    return _entry_out(entry)


@router.post("/entries/{entry_id}/reset", response_model=KbEntryOut, summary="恢复成拆书生成的版本（覆盖作者修改）")
async def reset_entry(entry_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    entry = await _require_entry(db, user, entry_id)
    if not await regenerate_entry(db, entry):
        raise HTTPException(status_code=409, detail="拆书结果里已经没有这一条，无法恢复；可以保留作者版本")
    await db.commit()
    return _entry_out(entry)


@router.get("/search", response_model=KbSearchOut, summary="关键词检索（空格分隔，每个词都要命中）")
async def search(
    q: str = Query(..., min_length=1, max_length=200), source_id: Optional[str] = Query(None),
    entry_type: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(require_login), db: AsyncSession = Depends(get_db),
):
    rows, total = await kb_query.search_entries(db, user.user_id, q, source_id=source_id, entry_type=entry_type,
                                                limit=limit, offset=offset)
    titles = {s.id: s.title for s in await kb_query.list_sources(db, user.user_id)}
    return KbSearchOut(
        items=[KbSearchHit(**_summary_fields(e), source_title=titles.get(e.source_id, "")) for e in rows], total=total,
    )


# ---------------- 项目的仿写参考 ----------------

async def _require_project(db: AsyncSession, user: User, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    return project


async def _link_out(db: AsyncSession, link: KbProjectLink) -> Optional[KbProjectLinkOut]:
    source = await db.get(KbSource, link.source_id)
    if source is None:
        return None
    volumes = (await db.execute(
        select(KbEntry).where(KbEntry.source_id == source.id, KbEntry.entry_type == "volume").order_by(KbEntry.sort_order)
    )).scalars().all()
    chapters = (await db.execute(
        select(KbEntry.chapter_start).where(KbEntry.source_id == source.id, KbEntry.entry_type == "chapter")
    )).scalars().all()
    numbers = [n for n in chapters if n]
    return KbProjectLinkOut(
        source_id=source.id, source_title=source.title, mode=link.mode, volume_map=_loads(link.volume_map, {}),
        source_chapter_count=source.chapter_count or 0,
        source_volumes=[KbSourceVolume(index=v.volume_index, title=v.title, chapter_start=v.chapter_start,
                                       chapter_end=v.chapter_end) for v in volumes if v.volume_index],
        dissected_range=[min(numbers), max(numbers)] if numbers else None,
    )


@project_router.get("", response_model=KbProjectLinkView, summary="项目的对标书与仿写方式")
async def get_project_link(project_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await _require_project(db, user, project_id)
    link = await db.get(KbProjectLink, project_id)
    return KbProjectLinkView(link=await _link_out(db, link) if link is not None else None)


@project_router.put("", response_model=KbProjectLinkOut, summary="设置对标书与仿写方式")
async def put_project_link(project_id: str, payload: KbProjectLinkIn, user: User = Depends(require_login),
                           db: AsyncSession = Depends(get_db)):
    await _require_project(db, user, project_id)
    link = await set_project_link(db, user.user_id, project_id, payload.source_id, mode=payload.mode,
                                  volume_map=payload.volume_map)
    if link is None:
        raise HTTPException(status_code=404, detail="知识库来源不存在或无权访问")
    await db.commit()
    return await _link_out(db, link)


@project_router.delete("", summary="取消对标（生成时不再注入仿写参考）")
async def delete_project_link(project_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await _require_project(db, user, project_id)
    link = await db.get(KbProjectLink, project_id)
    if link is not None:
        await db.delete(link)
        await db.commit()
    return {"deleted": link is not None}


@project_router.post("/preview", response_model=KbPreviewOut, summary="预览某个场景会注入的仿写参考")
async def preview_project_context(project_id: str, payload: KbPreviewIn, user: User = Depends(require_login),
                                  db: AsyncSession = Depends(get_db)):
    await _require_project(db, user, project_id)
    volume = unit = outline = None
    if payload.volume_id:
        volume = await db.get(Volume, payload.volume_id)
        if volume is None or volume.project_id != project_id:
            raise HTTPException(status_code=404, detail="卷纲不存在")
        if payload.unit_index is not None:
            unit = next((u for u in vp.loads_units(volume.units) if int(u.get("index") or 0) == payload.unit_index), None)
            if unit is None:
                raise HTTPException(status_code=404, detail="剧情单元不存在")
    if payload.chapter_outline_id:
        outline = await db.get(ChapterOutline, payload.chapter_outline_id)
        if outline is None or outline.project_id != project_id:
            raise HTTPException(status_code=404, detail="章纲不存在")
    ctx = await build_kb_context(db, project_id, payload.scene, volume=volume, unit=unit, outline=outline,
                                 kb_chapter=payload.kb_chapter)
    return KbPreviewOut(
        scene=ctx.scene, mode=ctx.mode, text=ctx.text, style=ctx.style, ref_instruction=ctx.ref_instruction,
        refs=[KbRefOut(key=r.key, entry_id=r.entry_id, entry_type=r.entry_type, label=r.label,
                       prompt_label=r.prompt_label, reason=r.reason) for r in ctx.refs.values()],
    )


@project_router.get("/citations", response_model=dict[str, List[KbCitationOut]], summary="查询生成结果的对标引用")
async def project_citations(
    project_id: str, target_type: str = Query(..., pattern="^(volume|unit|chapter_outline|chapter_candidate)$"),
    target_ids: str = Query("", max_length=20000), user: User = Depends(require_login), db: AsyncSession = Depends(get_db),
):
    await _require_project(db, user, project_id)
    ids = [t.strip() for t in target_ids.split(",") if t.strip()][:500]
    return await kb_refs.citations_for(db, project_id, target_type, ids)
