"""V3 R5 一键仿写 API

两个端点：
- POST /api/projects/{project_id}/imitate-chapter-preview
    同步返回拼装后的 prompt 元数据（不调 LLM）。供前端"调试模式"和测试使用。
- POST /api/projects/{project_id}/imitate-chapter-stream
    SSE：启动 chapter_imitate 后台任务并从头流式输出其事件（meta / content / progress / stage / result / done），
    任务寿命独立于连接；重连 / 停止走 /api/ai-jobs/*。

权限：
- 项目所有权强校验；非 owner 一律 404
- 显式传入的 pack_ids 必须已挂载到该项目（service 层会再校验一次）
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_jobs import job_sse_response
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.models.project import Project
from app.schemas.imitation import (
    ImitateChapterRequest,
    ImitatePromptPreview,
    ImitationPackUsage,
)
from app.services.ai_jobs import AIJob, AIJobConflictError, Runner, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.generation_trace import stage_scope
from app.services.imitation_service import ImitationService

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["一键仿写"])


# ============================================================
# 辅助
# ============================================================


async def _ensure_project_owned(
    db: AsyncSession, project_id: str, user_id: str
) -> Project:
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    return project


# ============================================================
# 1) Preview / dry-run
# ============================================================


@router.post(
    "/{project_id}/imitate-chapter-preview",
    response_model=ImitatePromptPreview,
    summary="一键仿写：拼装预览（不调用 LLM）",
)
async def preview_imitation(
    project_id: str,
    payload: ImitateChapterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """同步返回拼装好的 system/user prompt + 实际生效的参考包/维度/强度。

    前端可在弹板内调用本端点做"预览"，避免每次都消耗 LLM 配额。
    """
    user_id = getattr(request.state, "user_id", None)
    await _ensure_project_owned(db, project_id, user_id)

    service = ImitationService(user_ai_service)
    try:
        bundle = await service.assemble_prompt(
            db,
            project_id,
            user_intent=payload.user_intent,
            target_chapter_id=payload.target_chapter_id,
            pack_ids=payload.pack_ids,
            dimensions=payload.dimensions,
            strength=payload.strength,
            target_word_count=payload.target_word_count,
            style_id=payload.style_id,
            user_id=user_id,
        )
    except ValueError as e:
        # 参考包未挂载 / 显式 pack 不在挂载列表 / 参考包未就绪 → 422
        raise HTTPException(status_code=422, detail=str(e))

    return ImitatePromptPreview(
        system_prompt=bundle["system_prompt"],
        user_prompt=bundle["user_prompt"],
        used_packs=[ImitationPackUsage(**p) for p in bundle["used_packs"]],
        used_dimensions=bundle["used_dimensions"],
        strength=bundle["strength"],
        target_word_count=bundle["target_word_count"],
        project_context_chars=bundle["project_context_chars"],
        reference_chars=bundle["reference_chars"],
    )


# ============================================================
# 2) Stream
# ============================================================


def make_imitation_runner(
    *,
    project_id: str,
    user_id: str,
    payload: ImitateChapterRequest,
    ai_service: AIService,
    session_factory: Callable[[], Any],
) -> Runner:
    """后台任务体：assemble（参考包 reference 事件由注入器自动上报）→ meta 场景事件 → 流式生成草稿（content 进日志）。

    参考包未挂载等 ValueError 直接抛出 → 任务 error 事件（前端弹窗显示文案）。
    """
    service = ImitationService(ai_service)

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            job.progress("开始拼装参考包与项目状态...", 5)
            async with stage_scope("assemble", "拼装参考包与项目状态") as st:
                bundle = await service.assemble_prompt(
                    db,
                    project_id,
                    user_intent=payload.user_intent,
                    target_chapter_id=payload.target_chapter_id,
                    pack_ids=payload.pack_ids,
                    dimensions=payload.dimensions,
                    strength=payload.strength,
                    target_word_count=payload.target_word_count,
                    style_id=payload.style_id,
                    user_id=user_id,
                )
                st.note(packs=len(bundle["used_packs"]), dimensions="、".join(bundle["used_dimensions"]),
                        strength=bundle["strength"], reference_chars=bundle["reference_chars"])
            # 场景级 meta：对话框据此显示"用了哪些 pack / 维度"
            job.publish({
                "type": "meta",
                "used_packs": bundle["used_packs"],
                "used_dimensions": bundle["used_dimensions"],
                "strength": bundle["strength"],
                "project_context_chars": bundle["project_context_chars"],
                "reference_chars": bundle["reference_chars"],
            })
            job.progress("📚 已整合参考资料，开始生成草稿...", 25)

            accumulated = 0
            last_progress_at = 0
            target = max(payload.target_word_count, 1)
            async with stage_scope("llm", "模型生成仿写草稿") as st:
                async for chunk in ai_service.generate_text_stream(
                    prompt=bundle["user_prompt"],
                    system_prompt=bundle["system_prompt"],
                ):
                    if not chunk:
                        continue
                    accumulated += len(chunk)
                    job.publish({"type": "content", "content": chunk})
                    if accumulated - last_progress_at >= 200:
                        last_progress_at = accumulated
                        progress = min(25 + int((accumulated / target) * 70), 95)
                        job.publish({"type": "progress", "message": f"已写出 {accumulated} 字", "progress": progress,
                                     "status": "processing", "word_count": accumulated})
                    await asyncio.sleep(0)
                st.note(chars=accumulated)
            return {"chars": accumulated, "used_dimensions": bundle["used_dimensions"], "strength": bundle["strength"]}

    return runner


@router.post(
    "/{project_id}/imitate-chapter-stream",
    summary="一键仿写：后台任务 + SSE 事件流",
)
async def imitate_chapter_stream(
    project_id: str,
    payload: ImitateChapterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """项目所有权先校验 → 启动 chapter_imitate 任务 → 从头流式输出 meta / stage / content / progress / result / done。

    同项目已有仿写在跑 → 409；重连与停止走 /api/ai-jobs/*。
    """
    user_id = getattr(request.state, "user_id", None)
    await _ensure_project_owned(db, project_id, user_id)
    runner = make_imitation_runner(
        project_id=project_id, user_id=user_id, payload=payload, ai_service=user_ai_service,
        session_factory=job_session_factory(user_id),
    )
    try:
        job = await ai_jobs.start(
            kind="chapter_imitate",
            title="一键仿写草稿",
            user_id=user_id,
            project_id=project_id,
            scope=f"chapter_imitate:{project_id}",
            runner=runner,
            cancel_message="已停止仿写；草稿未保存",
            meta={"target_chapter_id": payload.target_chapter_id, "target_word_count": payload.target_word_count},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)
