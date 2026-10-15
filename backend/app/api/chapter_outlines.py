"""章纲 API 路由（全部校验项目归属：所有用户共用一个数据库，只按 ID 查会越权读写别人的书）"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import Any, List, Optional
import json

from app.api.deps import load_owned, verify_owned_ids, verify_request_project
from app.database import get_db
from app.logger import get_logger
from app.services import outline_review_service as review
from app.services.narrative_tasks import parse_narrative_tasks

logger = get_logger(__name__)
from app.models import ChapterOutline
from app.schemas.chapter_outline import (
    ChapterOutlineCreate, ChapterOutlineUpdate, ChapterOutlineResponse,
    ChapterOutlineReorderRequest,
    ChapterOutlineListResponse, ChapterOutlineBatchCreateRequest
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


def _outline_response(outline: ChapterOutline) -> ChapterOutlineResponse:
    return ChapterOutlineResponse(
        id=outline.id,
        project_id=outline.project_id,
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
        volume_id=outline.volume_id,
        unit_index=outline.unit_index,
        created_at=outline.created_at,
        updated_at=outline.updated_at,
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
    volume_id: Optional[str] = Query(None, description="只看某一卷的章纲"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目的章纲列表"""
    await verify_request_project(request, project_id, db)
    query = select(ChapterOutline).where(ChapterOutline.project_id == project_id)

    if volume_id:
        query = query.where(ChapterOutline.volume_id == volume_id)

    query = query.order_by(ChapterOutline.chapter_number.asc(), ChapterOutline.order_index.asc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    outlines = (await db.execute(query.offset(skip).limit(limit))).scalars().all()
    return ChapterOutlineListResponse(total=total, items=[_outline_response(o) for o in outlines])


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

    fields = _dump_lists(outline_data.model_dump(exclude={"project_id"}))
    outline = ChapterOutline(project_id=outline_data.project_id, review_status=review.CONFIRMED, **fields)
    db.add(outline)
    await db.commit()
    await db.refresh(outline)

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

        fields = _dump_lists(outline_data.model_dump(exclude={"project_id"}))
        outline = ChapterOutline(project_id=batch_data.project_id, review_status=review.CONFIRMED, **fields)
        db.add(outline)
        created_outlines.append(outline)

    await db.commit()

    for outline in created_outlines:
        await db.refresh(outline)
    return [_outline_response(outline) for outline in created_outlines]
