"""章纲 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, distinct
from typing import List, Optional
import json

from app.database import get_db
from app.logger import get_logger

logger = get_logger(__name__)
from app.models import (
    ChapterOutline, Project, PlotLine, PlotCard,
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


@router.get("/project/{project_id}", response_model=ChapterOutlineListResponse)
async def get_chapter_outlines(
    project_id: str,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(100, ge=1, le=100, description="限制数量"),
    plot_line_id: Optional[str] = Query(None, description="剧情线ID筛选"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目的章纲列表"""
    
    # 构建查询
    query = select(ChapterOutline).where(ChapterOutline.project_id == project_id)
    
    # 如果指定了剧情线ID，通过关联表筛选
    if plot_line_id:
        query = query.join(
            ChapterOutlinePlotLineLink,
            ChapterOutline.id == ChapterOutlinePlotLineLink.chapter_outline_id
        ).where(ChapterOutlinePlotLineLink.plot_line_id == plot_line_id)
    
    # 按章节号排序
    query = query.order_by(ChapterOutline.chapter_number.asc(), ChapterOutline.order_index.asc())
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页查询
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    outlines = result.scalars().all()
    
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
    
    # 构建响应数据，添加关联统计信息
    response_outlines = []
    for outline in outlines:
        # 处理 JSON 字段
        key_events = []
        if outline.key_events:
            try:
                parsed_events = json.loads(outline.key_events)
                # 转换为字符串列表：如果是字典列表，提取描述；如果是字符串列表，直接使用
                if isinstance(parsed_events, list):
                    key_events = []
                    for event in parsed_events:
                        if isinstance(event, dict):
                            # 字典格式，提取描述或标题
                            event_desc = event.get('description', event.get('title', str(event)))
                            key_events.append(event_desc)
                        else:
                            # 字符串格式，直接使用
                            key_events.append(str(event))
                else:
                    key_events = [str(parsed_events)] if parsed_events else []
            except:
                key_events = []
        
        characters_involved = []
        if outline.characters_involved:
            try:
                parsed_characters = json.loads(outline.characters_involved)
                # 转换为字符串列表：如果是字典列表，提取名称；如果是字符串列表，直接使用
                if isinstance(parsed_characters, list):
                    characters_involved = []
                    for char in parsed_characters:
                        if isinstance(char, dict):
                            # 字典格式，提取名称
                            char_name = char.get('name', str(char))
                            characters_involved.append(char_name)
                        else:
                            # 字符串格式，直接使用
                            characters_involved.append(str(char))
                else:
                    characters_involved = [str(parsed_characters)] if parsed_characters else []
            except:
                characters_involved = []
        
        plot_line_count = plot_line_counts.get(outline.id, 0)
        plot_card_count = plot_card_counts.get(outline.id, 0)
        
        # 创建统一的响应对象
        response_outline = ChapterOutlineResponse(
            id=outline.id,
            project_id=outline.project_id,
            plot_line_id=None,  # 章纲模型中没有这个字段
            chapter_number=outline.chapter_number,
            title=outline.title,
            scene=outline.scene,  # ✅ 补上场景字段
            pov=outline.pov,      # ✅ 补上视角字段
            summary=outline.summary,
            plot_points=outline.plot_points,
            target_word_count=outline.target_word_count,
            order_index=outline.order_index,
            key_events=key_events,
            characters_involved=characters_involved,
            created_at=outline.created_at,
            updated_at=outline.updated_at,
            # 统一的关联统计
            plot_line_count=plot_line_count,
            plot_card_count=plot_card_count
        )
        
        response_outlines.append(response_outline)
    
    return ChapterOutlineListResponse(total=total, items=response_outlines)


