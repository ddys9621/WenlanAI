"""世界设定条目管理 API（术语 / 铁律 / 势力 / 通用规则等；与世界规则的境界·装备·地图三类互补）。

每条独立容量、生成时语义检索注入，让作者不必再把海量世界观堆进 project.world_rules 单字段撑爆上限。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_project_access
from app.database import get_db
from app.logger import get_logger
from app.models.setting_entry import SettingEntry
from app.schemas.setting_entry import (
    SettingEntryCreate, SettingEntryListResponse, SettingEntryResponse, SettingEntryUpdate,
)
from app.services import setting_entry_service

router = APIRouter(tags=["世界设定条目"])
logger = get_logger(__name__)


async def _sync(entry: SettingEntry, what: str) -> None:
    try:
        await setting_entry_service.setting_entry_index().sync(entry)
    except Exception as exc:  # noqa: BLE001 - 向量只是增强，失败不影响主流程
        logger.warning(f"⚠️ 设定条目向量{what}失败（不影响）：{exc}")


@router.get("/projects/{project_id}/setting-entries", response_model=SettingEntryListResponse, summary="获取世界设定条目列表")
async def list_setting_entries(
    project_id: str, request: Request, category: Optional[str] = Query(None, description="分类过滤"),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(project_id, getattr(request.state, "user_id", None), db)
    items = await setting_entry_service.list_entries(db, project_id, category)
    return SettingEntryListResponse(total=len(items), items=items)


@router.post("/projects/{project_id}/setting-entries", response_model=SettingEntryResponse, summary="创建世界设定条目")
async def create_setting_entry(
    project_id: str, body: SettingEntryCreate, request: Request, db: AsyncSession = Depends(get_db),
):
    await verify_project_access(project_id, getattr(request.state, "user_id", None), db)
    entry = await setting_entry_service.create_entry(
        db, project_id, category=body.category, title=body.title, summary=body.summary or "",
        content=body.content or "", order_index=body.order_index,
    )
    await db.commit()
    await db.refresh(entry)
    await _sync(entry, "化")
    logger.info(f"创建世界设定条目: project_id={project_id}, category={entry.category}, title={entry.title}")
    return entry


@router.put("/setting-entries/{entry_id}", response_model=SettingEntryResponse, summary="更新世界设定条目")
async def update_setting_entry(
    entry_id: str, body: SettingEntryUpdate, request: Request, db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    entry = await db.get(SettingEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="设定条目不存在")
    await verify_project_access(entry.project_id, user_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    await _sync(entry, "更新")
    return entry


@router.delete("/setting-entries/{entry_id}", summary="删除世界设定条目")
async def delete_setting_entry(entry_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    entry = await db.get(SettingEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="设定条目不存在")
    await verify_project_access(entry.project_id, user_id, db)
    project_id = entry.project_id
    await db.delete(entry)
    await db.commit()
    try:
        await setting_entry_service.setting_entry_index().remove(project_id, entry_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"⚠️ 设定条目向量删除失败（不影响）：{exc}")
    return {"message": "删除成功"}
