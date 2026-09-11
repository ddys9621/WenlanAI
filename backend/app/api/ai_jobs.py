"""通用 AI 后台任务 API：列出 / 快照 / 事件回放续尾 / 取消。

各业务的"发起"端点仍在各自模块（带自己的校验与请求体，返回 job_sse_response），发起之后的
重连（刷新 / 切页 / 断网）、停止与移除统一走这里；前端 aiJobsStore 只认这五个端点。

- GET    /api/ai-jobs?project_id=      当前用户的任务（running 优先 + 保留期内的终态）
- GET    /api/ai-jobs/{job_id}         快照
- POST   /api/ai-jobs/{job_id}/events  SSE：从 since 之后回放并续尾到终态（POST 以复用前端 ssePost）
- DELETE /api/ai-jobs/{job_id}         取消（运行中 → 已停止，仍留在列表）
- POST   /api/ai-jobs/{job_id}/dismiss 移除终态任务（托盘 ×）：不移除的话刷新后 GET 列表会把它同步回托盘
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import require_login
from app.models.user import User
from app.services.ai_jobs import AIJob, ai_jobs
from app.utils.sse_response import SSEResponse, create_sse_response

router = APIRouter(prefix="/ai-jobs", tags=["AI 后台任务"])


class JobEventsRequest(BaseModel):
    """事件回放起点：只要 seq > since 的事件。"""
    since: int = Field(default=0, ge=0)


def _owned_job(job_id: str, user_id: str) -> AIJob:
    job = ai_jobs.get(job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


async def stream_job_events(job_id: str, *, since: int = 0, announce: bool = False) -> AsyncGenerator[str, None]:
    """SSE 文本流：announce=True 时先发 start{job_id}（发起端点用），随后回放 + 续尾。"""
    if announce:
        yield SSEResponse.format_sse({"type": "start", "job_id": job_id})
    async for evt in ai_jobs.events(job_id, since=since):
        yield SSEResponse.format_sse(evt)


def job_sse_response(job: AIJob) -> StreamingResponse:
    """供各业务"发起"端点复用：启动任务后返回 start + 从头续尾的 SSE。"""
    return create_sse_response(stream_job_events(job.id, announce=True))


@router.get("")
async def list_jobs_endpoint(
    project_id: Optional[str] = Query(default=None),
    user: User = Depends(require_login),
):
    return {"jobs": [j.snapshot() for j in ai_jobs.list_for_user(user.user_id, project_id=project_id)]}


@router.get("/{job_id}")
async def get_job_endpoint(job_id: str, user: User = Depends(require_login)):
    return _owned_job(job_id, user.user_id).snapshot()


@router.post("/{job_id}/events")
async def job_events_endpoint(
    job_id: str,
    payload: JobEventsRequest,
    user: User = Depends(require_login),
):
    _owned_job(job_id, user.user_id)
    return create_sse_response(stream_job_events(job_id, since=payload.since))


@router.delete("/{job_id}")
async def cancel_job_endpoint(job_id: str, user: User = Depends(require_login)):
    _owned_job(job_id, user.user_id)
    return {"cancelled": await ai_jobs.cancel(job_id)}


@router.post("/{job_id}/dismiss")
async def dismiss_job_endpoint(job_id: str, user: User = Depends(require_login)):
    _owned_job(job_id, user.user_id)
    return {"dismissed": ai_jobs.dismiss(job_id)}
