"""写作风格管理 API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from typing import List

from ..database import get_db
from ..models.writing_style import WritingStyle
from ..models.project_default_style import ProjectDefaultStyle
from ..schemas.writing_style import (
    WritingStyleCreate,
    WritingStyleUpdate,
    WritingStyleResponse,
    WritingStyleListResponse,
    SetDefaultStyleRequest
)
from ..services.prompt_service import WritingStyleManager
from ..logger import get_logger
from app.api.deps import verify_project_access

router = APIRouter(prefix="/writing-styles", tags=["writing-styles"])
logger = get_logger(__name__)


@router.get("/presets/list", response_model=List[dict])
async def get_preset_styles():
    """
    获取所有预设风格列表
    
    返回格式：数组形式的预设风格列表
    [
        {"id": "natural", "name": "自然流畅", "description": "...", "prompt_content": "..."},
        {"id": "classical", "name": "古风韵味", ...}
    ]
    """
    presets = WritingStyleManager.get_all_presets()
    # 将字典转换为数组，添加 id 字段
    return [
        {"id": preset_id, **preset_data}
        for preset_id, preset_data in presets.items()
    ]


@router.post("", response_model=WritingStyleResponse, status_code=201)
async def create_writing_style(
    style_data: WritingStyleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    创建新的写作风格
    
    - **基于预设创建**：提供 preset_id，系统会自动填充预设内容
    - **完全自定义**：不提供 preset_id，需要手动填写所有字段
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(style_data.project_id, user_id, db)
    
    # 如果基于预设创建，获取预设内容
    if style_data.preset_id:
        preset = WritingStyleManager.get_preset_style(style_data.preset_id)
        if not preset:
            raise HTTPException(status_code=400, detail=f"预设风格 '{style_data.preset_id}' 不存在")
        
        # 使用预设内容填充（如果用户未提供）
        if not style_data.name:
            style_data.name = preset["name"]
        if not style_data.description:
            style_data.description = preset["description"]
        if not style_data.prompt_content:
            style_data.prompt_content = preset["prompt_content"]
    
    # 验证必填字段
    if not style_data.name or not style_data.prompt_content:
        raise HTTPException(
            status_code=400,
            detail="name 和 prompt_content 是必填字段"
        )
    
    # 获取当前最大 order_index
    count_result = await db.execute(
        select(func.count(WritingStyle.id))
        .where(WritingStyle.project_id == style_data.project_id)
    )
    max_order = count_result.scalar_one()
    
    # 创建风格记录
    new_style = WritingStyle(
        project_id=style_data.project_id,
        name=style_data.name,
        style_type=style_data.style_type or ("preset" if style_data.preset_id else "custom"),
        preset_id=style_data.preset_id,
        description=style_data.description,
        prompt_content=style_data.prompt_content,
        order_index=max_order + 1
    )
    
    db.add(new_style)
    await db.commit()
    await db.refresh(new_style)
    
    # 返回包含 is_default 字段的字典（新创建的风格默认不是默认风格）
    return {
        "id": new_style.id,
        "project_id": new_style.project_id,
        "name": new_style.name,
        "style_type": new_style.style_type,
        "preset_id": new_style.preset_id,
        "description": new_style.description,
        "prompt_content": new_style.prompt_content,
        "order_index": new_style.order_index,
        "created_at": new_style.created_at,
        "updated_at": new_style.updated_at,
        "is_default": False
    }


@router.get("/project/{project_id}", response_model=WritingStyleListResponse)
async def get_project_styles(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取项目的所有可用写作风格
    
    返回：全局预设风格 + 该项目的自定义风格
    按 order_index 排序，并标记哪个是当前项目的默认风格
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取该项目的默认风格ID
    result = await db.execute(
        select(ProjectDefaultStyle.style_id)
        .where(ProjectDefaultStyle.project_id == project_id)
    )
    default_style_id = result.scalar_one_or_none()
    
    # 获取全局预设风格（project_id 为 NULL）
    result = await db.execute(
        select(WritingStyle)
        .where(WritingStyle.project_id.is_(None))
        .order_by(WritingStyle.order_index)
    )
    preset_styles = list(result.scalars().all())
    
    # 获取项目自定义风格
    result = await db.execute(
        select(WritingStyle)
        .where(WritingStyle.project_id == project_id)
        .order_by(WritingStyle.order_index)
    )
    custom_styles = list(result.scalars().all())
    
    # 合并：预设风格 + 自定义风格
    all_styles = preset_styles + custom_styles
    
    # 为每个风格添加 is_default 标记（用于前端显示）
    styles_with_default = []
    for style in all_styles:
        style_dict = {
            "id": style.id,
            "project_id": style.project_id,
            "name": style.name,
            "style_type": style.style_type,
            "preset_id": style.preset_id,
            "description": style.description,
            "prompt_content": style.prompt_content,
            "order_index": style.order_index,
            "created_at": style.created_at,
            "updated_at": style.updated_at,
            "is_default": style.id == default_style_id
        }
        styles_with_default.append(style_dict)
    
    return {"styles": styles_with_default, "total": len(styles_with_default)}


@router.get("/{style_id}", response_model=WritingStyleResponse)
async def get_writing_style(
    style_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取单个写作风格详情"""
    result = await db.execute(
        select(WritingStyle).where(WritingStyle.id == style_id)
    )
    style = result.scalar_one_or_none()
    if not style:
        raise HTTPException(status_code=404, detail="写作风格不存在")
    
    # 检查是否有项目将其设置为默认风格（全局预设可同时是多个项目的默认，可能命中多行）
    result = await db.execute(
        select(ProjectDefaultStyle).where(ProjectDefaultStyle.style_id == style_id)
    )
    is_default = result.scalars().first() is not None
    
    # 返回包含 is_default 字段的字典
    return {
        "id": style.id,
        "project_id": style.project_id,
        "name": style.name,
        "style_type": style.style_type,
        "preset_id": style.preset_id,
        "description": style.description,
        "prompt_content": style.prompt_content,
        "order_index": style.order_index,
        "created_at": style.created_at,
        "updated_at": style.updated_at,
        "is_default": is_default
    }


