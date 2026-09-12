"""章节管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json
import asyncio
from datetime import datetime
from asyncio import Lock

from app.database import get_db
from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.character import Character
from app.models.relationship import Organization, OrganizationMember
from app.models.generation_history import GenerationHistory
from app.models.writing_style import WritingStyle
from app.models.analysis_task import AnalysisTask
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.deai_prompt import DeaiPrompt
from app.models.plot_card import PlotCard
from app.models.plot_card_chapter_outline_link import PlotCardChapterOutlineLink
from app.schemas.chapter import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterListResponse,
    ChapterGenerateRequest,
)
from app.schemas.regeneration import ChapterRegenerateRequest
from app.api.ai_jobs import job_sse_response
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService
from app.services.chapter_analysis_jobs import create_analysis_task, start_chapter_analysis
from app.services.deai_rewrite import build_rewrite_prompt
from app.services.generation_trace import begin_stage, stage_scope, trace_progress, trace_reference
from app.services.prompt_service import prompt_service
from app.services.plot_analyzer import PlotAnalyzer
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.config import settings as config_settings
from app.utils.character_names import build_name_index
from app.utils.data_consistency import sync_organization_member_count
from app.utils.text_utils import count_words
from app.api.deps import verify_project_access

router = APIRouter(prefix="/chapters", tags=["章节管理"])
logger = get_logger(__name__)

# 全局数据库写入锁（每个用户一个锁，用于保护SQLite写入操作）
db_write_locks: dict[str, Lock] = {}


async def get_db_write_lock(user_id: str) -> Lock:
    """获取或创建用户的数据库写入锁"""
    if user_id not in db_write_locks:
        db_write_locks[user_id] = Lock()
        logger.debug(f"🔒 为用户 {user_id} 创建数据库写入锁")
    return db_write_locks[user_id]


async def _auto_create_entities(
    db: AsyncSession,
    project_id: str,
    chapter_number: int,
    entity_result: dict,
) -> int:
    """Auto-create or incrementally enrich characters/organizations.

    - New entity  → create with all available fields
    - Existing entity with empty fields → fill in from new extraction (never overwrite non-empty)
    Returns total number of created + enriched entities.
    """
    # --- 后置校验：自动纠正 AI 分类错误 ---
    ORG_SUFFIXES = ("宗", "派", "门", "堂", "殿", "阁", "院", "府", "家", "帮", "盟", "会", "楼", "馆", "谷", "洞", "族", "庄", "寺", "观", "教", "营", "军", "城", "国")
    characters_list = list(entity_result.get("characters", []) or [])
    organizations_list = list(entity_result.get("organizations", []) or [])

    corrected = []
    kept_characters = []
    for char in characters_list:
        name = (char.get("name") or "").strip()
        if name and name[-1] in ORG_SUFFIXES:
            # 从 character 格式转为 organization 格式
            org_entry = {
                "name": name,
                "organization_type": None,
                "organization_purpose": None,
                "personality": char.get("personality"),
                "appearance": char.get("appearance"),
                "location": None,
                "known_members": [],
                "traits": char.get("traits"),
                "background": char.get("background"),
            }
            organizations_list.append(org_entry)
            corrected.append(name)
        else:
            kept_characters.append(char)

    if corrected:
        logger.info(f"🔄 自动纠正分类: {corrected} 从人物移至组织")

    entity_result = {
        **entity_result,
        "characters": kept_characters,
        "organizations": organizations_list,
    }

    existing_result = await db.execute(
        select(Character).where(Character.project_id == project_id)
    )
    # 正式名 + 曾用名都指向同一角色：改名后旧章节里的旧名不会被当成新角色重复建档
    existing_map: dict[str, Character] = build_name_index(existing_result.scalars().all())

    created = 0
    enriched = 0

    def _val(raw: object) -> str | None:
        """Return stripped non-empty string or None."""
        if raw is None:
            return None
        s = str(raw).strip()
        return s if s and s.lower() not in ("null", "none", "未知", "") else None

    def _enrich(existing: Character, data: dict, is_org: bool = False) -> bool:
        """Fill empty fields on *existing* from *data*. Returns True if anything changed."""
        import json as _json
        changed = False
        field_map = {
            "gender": "gender",
            "age": "age",
            "personality": "personality",
            "appearance": "appearance",
            "traits": "traits",
        }
        if is_org:
            field_map.update({
                "organization_type": "organization_type",
                "organization_purpose": "organization_purpose",
            })

        for src_key, db_field in field_map.items():
            new_val = _val(data.get(src_key))
            if not new_val:
                continue
            cur_val = getattr(existing, db_field, None)
            if cur_val and str(cur_val).strip():
                continue
            if db_field == "traits":
                import json as _json
                raw_traits = data.get("traits")
                if isinstance(raw_traits, list) and raw_traits:
                    setattr(existing, db_field, _json.dumps(raw_traits, ensure_ascii=False))
                    changed = True
                continue
            setattr(existing, db_field, new_val)
            changed = True

        # background: append new info rather than overwrite
        new_bg = _val(data.get("background"))
        if new_bg:
            cur_bg = (existing.background or "").strip()
            if new_bg not in cur_bg:
                sep = "\n" if cur_bg else ""
                existing.background = f"{cur_bg}{sep}第{chapter_number}章：{new_bg}"
                changed = True

        # organization_members: merge new member names into existing list
        if is_org:
            new_members = data.get("known_members") or []
            if isinstance(new_members, list) and new_members:
                cur_members_raw = existing.organization_members or "[]"
                try:
                    cur_list = _json.loads(cur_members_raw) if isinstance(cur_members_raw, str) else (cur_members_raw or [])
                except (ValueError, TypeError):
                    cur_list = []
                cur_set = {str(m).strip().lower() for m in cur_list if m}
                added = [m for m in new_members if str(m).strip() and str(m).strip().lower() not in cur_set]
                if added:
                    merged = list(cur_list) + added
                    existing.organization_members = _json.dumps(merged, ensure_ascii=False)
                    changed = True

        # upgrade role_type: minor → supporting → major → protagonist (never downgrade)
        role_rank = {"minor": 0, "supporting": 1, "major": 2, "protagonist": 3}
        new_role = _val(data.get("role_type"))
        if new_role and new_role in role_rank:
            cur_role = (existing.role_type or "minor").lower()
            if role_rank.get(new_role, 0) > role_rank.get(cur_role, 0):
                existing.role_type = new_role
                changed = True

        return changed

    # --- Process characters ---
    for char in entity_result.get("characters", []) or []:
        name = _val(char.get("name"))
        if not name:
            continue
        existing = existing_map.get(name.lower())
        if existing:
            if _enrich(existing, char, is_org=False):
                enriched += 1
        else:
            import json as _json
            traits_raw = char.get("traits")
            traits_str = _json.dumps(traits_raw, ensure_ascii=False) if isinstance(traits_raw, list) and traits_raw else None
            new_char = Character(
                project_id=project_id,
                name=name,
                gender=_val(char.get("gender")),
                age=_val(char.get("age")),
                role_type=_val(char.get("role_type")) or "minor",
                personality=_val(char.get("personality")),
                appearance=_val(char.get("appearance")),
                background=f"第{chapter_number}章首次出场。{_val(char.get('background')) or ''}",
                traits=traits_str,
            )
            db.add(new_char)
            existing_map[name.lower()] = new_char
            created += 1

    # --- Process organizations ---
    for org in entity_result.get("organizations", []) or []:
        name = _val(org.get("name"))
        if not name:
            continue
        existing = existing_map.get(name.lower())
        if existing:
            if _enrich(existing, org, is_org=True):
                enriched += 1
        else:
            import json as _json
            traits_raw = org.get("traits")
            traits_str = _json.dumps(traits_raw, ensure_ascii=False) if isinstance(traits_raw, list) and traits_raw else None
            members_raw = org.get("known_members")
            members_str = _json.dumps(members_raw, ensure_ascii=False) if isinstance(members_raw, list) and members_raw else None
            location = _val(org.get("location"))
            bg_parts = [f"第{chapter_number}章首次出场。"]
            if location:
                bg_parts.append(f"位于{location}。")
            if _val(org.get("background")):
                bg_parts.append(_val(org.get("background")))
            new_org = Character(
                project_id=project_id,
                name=name,
                is_organization=True,
                role_type="supporting",
                organization_type=_val(org.get("organization_type")),
                organization_purpose=_val(org.get("organization_purpose")),
                personality=_val(org.get("personality")),
                appearance=_val(org.get("appearance")),
                background="".join(bg_parts),
                traits=traits_str,
                organization_members=members_str,
            )
            db.add(new_org)
            existing_map[name.lower()] = new_org
            created += 1

    # --- Process affiliations (character → organization membership) ---
    await db.flush()  # ensure all new entities have IDs
    affiliation_count = 0
    dirty_organizations: dict[str, Organization] = {}
    for char in entity_result.get("characters", []) or []:
        char_name = _val(char.get("name"))
        if not char_name:
            continue
        char_obj = existing_map.get(char_name.lower())
        if not char_obj or not hasattr(char_obj, 'id') or not char_obj.id:
            continue

        for aff in char.get("affiliations", []) or []:
            org_name = _val(aff.get("org_name"))
            if not org_name:
                continue
            org_char = existing_map.get(org_name.lower())
            if not org_char or not getattr(org_char, 'is_organization', False):
                continue
            if not org_char.id:
                continue

            # Find or create Organization detail record
            org_result = await db.execute(
                select(Organization).where(Organization.character_id == org_char.id)
            )
            org = org_result.scalar_one_or_none()
            if not org:
                org = Organization(
                    character_id=org_char.id,
                    project_id=project_id,
                    member_count=0,
                )
                db.add(org)
                await db.flush()

            # Check existing membership
            member_result = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org.id,
                    OrganizationMember.character_id == char_obj.id,
                )
            )
            existing_member = member_result.scalar_one_or_none()

            change = (aff.get("change") or "active").strip().lower()
            position = _val(aff.get("position"))
            reason = _val(aff.get("reason"))

            def _append_note(member: OrganizationMember, action: str) -> None:
                """Append a timestamped note to member.notes for history tracking."""
                note = f"第{chapter_number}章 {action}"
                if reason:
                    note += f"（{reason}）"
                cur = (member.notes or "").strip()
                member.notes = f"{cur}\n{note}".strip() if cur else note

            def _mark_org_count_dirty() -> None:
                """Track organizations whose active-member count must be resynced."""
                if org.id:
                    dirty_organizations[org.id] = org

            if existing_member:
                if change in ("left", "expelled", "promoted", "joined", "active"):
                    _mark_org_count_dirty()
                if change in ("left", "expelled"):
                    if existing_member.status != change:
                        existing_member.status = change
                        existing_member.left_at = f"第{chapter_number}章"
                        _append_note(existing_member, "离开" if change == "left" else "被逐出")
                        affiliation_count += 1
                elif change == "promoted" and position:
                    if existing_member.position != position or existing_member.status != "active":
                        existing_member.position = position
                        existing_member.status = "active"
                        existing_member.left_at = None
                        _append_note(existing_member, f"晋升为{position}")
                        affiliation_count += 1
                elif change in ("joined", "active"):
                    if existing_member.status != "active":
                        existing_member.status = "active"
                        if change == "joined":
                            existing_member.joined_at = f"第{chapter_number}章"
                        existing_member.left_at = None
                        if position:
                            existing_member.position = position
                        _append_note(existing_member, "重新加入" if change == "joined" else "恢复活跃状态")
                        affiliation_count += 1
            else:
                if change not in ("left", "expelled"):
                    note = f"第{chapter_number}章 加入"
                    if reason:
                        note += f"（{reason}）"
                    new_member = OrganizationMember(
                        organization_id=org.id,
                        character_id=char_obj.id,
                        position=position or "成员",
                        rank=0,
                        loyalty=50,
                        status="active",
                        joined_at=f"第{chapter_number}章",
                        source="ai",
                        notes=note,
                    )
                    db.add(new_member)
                    _mark_org_count_dirty()
                    affiliation_count += 1

    if dirty_organizations:
        # Recount touched organizations from active memberships so status flips never leave stale totals behind.
        await db.flush()
        for touched_org in dirty_organizations.values():
            await sync_organization_member_count(touched_org, db)

    if created > 0 or enriched > 0 or affiliation_count > 0:
        logger.info(f"👥 第{chapter_number}章实体入库: 新建{created}个, 丰富{enriched}个, 归属变动{affiliation_count}条")

    return created + enriched + affiliation_count


@router.post("", response_model=ChapterResponse, summary="创建章节")
async def create_chapter(
    chapter: ChapterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """创建新的章节"""
    # 验证用户权限和项目是否存在
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(chapter.project_id, user_id, db)

    # 计算字数（使用中英文混合字数统计）
    word_count = count_words(chapter.content)
    
    db_chapter = Chapter(
        **chapter.model_dump(),
        word_count=word_count
    )
    db.add(db_chapter)
    
    # 更新项目的当前字数
    project.current_words = project.current_words + word_count
    
    await db.commit()
    await db.refresh(db_chapter)
    return db_chapter


@router.post("/project/{project_id}/sync-from-outlines", summary="从章纲批量同步章节")
async def sync_chapters_from_outlines(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    将项目中所有章纲同步为章节。
    已有对应章节的章纲会跳过，仅为缺少章节的章纲创建新章节。
    """
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    outlines_result = await db.execute(
        select(ChapterOutline)
        .where(ChapterOutline.project_id == project_id)
        .order_by(ChapterOutline.chapter_number)
    )
    outlines = outlines_result.scalars().all()

    if not outlines:
        return {"created": 0, "skipped": 0, "total_outlines": 0, "message": "没有章纲可同步"}

    existing_result = await db.execute(
        select(Chapter.chapter_outline_id)
        .where(
            Chapter.project_id == project_id,
            Chapter.chapter_outline_id.isnot(None)
        )
    )
    existing_outline_ids = set(existing_result.scalars().all())

    created = 0
    skipped = 0
    for outline in outlines:
        if outline.id in existing_outline_ids:
            skipped += 1
            continue
        chapter = Chapter(
            project_id=project_id,
            chapter_outline_id=outline.id,
            chapter_number=outline.chapter_number,
            title=outline.title,
            summary=outline.summary,
            status="draft",
            word_count=0
        )
        db.add(chapter)
        created += 1

    if created > 0:
        await db.commit()

    logger.info(f"📚 章纲同步完成: 项目 {project_id}, 创建 {created}, 跳过 {skipped}")
    return {
        "created": created,
        "skipped": skipped,
        "total_outlines": len(outlines),
        "message": f"同步完成：新建 {created} 章，跳过 {skipped} 章（已存在）"
    }


