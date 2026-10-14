"""章纲 API 路由（全部校验项目归属：所有用户共用一个数据库，只按 ID 查会越权读写别人的书）"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, distinct
from typing import Any, List, Optional
import json

from app.api.deps import load_owned, verify_owned_ids, verify_request_project
from app.database import get_db
from app.logger import get_logger
from app.services import outline_review_service as review
from app.services.narrative_tasks import parse_narrative_tasks

logger = get_logger(__name__)
from app.models import (
    ChapterOutline, PlotLine, PlotCard,
    ChapterOutlinePlotLineLink, PlotCardChapterOutlineLink, PlotCardPlotLineLink
)
from app.schemas.chapter_outline import (
    ChapterOutlineCreate, ChapterOutlineUpdate, ChapterOutlineResponse,
    ChapterOutlineReorderRequest,
    ChapterOutlineListResponse, ChapterOutlineBatchCreateRequest
)
from app.schemas.link_schemas import (
    PlotLineWithLinks, PlotCardWithLinks,
    LinkPlotLinesToChapterRequest, UnlinkRequest
)

router = APIRouter(prefix="/chapter-outlines", tags=["章纲"])

JSON_LIST_FIELDS = ("key_events", "characters_involved", "forbidden")


def _string_list(raw: Any, dict_keys: tuple[str, ...] = ()) -> list[str]:
    """JSON 文本 → 字符串列表；元素是对象时取 dict_keys 里第一个有值的键（兼容旧格式）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return [str(parsed)] if parsed else []
    out = []
    for item in parsed:
        if isinstance(item, dict):
            value = next((item.get(k) for k in dict_keys if item.get(k)), None)
            out.append(str(value if value is not None else item))
        elif str(item).strip():
            out.append(str(item))
    return out


def _outline_response(outline: ChapterOutline, plot_line_count: int = 0, plot_card_count: int = 0) -> ChapterOutlineResponse:
    return ChapterOutlineResponse(
        id=outline.id,
        project_id=outline.project_id,
        plot_line_id=None,  # 章纲模型中没有这个字段
        chapter_number=outline.chapter_number,
        title=outline.title,
        scene=outline.scene,
        pov=outline.pov,
        summary=outline.summary,
        plot_points=outline.plot_points,
        entry_state=outline.entry_state,
        exit_state=outline.exit_state,
        forbidden=_string_list(outline.forbidden),
        target_word_count=outline.target_word_count or 3000,
        order_index=outline.order_index,
        key_events=_string_list(outline.key_events, ("description", "title")),
        characters_involved=_string_list(outline.characters_involved, ("name",)),
        narrative_tasks=parse_narrative_tasks(outline.narrative_tasks) if outline.narrative_tasks else None,
        review_status=outline.review_status or review.CONFIRMED,
        confirmed_at=outline.confirmed_at,
        upstream_stale=bool(outline.upstream_stale),
        upstream_reason=outline.upstream_reason,
        bridge_id=outline.bridge_id,
        bridge_position=outline.bridge_position,
        created_at=outline.created_at,
        updated_at=outline.updated_at,
        plot_line_count=plot_line_count,
        plot_card_count=plot_card_count,
    )


def _dump_lists(data: dict[str, Any]) -> dict[str, Any]:
    for field in JSON_LIST_FIELDS:
        if field in data and data[field] is not None:
            data[field] = json.dumps(data[field], ensure_ascii=False)
    return data


async def _load_outline(db: AsyncSession, request: Request, outline_id: str) -> ChapterOutline:
    return await load_owned(db, request, ChapterOutline, outline_id, not_found=f"章纲不存在: {outline_id}")


