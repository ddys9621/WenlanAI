"""剧情卡片 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import Any, Dict, List, Optional
import json

from app.database import get_db
from app.models import (
    PlotCard, Project, PlotLine, ChapterOutline,
    PlotCardPlotLineLink, PlotCardChapterOutlineLink, ChapterOutlinePlotLineLink
)
from app.schemas.plot_card import (
    PlotCardCreate, PlotCardUpdate, PlotCardResponse, 
    PlotCardGenerateRequest, PlotCardReorderRequest, PlotCardListResponse
)
from app.schemas.link_schemas import (
    PlotCardPlotLineLinkBatch, PlotCardChapterOutlineLinkBatch,
    PlotLineWithLinks, ChapterOutlineWithLinks, UnlinkRequest
)
from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_project_access
from app.services.ai_jobs import AIJob, AIJobConflictError, Runner, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.plot_generation_service import PlotGenerationService
from app.api.settings import get_user_ai_service
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/plot-cards", tags=["剧情卡片"])


@router.get("/project/{project_id}", response_model=PlotCardListResponse)
async def get_plot_cards(
    project_id: str,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(100, ge=1, le=100, description="限制数量"),
    card_type: Optional[str] = Query(None, description="卡片类型筛选"),
    chapter_outline_id: Optional[str] = Query(None, description="按章纲筛选"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目的剧情卡片列表"""
    
    # 构建查询
    query = select(PlotCard).where(PlotCard.project_id == project_id)
    
    if card_type:
        query = query.where(PlotCard.card_type == card_type)
    
    # 如果指定了章纲ID，通过关联表筛选
    if chapter_outline_id:
        query = query.join(
            PlotCardChapterOutlineLink,
            PlotCard.id == PlotCardChapterOutlineLink.plot_card_id
        ).where(PlotCardChapterOutlineLink.chapter_outline_id == chapter_outline_id)
    
    # 按排序序号排序
    query = query.order_by(PlotCard.order_index.asc(), PlotCard.created_at.asc())
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页查询
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    cards = result.scalars().all()
    
    # 关联计数一次 GROUP BY 取齐（此前每行各查 2 次 COUNT）
    card_ids = [c.id for c in cards]
    plot_line_counts: dict[str, int] = {}
    chapter_outline_counts: dict[str, int] = {}
    if card_ids:
        rows = await db.execute(
            select(PlotCardPlotLineLink.plot_card_id, func.count(PlotCardPlotLineLink.id))
            .where(PlotCardPlotLineLink.plot_card_id.in_(card_ids))
            .group_by(PlotCardPlotLineLink.plot_card_id)
        )
        plot_line_counts = dict(rows.all())
        rows = await db.execute(
            select(PlotCardChapterOutlineLink.plot_card_id, func.count(PlotCardChapterOutlineLink.id))
            .where(PlotCardChapterOutlineLink.plot_card_id.in_(card_ids))
            .group_by(PlotCardChapterOutlineLink.plot_card_id)
        )
        chapter_outline_counts = dict(rows.all())
    
    # 构建响应数据，添加关联统计信息
    response_cards = []
    for card in cards:
        # 处理 tags 字段
        tags = []
        if card.tags:
            try:
                tags = json.loads(card.tags)
            except:
                tags = []
        
        plot_line_count = plot_line_counts.get(card.id, 0)
        chapter_outline_count = chapter_outline_counts.get(card.id, 0)
        
        # 创建统一的响应对象
        response_card = PlotCardResponse(
            id=card.id,
            project_id=card.project_id,
            outline_id=None,  # 剧情卡片模型中没有这个字段
            chapter_outline_id=None,  # 剧情卡片模型中没有这个字段
            title=card.title,
            content=card.content,
            card_type=card.card_type,
            order_index=card.order_index,
            tags=tags,
            created_at=card.created_at,
            updated_at=card.updated_at,
            # 统一的关联统计
            plot_line_count=plot_line_count,
            chapter_outline_count=chapter_outline_count
        )
        
        response_cards.append(response_card)
    
    return PlotCardListResponse(total=total, items=response_cards)


