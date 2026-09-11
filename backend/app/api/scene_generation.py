"""场景生成 API 路由 - 简化版，按剧情卡片分段生成"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional

from app.api.ai_jobs import job_sse_response
from app.database import get_db
from app.logger import get_logger
from app.models.plot_card import PlotCard
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.generation_trace import begin_stage
from app.services.scene_generation_service import SceneGenerationService
from app.services.ai_service import AIService
from app.api.settings import get_user_ai_service

logger = get_logger(__name__)
router = APIRouter(prefix="/scene-generation", tags=["场景生成"])


# ============ Pydantic 模型 ============

class DirectGenerateRequest(BaseModel):
    """直接生成场景请求"""
    chapter_outline_id: str = Field(..., description="章纲ID")
    plot_card_id: str = Field(..., description="剧情卡片ID")
    writing_style_id: Optional[str] = Field(None, description="写作风格ID")
    previous_generated_content: Optional[str] = Field(None, description="前端编辑器中已有的内容（用户可能已修改）")
    # R8 拆书参考包显式参数（任一为空则走 injector 默认）
    pack_ids: Optional[List[str]] = Field(None, description="显式选中的拆书参考包 ID 列表")
    dimensions: Optional[List[str]] = Field(None, description="显式选中的参考维度")
    strength: Optional[str] = Field(None, description="参考强度：light/medium/deep")


class PlotCardResponse(BaseModel):
    """剧情卡片响应"""
    id: str
    title: str
    content: Optional[str] = None
    generation_status: str
    word_count_target: int
    word_count_actual: int
    generation_order: int


# ============ 辅助函数 ============

async def get_user_id(request: Request) -> str:
    """从请求中获取用户ID"""
    user_id = request.state.user_id if hasattr(request.state, 'user_id') else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return user_id


def get_scene_service(
    user_ai_service: AIService = Depends(get_user_ai_service)
) -> SceneGenerationService:
    """获取场景生成服务实例"""
    return SceneGenerationService(user_ai_service)


# ============ API 端点 ============

@router.get("/chapter-outlines/{chapter_outline_id}/plot-cards")
async def get_chapter_outline_plot_cards(
    chapter_outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: SceneGenerationService = Depends(get_scene_service)
):
    """获取章纲关联的剧情卡片列表"""
    await get_user_id(request)
    
    try:
        plot_cards = await service.get_plot_cards_for_chapter(db, chapter_outline_id)
        return {
            "chapter_outline_id": chapter_outline_id,
            "plot_cards": [
                {
                    "id": card.id,
                    "title": card.title,
                    "content": card.content,
                    "generation_status": card.generation_status or "pending",
                    "word_count_target": card.word_count_target or 500,
                    "word_count_actual": card.word_count_actual or 0,
                    "generation_order": card.generation_order or 0,
                }
                for card in plot_cards
            ]
        }
    except Exception as e:
        logger.error(f"获取剧情卡片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _load_plot_card(db: AsyncSession, plot_card_id: str) -> Optional[PlotCard]:
    return (await db.execute(select(PlotCard).where(PlotCard.id == plot_card_id))).scalar_one_or_none()


@router.post("/generate-scene-stream")
async def generate_scene_stream(
    request_data: DirectGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: SceneGenerationService = Depends(get_scene_service)
):
    """流式生成场景内容（后台任务 + SSE 事件流）。

    start → stage(llm) / reference(参考包) / llm → content（逐块进任务日志，可回放）→ result{plot_card_id, word_count} → done。
    任务寿命独立于本连接；重连与停止走 /api/ai-jobs/*；同一章纲已有场景在生成 → 409。
    取消时把卡片 generation_status 复位为 pending（服务层只兜底普通异常）。
    """
    user_id = await get_user_id(request)
    card = await _load_plot_card(db, request_data.plot_card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="剧情卡片不存在")

    async def runner(job):
        async with job_session_factory(user_id)() as db_session:
            st = begin_stage("llm", f"模型生成场景「{card.title}」")
            full = ""
            last_progress_at = 0
            try:
                async for chunk in service.generate_scene_direct(
                    db=db_session,
                    chapter_outline_id=request_data.chapter_outline_id,
                    plot_card_id=request_data.plot_card_id,
                    user_id=user_id,
                    writing_style_id=request_data.writing_style_id,
                    previous_generated_content=request_data.previous_generated_content,
                    pack_ids=request_data.pack_ids,
                    dimensions=request_data.dimensions,
                    strength=request_data.strength,
                ):
                    if not chunk:
                        continue
                    full += chunk
                    job.publish({"type": "content", "content": chunk})
                    if len(full) - last_progress_at >= 200:
                        last_progress_at = len(full)
                        job.progress(f"已写出 {len(full)} 字", min(95, 10 + len(full) // 20))
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                # 服务层的 except Exception 不接取消：这里把卡片状态复位，避免永远"生成中"
                stale = await _load_plot_card(db_session, request_data.plot_card_id)
                if stale is not None and stale.generation_status == "generating":
                    stale.generation_status = "pending"
                    await db_session.commit()
                raise
            st.done(chars=len(full))
            return {"plot_card_id": request_data.plot_card_id, "word_count": len(full)}

    try:
        job = await ai_jobs.start(
            kind="scene_generate",
            title=f"生成场景「{card.title}」",
            user_id=user_id,
            project_id=card.project_id,
            scope=f"scene_generate:{request_data.chapter_outline_id}",
            runner=runner,
            cancel_message="已停止生成场景；卡片状态已复位",
            meta={"chapter_outline_id": request_data.chapter_outline_id, "plot_card_id": request_data.plot_card_id},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)