@router.get("/project/{project_id}", response_model=ChapterListResponse, summary="获取项目的所有章节")
async def get_project_chapters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有章节（路径参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Chapter.id)).where(Chapter.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取章节列表
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    chapters = result.scalars().all()
    
    return ChapterListResponse(total=total, items=chapters)


@router.get("/{chapter_id}", response_model=ChapterResponse, summary="获取章节详情")
async def get_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取章节详情"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    return chapter


@router.put("/{chapter_id}", response_model=ChapterResponse, summary="更新章节")
async def update_chapter(
    chapter_id: str,
    chapter_update: ChapterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新章节信息"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 记录旧字数
    old_word_count = chapter.word_count or 0
    
    # 更新字段
    update_data = chapter_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(chapter, field, value)
    
    # 如果内容更新了，重新计算字数（含清空为 "" 的场景，word_count 需归零）
    if "content" in update_data:
        new_word_count = count_words(chapter.content or "")
        chapter.word_count = new_word_count

        # 更新项目字数
        result = await db.execute(
            select(Project).where(Project.id == chapter.project_id)
        )
        project = result.scalar_one_or_none()
        if project:
            project.current_words = max(
                0, (project.current_words or 0) - old_word_count + new_word_count
            )
    
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.delete("/{chapter_id}", summary="删除章节")
async def delete_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除章节"""
    from app.services.memory_service import memory_service
    from app.models.memory import StoryMemory
    
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 1. 先清理该章节的记忆数据（关系数据库）
    memories_result = await db.execute(
        select(StoryMemory).where(
            StoryMemory.project_id == chapter.project_id,
            StoryMemory.chapter_id == chapter_id
        )
    )
    memories = memories_result.scalars().all()
    memory_count = len(memories)
    
    for memory in memories:
        await db.delete(memory)
    
    # 2. 清理向量数据库中的记忆
    if user_id and memory_count > 0:
        try:
            await memory_service.delete_chapter_memories(
                user_id=user_id,
                project_id=chapter.project_id,
                chapter_id=chapter_id
            )
            logger.info(f"✅ 已清理章节{chapter_id[:8]}的{memory_count}条记忆")
        except Exception as e:
            logger.warning(f"⚠️ 向量记忆清理失败（继续删除章节）: {str(e)}")
    
    # 3. 更新项目字数
    result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = result.scalar_one_or_none()
    if project:
        project.current_words = max(0, project.current_words - chapter.word_count)
    
    # 4. 删除章节
    await db.delete(chapter)
    await db.commit()
    
    return {
        "message": "章节删除成功",
        "memories_cleared": memory_count
    }


async def check_prerequisites(db: AsyncSession, chapter: Chapter) -> tuple[bool, str, list[Chapter]]:
    """
    检查章节前置条件
    
    Args:
        db: 数据库会话
        chapter: 当前章节
        
    Returns:
        (可否生成, 错误信息, 前置章节列表)
    """
    # 如果是第一章，无需检查前置
    if chapter.chapter_number == 1:
        return True, "", []
    
    # 查询所有前置章节（序号小于当前章节的）
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id)
        .where(Chapter.chapter_number < chapter.chapter_number)
        .order_by(Chapter.chapter_number)
    )
    previous_chapters = result.scalars().all()
    
    # 检查是否所有前置章节都有内容
    incomplete_chapters = [
        ch for ch in previous_chapters
        if not ch.content or ch.content.strip() == ""
    ]
    
    if incomplete_chapters:
        missing_numbers = [str(ch.chapter_number) for ch in incomplete_chapters]
        error_msg = f"需要先完成前置章节：第 {', '.join(missing_numbers)} 章"
        return False, error_msg, previous_chapters
    
    return True, "", previous_chapters


async def _unanalyzed_previous_chapters(db: AsyncSession, chapter: Chapter) -> list[Chapter]:
    """返回当前章节之前「有正文但从未分析（无 PlotAnalysis 记忆状态）」的章节列表。

    用于生成前提醒：这些章节缺少记忆状态，续写会缺乏它们的剧情/角色/伏笔上下文。
    判定「已分析」= 存在 PlotAnalysis 记录（哪怕已过期），因为记忆状态在分析时写入。
    """
    if chapter.chapter_number <= 1:
        return []

    prev_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id)
        .where(Chapter.chapter_number < chapter.chapter_number)
        .where(Chapter.content.isnot(None))
        .where(Chapter.content != "")
        .order_by(Chapter.chapter_number)
    )
    previous_chapters = list(prev_result.scalars().all())
    if not previous_chapters:
        return []

    analyzed_result = await db.execute(
        select(PlotAnalysis.chapter_id).where(
            PlotAnalysis.chapter_id.in_([c.id for c in previous_chapters])
        )
    )
    analyzed_ids = set(analyzed_result.scalars().all())
    return [c for c in previous_chapters if c.id not in analyzed_ids]


async def _purge_chapter_analysis_and_memory(db: AsyncSession, chapter_id: str) -> int:
    """删除该章全部分析产物：PlotAnalysis + AnalysisTask + StoryMemory（DB 行）+ 叙事状态（伏笔 / 承诺、因果、时间轴、
    关系事件、已知信息）+ 一致性信号与问题。

    用于「正文被整章覆盖」后清理过期分析（不标过期，直接删，回到「未分析」，由用户手动重新分析）。
    仅删关系库行，不提交、不清向量；返回删除的记忆条数供调用方做向量清理。
    """
    for _pa in (await db.execute(
        select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id)
    )).scalars().all():
        await db.delete(_pa)
    for _at in (await db.execute(
        select(AnalysisTask).where(AnalysisTask.chapter_id == chapter_id)
    )).scalars().all():
        await db.delete(_at)
    mem_rows = (await db.execute(
        select(StoryMemory).where(StoryMemory.chapter_id == chapter_id)
    )).scalars().all()
    for _m in mem_rows:
        await db.delete(_m)
    await narrative_state_service.clear_chapter_state(db, chapter_id)
    await chapter_consistency_service.clear_chapter_records(db, chapter_id)
    return len(mem_rows)


async def _purge_chapter_vector_memory(user_id: str | None, project_id: str, chapter_id: str, mem_count: int) -> None:
    """向量库记忆清理（best-effort；须在 DB 删除已提交后调用）。"""
    if not mem_count or not user_id:
        return
    try:
        await memory_service.delete_chapter_memories(
            user_id=user_id, project_id=project_id, chapter_id=chapter_id
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ 向量记忆清理失败（不影响正文覆盖）: {e}")


async def build_smart_chapter_context(
    db: AsyncSession,
    project_id: str,
    current_chapter_number: int,
    user_id: str
) -> dict:
    """
    智能构建章节生成上下文（支持海量章节场景）
    
    策略：
    1. 故事骨架：每50章采样1章（标题+摘要）
    2. 相关历史：通过chapter_summary记忆语义检索15个最相关章节
    3. 近期概要：最近30章的简要摘要（200字/章）
    4. 最近完整：最近3章的完整内容
    
    Args:
        db: 数据库会话
        project_id: 项目ID
        current_chapter_number: 当前章节序号
        user_id: 用户ID
        
    Returns:
        包含各部分上下文的字典
    """
    context_parts = {
        'story_skeleton': '',      # 故事骨架
        'relevant_history': '',    # 相关历史章节
        'recent_summary': '',      # 近期概要
        'recent_full': '',         # 最近完整内容
        'stats': {}                # 统计信息
    }
    
    # 初始化变量，避免后续引用时出现 NameError
    relevant_memories = []
    recent_summaries = []
    
    try:
        # 1. 获取所有已完成的前置章节（只取ID和序号）
        all_chapters_result = await db.execute(
            select(Chapter.id, Chapter.chapter_number, Chapter.title)
            .where(Chapter.project_id == project_id)
            .where(Chapter.chapter_number < current_chapter_number)
            .where(Chapter.content != None)
            .where(Chapter.content != "")
            .order_by(Chapter.chapter_number)
        )
        all_chapters_info = all_chapters_result.all()
        total_previous = len(all_chapters_info)
        
        if total_previous == 0:
            logger.info("📚 这是第一章，无需构建前置上下文")
            return context_parts
        
        logger.info(f"📚 开始构建智能上下文：共{total_previous}章前置内容")
        
        # 2. 构建故事骨架（每50章采样）
        skeleton_chapters = []
        if total_previous > 50:
            sample_interval = 50
            skeleton_indices = list(range(0, total_previous, sample_interval))
            
            for idx in skeleton_indices:
                chapter_info = all_chapters_info[idx]
                # 获取章节摘要（优先从chapter_summary记忆获取）
                summary_result = await db.execute(
                    select(StoryMemory.content)
                    .where(StoryMemory.project_id == project_id)
                    .where(StoryMemory.chapter_id == chapter_info.id)
                    .where(StoryMemory.memory_type == 'chapter_summary')
                    .limit(1)
                )
                summary_row = summary_result.scalar_one_or_none()
                summary = summary_row if summary_row else "（无摘要）"
                
                skeleton_chapters.append({
                    'number': chapter_info.chapter_number,
                    'title': chapter_info.title,
                    'summary': summary
                })
            
            context_parts['story_skeleton'] = "【故事骨架】\n" + "\n".join([
                f"第{ch['number']}章《{ch['title']}》：{ch['summary']}"
                for ch in skeleton_chapters
            ])
            logger.info(f"  ✅ 故事骨架：采样{len(skeleton_chapters)}章（每50章1个）")

        # 收集需要排除的章节（用于语义检索去重）
        skeleton_chapter_ids = set()
        if total_previous > 50:
            skeleton_chapter_ids = {all_chapters_info[idx].id for idx in skeleton_indices}

        # 计算近期章节范围（最近30章 + 最近3章完整内容），这些章节不需要在语义检索中重复出现
        recent_summary_start = max(1, current_chapter_number - 30)
        exclude_chapter_numbers = set(range(recent_summary_start, current_chapter_number))

        # 3. 语义检索相关历史章节（使用chapter_summary记忆）
        # 获取当前章节的章纲作为查询
        current_outline_result = await db.execute(
            select(ChapterOutline.summary, ChapterOutline.plot_points)
            .join(Chapter, Chapter.chapter_outline_id == ChapterOutline.id)
            .where(Chapter.project_id == project_id)
            .where(Chapter.chapter_number == current_chapter_number)
        )
        current_outline_data = current_outline_result.first()
        
        current_outline_text = ""
        if current_outline_data:
            summary, plot_points = current_outline_data
            current_outline_text = f"{summary or ''} {plot_points or ''}".strip()
        
        if current_outline_text and total_previous > 3:
            # 使用记忆服务进行语义检索
            relevant_memories = await memory_service.search_memories(
                user_id=user_id,
                project_id=project_id,
                query=current_outline_text,
                memory_types=['chapter_summary'],
                limit=15,  # 检索15个最相关的章节
                min_importance=0.0  # 不过滤重要性，依赖语义相关度
            )
            
            if relevant_memories:
                relevant_chapters_text = []
                skipped_count = 0
                for mem in relevant_memories:
                    chapter_id = mem['metadata'].get('chapter_id')

                    # 去重：跳过已在故事骨架中的章节
                    if chapter_id in skeleton_chapter_ids:
                        skipped_count += 1
                        continue

                    # 获取章节信息
                    chapter_result = await db.execute(
                        select(Chapter.chapter_number, Chapter.title)
                        .where(Chapter.id == chapter_id)
                    )
                    chapter_info = chapter_result.first()
                    if chapter_info:
                        # 去重：跳过近期章节（已在近期概要或完整内容中）
                        if chapter_info.chapter_number in exclude_chapter_numbers:
                            skipped_count += 1
                            continue

                        relevant_chapters_text.append(
                            f"第{chapter_info.chapter_number}章《{chapter_info.title}》：{mem['content']} "
                            f"(相关度:{mem['similarity']:.2f})"
                        )

                context_parts['relevant_history'] = "【相关历史章节】\n" + "\n".join(relevant_chapters_text)
                logger.info(f"  ✅ 相关历史：语义检索到{len(relevant_chapters_text)}章（去重跳过{skipped_count}章）")
        
        # 4. 近期概要（最近30章，每章200字摘要）
        recent_summary_count = min(30, total_previous)
        recent_for_summary = all_chapters_info[-recent_summary_count:] if total_previous > 3 else []
        
        if recent_for_summary and len(recent_for_summary) > 3:  # 至少要有3章才做摘要
            recent_summaries = []
            for chapter_info in recent_for_summary[:-3]:  # 排除最后3章（它们会完整展示）
                # 优先获取chapter_summary记忆
                summary_result = await db.execute(
                    select(StoryMemory.content)
                    .where(StoryMemory.project_id == project_id)
                    .where(StoryMemory.chapter_id == chapter_info.id)
                    .where(StoryMemory.memory_type == 'chapter_summary')
                    .limit(1)
                )
                summary = summary_result.scalar_one_or_none()
                
                if summary:
                    recent_summaries.append(
                        f"第{chapter_info.chapter_number}章《{chapter_info.title}》：{summary}"
                    )
            
            if recent_summaries:
                context_parts['recent_summary'] = "【近期章节概要】\n" + "\n".join(recent_summaries)
                logger.info(f"  ✅ 近期概要：{len(recent_summaries)}章摘要")
        
        # 5. 最近完整内容（最近3章）
        recent_full_count = min(3, total_previous)
        recent_full_chapters = all_chapters_info[-recent_full_count:]
        
        # 获取完整内容
        recent_full_texts = []
        for chapter_info in recent_full_chapters:
            chapter_result = await db.execute(
                select(Chapter.content)
                .where(Chapter.id == chapter_info.id)
            )
            content = chapter_result.scalar_one_or_none()
            if content:
                recent_full_texts.append(
                    f"=== 第{chapter_info.chapter_number}章：{chapter_info.title} ===\n{content}"
                )
        
        context_parts['recent_full'] = "【最近章节完整内容】\n" + "\n\n".join(recent_full_texts)
        logger.info(f"  ✅ 最近完整：{len(recent_full_texts)}章全文")
        
        # 6. 统计信息
        context_parts['stats'] = {
            'total_previous': total_previous,
            'skeleton_samples': len(skeleton_chapters),
            'relevant_history': len(relevant_memories) if total_previous > 3 else 0,
            'recent_summaries': len(recent_summaries) if recent_for_summary and len(recent_for_summary) > 3 else 0,
            'recent_full': len(recent_full_texts)
        }
        
        # 计算总长度
        total_length = sum([
            len(context_parts['story_skeleton']),
            len(context_parts['relevant_history']),
            len(context_parts['recent_summary']),
            len(context_parts['recent_full'])
        ])
        context_parts['stats']['total_length'] = total_length
        
        logger.info(f"📊 智能上下文构建完成：总长度 {total_length} 字符")
        
    except Exception as e:
        logger.error(f"❌ 构建智能上下文失败: {str(e)}", exc_info=True)
    
    return context_parts


@router.get("/{chapter_id}/can-generate", summary="检查章节是否可以生成")
async def check_can_generate(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    检查章节是否满足生成条件
    返回可生成状态和前置章节信息
    """
    # 获取章节
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 检查前置条件
    can_generate, error_msg, previous_chapters = await check_prerequisites(db, chapter)
    
    # 构建前置章节信息
    previous_info = [
        {
            "id": ch.id,
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "has_content": bool(ch.content and ch.content.strip()),
            "word_count": ch.word_count or 0
        }
        for ch in previous_chapters
    ]
    
    return {
        "can_generate": can_generate,
        "reason": error_msg if not can_generate else "",
        "previous_chapters": previous_info,
        "chapter_number": chapter.chapter_number
    }


async def analyze_chapter_background(
    chapter_id: str,
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: AIService
):
    """
    后台异步分析章节（支持并发，使用锁保护数据库写入）
    
    Args:
        chapter_id: 章节ID
        user_id: 用户ID
        project_id: 项目ID
        task_id: 任务ID
        ai_service: AI服务实例
    """
    db_session = None
    write_lock = await get_db_write_lock(user_id)
    
    try:
        logger.info(f"🔍 开始分析章节: {chapter_id}, 任务ID: {task_id}")
        
        # 创建独立数据库会话
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        db_session = AsyncSessionLocal()
        
        # 1. 获取任务（读操作）
        task_result = await db_session.execute(
            select(AnalysisTask).where(AnalysisTask.id == task_id)
        )
        task = task_result.scalar_one_or_none()
        
        if not task:
            logger.error(f"❌ 任务不存在: {task_id}")
            return
        
        # 更新任务状态（写操作，需要锁）
        async with write_lock:
            task.status = 'running'
            task.started_at = datetime.now()
            task.progress = 10
            await db_session.commit()
        trace_progress("读取章节…", 10)
        
        # 2. 获取章节信息（读操作）
        chapter_result = await db_session.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        if not chapter or not chapter.content:
            async with write_lock:
                task.status = 'failed'
                task.error_message = '章节不存在或内容为空'
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.error(f"❌ 章节不存在或内容为空: {chapter_id}")
            return
        
        async with write_lock:
            task.progress = 20
            await db_session.commit()
        trace_progress("模型分析章节中…", 20)
        
        # 3. 并行执行：章节分析 + 实体提取
        analyzer = PlotAnalyzer(ai_service)
        async with stage_scope("analyze", "模型分析章节 + 提取实体") as st:
            analysis_task_coro = analyzer.analyze_chapter(
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content=chapter.content,
                word_count=chapter.word_count or count_words(chapter.content)
            )
            entity_task_coro = analyzer.extract_entities(
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content=chapter.content,
            )
            analysis_result, entity_result = await asyncio.gather(
                analysis_task_coro, entity_task_coro, return_exceptions=True
            )
            # 处理异常：gather 可能返回 Exception 对象
            if isinstance(analysis_result, Exception):
                logger.error(f"❌ 章节分析异常: {analysis_result}")
                analysis_result = None
            if isinstance(entity_result, Exception):
                logger.error(f"⚠️ 实体提取异常(非致命): {entity_result}")
                entity_result = None
            st.note(analysis_ok=bool(analysis_result), entities_ok=bool(entity_result))
        
        if not analysis_result:
            async with write_lock:
                task.status = 'failed'
                task.error_message = 'AI分析失败，请检查日志'
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.error(f"❌ AI分析失败: {chapter_id}")
            return
        
        # 3.5 将提取到的人物/组织自动入库（去重）
        if entity_result:
            async with write_lock:
                await _auto_create_entities(db_session, project_id, chapter.chapter_number, entity_result)
                await db_session.commit()
        
        async with write_lock:
            task.progress = 60
            await db_session.commit()
        trace_progress("分析完成，写入结果…", 60)
        
        # 4. 保存分析结果到数据库（写操作，需要锁）
        async with stage_scope("persist_analysis", "写入分析结果"):
            async with write_lock:
                existing_analysis_result = await db_session.execute(
                    select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id)
                )
                existing_analysis = existing_analysis_result.scalar_one_or_none()
            
                if existing_analysis:
                    # 更新现有记录
                    logger.info(f"  更新现有分析记录: {existing_analysis.id}")
                    existing_analysis.plot_stage = analysis_result.get('plot_stage', '发展')
                    existing_analysis.conflict_level = analysis_result.get('conflict', {}).get('level', 0)
                    existing_analysis.conflict_types = analysis_result.get('conflict', {}).get('types', [])
                    existing_analysis.emotional_tone = analysis_result.get('emotional_arc', {}).get('primary_emotion', '')
                    existing_analysis.emotional_intensity = analysis_result.get('emotional_arc', {}).get('intensity', 0) / 10.0
                    existing_analysis.hooks = analysis_result.get('hooks', [])
                    existing_analysis.hooks_count = len(analysis_result.get('hooks', []))
                    existing_analysis.foreshadows = analysis_result.get('foreshadows', [])
                    existing_analysis.foreshadows_planted = sum(1 for f in analysis_result.get('foreshadows', []) if f.get('type') == 'planted')
                    existing_analysis.foreshadows_resolved = sum(1 for f in analysis_result.get('foreshadows', []) if f.get('type') == 'resolved')
                    existing_analysis.plot_points = analysis_result.get('plot_points', [])
                    existing_analysis.plot_points_count = len(analysis_result.get('plot_points', []))
                    existing_analysis.character_states = analysis_result.get('character_states', [])
                    existing_analysis.scenes = analysis_result.get('scenes', [])
                    existing_analysis.pacing = analysis_result.get('pacing', 'moderate')
                    existing_analysis.overall_quality_score = analysis_result.get('scores', {}).get('overall', 0)
                    existing_analysis.pacing_score = analysis_result.get('scores', {}).get('pacing', 0)
                    existing_analysis.engagement_score = analysis_result.get('scores', {}).get('engagement', 0)
                    existing_analysis.coherence_score = analysis_result.get('scores', {}).get('coherence', 0)
                    existing_analysis.analysis_report = analyzer.generate_analysis_summary(analysis_result)
                    existing_analysis.suggestions = analysis_result.get('suggestions', [])
                    existing_analysis.dialogue_ratio = analysis_result.get('dialogue_ratio', 0)
                    existing_analysis.description_ratio = analysis_result.get('description_ratio', 0)
                    # 刷新分析时间戳：用于前端"内容修改后分析过期"判断（is_stale）
                    # 注意必须用 func.now()（SQLite CURRENT_TIMESTAMP，UTC），
                    # 与 chapter.updated_at 的 onupdate=func.now() 保持同一时钟，
                    # 否则 datetime.now()（本地时区）会让 stale 比较在时差窗口内失效
                    existing_analysis.created_at = func.now()
                else:
                    # 创建新记录
                    logger.info(f"  创建新的分析记录")
                    plot_analysis = PlotAnalysis(
                        chapter_id=chapter_id,
                        project_id=project_id,
                        plot_stage=analysis_result.get('plot_stage', '发展'),
                        conflict_level=analysis_result.get('conflict', {}).get('level', 0),
                        conflict_types=analysis_result.get('conflict', {}).get('types', []),
                        emotional_tone=analysis_result.get('emotional_arc', {}).get('primary_emotion', ''),
                        emotional_intensity=analysis_result.get('emotional_arc', {}).get('intensity', 0) / 10.0,
                        hooks=analysis_result.get('hooks', []),
                        hooks_count=len(analysis_result.get('hooks', [])),
                        foreshadows=analysis_result.get('foreshadows', []),
                        foreshadows_planted=sum(1 for f in analysis_result.get('foreshadows', []) if f.get('type') == 'planted'),
                        foreshadows_resolved=sum(1 for f in analysis_result.get('foreshadows', []) if f.get('type') == 'resolved'),
                        plot_points=analysis_result.get('plot_points', []),
                        plot_points_count=len(analysis_result.get('plot_points', [])),
                        character_states=analysis_result.get('character_states', []),
                        scenes=analysis_result.get('scenes', []),
                        pacing=analysis_result.get('pacing', 'moderate'),
                        overall_quality_score=analysis_result.get('scores', {}).get('overall', 0),
                        pacing_score=analysis_result.get('scores', {}).get('pacing', 0),
                        engagement_score=analysis_result.get('scores', {}).get('engagement', 0),
                        coherence_score=analysis_result.get('scores', {}).get('coherence', 0),
                        analysis_report=analyzer.generate_analysis_summary(analysis_result),
                        suggestions=analysis_result.get('suggestions', []),
                        dialogue_ratio=analysis_result.get('dialogue_ratio', 0),
                        description_ratio=analysis_result.get('description_ratio', 0)
                    )
                    db_session.add(plot_analysis)
            
                await db_session.commit()
            
                task.progress = 80
                await db_session.commit()
        trace_progress("分析结果已写入，提取记忆…", 80)
        
        # 5. 提取记忆并保存到向量数据库（传入章节内容用于计算位置）
        async with stage_scope("memories", "提取记忆 / 结算状态 / 一致性审计") as st:
            memories = analyzer.extract_memories_from_analysis(
                analysis=analysis_result,
                chapter_id=chapter_id,
                chapter_number=chapter.chapter_number,
                chapter_content=chapter.content or "",
                chapter_title=chapter.title or ""
            )
        
            # 先删除该章节的旧记忆（写操作，需要锁）
            async with write_lock:
                old_memories_result = await db_session.execute(
                    select(StoryMemory).where(StoryMemory.chapter_id == chapter_id)
                )
                old_memories = old_memories_result.scalars().all()
                for old_mem in old_memories:
                    await db_session.delete(old_mem)
                await db_session.commit()
                logger.info(f"  删除旧记忆: {len(old_memories)}条")
        
            # 准备批量添加的记忆数据（不需要锁）
            memory_records = []
            for mem in memories:
                memory_id = f"{chapter_id}_{mem['type']}_{len(memory_records)}"
                memory_records.append({
                    'id': memory_id,
                    'content': mem['content'],
                    'type': mem['type'],
                    'metadata': mem['metadata']
                })
            
            # 保存到关系数据库（写操作，需要锁）
            async with write_lock:
                for mem in memories:
                    memory_id = memory_records[memories.index(mem)]['id']
                    text_position = mem['metadata'].get('text_position', -1)
                    text_length = mem['metadata'].get('text_length', 0)
                
                    story_memory = StoryMemory(
                        id=memory_id,
                        project_id=project_id,
                        chapter_id=chapter_id,
                        memory_type=mem['type'],
                        content=mem['content'],
                        title=mem['title'],
                        importance_score=mem['metadata'].get('importance_score', 0.5),
                        tags=mem['metadata'].get('tags', []),
                        is_foreshadow=mem['metadata'].get('is_foreshadow', 0),
                        story_timeline=chapter.chapter_number,
                        chapter_position=text_position,
                        text_length=text_length,
                        related_characters=mem['metadata'].get('related_characters', []),
                        related_locations=mem['metadata'].get('related_locations', [])
                    )
                    db_session.add(story_memory)
                
                    if text_position >= 0:
                        logger.debug(f"  保存记忆 {memory_id}: position={text_position}, length={text_length}")
            
                await db_session.commit()
            
                settlement_stats = await narrative_state_service.settle_chapter_state(
                    db=db_session,
                    project_id=project_id,
                    chapter=chapter,
                    analysis=analysis_result,
                )
                consistency_stats = await chapter_consistency_service.settle_signals_and_audit(
                    db=db_session,
                    project_id=project_id,
                    chapter=chapter,
                    analysis=analysis_result,
                )
                task.progress = 90
                await db_session.commit()
                logger.info(f"✅ 章节状态结算完成: {settlement_stats}, 一致性审计: {consistency_stats}")
            st.note(memories=len(memories))
        trace_progress("记忆已结算，写入向量库…", 90)
        
        # 批量添加到向量数据库
        async with stage_scope("vector", "写入向量库") as st:
            if memory_records:
                added_count = await memory_service.batch_add_memories(
                    user_id=user_id,
                    project_id=project_id,
                    memories=memory_records
                )
                logger.info(f"✅ 添加{added_count}条记忆到向量库")
            st.note(records=len(memory_records))
        
        # 最终更新任务状态（写操作，需要锁）- 增加重试机制
        update_success = False
        for retry in range(3):
            try:
                async with write_lock:
                    task.progress = 100
                    task.status = 'completed'
                    task.completed_at = datetime.now()
                    await db_session.commit()
                    update_success = True
                    logger.info(f"✅ 章节分析完成: {chapter_id}, 提取{len(memories)}条记忆")
                    break
            except Exception as commit_error:
                logger.error(f"❌ 提交任务完成状态失败(重试{retry+1}/3): {str(commit_error)}")
                if retry < 2:
                    await asyncio.sleep(0.1)
                else:
                    logger.error(f"❌ 无法更新任务为completed状态: {task_id}")
                    # 即使失败也不抛出异常，因为分析本身已经完成
        
        if not update_success:
            logger.warning(f"⚠️  章节分析完成但状态更新失败: {chapter_id}")
        
    except Exception as e:
        logger.error(f"❌ 后台分析异常: {str(e)}", exc_info=True)
        # 确保任务状态被更新为failed（写操作，需要锁）
        if db_session:
            # 多次重试更新任务状态
            for retry in range(3):
                try:
                    async with write_lock:
                        # 重新获取任务（可能是旧会话导致的问题）
                        task_result = await db_session.execute(
                            select(AnalysisTask).where(AnalysisTask.id == task_id)
                        )
                        task = task_result.scalar_one_or_none()
                        if task:
                            task.status = 'failed'
                            task.error_message = str(e)[:500]
                            task.completed_at = datetime.now()
                            task.progress = 0
                            await db_session.commit()
                            logger.info(f"✅ 任务状态已更新为failed: {task_id} (重试{retry+1}次)")
                            break
                        else:
                            logger.error(f"❌ 无法找到任务进行状态更新: {task_id}")
                            break
                except Exception as update_error:
                    logger.error(f"❌ 更新任务状态失败(重试{retry+1}/3): {str(update_error)}")
                    if retry < 2:
                        await asyncio.sleep(0.1)  # 短暂等待后重试
                    else:
                        logger.error(f"❌ 任务状态更新失败，已达到最大重试次数: {task_id}")
    finally:
        if db_session:
            await db_session.close()


@router.get("/{chapter_id}/generation-precheck", summary="生成前检查前置章节是否都已分析")
async def chapter_generation_precheck(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """生成前预检查：前面是否有「有正文但未分析（无记忆状态）」的章节。

    前端在触发生成前调用；count>0 时提示用户「前面有 N 章没有记忆状态，是否继续生成」。
    这是提醒性检查，不阻断生成（用户确认后仍可正常调用 generate-stream）。
    """
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    unanalyzed = await _unanalyzed_previous_chapters(db, chapter)
    numbers = [c.chapter_number for c in unanalyzed]
    message = (
        f"前面有 {len(numbers)} 章尚未分析（缺少记忆状态）：第 {', '.join(map(str, numbers))} 章。"
        "缺少记忆状态可能影响续写的剧情连贯性，是否继续生成？"
        if numbers else ""
    )
    return {
        "count": len(unanalyzed),
        "chapters": [
            {"id": c.id, "chapter_number": c.chapter_number, "title": c.title}
            for c in unanalyzed
        ],
        "message": message,
    }


@router.post("/{chapter_id}/generate-stream", summary="AI创作章节内容（流式）")
async def generate_chapter_content_stream(
    chapter_id: str,
    request: Request,
    generate_request: ChapterGenerateRequest = ChapterGenerateRequest(),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据大纲、前置章节内容和项目信息AI创作章节完整内容（流式返回）
    要求：必须按顺序生成，确保前置章节都已完成
    
    请求体参数：
    - style_id: 可选，指定使用的写作风格ID。不提供则不使用任何风格
    - target_word_count: 可选，目标字数，默认3000字，范围500-10000字
    - enable_mcp: 可选，是否启用MCP工具增强，默认True
    
    注意：此函数不使用依赖注入的db，而是在生成器内部创建独立的数据库会话
    以避免流式响应期间的连接泄漏问题
    """
    style_id = generate_request.style_id
    target_word_count = generate_request.target_word_count or 3000
    enable_mcp = generate_request.enable_mcp if hasattr(generate_request, 'enable_mcp') else True
    selected_plugins = generate_request.selected_plugins if hasattr(generate_request, 'selected_plugins') else None
    # auto_analyze：批量生成时前端传 True → 生成后自动排队分析（累积记忆 + 支撑一致性闸门）；
    # 单章生成默认 False → 不自动分析，由用户手动触发（可先改正文再分析）
    auto_analyze = getattr(generate_request, 'auto_analyze', False)
    # 预先验证章节存在性（使用临时会话）
    async for temp_db in get_db(request):
        result = await temp_db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = result.scalar_one_or_none()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        
        # 检查前置条件
        can_generate, error_msg, previous_chapters = await check_prerequisites(temp_db, chapter)
        if not can_generate:
            raise HTTPException(status_code=400, detail=error_msg)
        break
    
    user_id = getattr(request.state, "user_id", "system")

    async def runner(job):
        """后台任务体：独立会话 → 上下文 / MCP / 参考包 → 流式创作 → 写库 → 排队分析。事件进任务日志，可回放。"""
        current_user_id = user_id
        async with job_session_factory(current_user_id)() as db_session:
            st_ctx = begin_stage("context", "加载章纲 / 世界规则 / 角色 / 剧情卡")
            # 重新获取章节信息
            chapter_result = await db_session.execute(
                select(Chapter).where(Chapter.id == chapter_id)
            )
            current_chapter = chapter_result.scalar_one_or_none()
            if not current_chapter:
                raise ValueError('章节不存在')
        
            # 获取项目信息
            project_result = await db_session.execute(
                select(Project).where(Project.id == current_chapter.project_id)
            )
            project = project_result.scalar_one_or_none()
            if not project:
                raise ValueError('项目不存在')

            # 检查章节是否关联章纲
            if not current_chapter.chapter_outline_id:
                raise ValueError('章节未关联章纲，无法生成。请先在章纲管理中创建章纲。')

            # 获取当前章纲
            chapter_outline_result = await db_session.execute(
                select(ChapterOutline).where(ChapterOutline.id == current_chapter.chapter_outline_id)
            )
            chapter_outline = chapter_outline_result.scalar_one_or_none()

            if not chapter_outline:
                raise ValueError('关联的章纲不存在')

            # 构建查询文本（用于智能检索世界规则）
            outline_text = chapter_outline.summary or chapter_outline.plot_points or ''
            query_text = f"{project.theme or ''} {project.genre or ''} {outline_text[:500]}"

            # 增强世界规则（使用语义检索）
            from app.services.world_rule_service import world_rule_service
            enhanced_world_rules = await world_rule_service.generate_rules_summary_with_search(
                db_session, project.id, query_text, limit=5
            )
            final_world_rules = project.world_rules or '未设定'
            if enhanced_world_rules:
                final_world_rules = f"{final_world_rules}\n\n{enhanced_world_rules}"
            
            # 获取所有章纲用于上下文
            all_chapter_outlines_result = await db_session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.project_id == current_chapter.project_id)
                .order_by(ChapterOutline.chapter_number)
            )
            all_chapter_outlines = all_chapter_outlines_result.scalars().all()
            
            # 构建章纲上下文
            outlines_context = "\n".join([
                f"第{co.chapter_number}章 {co.title}:\n摘要: {co.summary or ''}\n剧情要点: {co.plot_points or ''}"
                for co in all_chapter_outlines
            ])
            
            # 当前章节的详细规划
            try:
                key_events = json.loads(chapter_outline.key_events or '[]')
                characters_involved = json.loads(chapter_outline.characters_involved or '[]')
            except json.JSONDecodeError:
                key_events = []
                characters_involved = []
            
            current_outline_content = f"""
【章节标题】{chapter_outline.title}

【章节摘要】
{chapter_outline.summary or '无'}

【剧情要点】
{chapter_outline.plot_points or '无'}

【关键事件】
{', '.join(key_events) if key_events else '无'}

【涉及角色】
{', '.join(characters_involved) if characters_involved else '无'}

【目标字数】
{chapter_outline.target_word_count or target_word_count}字
"""
            
            logger.info(f"📖 使用章纲生成: 第{chapter_outline.chapter_number}章《{chapter_outline.title}》")
            
            # 🎯 获取章纲关联的剧情卡片
            plot_cards_result = await db_session.execute(
                select(PlotCard, PlotCardChapterOutlineLink.usage_type, PlotCardChapterOutlineLink.usage_notes)
                .join(PlotCardChapterOutlineLink, PlotCard.id == PlotCardChapterOutlineLink.plot_card_id)
                .where(PlotCardChapterOutlineLink.chapter_outline_id == chapter_outline.id)
                .order_by(PlotCardChapterOutlineLink.created_at)
            )
            linked_plot_cards_data = plot_cards_result.all()
            
            # 构建剧情卡片上下文
            linked_cards_context = ""
            if linked_plot_cards_data:
                cards_text = []
                for card, usage_type, usage_notes in linked_plot_cards_data[:10]:  # 限制最多10个卡片
                    card_type_label = {
                        'plot': '剧情',
                        'character': '角色',
                        'scene': '场景',
                        'conflict': '冲突'
                    }.get(card.card_type, '其他')
                    
                    usage_type_label = {
                        'reference': '参考',
                        'used': '已使用',
                        'planned': '计划使用'
                    }.get(usage_type or 'reference', '参考')
                    
                    # 截断内容，避免过长
                    content_preview = card.content[:200] if card.content else "无内容"
                    if len(card.content or "") > 200:
                        content_preview += "..."
                    
                    card_text = f"【{card_type_label}卡片】{card.title}（{usage_type_label}）\n{content_preview}"
                    if usage_notes:
                        card_text += f"\n使用说明：{usage_notes}"
                    
                    cards_text.append(card_text)
                
                linked_cards_context = "\n\n".join(cards_text)
                logger.info(f"📇 找到 {len(linked_plot_cards_data)} 个关联剧情卡片（使用前 {min(10, len(linked_plot_cards_data))} 个）")
                logger.info(f"📏 剧情卡片上下文长度: {len(linked_cards_context)} 字符")
            else:
                logger.info(f"📇 本章纲未关联剧情卡片")
            
            if linked_plot_cards_data:
                trace_reference("plot_cards", "关联剧情卡", [
                    {"title": card.title, "detail": usage_type or "reference"} for card, usage_type, _notes in linked_plot_cards_data[:10]
                ])

            # 获取角色信息
            characters_result = await db_session.execute(
                select(Character).where(Character.project_id == current_chapter.project_id)
            )
            characters = characters_result.scalars().all()
            characters_info = "\n".join([
                f"- {c.name}({'组织' if c.is_organization else '角色'}, {c.role_type}): {c.personality[:100] if c.personality else ''}"
                for c in characters
            ])
            
            # 获取写作风格
            style_content = ""
            if style_id:
                # 使用指定的风格
                style_result = await db_session.execute(
                    select(WritingStyle).where(WritingStyle.id == style_id)
                )
                style = style_result.scalar_one_or_none()
                if style:
                    # 验证风格是否可用：全局预设风格（project_id为NULL）或者当前项目的自定义风格
                    if style.project_id is None or style.project_id == current_chapter.project_id:
                        style_content = style.prompt_content or ""
                        style_type = "全局预设" if style.project_id is None else "项目自定义"
                        logger.info(f"使用指定风格: {style.name} ({style_type})")
                    else:
                        logger.warning(f"风格 {style_id} 不属于当前项目，无法使用")
                else:
                    logger.warning(f"未找到风格 {style_id}")
            else:
                logger.info("未指定写作风格，使用原始提示词")
            
            st_ctx.done(characters=len(characters), plot_cards=len(linked_plot_cards_data), outlines=len(all_chapter_outlines),
                        style=bool(style_content))
            st_smart = begin_stage("smart_context", "组装前文上下文 + 记忆")
            # 🚀 使用智能上下文构建（支持海量章节）
            smart_context = await build_smart_chapter_context(
                db=db_session,
                project_id=project.id,
                current_chapter_number=current_chapter.chapter_number,
                user_id=current_user_id
            )
            
            # 组装上下文
            previous_content = ""
            if smart_context['story_skeleton']:
                previous_content += smart_context['story_skeleton'] + "\n\n"
            if smart_context['relevant_history']:
                previous_content += smart_context['relevant_history'] + "\n\n"
            if smart_context['recent_summary']:
                previous_content += smart_context['recent_summary'] + "\n\n"
            if smart_context['recent_full']:
                previous_content += smart_context['recent_full']
            
            # 日志输出统计信息
            stats = smart_context['stats']
            logger.info(f"📊 智能上下文统计:")
            logger.info(f"  - 前置章节总数: {stats.get('total_previous', 0)}")
            logger.info(f"  - 故事骨架采样: {stats.get('skeleton_samples', 0)}章")
            logger.info(f"  - 相关历史检索: {stats.get('relevant_history', 0)}章")
            logger.info(f"  - 近期章节概要: {stats.get('recent_summaries', 0)}章")
            logger.info(f"  - 最近完整内容: {stats.get('recent_full', 0)}章")
            logger.info(f"  - 上下文总长度: {stats.get('total_length', 0)}字符")
            
            # 🧠 构建记忆增强上下文
            logger.info(f"🧠 开始构建记忆增强上下文...")
            memory_context = await memory_service.build_context_for_generation(
                user_id=current_user_id,
                project_id=project.id,
                current_chapter=current_chapter.chapter_number,
                chapter_outline=current_outline_content,
                character_names=[c.name for c in characters] if characters else None
            )
            state_context = await narrative_state_service.build_generation_context(
                db=db_session,
                project_id=project.id,
                current_chapter=current_chapter.chapter_number,
                pov_character_name=chapter_outline.pov if chapter_outline else None,
            )
            memory_context = {
                **memory_context,
                **state_context,
            }
            
            # 计算各部分的字符长度
            context_lengths = {
                'recent_context': len(memory_context.get('recent_context', '')),
                'relevant_memories': len(memory_context.get('relevant_memories', '')),
                'foreshadows': len(memory_context.get('foreshadows', '')),
                'character_states': len(memory_context.get('character_states', '')),
                'plot_points': len(memory_context.get('plot_points', ''))
            }
            total_memory_length = sum(context_lengths.values())
            
            logger.info(f"✅ 记忆上下文构建完成: {memory_context['stats']}")
            logger.info(f"📏 记忆上下文长度统计:")
            logger.info(f"  - 最近章节记忆: {context_lengths['recent_context']} 字符")
            logger.info(f"  - 语义相关记忆: {context_lengths['relevant_memories']} 字符")
            logger.info(f"  - 未完结伏笔: {context_lengths['foreshadows']} 字符")
            logger.info(f"  - 角色状态记忆: {context_lengths['character_states']} 字符")
            logger.info(f"  - 重要情节点: {context_lengths['plot_points']} 字符")
            logger.info(f"  - 记忆总长度: {total_memory_length} 字符")
            logger.info(f"  - 前置章节上下文长度: {len(previous_content)} 字符")
            logger.info(f"  - 总上下文长度(估算): {total_memory_length + len(previous_content) + 2000} 字符")
        
            st_smart.done(previous_chapters=stats.get('total_previous', 0), context_chars=stats.get('total_length', 0),
                          memory_chars=total_memory_length)
            trace_reference("memory", "记忆与前文上下文", [
                {"title": "故事骨架采样", "detail": f"{stats.get('skeleton_samples', 0)} 章"},
                {"title": "相关历史检索", "detail": f"{stats.get('relevant_history', 0)} 章"},
                {"title": "近期章节概要", "detail": f"{stats.get('recent_summaries', 0)} 章"},
                {"title": "最近完整内容", "detail": f"{stats.get('recent_full', 0)} 章"},
                {"title": "语义相关记忆", "detail": f"{context_lengths['relevant_memories']} 字符"},
                {"title": "未完结伏笔", "detail": f"{context_lengths['foreshadows']} 字符"},
                {"title": "角色状态记忆", "detail": f"{context_lengths['character_states']} 字符"},
            ], chars=total_memory_length + len(previous_content))
            job.progress('开始AI创作...', 25)
            
            # 🔧 MCP工具增强：收集章节参考资料（使用剧情线标准模式）
            mcp_reference_materials = ""
            # 前置检查：用户是否有启用的 MCP 插件，没有则直接跳过（避免白等 1 分钟+）
            _has_mcp_plugins = False
            if enable_mcp and current_user_id:
                from app.services.mcp_tool_service import mcp_tool_service
                _available_tools = await mcp_tool_service.get_user_enabled_tools(
                    user_id=current_user_id,
                    db_session=db_session,
                    plugin_names=selected_plugins,
                )
                _has_mcp_plugins = len(_available_tools) > 0
                if not _has_mcp_plugins:
                    logger.info("⏭️ 用户没有启用的MCP插件，跳过MCP工具收集")

            if enable_mcp and current_user_id and _has_mcp_plugins:
                st_mcp = begin_stage("mcp", "MCP 规划收集参考资料")
                job.progress('🔍 尝试使用MCP工具收集参考资料...', 28)

                # 使用 PlotGenerationService._plan_with_mcp 进行严格的 MCP 规划
                from app.services.plot_generation_service import PlotGenerationService
                plot_service = PlotGenerationService(user_ai_service)

                project_data = {
                    'title': project.title,
                    'genre': project.genre or '未知',
                    'theme': project.theme or '未知'
                }

                # 调用统一的 MCP 规划方法
                # 这里会：
                # 1. 强制工具调用（tool_choice="required"）
                # 2. 工具未触发时抛出 MCPToolNotTriggeredError
                # 3. 其他异常包装为 MCPPlanningFailedError
                planning_result = await plot_service._plan_with_mcp(
                    context_type="chapter_content",
                    project_data=project_data,
                    outline_content=None,
                    chapter_outline=current_outline_content,
                    user_id=current_user_id,
                    db_session=db_session,
                    selected_plugins=selected_plugins,
                    provider=None,
                    model=None
                )

                # 提取参考资料（已经过截断处理）
                mcp_reference_materials = planning_result.get("reference_materials", "")
                tool_count = planning_result.get("tool_calls_made", 0)
                tools_used = planning_result.get("tools_used", [])
                planning_time = planning_result.get("planning_time", 0)

                job.progress(f'✅ MCP工具调用成功（{tool_count}次，耗时{planning_time:.1f}秒）', 32)
                logger.info(f"📚 MCP工具收集参考资料：{len(mcp_reference_materials)} 字符")
                logger.info(f"  - 使用的工具: {', '.join(tools_used)}")
                logger.info(f"  - 规划耗时: {planning_time:.2f}秒")
                st_mcp.done(tools=len(tools_used), chars=len(mcp_reference_materials))

            # 拆书参考注入（R5-S3）：把已挂载参考包的 style/methodology/corpus 等拼到生成参数
            # user_segment → mcp_references；system_segment（style 维度）→ style_content
            # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
            st_ref = begin_stage("reference_pack", "组装拆书参考包")
            try:
                from app.services.reference_pack_injector import ReferencePackInjector
                _injector = ReferencePackInjector()
                _anchor = (
                    f"{current_chapter.title or ''} "
                    f"{current_outline_content[:300] if current_outline_content else ''}"
                ).strip() or "章节正文"
                _ref_block = await _injector.build_reference_block(
                    db_session, project.id,
                    scene="chapter_content",
                    pack_ids=generate_request.pack_ids,
                    dimensions=generate_request.dimensions,
                    strength=generate_request.strength,
                    anchor_query=_anchor,
                )
                if _ref_block.user_segment:
                    mcp_reference_materials = (
                        f"{mcp_reference_materials}\n\n{_ref_block.user_segment}".strip()
                        if mcp_reference_materials
                        else _ref_block.user_segment
                    )
                if _ref_block.system_segment:
                    # 拆书 style 维度并入项目内已有 writing_style（叠加注入，互不冲突）
                    style_content = (
                        f"{style_content}\n\n{_ref_block.system_segment}".strip()
                        if style_content
                        else _ref_block.system_segment
                    )
                if not _ref_block.is_empty:
                    logger.info(
                        f"📚 [R5-章节正文] 注入拆书参考包 {len(_ref_block.used_packs)} 个，"
                        f"维度={_ref_block.used_dimensions}，强度={_ref_block.used_strength}"
                    )
                    _dims_label = ','.join(_ref_block.used_dimensions)
                    job.progress(f'📚 已注入拆书参考包（{_dims_label}）', 33)
                    st_ref.done(packs=len(_ref_block.used_packs), dimensions=_dims_label, strength=_ref_block.used_strength)
                else:
                    st_ref.skip("参考包无可用内容")
            except ValueError:
                # 项目未挂载参考包 → 优雅跳过
                st_ref.skip("项目未挂载参考包")
            except Exception as _e:  # pragma: no cover - 防御性兜底
                logger.warning(f"[R5-章节正文] 拆书参考注入失败（已跳过）: {_e}")
                st_ref.skip("注入失败，已跳过")

            # 🆕 V4.1 K2 桥段位置约束注入（chapter_outline 含 bridge_id 时自动启用）
            # 与上方 v3 拆书注入互补：v3 管拆书维度，V4 管桥段位置约束
            st_bridge = None
            try:
                from app.services.reference_pack import (
                    build_v4_bridge_constraint_only,
                    fetch_bridge_context,
                )
                # 本函数里章纲变量叫 chapter_outline（上文第 1559 行）；此前误写 current_outline，
                # NameError 被下面的 except 吞成 WARNING，导致桥段位置约束从未真正注入
                if chapter_outline and getattr(chapter_outline, "bridge_id", None):
                    st_bridge = begin_stage("bridge_constraint", "桥段位置约束")
                    _v4_bridge_seg = None
                    _bridge_ctx = await fetch_bridge_context(db_session, chapter_outline)
                    if _bridge_ctx:
                        _v4_bridge_seg = await build_v4_bridge_constraint_only(
                            db_session, project.id,
                            scene="chapter_content",
                            model_name=getattr(user_ai_service, "default_model", None) or "deepseek-v3",
                            bridge_position=chapter_outline.bridge_position,
                            bridge_context=_bridge_ctx,
                            chapter_outline_id=chapter_outline.id,
                            target_word_count=target_word_count,
                        )
                        if _v4_bridge_seg:
                            mcp_reference_materials = (
                                f"{mcp_reference_materials}\n\n{_v4_bridge_seg}".strip()
                                if mcp_reference_materials
                                else _v4_bridge_seg
                            )
                            logger.info(
                                f"🎯 [V4.1 K2] 注入桥段位置约束 "
                                f"position={chapter_outline.bridge_position} "
                                f"bridge={_bridge_ctx.get('title','?')}"
                            )
                    st_bridge.done(position=chapter_outline.bridge_position, injected=bool(_v4_bridge_seg))
            except Exception as _be:  # pragma: no cover
                logger.warning(f"[V4.1 K2] 桥段约束注入失败（已跳过）: {_be}")
                if st_bridge is not None:
                    st_bridge.skip("注入失败，已跳过")

            # 根据是否有前置内容选择不同的提示词，并应用写作风格、记忆增强、剧情卡片和MCP参考资料
            if previous_content:
                prompt = prompt_service.get_chapter_generation_with_context_prompt(
                    title=project.title,
                    theme=project.theme or '',
                    genre=project.genre or '',
                    narrative_perspective=project.narrative_perspective or '第三人称',
                    time_period=project.world_time_period or '未设定',
                    location=project.world_location or '未设定',
                    atmosphere=project.world_atmosphere or '未设定',
                    rules=final_world_rules,
                    characters_info=characters_info or '暂无角色信息',
                    outlines_context=outlines_context,
                    previous_content=previous_content,
                    chapter_number=current_chapter.chapter_number,
                    chapter_title=current_chapter.title,
                    chapter_outline=current_outline_content,
                    style_content=style_content,
                    target_word_count=target_word_count,
                    memory_context=memory_context,
                    linked_cards_context=linked_cards_context,
                    mcp_references=mcp_reference_materials,
                )
            else:
                prompt = prompt_service.get_chapter_generation_prompt(
                    title=project.title,
                    theme=project.theme or '',
                    genre=project.genre or '',
                    narrative_perspective=project.narrative_perspective or '第三人称',
                    time_period=project.world_time_period or '未设定',
                    location=project.world_location or '未设定',
                    atmosphere=project.world_atmosphere or '未设定',
                    rules=final_world_rules,
                    characters_info=characters_info or '暂无角色信息',
                    outlines_context=outlines_context,
                    chapter_number=current_chapter.chapter_number,
                    chapter_title=current_chapter.title,
                    chapter_outline=current_outline_content,
                    style_content=style_content,
                    target_word_count=target_word_count,
                    memory_context=memory_context,
                    linked_cards_context=linked_cards_context,
                    mcp_references=mcp_reference_materials,
                )

            prompt = prompt_service.apply_project_generation_prompt(
                prompt,
                project.generation_prompt or ''
            )
            
            if mcp_reference_materials:
                logger.info(f"📖 已整合MCP参考资料（{len(mcp_reference_materials)}字符）到章节生成提示词")
            
            if linked_cards_context:
                logger.info(f"📇 已整合剧情卡片上下文（{len(linked_cards_context)}字符）到章节生成提示词")
            
            logger.info(f"开始AI流式创作章节 {chapter_id}")
            job.progress('🎨 AI开始创作章节内容...', 35)

            # 流式生成内容（content 事件逐块进任务日志：重连即可重建全文；进度每累计 ≥200 字发一次）
            st_llm = begin_stage("llm", "模型创作正文")
            full_content = ""
            accumulated_length = 0
            last_progress_at = 0
            async for chunk in user_ai_service.generate_text_stream(prompt=prompt):
                full_content += chunk
                accumulated_length += len(chunk)

                # 发送内容块（使用 'content' 类型，与前端保持一致）
                job.publish({'type': 'content', 'content': chunk})

                # 计算进度（35%-95%，为后处理预留5%）
                if accumulated_length - last_progress_at >= 200:
                    last_progress_at = accumulated_length
                    generation_progress = min(35 + (accumulated_length / target_word_count) * 60, 95)
                    job.publish({'type': 'progress', 'message': f'🎨 AI 创作中… 已写出 {accumulated_length} 字',
                                 'progress': int(generation_progress), 'status': 'processing', 'word_count': accumulated_length})

                await asyncio.sleep(0)  # 让出控制权
            st_llm.done(chars=accumulated_length)
            st_persist = begin_stage("persist", "写入正文 / 生成历史")
            
            # 更新章节内容到数据库
            old_word_count = current_chapter.word_count or 0
            current_chapter.content = full_content
            new_word_count = count_words(full_content)
            current_chapter.word_count = new_word_count
            current_chapter.status = "completed"
            
            # 更新项目字数
            project.current_words = project.current_words - old_word_count + new_word_count
            
            # 记录生成历史
            history = GenerationHistory(
                project_id=current_chapter.project_id,
                chapter_id=current_chapter.id,
                prompt=f"创作章节: 第{current_chapter.chapter_number}章 {current_chapter.title}",
                generated_content=full_content[:500] if len(full_content) > 500 else full_content,
                model="default"
            )
            db_session.add(history)
            
            await db_session.commit()
            await db_session.refresh(current_chapter)

            logger.info(f"成功创作章节 {chapter_id}，共 {new_word_count} 字")
            job.publish({'type': 'progress', 'message': '✅ 章节创作完成', 'progress': 95, 'status': 'processing', 'word_count': new_word_count})
            
            st_persist.done(word_count=new_word_count)

            # 单章生成：不自动分析，仅落库（用户可先改正文再手动分析）。
            # 批量生成（auto_analyze=True）：自动排队分析，累积记忆并支撑批量一致性闸门。
            if not auto_analyze:
                return {'word_count': new_word_count, 'analysis_task_id': None, 'analysis_job_id': None}

            st_ana = begin_stage("analysis", "排队章节分析")
            task_id = await create_analysis_task(db_session, chapter_id=chapter_id, user_id=current_user_id, project_id=project.id)
            logger.info(f"📋 已创建分析任务: {task_id}")
            analysis_job_id = None
            try:
                analysis_job = await start_chapter_analysis(
                    chapter_id=chapter_id, chapter_number=current_chapter.chapter_number, chapter_title=current_chapter.title,
                    user_id=current_user_id, project_id=project.id, task_id=task_id, ai_service=user_ai_service,
                )
                analysis_job_id = analysis_job.id
                st_ana.done(task_id=task_id)
            except AIJobConflictError as conflict:
                logger.warning(f"⚠️ 章节分析任务未启动（已有同章分析在跑）: {conflict}")
                st_ana.skip("同章分析任务已在运行")

            return {'word_count': new_word_count, 'analysis_task_id': task_id, 'analysis_job_id': analysis_job_id}
            
    try:
        job = await ai_jobs.start(
            kind="chapter_generate",
            title=f"生成第 {chapter.chapter_number} 章《{chapter.title}》",
            user_id=user_id,
            project_id=chapter.project_id,
            scope=f"chapter_write:{chapter.project_id}",
            runner=runner,
            cancel_message="已停止生成；本章正文未写入",
            meta={"chapter_id": chapter_id, "target_word_count": target_word_count},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)



@router.get("/{chapter_id}/analysis/status", summary="查询章节分析任务状态")
async def get_analysis_task_status(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    查询指定章节的最新分析任务状态
    
    自动恢复机制：
    - 如果任务状态为running且超过配置阈值未完成，自动标记为failed
    - 如果任务状态为pending且超过配置阈值未启动，自动标记为failed
    
    返回:
    - has_task: 是否存在分析任务
    - task_id: 任务ID（如果存在）
    - status: pending/running/completed/failed/none（如果不存在则为none）
    - progress: 0-100
    - error_message: 错误信息(如果失败)
    - auto_recovered: 是否被自动恢复
    - created_at: 创建时间
    - completed_at: 完成时间
    
    注意：当章节不存在或无权访问时返回404，当没有分析任务时返回has_task=false
    """
    from datetime import timedelta
    
    # 先获取章节以验证存在性和权限
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取该章节最新的分析任务
    result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id == chapter_id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        # 返回无任务状态，而不是抛出404错误
        return {
            "has_task": False,
            "chapter_id": chapter_id,
            "status": "none",
            "progress": 0,
            "error_message": None,
            "auto_recovered": False,
            "task_id": None,
            "created_at": None,
            "started_at": None,
            "completed_at": None
        }
    
    auto_recovered = False
    current_time = datetime.now()
    running_timeout = timedelta(seconds=max(config_settings.analysis_task_running_timeout_seconds, 60))
    pending_timeout = timedelta(seconds=max(config_settings.analysis_task_pending_timeout_seconds, 30))
    
    # 自动恢复卡住的任务
    if task.status == 'running':
        # 如果任务在running状态超过阈值，标记为失败
        if task.started_at and (current_time - task.started_at) > running_timeout:
            task.status = 'failed'
            timeout_minutes = max(config_settings.analysis_task_running_timeout_seconds // 60, 1)
            task.error_message = f'任务超时（超过{timeout_minutes}分钟未完成，已自动恢复）'
            task.completed_at = current_time
            task.progress = 0
            auto_recovered = True
            await db.commit()
            await db.refresh(task)
            logger.warning(f"🔄 自动恢复卡住的任务: {task.id}, 章节: {chapter_id}")
    
    elif task.status == 'pending':
        # 如果任务在pending状态超过阈值仍未开始，标记为失败
        if task.created_at and (current_time - task.created_at) > pending_timeout:
            task.status = 'failed'
            timeout_minutes = max(config_settings.analysis_task_pending_timeout_seconds // 60, 1)
            task.error_message = f'任务启动超时（超过{timeout_minutes}分钟未启动，已自动恢复）'
            task.completed_at = current_time
            task.progress = 0
            auto_recovered = True
            await db.commit()
            await db.refresh(task)
            logger.warning(f"🔄 自动恢复未启动的任务: {task.id}, 章节: {chapter_id}")
    
    return {
        "has_task": True,
        "task_id": task.id,
        "chapter_id": task.chapter_id,
        "status": task.status,
        "progress": task.progress,
        "error_message": task.error_message,
        "auto_recovered": auto_recovered,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None
    }


@router.get("/{chapter_id}/analysis", summary="获取章节分析结果")
async def get_chapter_analysis(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取章节的完整分析结果
    
    返回:
    - analysis_data: 完整的分析数据(JSON)
    - summary: 分析摘要文本
    - memories: 提取的记忆列表
    - created_at: 分析时间
    """
    # 先获取章节以验证权限
    chapter_result_check = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter_check = chapter_result_check.scalar_one_or_none()
    if not chapter_check:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter_check.project_id, user_id, db)
    
    # 获取分析结果
    analysis_result = await db.execute(
        select(PlotAnalysis)
        .where(PlotAnalysis.chapter_id == chapter_id)
        .order_by(PlotAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = analysis_result.scalar_one_or_none()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="该章节暂无分析结果")
    
    # 获取相关记忆
    memories_result = await db.execute(
        select(StoryMemory)
        .where(StoryMemory.chapter_id == chapter_id)
        .order_by(StoryMemory.importance_score.desc())
    )
    memories = memories_result.scalars().all()

    visualization_payload = await chapter_consistency_service.build_chapter_visualization_payload(
        db=db,
        chapter=chapter_check,
    )

    # 失效判定：章节内容在分析之后被修改过 → 分析/记忆/审计结果可能过期
    is_stale = bool(
        analysis.created_at
        and chapter_check.updated_at
        and chapter_check.updated_at > analysis.created_at
    )

    return {
        "chapter_id": chapter_id,
        "is_stale": is_stale,
        "content_updated_at": chapter_check.updated_at.isoformat() if chapter_check.updated_at else None,
        "analysis": analysis.to_dict(),  # 使用to_dict()方法
        "memories": [
            {
                "id": mem.id,
                "type": mem.memory_type,
                "title": mem.title,
                "content": mem.content,
                "importance": mem.importance_score,
                "tags": mem.tags,
                "is_foreshadow": mem.is_foreshadow,
                "position": mem.chapter_position,
                "related_characters": mem.related_characters
            }
            for mem in memories
        ],
        "narrative_state": {
            "causal_links": visualization_payload["causal_links"],
            "promises": visualization_payload["promises"],
            "timeline_events": visualization_payload["timeline_events"],
            "relationship_graph": visualization_payload["relationship_graph"],
        },
        "consistency_audit": visualization_payload["consistency_audit"],
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None
    }


# 可在章节正文中定位/展示的记忆类型（与前端 AnnotatedText / MemorySidebar 的类型集合一致）
ANNOTATION_MEMORY_TYPES = ("hook", "foreshadow", "plot_point", "character_event")


@router.get("/{chapter_id}/annotations", summary="获取章节标注数据")
async def get_chapter_annotations(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取章节的标注数据（用于前端展示标注）
    
    返回格式化的标注列表，包含精确位置信息
    适用于章节内容的可视化标注展示
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    
    # 获取章节
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证项目访问权限
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取分析结果
    analysis_result = await db.execute(
        select(PlotAnalysis)
        .where(PlotAnalysis.chapter_id == chapter_id)
        .order_by(PlotAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = analysis_result.scalar_one_or_none()
    
    # 获取记忆：只取锚定在正文上的标注类型。
    # chapter_summary 记忆的 chapter_position/text_length 是 (0, len(摘要))，与正文无关，
    # 若原样下发会变成一条吞掉章节开头的伪标注，与真实标注重叠导致前端正文错位、重复。
    memories_result = await db.execute(
        select(StoryMemory)
        .where(
            StoryMemory.chapter_id == chapter_id,
            StoryMemory.memory_type.in_(ANNOTATION_MEMORY_TYPES),
        )
        .order_by(StoryMemory.importance_score.desc())
    )
    memories = memories_result.scalars().all()
    
    # 构建标注数据
    annotations = []
    
    for mem in memories:
        # 优先从数据库读取位置信息
        position = mem.chapter_position if mem.chapter_position is not None else -1
        length = mem.text_length if hasattr(mem, 'text_length') and mem.text_length is not None else 0
        metadata_extra = {}
        
        # 如果数据库中没有位置信息，尝试从分析数据中重新计算
        if position == -1 and analysis and chapter.content:
            # 根据记忆类型从分析数据中查找对应项
            if mem.memory_type == 'hook' and analysis.hooks:
                for hook in analysis.hooks:
                    # 通过标题或内容匹配
                    if mem.title and hook.get('type') in mem.title:
                        keyword = hook.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        metadata_extra["strength"] = hook.get('strength', 5)
                        metadata_extra["position_desc"] = hook.get('position', '')
                        break
            
            elif mem.memory_type == 'foreshadow' and analysis.foreshadows:
                for foreshadow in analysis.foreshadows:
                    if foreshadow.get('content') in mem.content:
                        keyword = foreshadow.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        metadata_extra["foreshadow_type"] = foreshadow.get('type', 'planted')
                        metadata_extra["strength"] = foreshadow.get('strength', 5)
                        break
            
            elif mem.memory_type == 'plot_point' and analysis.plot_points:
                for plot_point in analysis.plot_points:
                    if plot_point.get('content') in mem.content:
                        keyword = plot_point.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        break
        else:
            # 如果数据库有位置，也从分析数据中提取额外的元数据
            if analysis:
                if mem.memory_type == 'hook' and analysis.hooks:
                    for hook in analysis.hooks:
                        if mem.title and hook.get('type') in mem.title:
                            metadata_extra["strength"] = hook.get('strength', 5)
                            metadata_extra["position_desc"] = hook.get('position', '')
                            break
                
                elif mem.memory_type == 'foreshadow' and analysis.foreshadows:
                    for foreshadow in analysis.foreshadows:
                        if foreshadow.get('content') in mem.content:
                            metadata_extra["foreshadow_type"] = foreshadow.get('type', 'planted')
                            metadata_extra["strength"] = foreshadow.get('strength', 5)
                            break
        
        annotation = {
            "id": mem.id,
            "type": mem.memory_type,
            "title": mem.title,
            "content": mem.content,
            "importance": mem.importance_score or 0.5,
            "position": position,
            "length": length,
            "tags": mem.tags or [],
            "metadata": {
                "is_foreshadow": mem.is_foreshadow,
                "related_characters": mem.related_characters or [],
                "related_locations": mem.related_locations or [],
                **metadata_extra
            }
        }
        
        annotations.append(annotation)
    
    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "word_count": chapter.word_count or 0,
        "annotations": annotations,
        "has_analysis": analysis is not None,
        "summary": {
            "total_annotations": len(annotations),
            "hooks": len([a for a in annotations if a["type"] == "hook"]),
            "foreshadows": len([a for a in annotations if a["type"] == "foreshadow"]),
            "plot_points": len([a for a in annotations if a["type"] == "plot_point"]),
            "character_events": len([a for a in annotations if a["type"] == "character_event"])
        }
    }


@router.post("/{chapter_id}/analyze-stream", summary="手动触发章节分析（后台任务 + SSE 事件流）")
async def trigger_chapter_analysis_stream(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """手动触发章节分析（重新分析 / 分析旧章节）。

    建 AnalysisTask 行 → 启动 chapter_analyze 后台任务并从头流式输出其事件
    （stage：analyze / persist_analysis / memories / vector；llm 进度自动上报）。
    AnalysisTask 行仍由 analyze_chapter_background 维护，/analysis/status 照常可查；同章已在分析 → 409。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not chapter.content or chapter.content.strip() == "":
        raise HTTPException(status_code=400, detail="章节内容为空，无法分析")
    
    project_result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = project_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    task_id = await create_analysis_task(db, chapter_id=chapter_id, user_id=user_id, project_id=project.id)
    logger.info(f"📋 创建分析任务: {task_id}, 章节: {chapter_id}")
    try:
        job = await start_chapter_analysis(
            chapter_id=chapter_id,
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.title,
            user_id=user_id,
            project_id=project.id,
            task_id=task_id,
            ai_service=user_ai_service,
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)



# ==================== 去 AI 味重写 ====================

@router.post("/{chapter_id}/regenerate-stream", summary="按去 AI 味提示词重写正文并覆盖（后台任务 + SSE）")
async def regenerate_chapter_stream(
    chapter_id: str,
    request: Request,
    regenerate_request: ChapterRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """提示词只带用户勾选的项目去 AI 味提示词 + 本章原文（不带章纲 / 前文 / 设定）。

    完成后直接覆盖正文，并清掉本章已有的分析产物（分析 / 记忆 / 伏笔承诺 / 一致性…），回到「未分析」。不留版本、不可回滚。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    chapter = (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not (chapter.content or "").strip():
        raise HTTPException(status_code=400, detail="章节内容为空，无法重写")
    await verify_project_access(chapter.project_id, user_id, db)

    rows = (await db.execute(
        select(DeaiPrompt).where(DeaiPrompt.project_id == chapter.project_id, DeaiPrompt.id.in_(regenerate_request.prompt_ids))
    )).scalars().all()
    by_id = {row.id: row.content for row in rows}
    prompt_texts = [by_id[pid] for pid in regenerate_request.prompt_ids if pid in by_id]  # 保持用户勾选顺序
    if not prompt_texts:
        raise HTTPException(status_code=400, detail="请至少选择一条本项目的去 AI 味提示词")
    prompt = build_rewrite_prompt(prompt_texts, chapter.content)
    original_len = max(len(chapter.content), 1)
    project_id = chapter.project_id

    async def runner(job):
        """后台任务体：流式重写 → 覆盖正文 → 清旧分析与记忆。事件进任务日志，可回放。"""
        st_llm = begin_stage("llm", "模型按去 AI 味提示词重写正文")
        job.progress("开始重写…", 5)
        full_content = ""
        accumulated = 0
        last_progress_at = 0
        async for chunk in user_ai_service.generate_text_stream(prompt=prompt):
            full_content += chunk
            accumulated += len(chunk)
            job.publish({"type": "content", "content": chunk})
            if accumulated - last_progress_at >= 200:
                last_progress_at = accumulated
                job.publish({
                    "type": "progress", "message": f"重写中… 已写出 {accumulated} 字",
                    "progress": int(min(5 + accumulated / original_len * 85, 90)), "status": "processing", "word_count": accumulated,
                })
            await asyncio.sleep(0)
        st_llm.done(chars=accumulated)
        if not full_content.strip():
            raise ValueError("模型没有返回内容，正文未改动")

        st_persist = begin_stage("persist", "覆盖正文 / 清理旧分析与记忆")
        async with job_session_factory(user_id)() as db_session:
            target = (await db_session.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
            if not target:
                raise ValueError("章节不存在")
            old_wc = target.word_count or 0
            new_wc = count_words(full_content)
            target.content = full_content
            target.word_count = new_wc
            target.status = "completed"
            project = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if project:
                project.current_words = max(0, (project.current_words or 0) - old_wc + new_wc)
            purged = await _purge_chapter_analysis_and_memory(db_session, chapter_id)
            await db_session.commit()
        st_persist.done(word_count=new_wc, purged_memories=purged)
        await _purge_chapter_vector_memory(user_id, project_id, chapter_id, purged)
        logger.info(f"✅ 去 AI 味重写完成并覆盖正文: {chapter_id}，{new_wc} 字，清理旧记忆 {purged} 条")
        return {"word_count": new_wc}

    try:
        job = await ai_jobs.start(
            kind="chapter_regenerate",
            title=f"去 AI 味重写第 {chapter.chapter_number} 章《{chapter.title}》",
            user_id=user_id,
            project_id=project_id,
            scope=f"chapter_write:{project_id}",
            runner=runner,
            cancel_message="已停止重写；正文未改动",
            meta={"chapter_id": chapter_id},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)