@router.get("/{outline_id}", response_model=ChapterOutlineResponse)
async def get_chapter_outline(outline_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个章纲"""
    
    result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="章纲不存在")
    
    db.expunge(outline)
    if outline.key_events:
        try:
            outline.key_events = json.loads(outline.key_events)
        except:
            outline.key_events = []
    else:
        outline.key_events = []
        
    if outline.characters_involved:
        try:
            outline.characters_involved = json.loads(outline.characters_involved)
        except:
            outline.characters_involved = []
    else:
        outline.characters_involved = []
    
    return outline


@router.post("", response_model=ChapterOutlineResponse)
async def create_chapter_outline(outline_data: ChapterOutlineCreate, db: AsyncSession = Depends(get_db)):
    """创建章纲"""
    
    # 验证项目存在
    project_result = await db.execute(select(Project).where(Project.id == outline_data.project_id))
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查章节号是否已存在
    existing_result = await db.execute(
        select(ChapterOutline).where(
            ChapterOutline.project_id == outline_data.project_id,
            ChapterOutline.chapter_number == outline_data.chapter_number
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"第{outline_data.chapter_number}章章纲已存在")
    
    # 如果没有指定排序序号，自动设置为最大值+1
    if outline_data.order_index is None:
        max_order_result = await db.execute(
            select(func.max(ChapterOutline.order_index)).where(ChapterOutline.project_id == outline_data.project_id)
        )
        max_order = max_order_result.scalar() or 0
        outline_data.order_index = max_order + 1
    
    # 处理 JSON 字段
    key_events_json = None
    if outline_data.key_events:
        key_events_json = json.dumps(outline_data.key_events, ensure_ascii=False)
    
    characters_involved_json = None
    if outline_data.characters_involved:
        characters_involved_json = json.dumps(outline_data.characters_involved, ensure_ascii=False)
    
    # 创建章纲（专业网文版）
    outline = ChapterOutline(
        project_id=outline_data.project_id,
        chapter_number=outline_data.chapter_number,
        title=outline_data.title,
        # 场景信息（新增）
        scene=outline_data.scene,
        pov=outline_data.pov,
        # 剧情信息
        plot_points=outline_data.plot_points,
        key_events=key_events_json,
        characters_involved=characters_involved_json,
        # 旧字段（保留兼容）
        summary=outline_data.summary,
        # 系统字段
        target_word_count=outline_data.target_word_count,
        order_index=outline_data.order_index
    )

    db.add(outline)
    await db.commit()
    await db.refresh(outline)

    # 如果指定了剧情线ID，创建关联
    if outline_data.plot_line_id:
        link = ChapterOutlinePlotLineLink(
            chapter_outline_id=outline.id,
            plot_line_id=outline_data.plot_line_id,
            role="main"
        )
        db.add(link)
        await db.commit()
    
    db.expunge(outline)
    if outline.key_events:
        try:
            outline.key_events = json.loads(outline.key_events)
        except:
            outline.key_events = []
    else:
        outline.key_events = []
        
    if outline.characters_involved:
        try:
            outline.characters_involved = json.loads(outline.characters_involved)
        except:
            outline.characters_involved = []
    else:
        outline.characters_involved = []
    
    return outline


@router.put("/{outline_id}", response_model=ChapterOutlineResponse)
async def update_chapter_outline(
    outline_id: str, 
    outline_data: ChapterOutlineUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """更新章纲"""
    
    # 检查章纲是否存在
    result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="章纲不存在")
    
    # 如果要更新章节号，检查是否冲突
    if outline_data.chapter_number and outline_data.chapter_number != outline.chapter_number:
        existing_result = await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.project_id == outline.project_id,
                ChapterOutline.chapter_number == outline_data.chapter_number,
                ChapterOutline.id != outline_id
            )
        )
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"第{outline_data.chapter_number}章章纲已存在")
    
    # 更新字段
    update_data = outline_data.model_dump(exclude_unset=True)
    
    # 处理 JSON 字段
    if "key_events" in update_data and update_data["key_events"] is not None:
        update_data["key_events"] = json.dumps(update_data["key_events"], ensure_ascii=False)
    
    if "characters_involved" in update_data and update_data["characters_involved"] is not None:
        update_data["characters_involved"] = json.dumps(update_data["characters_involved"], ensure_ascii=False)
    
    if update_data:
        await db.execute(
            update(ChapterOutline).where(ChapterOutline.id == outline_id).values(**update_data)
        )
        await db.commit()
        await db.refresh(outline)
    
    db.expunge(outline)
    if outline.key_events:
        try:
            outline.key_events = json.loads(outline.key_events)
        except:
            outline.key_events = []
    else:
        outline.key_events = []
        
    if outline.characters_involved:
        try:
            outline.characters_involved = json.loads(outline.characters_involved)
        except:
            outline.characters_involved = []
    else:
        outline.characters_involved = []
    
    return outline


@router.delete("/{outline_id}")
async def delete_chapter_outline(outline_id: str, db: AsyncSession = Depends(get_db)):
    """删除章纲"""
    
    # 检查章纲是否存在
    result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="章纲不存在")
    
    await db.execute(delete(ChapterOutline).where(ChapterOutline.id == outline_id))
    await db.commit()
    
    return {"message": "章纲删除成功"}


@router.post("/reorder")
async def reorder_chapter_outlines(
    reorder_data: ChapterOutlineReorderRequest, 
    db: AsyncSession = Depends(get_db)
):
    """重排序章纲"""
    
    for order_item in reorder_data.orders:
        outline_id = order_item.get("id")
        new_order = order_item.get("order_index")
        new_chapter_number = order_item.get("chapter_number")
        
        if outline_id and new_order is not None:
            update_values = {"order_index": new_order}
            if new_chapter_number is not None:
                update_values["chapter_number"] = new_chapter_number
            
            await db.execute(
                update(ChapterOutline)
                .where(ChapterOutline.id == outline_id)
                .values(**update_values)
            )
    
    await db.commit()
    
    return {"message": "章纲排序更新成功"}


@router.post("/batch", response_model=List[ChapterOutlineResponse])
async def batch_create_chapter_outlines(
    batch_data: ChapterOutlineBatchCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量创建章纲"""
    
    # 验证项目存在
    project_result = await db.execute(select(Project).where(Project.id == batch_data.project_id))
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    
    created_outlines = []
    
    for outline_data in batch_data.outlines:
        # 检查章节号是否已存在
        existing_result = await db.execute(
            select(ChapterOutline).where(
                ChapterOutline.project_id == batch_data.project_id,
                ChapterOutline.chapter_number == outline_data.chapter_number
            )
        )
        if existing_result.scalar_one_or_none():
            continue  # 跳过已存在的章节
        
        # 处理 JSON 字段
        key_events_json = None
        if outline_data.key_events:
            key_events_json = json.dumps(outline_data.key_events, ensure_ascii=False)
        
        characters_involved_json = None
        if outline_data.characters_involved:
            characters_involved_json = json.dumps(outline_data.characters_involved, ensure_ascii=False)
        
        # 创建章纲（专业网文版）
        outline = ChapterOutline(
            project_id=batch_data.project_id,
            chapter_number=outline_data.chapter_number,
            title=outline_data.title,
            # 场景信息（新增）
            scene=outline_data.scene,
            pov=outline_data.pov,
            # 剧情信息
            plot_points=outline_data.plot_points,
            key_events=key_events_json,
            characters_involved=characters_involved_json,
            # 旧字段（保留兼容）
            summary=outline_data.summary,
            # 系统字段
            target_word_count=outline_data.target_word_count,
            order_index=outline_data.order_index
        )

        db.add(outline)
        created_outlines.append(outline)

    await db.commit()

    # 如果指定了剧情线ID，为所有章纲创建关联
    if batch_data.plot_line_id:
        for outline in created_outlines:
            await db.refresh(outline)
            link = ChapterOutlinePlotLineLink(
                chapter_outline_id=outline.id,
                plot_line_id=batch_data.plot_line_id,
                role="main"
            )
            db.add(link)
        await db.commit()

    # 刷新并处理返回数据（脱离会话后再修改，避免 autoflush 类型错误）
    for outline in created_outlines:
        await db.refresh(outline)
    
    for outline in created_outlines:
        db.expunge(outline)
        
        if outline.key_events:
            try:
                outline.key_events = json.loads(outline.key_events)
            except:
                outline.key_events = []
        else:
            outline.key_events = []
            
        if outline.characters_involved:
            try:
                outline.characters_involved = json.loads(outline.characters_involved)
            except:
                outline.characters_involved = []
        else:
            outline.characters_involved = []
    
    return created_outlines


@router.get("/project/{project_id}/statistics")
async def get_chapter_outline_statistics(project_id: str, db: AsyncSession = Depends(get_db)):
    """获取项目章纲统计信息"""
    
    # 总章纲数
    total_result = await db.execute(
        select(func.count(ChapterOutline.id)).where(ChapterOutline.project_id == project_id)
    )
    total_count = total_result.scalar()
    
    # 按剧情线分组统计（通过关联表）
    line_stats_result = await db.execute(
        select(
            ChapterOutlinePlotLineLink.plot_line_id,
            func.count(distinct(ChapterOutline.id)).label('count'),
            func.sum(ChapterOutline.target_word_count).label('total_words')
        )
        .join(ChapterOutline, ChapterOutline.id == ChapterOutlinePlotLineLink.chapter_outline_id)
        .where(ChapterOutline.project_id == project_id)
        .group_by(ChapterOutlinePlotLineLink.plot_line_id)
    )

    line_stats = line_stats_result.all()

    # 总目标字数
    total_words_result = await db.execute(
        select(func.sum(ChapterOutline.target_word_count)).where(ChapterOutline.project_id == project_id)
    )
    total_target_words = total_words_result.scalar() or 0

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
async def get_chapter_outline_plot_lines(
    outline_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取章纲关联的所有剧情线"""
    
    # 检查章纲是否存在
    outline_result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = outline_result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="章纲不存在")
    
    # 查询关联的剧情线（包含link_id和timeline_coverage）
    query = select(
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

    result = await db.execute(query)
    rows = result.all()

    # 构建响应
    plot_lines = []
    for row in rows:
        line = row[0]
        link_id = row[2]  # 获取link_id
        timeline_coverage_str = row[3]  # 获取timeline_coverage

        # 获取该剧情线关联的章纲数量
        chapter_count_result = await db.execute(
            select(func.count()).select_from(ChapterOutlinePlotLineLink)
            .where(ChapterOutlinePlotLineLink.plot_line_id == line.id)
        )
        chapter_count = chapter_count_result.scalar() or 0

        # 获取该剧情线关联的剧情卡片数量
        card_count_result = await db.execute(
            select(func.count()).select_from(PlotCardPlotLineLink)
            .where(PlotCardPlotLineLink.plot_line_id == line.id)
        )
        card_count = card_count_result.scalar() or 0

        # 解析timeline_data
        timeline_data = None
        if line.timeline_data:
            try:
                timeline_data = json.loads(line.timeline_data) if isinstance(line.timeline_data, str) else line.timeline_data
            except (json.JSONDecodeError, TypeError):
                timeline_data = None

        # 解析timeline_coverage
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
            link_id=link_id,  # 添加link_id
            timeline_data=timeline_data,  # 添加timeline_data
            timeline_coverage=timeline_coverage  # 添加timeline_coverage
        ))

    return plot_lines


@router.get("/{outline_id}/plot-cards", response_model=List[PlotCardWithLinks])
async def get_chapter_outline_plot_cards(
    outline_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取章纲关联的所有剧情卡片"""
    
    # 检查章纲是否存在
    outline_result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = outline_result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="章纲不存在")
    
    # 查询关联的剧情卡片
    query = select(
        PlotCard,
        PlotCardChapterOutlineLink.usage_type
    ).join(
        PlotCardChapterOutlineLink,
        PlotCard.id == PlotCardChapterOutlineLink.plot_card_id
    ).where(
        PlotCardChapterOutlineLink.chapter_outline_id == outline_id
    ).order_by(PlotCard.order_index.asc())
    
    result = await db.execute(query)
    rows = result.all()
    
    # 构建响应
    plot_cards = []
    for row in rows:
        card = row[0]
        
        # 获取该卡片关联的剧情线数量
        line_count_result = await db.execute(
            select(func.count()).select_from(PlotCardPlotLineLink)
            .where(PlotCardPlotLineLink.plot_card_id == card.id)
        )
        line_count = line_count_result.scalar() or 0
        
        # 获取该卡片关联的章纲数量
        chapter_count_result = await db.execute(
            select(func.count()).select_from(PlotCardChapterOutlineLink)
            .where(PlotCardChapterOutlineLink.plot_card_id == card.id)
        )
        chapter_count = chapter_count_result.scalar() or 0
        
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
    request: LinkPlotLinesToChapterRequest,
    db: AsyncSession = Depends(get_db)
):
    """将剧情线关联到章纲"""
    
    # 检查章纲是否存在
    outline_result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = outline_result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail=f"章纲不存在: {outline_id}")
    
    # 验证剧情线存在且属于同一项目（跨项目校验）
    lines_result = await db.execute(
        select(PlotLine).where(
            PlotLine.id.in_(request.plot_line_ids),
            PlotLine.project_id == outline.project_id  # 添加项目归属校验
        )
    )
    existing_lines = {line.id: line for line in lines_result.scalars().all()}
    
    # 检查是否有无效的ID
    invalid_ids = set(request.plot_line_ids) - set(existing_lines.keys())
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"以下剧情线不存在或不属于该项目: {', '.join(list(invalid_ids)[:5])}"
        )
    
    # 创建关联
    created_count = 0
    skipped_count = 0
    
    for plot_line_id in request.plot_line_ids:
        # 检查是否已存在关联
        existing_link = await db.execute(
            select(ChapterOutlinePlotLineLink).where(
                ChapterOutlinePlotLineLink.chapter_outline_id == outline_id,
                ChapterOutlinePlotLineLink.plot_line_id == plot_line_id
            )
        )
        
        if existing_link.scalar_one_or_none():
            skipped_count += 1
            continue  # 跳过已存在的关联
        
        # 创建新关联
        new_link = ChapterOutlinePlotLineLink(
            chapter_outline_id=outline_id,
            plot_line_id=plot_line_id,
            role=request.role
        )
        db.add(new_link)
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
    request: UnlinkRequest,
    db: AsyncSession = Depends(get_db)
):
    """取消剧情线与章纲的关联"""
    
    # 检查章纲是否存在
    outline_result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == outline_id))
    outline = outline_result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail=f"章纲不存在: {outline_id}")
    
    # 删除关联
    result = await db.execute(
        delete(ChapterOutlinePlotLineLink).where(
            ChapterOutlinePlotLineLink.chapter_outline_id == outline_id,
            ChapterOutlinePlotLineLink.plot_line_id.in_(request.ids)
        )
    )
    
    await db.commit()
    
    return {
        "message": f"成功取消 {result.rowcount} 条剧情线的关联",
        "removed_count": result.rowcount
    }

