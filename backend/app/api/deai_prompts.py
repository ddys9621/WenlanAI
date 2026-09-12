"""项目级去 AI 味提示词 CRUD：/projects/{project_id}/deai-prompts。

提示词只在「去 AI 味重写」时注入（api/chapters.py::regenerate_chapter_stream），首次生成不用。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_login, verify_project_access
from app.database import get_db
from app.models.deai_prompt import DeaiPrompt
from app.schemas.deai_prompt import DeaiPromptCreate, DeaiPromptResponse, DeaiPromptUpdate
from app.user_manager import User

router = APIRouter(prefix="/projects", tags=["去 AI 味提示词"])


async def _get_owned_prompt(db: AsyncSession, project_id: str, prompt_id: str) -> DeaiPrompt:
    row = (await db.execute(
        select(DeaiPrompt).where(DeaiPrompt.id == prompt_id, DeaiPrompt.project_id == project_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return row


@router.get("/{project_id}/deai-prompts", response_model=list[DeaiPromptResponse], summary="列出项目的去 AI 味提示词")
async def list_deai_prompts(project_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await verify_project_access(project_id, user.user_id, db)
    return (await db.execute(
        select(DeaiPrompt).where(DeaiPrompt.project_id == project_id).order_by(DeaiPrompt.order_index, DeaiPrompt.created_at)
    )).scalars().all()


@router.post("/{project_id}/deai-prompts", response_model=DeaiPromptResponse, status_code=201, summary="新增去 AI 味提示词")
async def create_deai_prompt(project_id: str, data: DeaiPromptCreate, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await verify_project_access(project_id, user.user_id, db)
    next_order = (await db.execute(
        select(func.coalesce(func.max(DeaiPrompt.order_index), -1)).where(DeaiPrompt.project_id == project_id)
    )).scalar_one() + 1
    row = DeaiPrompt(project_id=project_id, name=data.name, content=data.content, order_index=next_order)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.put("/{project_id}/deai-prompts/{prompt_id}", response_model=DeaiPromptResponse, summary="修改去 AI 味提示词")
async def update_deai_prompt(project_id: str, prompt_id: str, data: DeaiPromptUpdate, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await verify_project_access(project_id, user.user_id, db)
    row = await _get_owned_prompt(db, project_id, prompt_id)
    if data.name is not None:
        row.name = data.name
    if data.content is not None:
        row.content = data.content
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/deai-prompts/{prompt_id}", summary="删除去 AI 味提示词")
async def delete_deai_prompt(project_id: str, prompt_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    await verify_project_access(project_id, user.user_id, db)
    await db.delete(await _get_owned_prompt(db, project_id, prompt_id))
    await db.commit()
    return {"message": "已删除"}
