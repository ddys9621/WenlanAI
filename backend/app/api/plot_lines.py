"""剧情线 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import List, Optional, Dict, Any
import json

from app.database import get_db
from app.models import (
    PlotLine, Project, ChapterOutlinePlotLineLink, PlotCardPlotLineLink
)
from app.schemas.plot_line import (
    PlotLineCreate, PlotLineUpdate, PlotLineResponse,
    PlotLineGenerateRequest, PlotLineReorderRequest, PlotLineListResponse
)
from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_project_access
from app.services.ai_jobs import AIJob, AIJobConflictError, Runner, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.plot_link_service import PlotLinkService
from app.services.plot_generation_service import PlotGenerationService
from app.api.settings import get_user_ai_service
from app.logger import get_logger
from app.utils.plot_line_types import normalize_plot_line_type

router = APIRouter(prefix="/plot-lines", tags=["剧情线"])
logger = get_logger(__name__)


async def _serialize_plot_lines(db: AsyncSession, lines: List[PlotLine]) -> List[PlotLineResponse]:
    """批量转响应模型：关联卡片 id、章纲数各一条 GROUP BY / IN 查询取齐，不随剧情线数增长"""
    if not lines:
        return []
    line_ids = [line.id for line in lines]
    card_ids_by_line: Dict[str, List[str]] = {lid: [] for lid in line_ids}
    card_rows = await db.execute(
        select(PlotCardPlotLineLink.plot_line_id, PlotCardPlotLineLink.plot_card_id)
        .where(PlotCardPlotLineLink.plot_line_id.in_(line_ids))
    )
    for line_id, card_id in card_rows.all():
        card_ids_by_line[line_id].append(card_id)
    outline_rows = await db.execute(
        select(ChapterOutlinePlotLineLink.plot_line_id, func.count(ChapterOutlinePlotLineLink.id))
        .where(ChapterOutlinePlotLineLink.plot_line_id.in_(line_ids))
        .group_by(ChapterOutlinePlotLineLink.plot_line_id)
    )
    outline_count_by_line = dict(outline_rows.all())

    responses = []
    for line in lines:
        timeline_data: Dict[str, Any] | None = None
        if line.timeline_data:
            try:
                timeline_data = json.loads(line.timeline_data)
            except Exception:
                timeline_data = None
        plot_card_ids = card_ids_by_line[line.id]
        responses.append(PlotLineResponse(
            id=line.id,
            project_id=line.project_id,
            story_outline_id=line.story_outline_id,
            title=line.title,
            description=line.description,
            line_type=line.line_type,
            order_index=line.order_index,
            estimated_chapters=line.estimated_chapters,
            plot_cards=plot_card_ids,
            timeline_data=timeline_data,
            created_at=line.created_at,
            updated_at=line.updated_at,
            chapter_outline_count=outline_count_by_line.get(line.id, 0),
            plot_card_count=len(plot_card_ids),
        ))
    return responses


async def _serialize_plot_line(db: AsyncSession, line: PlotLine) -> PlotLineResponse:
    """单条剧情线转响应模型（含关联统计）"""
    return (await _serialize_plot_lines(db, [line]))[0]


@router.get("/project/{project_id}", response_model=PlotLineListResponse)
async def get_plot_lines(
    project_id: str,
    skip: int = Query(0, ge=0, description="跳过数量"),
    limit: int = Query(100, ge=1, le=100, description="限制数量"),
    line_type: Optional[str] = Query(None, description="剧情线类型筛选"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目的剧情线列表"""
    
    # 构建查询
    query = select(PlotLine).where(PlotLine.project_id == project_id)
    
    if line_type:
        query = query.where(PlotLine.line_type == normalize_plot_line_type(line_type))
    
    # 按排序序号排序
    query = query.order_by(PlotLine.order_index.asc(), PlotLine.created_at.asc())
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页查询
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    lines = result.scalars().all()

    return PlotLineListResponse(total=total, items=await _serialize_plot_lines(db, list(lines)))