@router.get("/project/{project_id}", response_model=ChapterOutlineListResponse)
async def get_chapter_outlines(
    project_id: str,
    request: Request,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(100, ge=1, le=100, description="限制数量"),
    plot_line_id: Optional[str] = Query(None, description="剧情线ID筛选"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目的章纲列表"""
    await verify_request_project(request, project_id, db)
    query = select(ChapterOutline).where(ChapterOutline.project_id == project_id)

    # 如果指定了剧情线ID，通过关联表筛选
    if plot_line_id:
        query = query.join(
            ChapterOutlinePlotLineLink,
            ChapterOutline.id == ChapterOutlinePlotLineLink.chapter_outline_id
        ).where(ChapterOutlinePlotLineLink.plot_line_id == plot_line_id)

    query = query.order_by(ChapterOutline.chapter_number.asc(), ChapterOutline.order_index.asc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    outlines = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    # 关联计数一次 GROUP BY 取齐（此前每行各查 2 次 COUNT，100 章 = 200 条 SQL）
    outline_ids = [o.id for o in outlines]
    plot_line_counts: dict[str, int] = {}
    plot_card_counts: dict[str, int] = {}
    if outline_ids:
        rows = await db.execute(
            select(ChapterOutlinePlotLineLink.chapter_outline_id, func.count(ChapterOutlinePlotLineLink.id))
            .where(ChapterOutlinePlotLineLink.chapter_outline_id.in_(outline_ids))
            .group_by(ChapterOutlinePlotLineLink.chapter_outline_id)
        )
        plot_line_counts = dict(rows.all())
        rows = await db.execute(
            select(PlotCardChapterOutlineLink.chapter_outline_id, func.count(PlotCardChapterOutlineLink.id))
            .where(PlotCardChapterOutlineLink.chapter_outline_id.in_(outline_ids))
            .group_by(PlotCardChapterOutlineLink.chapter_outline_id)
        )
        plot_card_counts = dict(rows.all())

    items = [
        _outline_response(o, plot_line_counts.get(o.id, 0), plot_card_counts.get(o.id, 0))
        for o in outlines
    ]
    return ChapterOutlineListResponse(total=total, items=items)


@router.get("/{outline_id}", response_model=ChapterOutlineResponse)
async def get_chapter_outline(outline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """获取单个章纲"""
    return _outline_response(await _load_outline(db, request, outline_id))


@router.post("", response_model=ChapterOutlineResponse)
async def create_chapter_outline(outline_data: ChapterOutlineCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """创建章纲（作者手建：直接算已确认）"""
    await verify_request_project(request, outline_data.project_id, db)

    # 检查章节号是否已存在
    existing_result = await db.execute(
        select(ChapterOutline).where(
            ChapterOutline.project_id == outline_data.project_id,
            ChapterOutline.chapter_number == outline_data.chapter_number
        )
    )
    if existing_result.scalars().first():
        raise HTTPException(status_code=400, detail=f"第{outline_data.chapter_number}章章纲已存在")

    # 如果没有指定排序序号，自动设置为最大值+1
    if outline_data.order_index is None:
        max_order_result = await db.execute(
            select(func.max(ChapterOutline.order_index)).where(ChapterOutline.project_id == outline_data.project_id)
        )
        outline_data.order_index = (max_order_result.scalar() or 0) + 1

    fields = _dump_lists(outline_data.model_dump(exclude={"project_id", "plot_line_id"}))
    outline = ChapterOutline(project_id=outline_data.project_id, review_status=review.CONFIRMED, **fields)
    db.add(outline)
    await db.commit()
    await db.refresh(outline)

    # 如果指定了剧情线ID，创建关联
    if outline_data.plot_line_id:
        db.add(ChapterOutlinePlotLineLink(chapter_outline_id=outline.id, plot_line_id=outline_data.plot_line_id, role="main"))
        await db.commit()
    return _outline_response(outline)


@router.put("/{outline_id}", response_model=ChapterOutlineResponse)
async def update_chapter_outline(
    outline_id: str,
    outline_data: ChapterOutlineUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新章纲（保存 ≠ 确认：确认状态与上游过期标记不在这里改，走 /confirm）"""
    outline = await _load_outline(db, request, outline_id)

    # 如果要更新章节号，检查是否冲突
    if outline_data.chapter_number and outline_data.chapter_number != outline.chapter_number:
        existing_result = await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.project_id == outline.project_id,
                ChapterOutline.chapter_number == outline_data.chapter_number,
                ChapterOutline.id != outline_id
            )
        )
        if existing_result.scalars().first():
            raise HTTPException(status_code=400, detail=f"第{outline_data.chapter_number}章章纲已存在")

    update_data = _dump_lists(outline_data.model_dump(exclude_unset=True))
    if update_data:
        await db.execute(update(ChapterOutline).where(ChapterOutline.id == outline_id).values(**update_data))
        await db.commit()
        await db.refresh(outline)
    return _outline_response(outline)


