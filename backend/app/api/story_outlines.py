"""故事大纲 API 端点"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import uuid

from app.database import get_db
from app.logger import get_logger
from app.models.story_outline import StoryOutline
from app.schemas.story_outline import (
    StoryOutlineCreate,
    StoryOutlineGenerateRequest,
    StoryOutlineResponse,
    StoryOutlineUpdate,
)
from app.services import outline_review_service as outline_review
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.sse_job_adapter import make_sse_generator_runner
from app.services.story_outline_service import StoryOutlineService
from app.api.ai_jobs import job_sse_response
from app.api.deps import verify_project_access
from app.api.settings import get_user_ai_service
from app.api.wizard_stream import outline_generator

logger = get_logger(__name__)
router = APIRouter(tags=["story-outlines"])


async def get_outline_with_access_check(outline_id: str, user_id: str, db: AsyncSession) -> StoryOutline:
    """获取故事大纲并校验所属项目访问权限"""
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(select(StoryOutline).where(StoryOutline.id == outline_id))
    outline = result.scalar_one_or_none()
    if not outline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故事大纲不存在",
        )

    await verify_project_access(outline.project_id, user_id, db)
    return outline


@router.post("/projects/{project_id}/story-outlines", response_model=StoryOutlineResponse)
async def create_story_outline(
    project_id: str,
    outline: StoryOutlineCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """创建故事大纲"""
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    # 验证内容
    if outline.content:
        StoryOutlineService.validate_outline_content(outline.content)

    # 创建大纲
    db_outline = StoryOutline(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title=outline.title,
        content=outline.content,
        order_index=outline.order_index,
        version=1,
        is_active=True
    )

    db.add(db_outline)
    await db.commit()
    await db.refresh(db_outline)

    return db_outline


@router.post("/projects/{project_id}/story-outlines/generate-stream", summary="AI 生成总纲（后台任务 + SSE）")
async def generate_story_outline_stream(
    project_id: str,
    body: StoryOutlineGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """谋篇页「AI 生成」：和向导第 3 步同一个生成器（提示词 / 世界规则 / 仿写参考 / MCP 一致），但存成新的活跃版本、
    旧版本保留，已有卷纲 / 章纲标「上游已改」。跑在通用后台任务上：弹窗 / 托盘可见、关页面不中断，
    重连与停止走 /api/ai-jobs/*；同项目已有总纲生成在跑 → 409。视角 / 章数 / 字数留空按项目设置。
    """
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(project_id, user_id, db)
    data = {
        "project_id": project.id,
        "user_id": user_id,
        "narrative_perspective": body.narrative_perspective or project.narrative_perspective,
        "chapter_count": body.chapter_count or project.chapter_count,
        "target_words": body.target_words or project.target_words,
        "requirements": (body.requirements or "").strip() or None,
        "enable_mcp": body.enable_mcp,
        "selected_plugins": body.selected_plugins,
    }
    data = {key: value for key, value in data.items() if value is not None}   # 生成器按 get(key, 默认值) 取，None 会顶掉默认值
    try:
        job = await ai_jobs.start(
            kind="story_outline_generate",
            title="AI 生成总纲",
            user_id=user_id,
            project_id=project.id,
            runner=make_sse_generator_runner(
                lambda session: outline_generator(data, session, user_ai_service, as_new_version=True),
                session_factory=job_session_factory(user_id),
            ),
            cancel_message="已停止生成总纲；原有总纲不受影响",
            meta={"chapter_count": data.get("chapter_count"), "enable_mcp": body.enable_mcp},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


@router.get("/projects/{project_id}/story-outlines", response_model=List[StoryOutlineResponse])
async def get_story_outlines(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取项目的所有故事大纲"""
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    result = await db.execute(
        select(StoryOutline)
        .where(StoryOutline.project_id == project_id)
        .order_by(StoryOutline.order_index.asc(), StoryOutline.version.desc())
    )
    outlines = result.scalars().all()
    return outlines


@router.get("/story-outlines/{outline_id}", response_model=StoryOutlineResponse)
async def get_story_outline(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取故事大纲详情"""
    user_id = getattr(request.state, 'user_id', None)
    return await get_outline_with_access_check(outline_id, user_id, db)


@router.put("/story-outlines/{outline_id}", response_model=StoryOutlineResponse)
async def update_story_outline(
    outline_id: str,
    outline_update: StoryOutlineUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新故事大纲；故事前提真改了 → 本项目全部章纲标「上游已改」，等作者核对确认"""
    editor_id = getattr(request.state, 'user_id', None)
    current = await get_outline_with_access_check(outline_id, editor_id, db)
    premise_changed = outline_update.content is not None and outline_update.content.strip() != (current.content or "").strip()

    updated = await StoryOutlineService.update_outline(
        db=db,
        outline_id=outline_id,
        outline_update=outline_update,
        editor_id=editor_id
    )
    if premise_changed:
        await outline_review.mark_project_outlines(db, updated.project_id, "总纲（故事大纲）已修改")
        await db.commit()
        await db.refresh(updated)
    return updated


@router.delete("/story-outlines/{outline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story_outline(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除故事大纲"""
    user_id = getattr(request.state, 'user_id', None)
    db_outline = await get_outline_with_access_check(outline_id, user_id, db)

    await db.delete(db_outline)
    await db.commit()

    return None


@router.post("/story-outlines/{outline_id}/activate", response_model=StoryOutlineResponse)
async def activate_story_outline(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """激活故事大纲版本"""
    user_id = getattr(request.state, 'user_id', None)
    db_outline = await get_outline_with_access_check(outline_id, user_id, db)

    # 更新其他版本为非激活状态
    other_outlines_result = await db.execute(
        select(StoryOutline).where(
            StoryOutline.project_id == db_outline.project_id,
            StoryOutline.id != outline_id
        )
    )
    other_outlines = other_outlines_result.scalars().all()
    for outline in other_outlines:
        outline.is_active = False

    # 激活当前版本
    db_outline.is_active = True

    await db.commit()
    await db.refresh(db_outline)

    return db_outline
