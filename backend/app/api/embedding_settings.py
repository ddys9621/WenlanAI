"""设置页「记忆检索」接口：查看向量模型状态（登录即可）、下载 / 切换（仅管理员；全站共用一份模型）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.ai_jobs import job_sse_response
from app.api.deps import require_admin, require_login
from app.services import embedding_models as em
from app.services import embedding_settings_service as svc
from app.services.ai_jobs import AIJobConflictError, ai_jobs
from app.user_manager import User

router = APIRouter(prefix="/settings/embedding", tags=["设置管理"])


class EmbeddingModelRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=200, description="模型仓库 id，如 BAAI/bge-small-zh-v1.5")


class EmbeddingDownloadRequest(EmbeddingModelRequest):
    activate: bool = Field(True, description="下载完成后直接启用")


def _status(user: User) -> dict:
    return svc.model_status(can_manage=bool(getattr(user, "is_admin", False)), manager=ai_jobs)


@router.get("", summary="向量（记忆检索）模型状态")
async def get_embedding_status(user: User = Depends(require_login)):
    return _status(user)


@router.post("/activate", summary="切换到已下载的向量模型（即时生效，随后后台重建检索索引）")
async def activate_embedding_model(body: EmbeddingModelRequest, user: User = Depends(require_admin)):
    if em.env_override():
        raise HTTPException(status_code=409, detail="向量模型由环境变量 / 配置文件 EMBEDDING_MODEL 指定，设置页不能切换")
    try:
        result = await svc.activate(body.model.strip(), user_id=user.user_id, manager=ai_jobs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": _status(user), **result}


@router.post("/download", summary="下载预设向量模型（后台任务 + SSE）")
async def download_embedding_model(body: EmbeddingDownloadRequest, user: User = Depends(require_admin)):
    model = body.model.strip()
    if em.preset(model) is None:
        raise HTTPException(status_code=400, detail="只能下载列表里的预设模型；其它模型请手动放进 embedding 目录")
    if body.activate and em.env_override():
        raise HTTPException(status_code=409, detail="向量模型由环境变量 / 配置文件 EMBEDDING_MODEL 指定，设置页不能切换")
    try:
        job = await svc.start_download(model, user_id=user.user_id, activate=body.activate, manager=ai_jobs)
    except AIJobConflictError:
        raise HTTPException(status_code=409, detail="已经有模型在下载，请等它完成或先停止")
    return job_sse_response(job)
