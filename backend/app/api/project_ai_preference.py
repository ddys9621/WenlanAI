"""项目级 AI 偏好：GET / PUT / DELETE /projects/{project_id}/ai-preference。

接口（provider / key / base_url）永远复用设置页那一套；这里只按项目覆盖模型与采样 / 思考参数。
生效方式：前端在项目内的每个请求带 X-Project-Id，`get_user_ai_service` 据此合并（见 api/settings.py）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_login, verify_project_access
from app.api.settings import load_or_create_settings
from app.database import get_db
from app.logger import get_logger
from app.models.project_ai_preference import ProjectAIPreference
from app.models.settings import Settings
from app.schemas.project_ai_preference import (
    AIOverrideFields,
    EffectiveAIConfig,
    ProjectAIPreferenceResponse,
    ProjectAIPreferenceUpdate,
)
from app.services.project_ai_preference import OVERRIDE_FIELDS, effective_config
from app.user_manager import User

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["项目 AI 偏好"])


def _build_response(project_id: str, settings: Settings, pref: ProjectAIPreference | None) -> ProjectAIPreferenceResponse:
    overrides = {f: getattr(pref, f) for f in OVERRIDE_FIELDS} if pref is not None else {}
    return ProjectAIPreferenceResponse(
        project_id=project_id,
        overrides=AIOverrideFields(**overrides),
        effective=EffectiveAIConfig(**effective_config(settings, pref)),
        global_defaults=EffectiveAIConfig(**effective_config(settings, None)),
    )


async def _get_pref(db: AsyncSession, project_id: str) -> ProjectAIPreference | None:
    result = await db.execute(select(ProjectAIPreference).where(ProjectAIPreference.project_id == project_id))
    return result.scalar_one_or_none()


@router.get("/{project_id}/ai-preference", response_model=ProjectAIPreferenceResponse, summary="获取项目 AI 偏好（覆盖项 + 实际生效值 + 全局值）")
async def get_project_ai_preference(
    project_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(project_id, user.user_id, db)
    settings = await load_or_create_settings(db, user.user_id)
    return _build_response(project_id, settings, await _get_pref(db, project_id))


@router.put("/{project_id}/ai-preference", response_model=ProjectAIPreferenceResponse, summary="保存项目 AI 偏好（整体替换，null=跟随全局）")
async def save_project_ai_preference(
    project_id: str,
    data: ProjectAIPreferenceUpdate,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(project_id, user.user_id, db)
    pref = await _get_pref(db, project_id)
    if pref is None:
        pref = ProjectAIPreference(project_id=project_id)
        db.add(pref)
    for f in OVERRIDE_FIELDS:
        setattr(pref, f, getattr(data, f))
    await db.commit()
    await db.refresh(pref)
    settings = await load_or_create_settings(db, user.user_id)
    logger.info(f"项目 {project_id} 保存 AI 偏好: model={pref.llm_model!r}")
    return _build_response(project_id, settings, pref)


@router.delete("/{project_id}/ai-preference", response_model=ProjectAIPreferenceResponse, summary="清除项目 AI 偏好（全部恢复跟随全局）")
async def reset_project_ai_preference(
    project_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(project_id, user.user_id, db)
    await db.execute(delete(ProjectAIPreference).where(ProjectAIPreference.project_id == project_id))
    await db.commit()
    settings = await load_or_create_settings(db, user.user_id)
    logger.info(f"项目 {project_id} 清除 AI 偏好，恢复跟随全局")
    return _build_response(project_id, settings, None)