@router.put("/{style_id}", response_model=WritingStyleResponse)
async def update_writing_style(
    style_id: int,
    style_data: WritingStyleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    更新写作风格
    
    - 只能修改自定义风格
    - 不能修改全局预设风格
    """
    result = await db.execute(
        select(WritingStyle).where(WritingStyle.id == style_id)
    )
    style = result.scalar_one_or_none()
    if not style:
        raise HTTPException(status_code=404, detail="写作风格不存在")
    
    # 检查是否为全局预设风格（不允许修改）
    if style.project_id is None:
        raise HTTPException(status_code=403, detail="不能修改全局预设风格，只能修改自定义风格")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(style.project_id, user_id, db)
    
    # 更新字段
    update_data = style_data.model_dump(exclude_unset=True)
    
    # 如果修改了内容，将 style_type 改为 custom
    if any(key in update_data for key in ["name", "description", "prompt_content"]):
        update_data["style_type"] = "custom"
    
    for key, value in update_data.items():
        setattr(style, key, value)
    
    await db.commit()
    await db.refresh(style)
    
    # 检查是否有项目将其设置为默认风格
    result = await db.execute(
        select(ProjectDefaultStyle).where(ProjectDefaultStyle.style_id == style_id)
    )
    is_default = result.scalars().first() is not None
    
    # 返回包含 is_default 字段的字典
    return {
        "id": style.id,
        "project_id": style.project_id,
        "name": style.name,
        "style_type": style.style_type,
        "preset_id": style.preset_id,
        "description": style.description,
        "prompt_content": style.prompt_content,
        "order_index": style.order_index,
        "created_at": style.created_at,
        "updated_at": style.updated_at,
        "is_default": is_default
    }


@router.delete("/{style_id}", status_code=204)
async def delete_writing_style(
    style_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    删除写作风格
    
    注意：
    - 只能删除自定义风格，不能删除全局预设风格
    - 不能删除默认风格（必须先设置其他风格为默认）
    - 删除后无法恢复
    """
    result = await db.execute(
        select(WritingStyle).where(WritingStyle.id == style_id)
    )
    style = result.scalar_one_or_none()
    if not style:
        raise HTTPException(status_code=404, detail="写作风格不存在")
    
    # 检查是否为全局预设风格（不允许删除）
    if style.project_id is None:
        raise HTTPException(status_code=403, detail="不能删除全局预设风格，只能删除自定义风格")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(style.project_id, user_id, db)
    
    # 检查是否有项目将其设置为默认风格
    result = await db.execute(
        select(ProjectDefaultStyle).where(ProjectDefaultStyle.style_id == style_id)
    )
    default_relation = result.scalars().first()
    if default_relation:
        raise HTTPException(
            status_code=400,
            detail="不能删除默认风格，请先设置其他风格为默认"
        )
    
    await db.delete(style)
    await db.commit()
    
    return None


@router.post("/{style_id}/set-default", response_model=dict)
async def set_default_style(
    style_id: int,
    request_data: SetDefaultStyleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    将指定风格设置为项目的默认风格
    
    使用 project_default_styles 表记录项目的默认风格选择
    每个项目只能有一个默认风格（通过 UniqueConstraint 保证）
    
    参数：
    - style_id: 要设置为默认的风格ID（路径参数）
    - project_id: 项目ID（请求体），用于确定在哪个项目上下文中设置默认
    """
    project_id = request_data.project_id
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 验证风格是否存在
    result = await db.execute(
        select(WritingStyle).where(WritingStyle.id == style_id)
    )
    style = result.scalar_one_or_none()
    if not style:
        raise HTTPException(status_code=404, detail="写作风格不存在")
    
    # 验证风格是否属于该项目（自定义风格）或是全局预设风格
    if style.project_id is not None and style.project_id != project_id:
        raise HTTPException(status_code=403, detail="无权操作其他项目的风格")
    
    # 使用 UPSERT 逻辑：先删除该项目的旧默认风格记录，再插入新的
    await db.execute(
        delete(ProjectDefaultStyle).where(ProjectDefaultStyle.project_id == project_id)
    )
    
    # 插入新的默认风格记录
    new_default = ProjectDefaultStyle(
        project_id=project_id,
        style_id=style_id
    )
    db.add(new_default)
    await db.commit()
    
    return {
        "message": "默认风格设置成功",
        "project_id": project_id,
        "style_id": style_id,
        "style_name": style.name
    }