@router.post("/{outline_id}/confirm", response_model=ChapterOutlineResponse, summary="确认章纲（清除 AI 草拟 / 上游已改标记）")
async def confirm_chapter_outline(outline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    outline = await _load_outline(db, request, outline_id)
    review.confirm(outline)
    await db.commit()
    await db.refresh(outline)
    return _outline_response(outline)


@router.post("/project/{project_id}/confirm-all", summary="一键确认本项目全部待确认 / 上游已改的章纲")
async def confirm_project_outlines(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await verify_request_project(request, project_id, db)
    count = await review.confirm_project(db, project_id)
    await db.commit()
    return {"confirmed": count}


@router.delete("/{outline_id}")
async def delete_chapter_outline(outline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """删除章纲"""
    await _load_outline(db, request, outline_id)
    await db.execute(delete(ChapterOutline).where(ChapterOutline.id == outline_id))
    await db.commit()
    return {"message": "章纲删除成功"}


@router.post("/reorder")
async def reorder_chapter_outlines(
    reorder_data: ChapterOutlineReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """重排序章纲"""
    await verify_owned_ids(db, request, ChapterOutline, [o.get("id") for o in reorder_data.orders])
    for order_item in reorder_data.orders:
        outline_id = order_item.get("id")
        new_order = order_item.get("order_index")
        new_chapter_number = order_item.get("chapter_number")

        if outline_id and new_order is not None:
            update_values = {"order_index": new_order}
            if new_chapter_number is not None:
                update_values["chapter_number"] = new_chapter_number
            await db.execute(update(ChapterOutline).where(ChapterOutline.id == outline_id).values(**update_values))

    await db.commit()
    return {"message": "章纲排序更新成功"}


@router.post("/batch", response_model=List[ChapterOutlineResponse])
async def batch_create_chapter_outlines(
    batch_data: ChapterOutlineBatchCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """批量创建章纲（作者手建 / 导入：算已确认）"""
    await verify_request_project(request, batch_data.project_id, db)

    created_outlines = []
    for outline_data in batch_data.outlines:
        existing_result = await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.project_id == batch_data.project_id,
                ChapterOutline.chapter_number == outline_data.chapter_number
            )
        )
        if existing_result.scalars().first():
            continue  # 跳过已存在的章节

        fields = _dump_lists(outline_data.model_dump(exclude={"project_id", "plot_line_id"}))
        outline = ChapterOutline(project_id=batch_data.project_id, review_status=review.CONFIRMED, **fields)
        db.add(outline)
        created_outlines.append(outline)

    await db.commit()

    # 如果指定了剧情线ID，为所有章纲创建关联
    if batch_data.plot_line_id:
        for outline in created_outlines:
            await db.refresh(outline)
            db.add(ChapterOutlinePlotLineLink(chapter_outline_id=outline.id, plot_line_id=batch_data.plot_line_id, role="main"))
        await db.commit()

    for outline in created_outlines:
        await db.refresh(outline)
    return [_outline_response(outline) for outline in created_outlines]


@router.get("/project/{project_id}/statistics")
async def get_chapter_outline_statistics(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """获取项目章纲统计信息"""
    await verify_request_project(request, project_id, db)

    total_count = (await db.execute(
        select(func.count(ChapterOutline.id)).where(ChapterOutline.project_id == project_id)
    )).scalar()

    # 按剧情线分组统计（通过关联表）
    line_stats = (await db.execute(
        select(
            ChapterOutlinePlotLineLink.plot_line_id,
            func.count(distinct(ChapterOutline.id)).label('count'),
            func.sum(ChapterOutline.target_word_count).label('total_words')
        )
        .join(ChapterOutline, ChapterOutline.id == ChapterOutlinePlotLineLink.chapter_outline_id)
        .where(ChapterOutline.project_id == project_id)
        .group_by(ChapterOutlinePlotLineLink.plot_line_id)
    )).all()

    total_target_words = (await db.execute(
        select(func.sum(ChapterOutline.target_word_count)).where(ChapterOutline.project_id == project_id)
    )).scalar() or 0

    return {
        "total_count": total_count,
        "total_target_words": total_target_words,
        "line_statistics": [
            {
                "plot_line_id": stat.plot_line_id,
                "chapter_count": stat.count,
                "total_target_words": stat.total_words or 0
            }
            for stat in line_stats
        ]
    }


# ============================================
# 章纲关联管理 API
# ============================================

@router.get("/{outline_id}/plot-lines", response_model=List[PlotLineWithLinks])
async def get_chapter_outline_plot_lines(outline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """获取章纲关联的所有剧情线"""
    await _load_outline(db, request, outline_id)

    rows = (await db.execute(
        select(
            PlotLine,
            ChapterOutlinePlotLineLink.role,
            ChapterOutlinePlotLineLink.id.label('link_id'),
            ChapterOutlinePlotLineLink.timeline_coverage
        ).join(
            ChapterOutlinePlotLineLink,
            PlotLine.id == ChapterOutlinePlotLineLink.plot_line_id
        ).where(
            ChapterOutlinePlotLineLink.chapter_outline_id == outline_id
        ).order_by(ChapterOutlinePlotLineLink.order_index.asc())
    )).all()

    plot_lines = []
    for row in rows:
        line, link_id, timeline_coverage_str = row[0], row[2], row[3]
        chapter_count = (await db.execute(
            select(func.count()).select_from(ChapterOutlinePlotLineLink)
            .where(ChapterOutlinePlotLineLink.plot_line_id == line.id)
        )).scalar() or 0
        card_count = (await db.execute(
            select(func.count()).select_from(PlotCardPlotLineLink)
            .where(PlotCardPlotLineLink.plot_line_id == line.id)
        )).scalar() or 0

        timeline_data = None
        if line.timeline_data:
            try:
                timeline_data = json.loads(line.timeline_data) if isinstance(line.timeline_data, str) else line.timeline_data
            except (json.JSONDecodeError, TypeError):
                timeline_data = None

        timeline_coverage = None
        if timeline_coverage_str:
            try:
                timeline_coverage = json.loads(timeline_coverage_str) if isinstance(timeline_coverage_str, str) else timeline_coverage_str
            except (json.JSONDecodeError, TypeError):
                timeline_coverage = None

        plot_lines.append(PlotLineWithLinks(
            id=line.id,
            title=line.title,
            description=line.description,
            line_type=line.line_type,
            chapter_count=chapter_count,
            card_count=card_count,
            link_id=link_id,
            timeline_data=timeline_data,
            timeline_coverage=timeline_coverage
        ))
    return plot_lines


@router.get("/{outline_id}/plot-cards", response_model=List[PlotCardWithLinks])
async def get_chapter_outline_plot_cards(outline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """获取章纲关联的所有剧情卡片"""
    await _load_outline(db, request, outline_id)

    rows = (await db.execute(
        select(PlotCard, PlotCardChapterOutlineLink.usage_type)
        .join(PlotCardChapterOutlineLink, PlotCard.id == PlotCardChapterOutlineLink.plot_card_id)
        .where(PlotCardChapterOutlineLink.chapter_outline_id == outline_id)
        .order_by(PlotCard.order_index.asc())
    )).all()

    plot_cards = []
    for row in rows:
        card = row[0]
        line_count = (await db.execute(
            select(func.count()).select_from(PlotCardPlotLineLink).where(PlotCardPlotLineLink.plot_card_id == card.id)
        )).scalar() or 0
        chapter_count = (await db.execute(
            select(func.count()).select_from(PlotCardChapterOutlineLink).where(PlotCardChapterOutlineLink.plot_card_id == card.id)
        )).scalar() or 0
        plot_cards.append(PlotCardWithLinks(
            id=card.id,
            title=card.title,
            content=card.content,
            card_type=card.card_type,
            plot_line_count=line_count,
            chapter_count=chapter_count
        ))
    return plot_cards


@router.post("/{outline_id}/link-plot-lines")
async def link_plot_lines_to_chapter_outline(
    outline_id: str,
    body: LinkPlotLinesToChapterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """将剧情线关联到章纲"""
    outline = await _load_outline(db, request, outline_id)

    # 验证剧情线存在且属于同一项目（跨项目校验）
    lines_result = await db.execute(
        select(PlotLine).where(PlotLine.id.in_(body.plot_line_ids), PlotLine.project_id == outline.project_id)
    )
    existing_lines = {line.id: line for line in lines_result.scalars().all()}
    invalid_ids = set(body.plot_line_ids) - set(existing_lines.keys())
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"以下剧情线不存在或不属于该项目: {', '.join(list(invalid_ids)[:5])}"
        )

    created_count = 0
    skipped_count = 0
    for plot_line_id in body.plot_line_ids:
        existing_link = await db.execute(
            select(ChapterOutlinePlotLineLink).where(
                ChapterOutlinePlotLineLink.chapter_outline_id == outline_id,
                ChapterOutlinePlotLineLink.plot_line_id == plot_line_id
            )
        )
        if existing_link.scalar_one_or_none():
            skipped_count += 1
            continue
        db.add(ChapterOutlinePlotLineLink(chapter_outline_id=outline_id, plot_line_id=plot_line_id, role=body.role))
        created_count += 1

    await db.commit()
    return {
        "message": f"成功关联 {created_count} 条剧情线到章纲",
        "created_count": created_count,
        "skipped_count": skipped_count
    }


@router.delete("/{outline_id}/unlink-plot-lines")
async def unlink_plot_lines_from_chapter_outline(
    outline_id: str,
    body: UnlinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """取消剧情线与章纲的关联"""
    await _load_outline(db, request, outline_id)
    result = await db.execute(
        delete(ChapterOutlinePlotLineLink).where(
            ChapterOutlinePlotLineLink.chapter_outline_id == outline_id,
            ChapterOutlinePlotLineLink.plot_line_id.in_(body.ids)
        )
    )
    await db.commit()
    return {
        "message": f"成功取消 {result.rowcount} 条剧情线的关联",
        "removed_count": result.rowcount
    }
