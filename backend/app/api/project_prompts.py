"""项目自定义提示词：/projects/{project_id}/prompts（列出 / 保存 / 单条恢复默认 / 全部恢复默认）。

只开放 services/project_prompts 登记的写作指导；输出格式、作品资料由各生成器自动拼接，不经过这里。
保存后从库里读回再返回：主库是单连接共用事务，别的请求收尾回滚可能冲掉这次写入，前端按回显核对。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_login, verify_project_access
from app.database import get_db
from app.models.project import Project
from app.schemas.project_prompt import ProjectPromptSave
from app.services import project_prompts as pp
from app.user_manager import User

router = APIRouter(prefix="/projects", tags=["项目提示词"])


def _spec(key: str) -> pp.PromptSpec:
    try:
        return pp.spec(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这条提示词")


async def _views(db: AsyncSession, project: Project, specs=pp.PROMPT_SPECS) -> list[dict]:
    rows = await pp.override_rows(db, project.id)
    ctx = pp.PromptContext.of(project)
    return [pp.prompt_view(s, ctx, rows.get(s.key)) for s in specs]


@router.get("/{project_id}/prompts", summary="列出项目可改的提示词")
async def list_project_prompts(project_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    project = await verify_project_access(project_id, user.user_id, db)
    groups = [{"id": g.id, "title": g.title, "description": g.description} for g in pp.PROMPT_GROUPS]
    return {"groups": groups, "items": await _views(db, project)}


@router.put("/{project_id}/prompts/{key}", summary="保存一条自定义提示词")
async def save_project_prompt(
    project_id: str, key: str, data: ProjectPromptSave,
    user: User = Depends(require_login), db: AsyncSession = Depends(get_db),
):
    project = await verify_project_access(project_id, user.user_id, db)
    spec = _spec(key)
    errors = pp.validate(key, data.content)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    await pp.save_override(db, project, key, data.content)
    await db.commit()
    return (await _views(db, project, [spec]))[0]


@router.delete("/{project_id}/prompts/{key}", summary="一条提示词恢复默认")
async def reset_project_prompt(
    project_id: str, key: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db),
):
    project = await verify_project_access(project_id, user.user_id, db)
    spec = _spec(key)
    await pp.reset_overrides(db, project.id, [key])
    await db.commit()
    return (await _views(db, project, [spec]))[0]


@router.delete("/{project_id}/prompts", summary="全部提示词恢复默认")
async def reset_all_project_prompts(project_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    project = await verify_project_access(project_id, user.user_id, db)
    count = await pp.reset_overrides(db, project.id)
    await db.commit()
    return {"reset": count, "items": await _views(db, project)}