@router.get("/{line_id}", response_model=PlotLineResponse)
async def get_plot_line(line_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个剧情线"""
    
    result = await db.execute(select(PlotLine).where(PlotLine.id == line_id))
    line = result.scalar_one_or_none()
    
    if not line:
        raise HTTPException(status_code=404, detail="剧情线不存在")
    
    return await _serialize_plot_line(db, line)


@router.post("", response_model=PlotLineResponse)
async def create_plot_line(line_data: PlotLineCreate, db: AsyncSession = Depends(get_db)):
    """创建剧情线"""
    
    # 验证项目存在
    project_result = await db.execute(select(Project).where(Project.id == line_data.project_id))
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 如果没有指定排序序号，自动设置为最大值+1
    if line_data.order_index is None:
        max_order_result = await db.execute(
            select(func.max(PlotLine.order_index)).where(PlotLine.project_id == line_data.project_id)
        )
        max_order = max_order_result.scalar() or 0
        line_data.order_index = max_order + 1
    
    # 处理 JSON 字段
    timeline_data_json = None
    if line_data.timeline_data:
        timeline_data_json = json.dumps(line_data.timeline_data, ensure_ascii=False)
    
    # 创建剧情线
    line = PlotLine(
        project_id=line_data.project_id,
        story_outline_id=line_data.story_outline_id,
        title=line_data.title,
        description=line_data.description,
        line_type=normalize_plot_line_type(line_data.line_type),
        order_index=line_data.order_index,
        timeline_data=timeline_data_json,
        estimated_chapters=line_data.estimated_chapters
    )
    
    db.add(line)
    await db.commit()
    await db.refresh(line)
    
    # 创建剧情卡片关联
    if line_data.plot_cards:
        try:
            await PlotLinkService.add_cards_to_plot_line(
                db=db,
                plot_line_id=line.id,
                card_ids=line_data.plot_cards
            )
        except Exception as e:
            logger.warning(f"创建剧情线时关联剧情卡片失败: {e}")
    
    return await _serialize_plot_line(db, line)


@router.put("/{line_id}", response_model=PlotLineResponse)
async def update_plot_line(
    line_id: str, 
    line_data: PlotLineUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """更新剧情线"""
    
    # 检查剧情线是否存在
    result = await db.execute(select(PlotLine).where(PlotLine.id == line_id))
    line = result.scalar_one_or_none()
    
    if not line:
        raise HTTPException(status_code=404, detail="剧情线不存在")
    
    # 更新字段
    update_data = line_data.model_dump(exclude_unset=True)
    
    # 提取 plot_cards 用于关联表更新
    plot_cards = update_data.pop("plot_cards", None)
    
    # 处理 JSON 字段
    if "timeline_data" in update_data and update_data["timeline_data"] is not None:
        update_data["timeline_data"] = json.dumps(update_data["timeline_data"], ensure_ascii=False)

    if "line_type" in update_data:
        update_data["line_type"] = normalize_plot_line_type(
            update_data["line_type"],
            default=line.line_type or "main"
        )
    
    # 更新基本字段
    if update_data:
        await db.execute(
            update(PlotLine).where(PlotLine.id == line_id).values(**update_data)
        )
        await db.commit()
        await db.refresh(line)
    
    # 更新剧情卡片关联（如果提供了）
    if plot_cards is not None:
        try:
            # 先删除所有现有关联
            await db.execute(
                delete(PlotCardPlotLineLink).where(PlotCardPlotLineLink.plot_line_id == line_id)
            )
            await db.commit()
            
            # 再创建新关联
            if plot_cards:
                await PlotLinkService.add_cards_to_plot_line(
                    db=db,
                    plot_line_id=line_id,
                    card_ids=plot_cards
                )
        except Exception as e:
            logger.warning(f"更新剧情线时关联剧情卡片失败: {e}")
    
    return await _serialize_plot_line(db, line)


@router.delete("/{line_id}")
async def delete_plot_line(line_id: str, db: AsyncSession = Depends(get_db)):
    """删除剧情线"""
    
    # 检查剧情线是否存在
    result = await db.execute(select(PlotLine).where(PlotLine.id == line_id))
    line = result.scalar_one_or_none()
    
    if not line:
        raise HTTPException(status_code=404, detail="剧情线不存在")
    
    await db.execute(delete(PlotLine).where(PlotLine.id == line_id))
    await db.commit()
    
    return {"message": "剧情线删除成功"}


@router.post("/reorder")
async def reorder_plot_lines(
    reorder_data: PlotLineReorderRequest, 
    db: AsyncSession = Depends(get_db)
):
    """重排序剧情线"""
    
    for order_item in reorder_data.orders:
        line_id = order_item.get("id")
        new_order = order_item.get("order_index")
        
        if line_id and new_order is not None:
            await db.execute(
                update(PlotLine)
                .where(PlotLine.id == line_id)
                .values(order_index=new_order)
            )
    
    await db.commit()
    
    return {"message": "剧情线排序更新成功"}


def make_plot_lines_runner(
    *,
    user_id: Optional[str],
    request: PlotLineGenerateRequest,
    ai_service: AIService,
    session_factory,
) -> Runner:
    """AI 生成剧情线的后台任务 runner：独立会话里跑 PlotGenerationService，返回序列化后的剧情线列表（result 事件）。

    MCP 未触发 / 规划失败 / 大纲不存在等异常直接抛出 → 管理器转成任务 error 事件（文案即异常信息）。
    """

    async def runner(job: AIJob) -> List[Dict[str, Any]]:
        async with session_factory() as db:
            lines = await PlotGenerationService(ai_service).generate_plot_lines(
                db=db,
                project_id=request.project_id,
                outline_id=request.story_outline_id,
                line_type=normalize_plot_line_type(request.line_type),
                based_on_cards=request.based_on_cards,
                based_on_lines=request.based_on_lines,
                custom_prompt=request.prompt,
                count=request.count,
                enable_mcp=request.enable_mcp,
                selected_plugins=request.selected_plugins,
                user_id=user_id,
                pack_ids=request.pack_ids,
                dimensions=request.dimensions,
                strength=request.strength,
            )
            return [item.model_dump(mode="json") for item in await _serialize_plot_lines(db, list(lines))]

    return runner


@router.post("/generate-stream")
async def generate_plot_lines_stream(
    generate_data: PlotLineGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """AI 生成剧情线（后台任务 + SSE 事件流）。

    start → stage(context / reference_pack / line-i / beats / persist) / tool_call / reference / llm → result(剧情线列表) → done。
    任务寿命独立于本连接；重连与停止走 /api/ai-jobs/*；同项目已有剧情线生成在跑 → 409。
    """
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(generate_data.project_id, user_id, db)
    logger.info(
        "🎯 [剧情线生成] 项目 %s（%s）line_type=%s count=%d 大纲=%s",
        project.id, "启用MCP" if generate_data.enable_mcp else "禁用MCP",
        normalize_plot_line_type(generate_data.line_type), generate_data.count, generate_data.story_outline_id or "无",
    )
    runner = make_plot_lines_runner(
        user_id=user_id, request=generate_data, ai_service=user_ai_service, session_factory=job_session_factory(user_id),
    )
    try:
        job = await ai_jobs.start(
            kind="plot_lines_generate",
            title=f"AI 生成剧情线（{generate_data.count} 条）",
            user_id=user_id,
            project_id=project.id,
            runner=runner,
            cancel_message="已停止生成剧情线；已写入的剧情线已保存",
            meta={"line_type": generate_data.line_type, "count": generate_data.count, "enable_mcp": generate_data.enable_mcp},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.get("/project/{project_id}/types")
async def get_line_types(project_id: str, db: AsyncSession = Depends(get_db)):
    """获取项目中使用的剧情线类型"""
    
    result = await db.execute(
        select(PlotLine.line_type, func.count(PlotLine.id).label('count'))
        .where(PlotLine.project_id == project_id)
        .group_by(PlotLine.line_type)
        .order_by(func.count(PlotLine.id).desc())
    )
    
    types = result.all()
    
    normalized_counts: Dict[str, int] = {}
    for item in types:
        normalized_type = normalize_plot_line_type(item.line_type)
        normalized_counts[normalized_type] = normalized_counts.get(normalized_type, 0) + item.count

    return {
        "types": [
            {"type": line_type, "count": count}
            for line_type, count in normalized_counts.items()
        ]
    }


@router.post("/{line_id}/add-cards")
async def add_cards_to_line(
    line_id: str,
    card_ids: List[str],
    db: AsyncSession = Depends(get_db)
):
    """向剧情线添加剧情卡片"""
    
    try:
        result = await PlotLinkService.add_cards_to_plot_line(
            db=db,
            plot_line_id=line_id,
            card_ids=card_ids
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


@router.delete("/{line_id}/remove-cards")
async def remove_cards_from_line(
    line_id: str,
    card_ids: List[str],
    db: AsyncSession = Depends(get_db)
):
    """从剧情线移除剧情卡片"""
    
    try:
        result = await PlotLinkService.remove_cards_from_plot_line(
            db=db,
            plot_line_id=line_id,
            card_ids=card_ids
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"移除失败: {str(e)}")



# ============================================
# 剧情线关联管理 API
# ============================================

@router.get("/{line_id}/progress")
async def get_plot_line_progress(
    line_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取剧情线的节点覆盖进度

    返回剧情线的整体进度和各节点的覆盖情况。

    Args:
        line_id: 剧情线ID

    Returns:
        {
            "plot_line_id": "...",
            "plot_line_title": "...",
            "has_beats": true/false,
            "total_progress": 0.45,  # 整体进度（0-1）
            "beats": [
                {
                    "index": 1,
                    "key": "opening",
                    "title": "开端",
                    "description": "...",
                    "weight": 0.15,
                    "coverage": 0.8,  # 该节点覆盖度（0-1）
                    "status": "completed/in_progress/not_started"
                }
            ],
            "linked_chapters_count": 5  # 关联的章节数量
        }
    """
    # 检查剧情线是否存在
    line_result = await db.execute(select(PlotLine).where(PlotLine.id == line_id))
    line = line_result.scalar_one_or_none()

    if not line:
        raise HTTPException(status_code=404, detail=f"剧情线不存在: {line_id}")

    # 解析剧情线的 timeline_data
    timeline_data = None
    beats = None

    if line.timeline_data:
        try:
            timeline_data = json.loads(line.timeline_data)
            beats = timeline_data.get("beats", [])
        except Exception as e:
            logger.error(f"解析剧情线 timeline_data 失败: {e}")

    # 如果没有 beats，返回简化的响应
    if not beats:
        # 统计关联的章节数量
        linked_chapters_result = await db.execute(
            select(func.count(ChapterOutlinePlotLineLink.id)).where(
                ChapterOutlinePlotLineLink.plot_line_id == line_id
            )
        )
        linked_chapters_count = linked_chapters_result.scalar() or 0

        return {
            "plot_line_id": line.id,
            "plot_line_title": line.title,
            "has_beats": False,
            "total_progress": None,
            "beats": [],
            "linked_chapters_count": linked_chapters_count,
            "message": "该剧情线尚未定义节点结构（beats），无法计算进度"
        }

    # 使用 PlotGenerationService 的方法计算进度
    ai_service = AIService()
    generation_service = PlotGenerationService(ai_service)

    try:
        coverage_summary = await generation_service._calculate_beats_coverage(
            db=db,
            plot_line_id=line_id,
            beats=beats
        )

        # 为每个节点添加状态标记
        beats_with_status = []
        for beat_info in coverage_summary.get("beats", []):
            coverage = beat_info.get("coverage", 0)

            # 确定状态
            if coverage >= 1.0:
                status = "completed"
            elif coverage > 0:
                status = "in_progress"
            else:
                status = "not_started"

            beats_with_status.append({
                **beat_info,
                "status": status
            })

        # 统计关联的章节数量
        linked_chapters_result = await db.execute(
            select(func.count(ChapterOutlinePlotLineLink.id)).where(
                ChapterOutlinePlotLineLink.plot_line_id == line_id
            )
        )
        linked_chapters_count = linked_chapters_result.scalar() or 0

        return {
            "plot_line_id": line.id,
            "plot_line_title": line.title,
            "has_beats": True,
            "total_progress": coverage_summary.get("total_progress", 0),
            "beats": beats_with_status,
            "linked_chapters_count": linked_chapters_count
        }

    except Exception as e:
        logger.error(f"计算剧情线进度失败: {e}")
        raise HTTPException(status_code=500, detail=f"计算进度失败: {str(e)}")


# ============================================
# 时间线编辑 API
# ============================================
