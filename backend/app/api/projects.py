"""项目管理API"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
import json
from urllib.parse import quote
from app.database import get_db
from app.models.project import Project
from app.models.character import Character
from app.models.story_outline import StoryOutline
from app.models.chapter import Chapter
from app.models.generation_history import GenerationHistory
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse
)
from app.schemas.import_export import (
    ExportOptions,
    ImportValidationResult,
    ImportResult
)
from app.services.import_export_service import ImportExportService
from app.services.memory_service import memory_service
from app.services.platform_presets import normalize_longform_settings
from app.logger import get_logger
from app.utils.data_consistency import (
    run_full_data_consistency_check,
    fix_missing_organization_records,
    fix_organization_member_counts
)

logger = get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["项目管理"])


@router.post("", response_model=ProjectResponse, summary="创建项目")
async def create_project(
    project: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试创建项目")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"创建新项目: {project.title}, user_id={user_id}")
        
        # 创建项目时自动设置user_id
        project_data = project.model_dump()
        longform = normalize_longform_settings(project_data)  # 平台预设（只收合法值）
        project_data.pop("platform_preset", None)
        project_data.update(longform)
        project_data['user_id'] = user_id
        db_project = Project(**project_data)
        
        db.add(db_project)
        await db.commit()
        await db.refresh(db_project)
        logger.info(f"项目创建成功: project_id={db_project.id}, user_id={user_id}")
        
        return db_project
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建项目失败: {str(e)}", exc_info=True)
        raise


@router.get("", response_model=ProjectListResponse, summary="获取项目列表")
async def get_projects(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    """获取当前用户的项目列表"""
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试获取项目列表")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.debug(f"获取项目列表: user_id={user_id}, skip={skip}, limit={limit}")
        
        # 只查询当前用户的项目
        count_result = await db.execute(
            select(func.count(Project.id)).where(Project.user_id == user_id)
        )
        total = count_result.scalar_one()
        
        result = await db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        projects = result.scalars().all()
        logger.info(f"获取项目列表成功: user_id={user_id}, 共{total}个项目")
        
        return ProjectListResponse(total=total, items=projects)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目列表失败: {str(e)}", exc_info=True)
        raise


@router.get("/{project_id}", response_model=ProjectResponse, summary="获取项目详情")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试获取项目详情")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.debug(f"获取项目详情: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        logger.info(f"获取项目详情成功: {project.title}")
        return project
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目详情失败: {str(e)}", exc_info=True)
        raise


@router.put("/{project_id}", response_model=ProjectResponse, summary="更新项目")
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试更新项目")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"更新项目: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        update_data = project_update.model_dump(exclude_unset=True)
        logger.debug(f"更新字段: {list(update_data.keys())}")
        for field, value in update_data.items():
            setattr(project, field, value)
        
        await db.commit()
        await db.refresh(project)
        logger.info(f"项目更新成功: {project.title}")
        return project
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新项目失败: {str(e)}", exc_info=True)
        raise


@router.delete("/{project_id}", summary="删除项目")
async def delete_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试删除项目")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"删除项目: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        project_title = project.title
        
        # 删除向量数据库中的记忆（user_id已在上面获取）
        if user_id:
            try:
                await memory_service.delete_project_memories(user_id, project_id)
                logger.info(f"✅ 向量数据库清理成功")
            except Exception as e:
                logger.warning(f"⚠️ 向量数据库清理失败（继续删除其他数据）: {str(e)}")
        else:
            logger.warning(f"⚠️ 未找到用户ID，跳过向量数据库清理")
        
        relationships_result = await db.execute(
            delete(CharacterRelationship).where(CharacterRelationship.project_id == project_id)
        )
        logger.debug(f"删除角色关系数: {relationships_result.rowcount}")
        
        orgs_result = await db.execute(
            select(Organization).where(Organization.project_id == project_id)
        )
        orgs = orgs_result.scalars().all()
        org_member_count = 0
        for org in orgs:
            members_result = await db.execute(
                delete(OrganizationMember).where(OrganizationMember.organization_id == org.id)
            )
            org_member_count += members_result.rowcount
        logger.debug(f"删除组织成员数: {org_member_count}")
        
        organizations_result = await db.execute(
            delete(Organization).where(Organization.project_id == project_id)
        )
        logger.debug(f"删除组织数: {organizations_result.rowcount}")
        
        history_result = await db.execute(
            delete(GenerationHistory).where(GenerationHistory.project_id == project_id)
        )
        logger.debug(f"删除生成历史数: {history_result.rowcount}")
        
        chapters_result = await db.execute(
            delete(Chapter).where(Chapter.project_id == project_id)
        )
        logger.debug(f"删除章节数: {chapters_result.rowcount}")
        
        outlines_result = await db.execute(
            delete(StoryOutline).where(StoryOutline.project_id == project_id)
        )
        logger.debug(f"删除大纲数: {outlines_result.rowcount}")
        
        characters_result = await db.execute(
            delete(Character).where(Character.project_id == project_id)
        )
        logger.debug(f"删除角色数: {characters_result.rowcount}")
        
        # 注意：StoryMemory和PlotAnalysis会通过数据库级联删除自动清理
        # 但向量数据库已在上面手动清理
        
        await db.delete(project)
        await db.commit()
        
        logger.info(f"项目删除成功: {project_title}")
        return {"message": "项目及所有关联数据（包括向量数据库）删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除项目失败: {str(e)}", exc_info=True)
        raise


@router.get("/{project_id}/export", summary="导出项目章节为TXT")
async def export_project_chapters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    """
    导出项目的所有章节内容为TXT文本文件
    按章节顺序组织，包含项目基本信息
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试导出项目")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始导出项目: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        chapters_result = await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_number)
        )
        chapters = chapters_result.scalars().all()
        
        if not chapters:
            logger.warning(f"项目没有章节: {project_id}")
            raise HTTPException(status_code=404, detail="项目没有任何章节")
        
        txt_content = []
        
        txt_content.append("=" * 80)
        txt_content.append(f"项目标题: {project.title}")
        txt_content.append("=" * 80)
        
        if project.description:
            txt_content.append(f"\n简介: {project.description}\n")
        
        if project.theme:
            txt_content.append(f"主题: {project.theme}")
        
        if project.genre:
            txt_content.append(f"类型: {project.genre}")
        
        txt_content.append(f"总章节数: {len(chapters)}")
        txt_content.append(f"总字数: {project.current_words}")
        txt_content.append("\n" + "=" * 80 + "\n\n")
        
        for chapter in chapters:
            txt_content.append(f"第 {chapter.chapter_number} 章  {chapter.title}")
            txt_content.append("-" * 80)
            txt_content.append("")  # 空行
            
            if chapter.content:
                txt_content.append(chapter.content)
            else:
                txt_content.append("（本章暂无内容）")
            
            txt_content.append("\n\n" + "=" * 80 + "\n\n")
        
        txt_content.append(f"--- 全文完 ---")
        
        # 获取当前时间
        from datetime import datetime
        export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        txt_content.append(f"\n导出时间: {export_time}")
        
        final_content = "\n".join(txt_content)
        
        safe_title = "".join(c for c in project.title if c.isalnum() or c in (' ', '-', '_', '，', '。', '、'))
        filename = f"{safe_title}.txt"
        
        from urllib.parse import quote
        encoded_filename = quote(filename)
        
        logger.info(f"导出成功: {filename}, 共{len(chapters)}章, {len(final_content)}字符")
        
        return Response(
            content=final_content.encode('utf-8'),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "Content-Type": "text/plain; charset=utf-8"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出项目失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.post("/{project_id}/check-consistency", summary="检查数据一致性")
async def check_project_consistency(
    project_id: str,
    request: Request,
    auto_fix: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """
    检查并修复项目的数据一致性问题
    
    Args:
        project_id: 项目ID
        auto_fix: 是否自动修复问题（默认True）
    
    返回检查报告，包含：
    - organization_records: 检查并修复缺失的Organization记录
    - member_counts: 检查并修复组织成员计数
    - relationships: 验证关系数据完整性
    - organization_members: 验证组织成员数据完整性
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试检查数据一致性")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始数据一致性检查: project_id={project_id}, user_id={user_id}, auto_fix={auto_fix}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        report = await run_full_data_consistency_check(project_id, db, auto_fix)
        
        logger.info(f"数据一致性检查完成: {project_id}")
        return report
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"数据一致性检查失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@router.post("/{project_id}/fix-organizations", summary="修复组织记录")
async def fix_project_organizations(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    修复项目中缺失的Organization记录
    
    为所有is_organization=True但没有Organization记录的Character创建记录
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试修复组织记录")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始修复组织记录: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        fixed_count, total_count = await fix_missing_organization_records(project_id, db)
        
        logger.info(f"组织记录修复完成: {project_id}, 修复{fixed_count}/{total_count}")
        return {
            "success": True,
            "message": "组织记录修复完成",
            "fixed_count": fixed_count,
            "total_count": total_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修复组织记录失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修复失败: {str(e)}")


@router.post("/{project_id}/fix-member-counts", summary="修复成员计数")
async def fix_project_member_counts(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    修复项目中所有组织的成员计数
    
    从实际成员记录重新计算每个组织的member_count
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试修复成员计数")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始修复成员计数: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        fixed_count, total_count = await fix_organization_member_counts(project_id, db)
        
        logger.info(f"成员计数修复完成: {project_id}, 修复{fixed_count}/{total_count}")
        return {
            "success": True,
            "message": "成员计数修复完成",
            "fixed_count": fixed_count,
            "total_count": total_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修复成员计数失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修复失败: {str(e)}")


@router.post("/{project_id}/export-data", summary="导出项目数据为JSON")
async def export_project_data(
    project_id: str,
    request: Request,
    options: ExportOptions,
    db: AsyncSession = Depends(get_db)
):
    """
    导出项目完整数据为JSON格式
    
    Args:
        project_id: 项目ID
        options: 导出选项
    
    Returns:
        JSON文件下载
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试导出项目数据")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始导出项目数据: project_id={project_id}, user_id={user_id}")
        
        # 只查询当前用户的项目
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        
        if not project:
            logger.warning(f"项目不存在或无权访问: project_id={project_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 导出数据
        export_data = await ImportExportService.export_project(
            project_id=project_id,
            db=db,
            include_generation_history=options.include_generation_history,
            include_writing_styles=options.include_writing_styles
        )
        
        # 转换为JSON
        json_content = export_data.model_dump_json(indent=2, exclude_none=True, by_alias=True)
        
        # 生成文件名
        safe_title = "".join(c for c in project.title if c.isalnum() or c in (' ', '-', '_'))
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"project_{safe_title}_{date_str}.json"
        encoded_filename = quote(filename)
        
        logger.info(f"项目数据导出成功: {filename}")
        
        return Response(
            content=json_content.encode('utf-8'),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出项目数据失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.post("/validate-import", response_model=ImportValidationResult, summary="验证导入文件")
async def validate_import_file(
    file: UploadFile = File(...)
):
    """
    验证导入文件的格式和内容
    
    Args:
        file: 上传的JSON文件
    
    Returns:
        验证结果
    """
    try:
        logger.info(f"验证导入文件: {file.filename}")
        
        # 检查文件类型
        if not file.filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="只支持JSON格式文件")
        
        # 读取文件内容
        content = await file.read()
        
        # 检查文件大小（50MB限制）
        max_size = 50 * 1024 * 1024  # 50MB
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")
        
        # 解析JSON
        try:
            data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"无效的JSON格式: {str(e)}")
        
        # 验证数据
        validation_result = ImportExportService.validate_import_data(data)
        
        logger.info(f"文件验证完成: valid={validation_result.valid}")
        return validation_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证导入文件失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/import", response_model=ImportResult, summary="导入项目")
async def import_project(
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    导入项目数据（创建新项目）
    
    Args:
        file: 上传的JSON文件
    
    Returns:
        导入结果
    """
    try:
        # 从认证中间件获取用户ID
        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            logger.warning("未登录用户尝试导入项目")
            raise HTTPException(status_code=401, detail="未登录")
        
        logger.info(f"开始导入项目: {file.filename}, user_id={user_id}")
        
        # 检查文件类型
        if not file.filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="只支持JSON格式文件")
        
        # 读取文件内容
        content = await file.read()
        
        # 检查文件大小
        max_size = 50 * 1024 * 1024  # 50MB
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")
        
        # 解析JSON
        try:
            data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"无效的JSON格式: {str(e)}")
        
        # 导入数据（传入user_id）
        import_result = await ImportExportService.import_project(data, db, user_id)
        
        if import_result.success:
            logger.info(f"项目导入成功: {import_result.project_id}")
        else:
            logger.warning(f"项目导入失败: {import_result.message}")
        
        return import_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入项目失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")