@router.get("/{card_id}", response_model=PlotCardResponse)
async def get_plot_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个剧情卡片"""
    
    result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")
    
    # 处理 tags 字段
    if card.tags:
        try:
            card.tags = json.loads(card.tags)
        except:
            card.tags = []
    else:
        card.tags = []
    
    return card


@router.post("", response_model=PlotCardResponse)
async def create_plot_card(card_data: PlotCardCreate, db: AsyncSession = Depends(get_db)):
    """创建剧情卡片"""
    
    # 验证项目存在
    project_result = await db.execute(select(Project).where(Project.id == card_data.project_id))
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 如果没有指定排序序号，自动设置为最大值+1
    if card_data.order_index is None:
        max_order_result = await db.execute(
            select(func.max(PlotCard.order_index)).where(PlotCard.project_id == card_data.project_id)
        )
        max_order = max_order_result.scalar() or 0
        card_data.order_index = max_order + 1
    
    # 处理 tags 字段
    tags_json = None
    if card_data.tags:
        tags_json = json.dumps(card_data.tags, ensure_ascii=False)
    
    # 创建卡片
    card = PlotCard(
        project_id=card_data.project_id,
        title=card_data.title,
        content=card_data.content,
        card_type=card_data.card_type,
        order_index=card_data.order_index,
        tags=tags_json
    )
    
    db.add(card)
    await db.commit()
    await db.refresh(card)
    
    # 处理返回的 tags 字段
    if card.tags:
        try:
            card.tags = json.loads(card.tags)
        except:
            card.tags = []
    else:
        card.tags = []
    
    return card


@router.put("/{card_id}", response_model=PlotCardResponse)
async def update_plot_card(
    card_id: str, 
    card_data: PlotCardUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """更新剧情卡片"""
    
    # 检查卡片是否存在
    result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")
    
    # 更新字段
    update_data = card_data.model_dump(exclude_unset=True)
    
    # 处理 tags 字段
    if "tags" in update_data and update_data["tags"] is not None:
        update_data["tags"] = json.dumps(update_data["tags"], ensure_ascii=False)
    
    if update_data:
        await db.execute(
            update(PlotCard).where(PlotCard.id == card_id).values(**update_data)
        )
        await db.commit()
        await db.refresh(card)
    
    # 处理返回的 tags 字段
    if card.tags:
        try:
            card.tags = json.loads(card.tags)
        except:
            card.tags = []
    else:
        card.tags = []
    
    return card


@router.delete("/{card_id}")
async def delete_plot_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """删除剧情卡片"""
    
    # 检查卡片是否存在
    result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")
    
    await db.execute(delete(PlotCard).where(PlotCard.id == card_id))
    await db.commit()
    
    return {"message": "剧情卡片删除成功"}


@router.post("/reorder")
async def reorder_plot_cards(
    reorder_data: PlotCardReorderRequest, 
    db: AsyncSession = Depends(get_db)
):
    """重排序剧情卡片"""
    
    for order_item in reorder_data.orders:
        card_id = order_item.get("id")
        new_order = order_item.get("order_index")
        
        if card_id and new_order is not None:
            await db.execute(
                update(PlotCard)
                .where(PlotCard.id == card_id)
                .values(order_index=new_order)
            )
    
    await db.commit()
    
    return {"message": "剧情卡片排序更新成功"}


def make_plot_cards_runner(
    *,
    user_id: Optional[str],
    request: PlotCardGenerateRequest,
    ai_service: AIService,
    session_factory,
) -> Runner:
    """AI 生成剧情卡的后台任务 runner：独立会话里跑 PlotGenerationService，返回序列化后的卡片列表（result 事件）。

    MCP 未触发 / 规划失败 / 大纲不存在等异常直接抛出 → 管理器转成任务 error 事件（文案即异常信息）。
    """
    outline_id = request.outline_id or request.story_outline_id   # 字段兼容：优先新字段名

    async def runner(job: AIJob) -> List[Dict[str, Any]]:
        async with session_factory() as db:
            cards = await PlotGenerationService(ai_service).generate_plot_cards(
                db=db,
                project_id=request.project_id,
                outline_id=outline_id,
                chapter_outline_id=request.chapter_outline_id,
                card_type=request.card_type,
                count=request.count,
                extend_from_card_id=request.extend_from_card_id,
                custom_prompt=request.prompt,
                enable_mcp=request.enable_mcp,
                selected_plugins=request.selected_plugins,
                user_id=user_id,
                pack_ids=request.pack_ids,
                dimensions=request.dimensions,
                strength=request.strength,
            )
            payload: List[Dict[str, Any]] = []
            for card in cards:
                data = PlotCardResponse.model_validate(card).model_dump(mode="json")
                try:
                    data["tags"] = json.loads(card.tags) if card.tags else []
                except (TypeError, ValueError):
                    data["tags"] = []
                payload.append(data)
            return payload

    return runner


@router.post("/generate-stream")
async def generate_plot_cards_stream(
    generate_data: PlotCardGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """AI 生成剧情卡片（后台任务 + SSE 事件流；必须基于故事大纲或章纲）。

    start → stage(context / mcp / reference_pack / llm / persist) / tool_call / reference / llm → result(卡片列表) → done。
    任务寿命独立于本连接；重连与停止走 /api/ai-jobs/*；同项目已有剧情卡生成在跑 → 409。
    """
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(generate_data.project_id, user_id, db)
    # 校验：至少需要提供大纲ID或章纲ID之一
    if not (generate_data.outline_id or generate_data.story_outline_id) and not generate_data.chapter_outline_id:
        raise HTTPException(
            status_code=400,
            detail="至少需要提供 outline_id 或 chapter_outline_id 之一作为生成上下文"
        )
    logger.info(
        "🎯 [剧情卡片生成] 项目 %s（%s）card_type=%s count=%d",
        project.id, "启用MCP" if generate_data.enable_mcp else "禁用MCP", generate_data.card_type, generate_data.count,
    )
    runner = make_plot_cards_runner(
        user_id=user_id, request=generate_data, ai_service=user_ai_service, session_factory=job_session_factory(user_id),
    )
    try:
        job = await ai_jobs.start(
            kind="plot_cards_generate",
            title=f"AI 生成剧情卡（{generate_data.count} 张）",
            user_id=user_id,
            project_id=project.id,
            runner=runner,
            cancel_message="已停止生成剧情卡",
            meta={"card_type": generate_data.card_type, "count": generate_data.count, "enable_mcp": generate_data.enable_mcp},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.get("/project/{project_id}/types")
async def get_card_types(project_id: str, db: AsyncSession = Depends(get_db)):
    """获取项目中使用的卡片类型"""
    
    result = await db.execute(
        select(PlotCard.card_type, func.count(PlotCard.id).label('count'))
        .where(PlotCard.project_id == project_id)
        .group_by(PlotCard.card_type)
        .order_by(func.count(PlotCard.id).desc())
    )
    
    types = result.all()
    
    return {
        "types": [{"type": t.card_type, "count": t.count} for t in types]
    }



# ============================================
# 剧情卡片关联管理 API
# ============================================

@router.get("/{card_id}/plot-lines", response_model=List[PlotLineWithLinks])
async def get_plot_card_plot_lines(
    card_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取剧情卡片关联的所有剧情线"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")
    
    # 查询关联的剧情线
    query = select(PlotLine).join(
        PlotCardPlotLineLink,
        PlotLine.id == PlotCardPlotLineLink.plot_line_id
    ).where(
        PlotCardPlotLineLink.plot_card_id == card_id
    ).order_by(PlotLine.order_index.asc())
    
    result = await db.execute(query)
    lines = result.scalars().all()
    
    # 构建响应
    plot_lines = []
    for line in lines:
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
        
        plot_lines.append(PlotLineWithLinks(
            id=line.id,
            title=line.title,
            description=line.description,
            line_type=line.line_type,
            chapter_count=chapter_count,
            card_count=card_count
        ))
    
    return plot_lines


@router.get("/{card_id}/chapter-outlines", response_model=List[ChapterOutlineWithLinks])
async def get_plot_card_chapter_outlines(
    card_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取剧情卡片关联的所有章纲"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")
    
    # 查询关联的章纲
    query = select(
        ChapterOutline,
        PlotCardChapterOutlineLink.usage_type
    ).join(
        PlotCardChapterOutlineLink,
        ChapterOutline.id == PlotCardChapterOutlineLink.chapter_outline_id
    ).where(
        PlotCardChapterOutlineLink.plot_card_id == card_id
    ).order_by(ChapterOutline.chapter_number.asc())
    
    result = await db.execute(query)
    rows = result.all()
    
    # 构建响应
    chapter_outlines = []
    for row in rows:
        outline = row[0]
        
        # 获取该章纲关联的剧情线数量
        line_count_result = await db.execute(
            select(func.count()).select_from(ChapterOutlinePlotLineLink)
            .where(ChapterOutlinePlotLineLink.chapter_outline_id == outline.id)
        )
        line_count = line_count_result.scalar() or 0
        
        # 获取该章纲关联的剧情卡片数量
        card_count_result = await db.execute(
            select(func.count()).select_from(PlotCardChapterOutlineLink)
            .where(PlotCardChapterOutlineLink.chapter_outline_id == outline.id)
        )
        card_count = card_count_result.scalar() or 0
        
        chapter_outlines.append(ChapterOutlineWithLinks(
            id=outline.id,
            chapter_number=outline.chapter_number,
            title=outline.title,
            summary=outline.summary,
            plot_line_count=line_count,
            card_count=card_count
        ))
    
    return chapter_outlines


@router.post("/{card_id}/link-plot-lines")
async def link_plot_lines_to_plot_card(
    card_id: str,
    link_data: PlotCardPlotLineLinkBatch,
    db: AsyncSession = Depends(get_db)
):
    """将剧情线关联到剧情卡片"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail=f"剧情卡片不存在: {card_id}")
    
    # 验证剧情线存在且属于同一项目（跨项目校验）
    lines_result = await db.execute(
        select(PlotLine).where(
            PlotLine.id.in_(link_data.plot_line_ids),
            PlotLine.project_id == card.project_id  # 添加项目归属校验
        )
    )
    existing_lines = {line.id: line for line in lines_result.scalars().all()}
    
    # 检查是否有无效的ID
    invalid_ids = set(link_data.plot_line_ids) - set(existing_lines.keys())
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"以下剧情线不存在或不属于该项目: {', '.join(list(invalid_ids)[:5])}"
        )
    
    # 创建关联
    created_count = 0
    skipped_count = 0
    
    for line_id in link_data.plot_line_ids:
        # 检查是否已存在关联
        existing_link = await db.execute(
            select(PlotCardPlotLineLink).where(
                PlotCardPlotLineLink.plot_card_id == card_id,
                PlotCardPlotLineLink.plot_line_id == line_id
            )
        )
        
        if existing_link.scalar_one_or_none():
            skipped_count += 1
            continue  # 跳过已存在的关联
        
        # 创建新关联
        link = PlotCardPlotLineLink(
            plot_card_id=card_id,
            plot_line_id=line_id
        )
        db.add(link)
        created_count += 1
    
    await db.commit()
    
    return {
        "message": f"成功关联 {created_count} 条剧情线到剧情卡片",
        "created_count": created_count,
        "skipped_count": skipped_count
    }


@router.delete("/{card_id}/unlink-plot-lines")
async def unlink_plot_lines_from_plot_card(
    card_id: str,
    request: UnlinkRequest,
    db: AsyncSession = Depends(get_db)
):
    """取消剧情线与剧情卡片的关联"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail=f"剧情卡片不存在: {card_id}")
    
    # 删除关联
    result = await db.execute(
        delete(PlotCardPlotLineLink).where(
            PlotCardPlotLineLink.plot_card_id == card_id,
            PlotCardPlotLineLink.plot_line_id.in_(request.ids)
        )
    )
    
    await db.commit()
    
    return {
        "message": f"成功取消 {result.rowcount} 条剧情线的关联",
        "removed_count": result.rowcount
    }


@router.post("/{card_id}/link-chapter-outlines")
async def link_chapter_outlines_to_plot_card(
    card_id: str,
    link_data: PlotCardChapterOutlineLinkBatch,
    db: AsyncSession = Depends(get_db)
):
    """将章纲关联到剧情卡片"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail=f"剧情卡片不存在: {card_id}")
    
    # 验证章纲存在且属于同一项目（跨项目校验）
    outline_ids = [link.chapter_outline_id for link in link_data.links]
    outlines_result = await db.execute(
        select(ChapterOutline).where(
            ChapterOutline.id.in_(outline_ids),
            ChapterOutline.project_id == card.project_id  # 添加项目归属校验
        )
    )
    existing_outlines = {outline.id: outline for outline in outlines_result.scalars().all()}
    
    # 检查是否有无效的ID
    invalid_ids = set(outline_ids) - set(existing_outlines.keys())
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"以下章纲不存在或不属于该项目: {', '.join(list(invalid_ids)[:5])}"
        )
    
    # 创建关联
    created_count = 0
    skipped_count = 0
    
    for link in link_data.links:
        # 检查是否已存在关联
        existing_link = await db.execute(
            select(PlotCardChapterOutlineLink).where(
                PlotCardChapterOutlineLink.plot_card_id == card_id,
                PlotCardChapterOutlineLink.chapter_outline_id == link.chapter_outline_id
            )
        )
        
        if existing_link.scalar_one_or_none():
            skipped_count += 1
            continue  # 跳过已存在的关联
        
        # 创建新关联
        new_link = PlotCardChapterOutlineLink(
            plot_card_id=card_id,
            chapter_outline_id=link.chapter_outline_id,
            usage_type=link.usage_type,
            usage_notes=link.usage_notes
        )
        db.add(new_link)
        created_count += 1
    
    await db.commit()
    
    return {
        "message": f"成功关联 {created_count} 个章纲到剧情卡片",
        "created_count": created_count,
        "skipped_count": skipped_count
    }


@router.delete("/{card_id}/unlink-chapter-outlines")
async def unlink_chapter_outlines_from_plot_card(
    card_id: str,
    request: UnlinkRequest,
    db: AsyncSession = Depends(get_db)
):
    """取消章纲与剧情卡片的关联"""
    
    # 检查剧情卡片是否存在
    card_result = await db.execute(select(PlotCard).where(PlotCard.id == card_id))
    card = card_result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail=f"剧情卡片不存在: {card_id}")
    
    # 删除关联
    result = await db.execute(
        delete(PlotCardChapterOutlineLink).where(
            PlotCardChapterOutlineLink.plot_card_id == card_id,
            PlotCardChapterOutlineLink.chapter_outline_id.in_(request.ids)
        )
    )
    
    await db.commit()
    
    return {
        "message": f"成功取消 {result.rowcount} 个章纲的关联",
        "removed_count": result.rowcount
    }
