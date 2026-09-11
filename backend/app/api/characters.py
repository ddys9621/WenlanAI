"""角色管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json
from typing import Optional

from app.database import get_db
from app.models.character import Character
from app.models.relationship import Organization, OrganizationMember
from app.services.character_rename_service import propagate_character_rename
from app.schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterListResponse,
    CharacterGenerateRequest
)
from app.api.ai_jobs import job_sse_response
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.character_generation_service import make_character_runner
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.utils.role_type import normalize_role_type
from app.utils.character_names import record_former_name
from app.api.deps import verify_project_access

router = APIRouter(prefix="/characters", tags=["角色管理"])
logger = get_logger(__name__)


def _parse_member_snapshot(raw: Optional[str]) -> list[str]:
    """解析 Character.organization_members 名字快照（AI 生成/导入写入），非法 JSON 视为空。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    names = []
    for item in parsed:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


async def _load_org_member_names(project_id: str, db: AsyncSession) -> dict[str, list[str]]:
    """按组织角色 ID 归组的在籍成员名：OrganizationMember JOIN Character 读时派生，改名后自然是新名。"""
    result = await db.execute(
        select(Organization.character_id, Character.name)
        .join_from(Organization, OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(Character, Character.id == OrganizationMember.character_id)
        .where(Organization.project_id == project_id, OrganizationMember.status == "active")
        .order_by(OrganizationMember.rank.desc(), OrganizationMember.created_at)
    )
    names: dict[str, list[str]] = {}
    for org_character_id, member_name in result.all():
        names.setdefault(org_character_id, []).append(member_name)
    return names


async def _build_character_list(project_id: str, db: AsyncSession) -> CharacterListResponse:
    """项目角色列表；组织条目附带 Organization 扩展字段与派生的成员名。"""
    count_result = await db.execute(
        select(func.count(Character.id)).where(Character.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    
    org_result = await db.execute(select(Organization).where(Organization.project_id == project_id))
    org_by_character = {org.character_id: org for org in org_result.scalars().all()}
    member_names_by_org = await _load_org_member_names(project_id, db)
    
    # 为组织类型的角色填充Organization表的额外字段
    enriched_characters = []
    for char in characters:
        char_dict = {
            "id": char.id,
            "project_id": char.project_id,
            "name": char.name,
            "aliases": char.aliases,
            "age": char.age,
            "gender": char.gender,
            "is_organization": char.is_organization,
            "role_type": char.role_type,
            "personality": char.personality,
            "background": char.background,
            "appearance": char.appearance,
            "relationships": char.relationships,
            "organization_type": char.organization_type,
            "organization_purpose": char.organization_purpose,
            "organization_members": char.organization_members,
            "traits": char.traits,
            "avatar_url": char.avatar_url,
            "created_at": char.created_at,
            "updated_at": char.updated_at,
            "power_level": None,
            "location": None,
            "motto": None,
            "color": None,
            "member_names": None,
        }
        
        if char.is_organization:
            org = org_by_character.get(char.id)
            if org:
                char_dict.update({
                    "power_level": org.power_level,
                    "location": org.location,
                    "motto": org.motto,
                    "color": org.color
                })
            # 有成员关系记录以关系表为准；没有（典型：AI 刚生成的组织）才回退到快照
            char_dict["member_names"] = (
                member_names_by_org.get(char.id) or _parse_member_snapshot(char.organization_members)
            )
        
        enriched_characters.append(char_dict)
    
    return CharacterListResponse(total=total, items=enriched_characters)


@router.get("", response_model=CharacterListResponse, summary="获取角色列表")
async def get_characters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有角色（query参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    return await _build_character_list(project_id, db)


@router.get("/project/{project_id}", response_model=CharacterListResponse, summary="获取项目的所有角色")
async def get_project_characters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有角色（路径参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    return await _build_character_list(project_id, db)


@router.get("/{character_id}", response_model=CharacterResponse, summary="获取角色详情")
async def get_character(
    character_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取角色详情"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    return character


@router.put("/{character_id}", response_model=CharacterResponse, summary="更新角色")
async def update_character(
    character_id: str,
    character_update: CharacterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新角色信息"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    # 更新字段
    old_name = character.name
    update_data = character_update.model_dump(exclude_unset=True)
    if "role_type" in update_data:
        update_data["role_type"] = normalize_role_type(update_data["role_type"], character.role_type)
    for field, value in update_data.items():
        setattr(character, field, value)
    
    # 改名：把其它表里的名字快照一并改掉（同一事务），旧名记入曾用名供按名匹配兜底
    new_name = update_data.get("name")
    if new_name and old_name and new_name.strip() != old_name.strip():
        await propagate_character_rename(db, character.project_id, old_name, new_name)
        character.aliases = record_former_name(character.aliases, old_name, new_name)
    
    await db.commit()
    await db.refresh(character)
    return character


@router.delete("/{character_id}", summary="删除角色")
async def delete_character(
    character_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除角色"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    await db.delete(character)
    await db.commit()
    
    return {"message": "角色删除成功"}


@router.post("", response_model=CharacterResponse, summary="手动创建角色")
async def create_character(
    character_data: CharacterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    手动创建角色或组织
    
    - 可以创建普通角色（is_organization=False）
    - 也可以创建组织（is_organization=True）
    - 如果创建组织且提供了组织额外字段，会自动创建Organization详情记录
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character_data.project_id, user_id, db)
    
    try:
        # 创建角色
        character = Character(
            project_id=character_data.project_id,
            name=character_data.name,
            age=character_data.age,
            gender=character_data.gender,
            is_organization=character_data.is_organization,
            role_type=normalize_role_type(character_data.role_type, "supporting"),
            personality=character_data.personality,
            background=character_data.background,
            appearance=character_data.appearance,
            relationships=character_data.relationships,
            organization_type=character_data.organization_type,
            organization_purpose=character_data.organization_purpose,
            organization_members=character_data.organization_members,
            traits=character_data.traits,
            avatar_url=character_data.avatar_url
        )
        db.add(character)
        await db.flush()  # 获取character.id
        
        logger.info(f"✅ 手动创建角色成功：{character.name} (ID: {character.id}, 是否组织: {character.is_organization})")
        
        # 如果是组织，且提供了组织额外字段，自动创建Organization详情记录
        if character.is_organization and (
            character_data.power_level is not None or
            character_data.location or
            character_data.motto or
            character_data.color
        ):
            organization = Organization(
                character_id=character.id,
                project_id=character_data.project_id,
                member_count=0,
                power_level=character_data.power_level or 50,
                location=character_data.location,
                motto=character_data.motto,
                color=character_data.color
            )
            db.add(organization)
            await db.flush()
            logger.info(f"✅ 自动创建组织详情：{character.name} (Org ID: {organization.id})")
        
        await db.commit()
        await db.refresh(character)
        
        logger.info(f"🎉 成功手动创建角色/组织: {character.name}")
        
        return character
        
    except Exception as e:
        logger.error(f"手动创建角色失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建角色失败: {str(e)}")

@router.post("/generate-stream", summary="AI生成角色（后台任务 + SSE 事件流）")
async def generate_character_stream(
    request: CharacterGenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """启动后台任务并从头流式输出其事件：start → stage / tool_call / reference / llm / progress → result(角色) → done。

    任务寿命独立于本连接（关弹窗 / 刷新 / 切页不中断）；重连与停止走 /api/ai-jobs/*。
    同项目已有角色生成在跑 → 409。生成逻辑见 services/character_generation_service.py。
    """
    user_id = getattr(http_request.state, "user_id", None)
    project = await verify_project_access(request.project_id, user_id, db)
    name = (request.name or "").strip()
    runner = make_character_runner(
        user_id=user_id,
        project_id=project.id,
        request=request,
        ai_service=user_ai_service,
        session_factory=job_session_factory(user_id),
    )
    try:
        job = await ai_jobs.start(
            kind="character_generate",
            title=f"AI 生成角色「{name}」" if name else "AI 生成角色",
            user_id=user_id,
            project_id=project.id,
            runner=runner,
            cancel_message="已停止生成角色",
            meta={"role_type": request.role_type, "enable_mcp": request.enable_mcp},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)