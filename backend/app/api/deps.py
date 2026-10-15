"""API 层公共依赖：登录校验与项目归属校验。

此前 8 个 api 模块各有一份逐字相同的 verify_project_access、5 个模块各有一份 require_login；
统一到这里。
"""
from typing import Any, Iterable, Optional

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.project import Project
from app.models.user import User

logger = get_logger(__name__)


def require_login(request: Request) -> User:
    """依赖：要求用户已登录"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="需要登录")
    return request.state.user


def require_admin(request: Request) -> User:
    """依赖：要求管理员（未登录 401，非管理员 403）"""
    user = require_login(request)
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def verify_project_access(project_id: str, user_id: str, db: AsyncSession) -> Project:
    """
    验证用户是否有权访问指定项目

    Raises:
        HTTPException: 401 未登录，404 项目不存在或无权访问
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        logger.warning(f"项目访问被拒绝: project_id={project_id}, user_id={user_id}")
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")

    return project


def request_user_id(request: Any) -> Optional[str]:
    return getattr(getattr(request, "state", None), "user_id", None)


async def verify_request_project(request: Any, project_id: str, db: AsyncSession) -> Project:
    """按请求里的登录用户校验项目归属（所有用户共用一个数据库，只按 ID 查会越权）。"""
    return await verify_project_access(project_id, request_user_id(request), db)


async def load_owned(db: AsyncSession, request: Any, model: Any, object_id: str, not_found: str = "记录不存在") -> Any:
    """按 ID 取一条带 project_id 的记录并校验它所属项目归当前用户；不存在或无权一律 404。"""
    obj = (await db.execute(select(model).where(model.id == object_id))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=not_found)
    await verify_project_access(obj.project_id, request_user_id(request), db)
    return obj


async def verify_owned_ids(db: AsyncSession, request: Any, model: Any, ids: Iterable[str]) -> None:
    """批量操作（排序等）里的每条记录都必须属于当前用户的项目。"""
    wanted = {i for i in ids if i}
    if not wanted:
        return
    rows = (await db.execute(select(model.id, model.project_id).where(model.id.in_(wanted)))).all()
    if len(rows) != len(wanted):
        raise HTTPException(status_code=404, detail="记录不存在")
    for project_id in {project_id for _id, project_id in rows}:
        await verify_project_access(project_id, request_user_id(request), db)
