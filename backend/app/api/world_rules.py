"""世界规则管理 API"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional
import uuid

from app.database import get_db
from app.models.world_rule import WorldRule
from app.schemas.world_rule import (
    WorldRuleCreate,
    WorldRuleUpdate,
    WorldRuleResponse,
    WorldRuleListResponse
)
from app.services.world_rule_service import world_rule_service
from app.logger import get_logger
from app.api.deps import verify_project_access

router = APIRouter(tags=["世界规则系统"])
logger = get_logger(__name__)


@router.get("/projects/{project_id}/world-rules", response_model=WorldRuleListResponse, summary="获取世界规则列表")
async def get_world_rules(
    project_id: str,
    request: Request,
    category: Optional[str] = Query(None, description="规则分类过滤：cultivation_realm/equipment_template"),
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的世界规则列表，支持按分类过滤"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 构建查询条件
    conditions = [WorldRule.project_id == project_id]
    if category:
        conditions.append(WorldRule.category == category)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(WorldRule.id)).where(and_(*conditions))
    )
    total = count_result.scalar_one()
    
    # 获取规则列表（按 order_index 和创建时间排序）
    result = await db.execute(
        select(WorldRule)
        .where(and_(*conditions))
        .order_by(WorldRule.order_index.asc(), WorldRule.created_at.asc())
    )
    rules = result.scalars().all()
    
    return WorldRuleListResponse(total=total, items=rules)


@router.post("/projects/{project_id}/world-rules", response_model=WorldRuleResponse, summary="创建世界规则")
async def create_world_rule(
    project_id: str,
    rule: WorldRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """创建新的世界规则"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 检查同一项目下是否已存在相同 key
    existing = await db.execute(
        select(WorldRule).where(
            WorldRule.project_id == project_id,
            WorldRule.key == rule.key
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"规则标识 '{rule.key}' 已存在")
    
    # 创建新规则
    db_rule = WorldRule(
        id=str(uuid.uuid4()),
        project_id=project_id,
        category=rule.category,
        key=rule.key,
        name=rule.name,
        order_index=rule.order_index,
        summary=rule.summary,
        details=rule.details
    )
    
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)

    # 向量化规则（异步，不阻塞响应）
    try:
        await world_rule_service.upsert_rule_to_vector_db(db_rule)
    except Exception as e:
        logger.warning(f"⚠️ 规则向量化失败（不影响创建）: {str(e)}")

    logger.info(f"创建世界规则: project_id={project_id}, category={rule.category}, key={rule.key}")
    return db_rule


@router.put("/world-rules/{rule_id}", response_model=WorldRuleResponse, summary="更新世界规则")
async def update_world_rule(
    rule_id: str,
    rule_update: WorldRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新指定的世界规则"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 获取规则并验证权限
    result = await db.execute(select(WorldRule).where(WorldRule.id == rule_id))
    db_rule = result.scalar_one_or_none()

    if not db_rule:
        raise HTTPException(status_code=404, detail="世界规则不存在")

    # 验证项目权限
    await verify_project_access(db_rule.project_id, user_id, db)

    # 如果更新 key，检查是否冲突
    if rule_update.key and rule_update.key != db_rule.key:
        existing = await db.execute(
            select(WorldRule).where(
                WorldRule.project_id == db_rule.project_id,
                WorldRule.key == rule_update.key,
                WorldRule.id != rule_id
            )
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail=f"规则标识 '{rule_update.key}' 已存在")

    # 更新字段
    update_data = rule_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_rule, field, value)

    await db.commit()
    await db.refresh(db_rule)

    # 更新向量（异步，不阻塞响应）
    try:
        await world_rule_service.upsert_rule_to_vector_db(db_rule)
    except Exception as e:
        logger.warning(f"⚠️ 规则向量更新失败（不影响更新）: {str(e)}")

    logger.info(f"更新世界规则: rule_id={rule_id}, project_id={db_rule.project_id}")
    return db_rule


@router.delete("/world-rules/{rule_id}", summary="删除世界规则")
async def delete_world_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除指定的世界规则"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 获取规则并验证权限
    result = await db.execute(select(WorldRule).where(WorldRule.id == rule_id))
    db_rule = result.scalar_one_or_none()

    if not db_rule:
        raise HTTPException(status_code=404, detail="世界规则不存在")

    # 验证项目权限
    await verify_project_access(db_rule.project_id, user_id, db)

    # 保存项目ID（删除后无法访问）
    project_id = db_rule.project_id

    # 删除规则
    await db.delete(db_rule)
    await db.commit()

    # 从向量库删除（异步，不阻塞响应）
    try:
        await world_rule_service.delete_rule_from_vector_db(project_id, rule_id)
    except Exception as e:
        logger.warning(f"⚠️ 规则向量删除失败（不影响删除）: {str(e)}")

    logger.info(f"删除世界规则: rule_id={rule_id}, project_id={project_id}")
    return {"message": "删除成功"}

