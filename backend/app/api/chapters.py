"""章节管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import defer
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime
from asyncio import Lock
from typing import Any, Optional

from app.config import settings as app_settings
from app.database import get_db
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
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
    ChapterBatchRequest,
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterListItem,
    ChapterListResponse,
    ChapterGenerateRequest,
)
from app.schemas.regeneration import ChapterRegenerateRequest
from app.api.ai_jobs import job_sse_response
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.ai_service import AIService, last_stream_finish_reason, reset_stream_finish_reason
from app.services import ai_flavor_metrics
from app.services.chapter_analysis_jobs import create_analysis_task, start_chapter_analysis
from app.services.chapter_batch_service import (
    CANCELLED_MESSAGE as BATCH_CANCELLED_MESSAGE,
    KIND as BATCH_KIND,
    BatchOptions,
    isolated_sqlite_engine,
    run_batch,
)
from app.services.chapter_context_service import (
    build_character_context,
    build_outline_window,
    build_query_text,
    parse_json_list,
)
from app.services.volume_context import fetch_volume_context, render_structure
from app.services.volume_context import hook_policy as volume_hook_policy
from app.services.chapter_prompt_builder import ChapterPromptInput, build_chapter_prompt, build_continuation_prompt
from app.services.adherence_review_service import has_reviewable_contract, review_candidate
from app.services.chapter_candidate_service import create_candidate
from app.services.chapter_purge_service import purge_chapter_analysis, purge_chapter_vector_memory
from app.services.chapter_readiness_service import (
    analysis_is_stale,
    chapter_brief,
    previous_chapter_issues,
    previous_issues_message,
)
from app.services.chapter_version_service import content_hash, replace_chapter_content
from app.services import outline_review_service as outline_review
from app.services.outline_contract import forbidden_items, outline_fingerprint
from app.services.platform_presets import default_chapter_words, platform_block
from app.services.deai_rewrite import (
    build_local_rewrite_prompt,
    build_rewrite_prompt,
    merge_paragraphs,
    parse_local_rewrite,
    split_paragraph_lines,
)
from app.services.generation_trace import begin_stage, stage_scope, trace_progress, trace_reference
from app.services.world_map_context import chapter_map_reference
from app.services.prompt_service import prompt_service
from app.services.plot_analyzer import PlotAnalyzer
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service
from app.services.narrative_tasks import render_narrative_tasks, task_promise_ids
from app.services import arc_summary_service
from app.logger import get_logger
from app.api.settings import get_user_ai_service
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
        if not is_org:
            field_map["speech_style"] = "speech_style"
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
            role_type = (_val(char.get("role_type")) or "minor").lower()
            if role_type == "minor":
                # 龙套（店小二 / 路人甲）不建档：长篇里每章都冒几个，角色表会无限膨胀；
                # 之后若升格为配角（再次出场且抽取为 supporting+）自然会建档
                continue
            import json as _json
            traits_raw = char.get("traits")
            traits_str = _json.dumps(traits_raw, ensure_ascii=False) if isinstance(traits_raw, list) and traits_raw else None
            new_char = Character(
                project_id=project_id,
                name=name,
                gender=_val(char.get("gender")),
                age=_val(char.get("age")),
                role_type=role_type,
                personality=_val(char.get("personality")),
                appearance=_val(char.get("appearance")),
                speech_style=_val(char.get("speech_style")),
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
                ).limit(1)
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
    """获取指定项目的所有章节（不含正文：列表只用元数据，正文按章 GET /chapters/{id}）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    # 不分页、一次取全，total 直接用行数；defer(content) 让几百章的全文不再进内存 / 不再进响应
    result = await db.execute(
        select(Chapter)
        .options(defer(Chapter.content))
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    chapters = result.scalars().all()
    outlines = {
        o.id: o for o in (await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id)
        )).scalars().all()
    }
    pending = dict((await db.execute(
        select(ChapterCandidate.chapter_id, func.count(ChapterCandidate.id))
        .where(ChapterCandidate.project_id == project_id, ChapterCandidate.status == "pending")
        .group_by(ChapterCandidate.chapter_id)
    )).all())

    items = []
    for chapter in chapters:
        item = ChapterListItem.model_validate(chapter)
        outline = outlines.get(chapter.chapter_outline_id) if chapter.chapter_outline_id else None
        if outline is not None:
            item.outline_review_status = outline.review_status
            item.outline_upstream_stale = bool(outline.upstream_stale)
            item.outline_changed = bool(
                (chapter.word_count or 0) > 0 and chapter.outline_hash
                and outline_fingerprint(outline) != chapter.outline_hash
            )
        item.pending_candidates = pending.get(chapter.id, 0)
        items.append(item)
    return ChapterListResponse(total=len(items), items=items)


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

    update_data = chapter_update.model_dump(exclude_unset=True)
    content_given = "content" in update_data
    new_content = update_data.pop("content", None)
    base_hash = update_data.pop("base_hash", None)
    # 编辑器自动保存带 base_hash：正文在别处被改过（采用候选稿 / 恢复旧版 / 另一个窗口）就拒绝，不覆盖
    if content_given and base_hash is not None and base_hash != content_hash(chapter.content):
        raise HTTPException(status_code=409, detail="正文在别处被改过（如采用了候选稿或在其他窗口编辑），请先载入最新内容")
    for field, value in update_data.items():
        setattr(chapter, field, value)

    # 正文变化：旧稿先进历史版本，再写新稿并同步字数（含清空为 "" 的场景）。
    # 自动保存（带 base_hash）同一写作时段只留一个版本；局部手改不清分析，分析结果靠正文指纹判过期，生成前预检会提醒重新分析
    if content_given:
        await replace_chapter_content(db, chapter, new_content, reason="manual_edit", coalesce=base_hash is not None)

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


# 整章替换后的分析清理在 chapter_purge_service（版本恢复 / 候选稿采用共用）；保留旧名供本模块与测试引用
_purge_chapter_analysis_and_memory = purge_chapter_analysis
_purge_chapter_vector_memory = purge_chapter_vector_memory


RECENT_FULL_COUNT = 2
RECENT_SUMMARY_COUNT = 10
RECENT_SUMMARY_MAX = 30
RELEVANT_HISTORY_LIMIT = 8
STORY_SO_FAR_BUDGET = 4000


async def build_smart_chapter_context(
    db: AsyncSession,
    project_id: str,
    current_chapter_number: int,
    user_id: str,
    query_text: str | None = None,
) -> dict:
    """
    智能构建章节生成上下文（长篇版：总长基本不随章数增长）

    策略：
    1. 前情脉络（story_skeleton 键）：层级摘要（卷 / 阶段 / 单元），每段章节取能覆盖它的最高一级
    2. 近期概要：层级摘要尚未覆盖的章节 + 最近 RECENT_SUMMARY_COUNT 章（不含全文章节），最多 RECENT_SUMMARY_MAX 章
    3. 相关历史：章节摘要语义检索（限定本章之前，去掉已在近期段里的章节）
    4. 最近完整：最近 RECENT_FULL_COUNT 章全文（衔接口吻与动作）

    Args:
        query_text: 精简检索语句（标题 + 关键事件 + 出场人物）；不给则用本章章纲
    """
    context_parts = {
        'story_skeleton': '',      # 前情脉络（层级摘要）
        'relevant_history': '',    # 相关历史章节
        'recent_summary': '',      # 近期概要
        'recent_full': '',         # 最近完整内容
        'stats': {}                # 统计信息
    }

    relevant_memories = []
    recent_summaries = []

    try:
        # 1. 前置章节（只取 ID / 序号 / 标题）
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
        chapters_by_id = {info.id: info for info in all_chapters_info}

        # 2. 前情脉络：层级摘要
        story_so_far, covered_until = await arc_summary_service.render_story_so_far(
            db, project_id, current_chapter_number, budget_chars=STORY_SO_FAR_BUDGET,
        )
        if story_so_far:
            context_parts['story_skeleton'] = "【前情脉络】\n" + story_so_far

        # 3. 各段章节范围：最近 N 章全文；近期概要 = 层级摘要未覆盖的 ∪ 最近 10 章（不含全文章节）
        recent_full_chapters = all_chapters_info[-min(RECENT_FULL_COUNT, total_previous):]
        full_ids = {info.id for info in recent_full_chapters}
        candidates = [info for info in all_chapters_info if info.id not in full_ids]
        tail = candidates[-RECENT_SUMMARY_COUNT:]
        uncovered = [info for info in candidates if info.chapter_number > covered_until]
        tail_ids = {info.id for info in tail}
        summary_targets = sorted(
            {info.id: info for info in [*uncovered, *tail]}.values(), key=lambda info: info.chapter_number,
        )[-RECENT_SUMMARY_MAX:]
        if not tail_ids:
            summary_targets = []

        summary_by_chapter: dict[str, str] = {}
        if summary_targets:
            summary_rows = await db.execute(
                select(StoryMemory.chapter_id, StoryMemory.content)
                .where(StoryMemory.project_id == project_id)
                .where(StoryMemory.memory_type == 'chapter_summary')
                .where(StoryMemory.chapter_id.in_([info.id for info in summary_targets]))
            )
            for chapter_id, content in summary_rows.all():
                summary_by_chapter.setdefault(chapter_id, content)

        # 4. 相关历史：章节摘要语义检索（限定本章之前；近期段里已有的章节去重）
        exclude_ids = full_ids | {info.id for info in summary_targets}
        if not query_text:
            current_outline_data = (await db.execute(
                select(ChapterOutline.title, ChapterOutline.summary, ChapterOutline.plot_points)
                .join(Chapter, Chapter.chapter_outline_id == ChapterOutline.id)
                .where(Chapter.project_id == project_id)
                .where(Chapter.chapter_number == current_chapter_number)
            )).first()
            if current_outline_data:
                title, summary, plot_points = current_outline_data
                query_text = f"{title or ''} {summary or ''} {(plot_points or '')[:200]}".strip()

        if query_text and total_previous > len(exclude_ids):
            relevant_memories = await memory_service.search_memories(
                user_id=user_id,
                project_id=project_id,
                query=query_text,
                memory_types=['chapter_summary'],
                limit=RELEVANT_HISTORY_LIMIT + len(exclude_ids) // 4,
                min_importance=0.0,
                chapter_range=(0, current_chapter_number - 1),
            )
            relevant_chapters_text = []
            for mem in relevant_memories:
                chapter_info = chapters_by_id.get(mem['metadata'].get('chapter_id'))
                if chapter_info is None or chapter_info.id in exclude_ids:
                    continue
                relevant_chapters_text.append(f"第{chapter_info.chapter_number}章《{chapter_info.title}》：{mem['content']}")
                if len(relevant_chapters_text) >= RELEVANT_HISTORY_LIMIT:
                    break
            if relevant_chapters_text:
                context_parts['relevant_history'] = "【相关历史章节】\n" + "\n".join(relevant_chapters_text)
                logger.info(f"  ✅ 相关历史：语义检索到{len(relevant_chapters_text)}章")

        # 5. 近期概要
        recent_summaries = [
            f"第{info.chapter_number}章《{info.title}》：{summary_by_chapter[info.id]}"
            for info in summary_targets
            if summary_by_chapter.get(info.id)
        ]
        if recent_summaries:
            context_parts['recent_summary'] = "【近期章节概要】\n" + "\n".join(recent_summaries)
            logger.info(f"  ✅ 近期概要：{len(recent_summaries)}章摘要")

        # 6. 最近完整内容（一条 IN 查询取全文，按章节顺序拼）
        content_rows = await db.execute(
            select(Chapter.id, Chapter.content).where(Chapter.id.in_([info.id for info in recent_full_chapters]))
        )
        content_by_id = dict(content_rows.all())
        recent_full_texts = [
            f"=== 第{info.chapter_number}章：{info.title} ===\n{content_by_id[info.id]}"
            for info in recent_full_chapters
            if content_by_id.get(info.id)
        ]
        context_parts['recent_full'] = "【最近章节完整内容】\n" + "\n\n".join(recent_full_texts)

        context_parts['stats'] = {
            'total_previous': total_previous,
            'skeleton_samples': 0,
            'arc_covered_until': covered_until,
            'relevant_history': len(relevant_memories),
            'recent_summaries': len(recent_summaries),
            'recent_full': len(recent_full_texts)
        }
        total_length = sum(len(context_parts[k]) for k in ('story_skeleton', 'relevant_history', 'recent_summary', 'recent_full'))
        context_parts['stats']['total_length'] = total_length
        logger.info(f"📊 智能上下文构建完成：总长度 {total_length} 字符（层级摘要覆盖到第 {covered_until} 章）")

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


ANALYSIS_KNOWN_CHARACTER_LIMIT = 60
_ROLE_ORDER = {"protagonist": 0, "antagonist": 1, "major": 2, "supporting": 3}


async def _load_analysis_inputs(db: AsyncSession, project_id: str, chapter: Chapter) -> dict:
    """章节分析的额外输入：未回收承诺（本章计划处理的排前面）、本章计划叙事任务、已登记角色正式名。"""
    planned_raw = None
    if chapter.chapter_outline_id:
        planned_raw = (await db.execute(
            select(ChapterOutline.narrative_tasks).where(ChapterOutline.id == chapter.chapter_outline_id)
        )).scalar_one_or_none()
    open_promises = await narrative_state_service._get_active_promises(
        db, project_id, chapter.chapter_number,
        focus_ids=task_promise_ids(planned_raw), limit=PlotAnalyzer.OPEN_PROMISE_LIMIT,
    )
    rows = (await db.execute(
        select(Character.name, Character.role_type)
        .where(Character.project_id == project_id, Character.is_organization.isnot(True))
    )).all()
    names = [name for name, _role in sorted(rows, key=lambda r: _ROLE_ORDER.get((r[1] or "").lower(), 9)) if name]
    return {
        "open_promises": open_promises,
        "planned_tasks": render_narrative_tasks(planned_raw, chapter.chapter_number, for_analysis=True),
        "known_characters": names[:ANALYSIS_KNOWN_CHARACTER_LIMIT],
    }


async def analyze_chapter_background(
    chapter_id: str,
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: AIService,
    engine=None,
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
        
        # engine 由服务端批量的流水线模式传入独立连接（StaticPool 共用连接时并发会话会互相回滚）
        engine = engine or await get_engine(user_id)
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
        # 分析结果绑定本次读到的正文指纹（分析期间正文若被改，结果一落库就显示为过期）
        analyzed_content_hash = content_hash(chapter.content)

        async with write_lock:
            task.progress = 20
            await db_session.commit()
        trace_progress("模型分析章节中…", 20)
        
        # 3. 并行执行：章节分析 + 实体提取
        # 分析带上「未回收承诺清单 + 本章计划叙事任务 + 已登记角色名」：回收必须用编号指认，不再按标题猜
        analysis_inputs = await _load_analysis_inputs(db_session, project_id, chapter)
        analyzer = PlotAnalyzer(ai_service)
        async with stage_scope("analyze", "模型分析章节 + 提取实体") as st:
            analysis_task_coro = analyzer.analyze_chapter(
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content=chapter.content,
                word_count=chapter.word_count or count_words(chapter.content),
                **analysis_inputs,
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
                    existing_analysis.content_hash = analyzed_content_hash
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
                        description_ratio=analysis_result.get('description_ratio', 0),
                        content_hash=analyzed_content_hash,
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
        
        # 批量添加到向量数据库：先清本章旧向量（Chroma 的 add 遇到已存在 id 会静默忽略，重新分析会留下旧摘要）
        async with stage_scope("vector", "写入向量库") as st:
            await memory_service.delete_chapter_memories(
                user_id=user_id, project_id=project_id, chapter_id=chapter_id
            )
            if memory_records:
                added_count = await memory_service.batch_add_memories(
                    user_id=user_id,
                    project_id=project_id,
                    memories=memory_records
                )
                logger.info(f"✅ 添加{added_count}条记忆到向量库")
            st.note(records=len(memory_records))

        # 层级摘要：本章所在单元 / 阶段 / 卷写齐了就汇总（卷末同时复盘并回写下一节点）；失败不影响分析结果
        async with stage_scope("arc_rollup", "汇总剧情单元 / 卷摘要") as st:
            try:
                async with write_lock:
                    rollup_calls = await arc_summary_service.maybe_rollup(
                        db_session, project_id, chapter.chapter_number, ai_service
                    )
                st.note(llm_calls=rollup_calls)
            except Exception as rollup_error:  # noqa: BLE001
                await db_session.rollback()
                logger.warning(f"⚠️ 层级摘要汇总失败（不影响本章分析）: {rollup_error}")
                st.note(error=str(rollup_error)[:200])
        
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
    """生成前预检查：前面有正文的章节里，哪些从未分析（无记忆状态）、哪些分析后正文又改过（记忆已过期）。

    前端在触发生成前调用；count>0 时提示用户是否继续。提醒性检查，不阻断生成。
    """
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, getattr(request.state, "user_id", None), db)

    issues = await previous_chapter_issues(db, chapter)
    outline = await db.get(ChapterOutline, chapter.chapter_outline_id) if chapter.chapter_outline_id else None
    warnings = outline_review.outline_warnings(outline) if outline is not None else []
    message = previous_issues_message(issues)
    if warnings:
        message = "；".join(warnings) + "。" + (message or "是否继续生成？")
    return {
        "count": len(issues.unanalyzed) + len(issues.stale) + len(warnings),
        "chapters": [chapter_brief(c) for c in issues.unanalyzed],
        "stale_chapters": [chapter_brief(c) for c in issues.stale],
        "outline_warnings": warnings,
        "message": message,
    }


@dataclass
class ChapterGenerateOptions:
    """一次正文生成的参数（单章端点与服务端批量共用）。target_word_count=None → 按章纲 / 平台默认。"""
    style_id: Optional[int] = None
    target_word_count: Optional[int] = None
    enable_mcp: bool = True
    selected_plugins: Optional[list[str]] = None
    pack_ids: Optional[list[str]] = None
    dimensions: Optional[list[str]] = None
    strength: Optional[str] = None
    adherence_review: bool = True

    @classmethod
    def from_request(cls, req: ChapterGenerateRequest) -> "ChapterGenerateOptions":
        explicit_words = "target_word_count" in getattr(req, "model_fields_set", set())
        return cls(
            style_id=req.style_id,
            target_word_count=req.target_word_count if explicit_words else None,
            enable_mcp=getattr(req, "enable_mcp", True),
            selected_plugins=getattr(req, "selected_plugins", None),
            adherence_review=getattr(req, "adherence_review", True),
            pack_ids=req.pack_ids,
            dimensions=req.dimensions,
            strength=req.strength,
        )


MAX_CONTINUATIONS = 2
CARD_TYPE_LABELS = {'plot': '剧情', 'character': '角色', 'scene': '场景', 'conflict': '冲突', 'event': '事件',
                    'dialogue': '对话', 'inner': '内心'}
USAGE_TYPE_LABELS = {'reference': '参考', 'used': '已使用', 'planned': '计划使用'}


def _outline_task_text(chapter_outline: ChapterOutline, target_word_count: int) -> str:
    key_events = parse_json_list(chapter_outline.key_events)
    characters_involved = parse_json_list(chapter_outline.characters_involved)
    lines = [f"【章节标题】{chapter_outline.title}"]
    if chapter_outline.scene:
        lines.append(f"【场景】{chapter_outline.scene}")
    if chapter_outline.pov:
        lines.append(f"【视角人物】{chapter_outline.pov}")
    entry_state = (getattr(chapter_outline, "entry_state", None) or "").strip()
    if entry_state:
        lines.append(f"【进入状态】{entry_state}（正文开头必须承接这里）")
    if chapter_outline.summary:
        lines.append(f"【章节摘要】{chapter_outline.summary}")
    lines.append(f"【剧情要点】{chapter_outline.plot_points or '无'}")
    if key_events:
        lines.append(f"【关键事件】{'、'.join(key_events)}（最后一条是章末落点）")
    exit_state = (getattr(chapter_outline, "exit_state", None) or "").strip()
    if exit_state:
        lines.append(f"【退出状态】{exit_state}（写到这里就停，不往下写下一章的事）")
    forbidden = forbidden_items(getattr(chapter_outline, "forbidden", None))
    if forbidden:
        lines.append("【禁止事项】本章不能发生 / 揭晓：\n" + "\n".join(f"- {item}" for item in forbidden))
    if characters_involved:
        lines.append(f"【涉及角色】{'、'.join(characters_involved)}")
    lines.append(f"【目标字数】{target_word_count}字")
    return "\n".join(lines)


async def run_chapter_generation(job, *, chapter_id: str, user_id: str, ai_service: AIService,
                                 options: ChapterGenerateOptions) -> dict:
    """生成一章正文：上下文装配（过预算器）→ 流式创作（截断自动续写）→ 存为候选稿（不动正式正文）。

    单章端点与服务端批量（chapter_batch_service）共用；单章由作者采用，批量过质检闸门后自动采用。
    事件写进 job 日志，可回放。
    """
    current_user_id = user_id
    async with job_session_factory(current_user_id)() as db_session:
        st_ctx = begin_stage("context", "加载章纲 / 世界规则 / 角色 / 剧情卡")
        current_chapter = (await db_session.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
        if not current_chapter:
            raise ValueError('章节不存在')
        project = (await db_session.execute(
            select(Project).where(Project.id == current_chapter.project_id)
        )).scalar_one_or_none()
        if not project:
            raise ValueError('项目不存在')
        if not current_chapter.chapter_outline_id:
            raise ValueError('章节未关联章纲，无法生成。请先在章纲管理中创建章纲。')
        chapter_outline = (await db_session.execute(
            select(ChapterOutline).where(ChapterOutline.id == current_chapter.chapter_outline_id)
        )).scalar_one_or_none()
        if not chapter_outline:
            raise ValueError('关联的章纲不存在')
        # 候选稿绑定生成时的正文与章纲指纹：采用时正文已改要确认，生成期间章纲被改要标记
        base_content_hash = content_hash(current_chapter.content)
        generation_outline_hash = outline_fingerprint(chapter_outline)

        target_word_count = (
            options.target_word_count
            or chapter_outline.target_word_count
            or default_chapter_words(project.platform_preset)
        )
        chapter_number = current_chapter.chapter_number

        # 世界规则：项目规则 + 语义检索相关条目
        outline_text = chapter_outline.summary or chapter_outline.plot_points or ''
        query_text = f"{project.theme or ''} {project.genre or ''} {outline_text[:500]}"
        from app.services.world_rule_service import world_rule_service
        enhanced_world_rules = await world_rule_service.generate_rules_summary_with_search(
            db_session, project.id, query_text, limit=5
        )
        final_world_rules = project.world_rules or '未设定'
        if enhanced_world_rules:
            final_world_rules = f"{final_world_rules}\n\n{enhanced_world_rules}"

        current_outline_content = _outline_task_text(chapter_outline, target_word_count)
        logger.info(f"📖 使用章纲生成: 第{chapter_outline.chapter_number}章《{chapter_outline.title}》")

        # 章纲关联的剧情卡
        linked_plot_cards_data = (await db_session.execute(
            select(PlotCard, PlotCardChapterOutlineLink.usage_type, PlotCardChapterOutlineLink.usage_notes)
            .join(PlotCardChapterOutlineLink, PlotCard.id == PlotCardChapterOutlineLink.plot_card_id)
            .where(PlotCardChapterOutlineLink.chapter_outline_id == chapter_outline.id)
            .order_by(PlotCardChapterOutlineLink.created_at)
        )).all()
        cards_text = []
        for card, usage_type, usage_notes in linked_plot_cards_data[:10]:
            content_preview = (card.content or "无内容")[:200] + ("..." if len(card.content or "") > 200 else "")
            card_text = (
                f"【{CARD_TYPE_LABELS.get(card.card_type, '其他')}卡片】{card.title}"
                f"（{USAGE_TYPE_LABELS.get(usage_type or 'reference', '参考')}）\n{content_preview}"
            )
            if usage_notes:
                card_text += f"\n使用说明：{usage_notes}"
            cards_text.append(card_text)
        linked_cards_context = "\n\n".join(cards_text)
        if linked_plot_cards_data:
            trace_reference("plot_cards", "关联剧情卡", [
                {"title": card.title, "detail": usage_type or "reference"} for card, usage_type, _notes in linked_plot_cards_data[:10]
            ])

        # 写作风格（进 system 提示词）
        style_content = ""
        if options.style_id:
            style = (await db_session.execute(
                select(WritingStyle).where(WritingStyle.id == options.style_id)
            )).scalar_one_or_none()
            if style and (style.project_id is None or style.project_id == current_chapter.project_id):
                style_content = style.prompt_content or ""
                logger.info(f"使用指定风格: {style.name}")
            elif style:
                logger.warning(f"风格 {options.style_id} 不属于当前项目，无法使用")

        characters = list((await db_session.execute(
            select(Character).where(Character.project_id == current_chapter.project_id)
        )).scalars().all())
        st_ctx.done(characters=len(characters), plot_cards=len(linked_plot_cards_data), style=bool(style_content))

        st_smart = begin_stage("smart_context", "组装前情脉络 / 近期剧情 / 上一章正文")
        char_ctx = await build_character_context(db_session, project.id, chapter_number, chapter_outline, characters)
        map_ref = await chapter_map_reference(
            db_session, project.id, chapter_number,
            scene=chapter_outline.scene, text=current_outline_content, character_names=char_ctx.names,
        )
        if map_ref.items:
            trace_reference("world_map", "世界地图", map_ref.items)
        retrieval_query = build_query_text(chapter_outline, char_ctx.involved or char_ctx.names)
        smart_context = await build_smart_chapter_context(
            db=db_session,
            project_id=project.id,
            current_chapter_number=chapter_number,
            user_id=current_user_id,
            query_text=retrieval_query,
        )
        stats = smart_context.get('stats') or {}
        st_smart.done(previous_chapters=stats.get('total_previous', 0), context_chars=stats.get('total_length', 0),
                      arc_covered_until=stats.get('arc_covered_until', 0))

        st_mem = begin_stage("memory", "角色状态卡 / 叙事账本 / 向量记忆")
        planned_tasks_raw = getattr(chapter_outline, "narrative_tasks", None)
        memory_context = await memory_service.build_context_for_generation(
            user_id=current_user_id,
            project_id=project.id,
            current_chapter=chapter_number,
            chapter_outline=current_outline_content,
            character_names=char_ctx.names,
            query_text=retrieval_query,
        )
        state_context = await narrative_state_service.build_generation_context(
            db=db_session,
            project_id=project.id,
            current_chapter=chapter_number,
            pov_character_name=char_ctx.pov_name,
            character_names=char_ctx.names,
            focus_promise_ids=task_promise_ids(planned_tasks_raw),
        )
        ledger_blocks = {**{k: v for k, v in (memory_context or {}).items() if isinstance(v, str)},
                         **{k: v for k, v in (state_context or {}).items() if isinstance(v, str)}}
        st_mem.done(characters=len(char_ctx.selected), ledger_blocks=len([v for v in ledger_blocks.values() if v]))
        trace_reference("memory", "前情与记忆", [
            {"title": "层级摘要覆盖", "detail": f"至第 {stats.get('arc_covered_until', 0)} 章"},
            {"title": "近期章节概要", "detail": f"{stats.get('recent_summaries', 0)} 章"},
            {"title": "最近完整内容", "detail": f"{stats.get('recent_full', 0)} 章"},
            {"title": "出场角色状态卡", "detail": f"{len(char_ctx.selected)} 人"},
        ])
        job.progress('开始AI创作...', 25)

        # MCP 参考资料（剧情线标准模式）
        mcp_reference_materials = ""
        _has_mcp_plugins = False
        if options.enable_mcp and current_user_id:
            from app.services.mcp_tool_service import mcp_tool_service
            _available_tools = await mcp_tool_service.get_user_enabled_tools(
                user_id=current_user_id,
                db_session=db_session,
                plugin_names=options.selected_plugins,
            )
            _has_mcp_plugins = len(_available_tools) > 0
            if not _has_mcp_plugins:
                logger.info("⏭️ 用户没有启用的MCP插件，跳过MCP工具收集")

        if options.enable_mcp and current_user_id and _has_mcp_plugins:
            st_mcp = begin_stage("mcp", "MCP 规划收集参考资料")
            job.progress('🔍 尝试使用MCP工具收集参考资料...', 28)
            from app.services.plot_generation_service import PlotGenerationService
            plot_service = PlotGenerationService(ai_service)
            planning_result = await plot_service._plan_with_mcp(
                context_type="chapter_content",
                project_data={'title': project.title, 'genre': project.genre or '未知', 'theme': project.theme or '未知'},
                outline_content=None,
                chapter_outline=current_outline_content,
                user_id=current_user_id,
                db_session=db_session,
                selected_plugins=options.selected_plugins,
                provider=None,
                model=None
            )
            mcp_reference_materials = planning_result.get("reference_materials", "")
            tools_used = planning_result.get("tools_used", [])
            job.progress(f'✅ MCP工具调用成功（{planning_result.get("tool_calls_made", 0)}次）', 32)
            st_mcp.done(tools=len(tools_used), chars=len(mcp_reference_materials))

        # 拆书参考注入：user 段进参考资料，style 段进 system
        st_ref = begin_stage("reference_pack", "组装拆书参考包")
        try:
            from app.services.reference_pack_injector import ReferencePackInjector
            _anchor = f"{current_chapter.title or ''} {current_outline_content[:300]}".strip() or "章节正文"
            _ref_block = await ReferencePackInjector().build_reference_block(
                db_session, project.id,
                scene="chapter_content",
                pack_ids=options.pack_ids,
                dimensions=options.dimensions,
                strength=options.strength,
                anchor_query=_anchor,
            )
            if _ref_block.user_segment:
                mcp_reference_materials = f"{mcp_reference_materials}\n\n{_ref_block.user_segment}".strip()
            if _ref_block.system_segment:
                style_content = f"{style_content}\n\n{_ref_block.system_segment}".strip()
            if not _ref_block.is_empty:
                _dims_label = ','.join(_ref_block.used_dimensions)
                job.progress(f'📚 已注入拆书参考包（{_dims_label}）', 33)
                st_ref.done(packs=len(_ref_block.used_packs), dimensions=_dims_label, strength=_ref_block.used_strength)
            else:
                st_ref.skip("参考包无可用内容")
        except ValueError:
            st_ref.skip("项目未挂载参考包")
        except Exception as _e:  # pragma: no cover - 防御性兜底
            logger.warning(f"[R5-章节正文] 拆书参考注入失败（已跳过）: {_e}")
            st_ref.skip("注入失败，已跳过")

        # 本章在卷纲中的位置（卷 → 剧情单元 → 第几章）→ 本章任务里的「结构要求」（软指导，不规定比例）
        st_volume = begin_stage("volume_position", "卷纲位置")
        _volume_ctx = await fetch_volume_context(db_session, chapter_outline)
        structure_requirements = render_structure(_volume_ctx)
        if _volume_ctx is None:
            st_volume.skip("本章没有挂卷纲")
        else:
            st_volume.done(volume=_volume_ctx.volume_number, unit_position=f"{_volume_ctx.index}/{_volume_ctx.size}")

        st_prompt = begin_stage("prompt", "上下文预算 / 组装提示词")
        prompt = build_chapter_prompt(ChapterPromptInput(
            title=project.title,
            theme=project.theme or '',
            genre=project.genre or '',
            narrative_perspective=project.narrative_perspective or '第三人称',
            time_period=project.world_time_period or '未设定',
            location=project.world_location or '未设定',
            atmosphere=project.world_atmosphere or '未设定',
            world_rules=final_world_rules,
            chapter_number=chapter_number,
            chapter_title=current_chapter.title,
            chapter_outline_text=current_outline_content,
            outline_window=await build_outline_window(db_session, project.id, chapter_outline),
            linked_cards=linked_cards_context,
            narrative_tasks=render_narrative_tasks(planned_tasks_raw, chapter_number),
            structure_requirements=structure_requirements,
            hook_policy=volume_hook_policy(_volume_ctx),
            story_so_far=smart_context.get('story_skeleton', ''),
            recent_summaries=smart_context.get('recent_summary', ''),
            relevant_history=smart_context.get('relevant_history', ''),
            recent_full=smart_context.get('recent_full', ''),
            character_cards=char_ctx.cards_text,
            absent_characters=char_ctx.absent_text,
            organizations=char_ctx.organizations_text,
            story_time=char_ctx.story_time_text,
            world_map=map_ref.text,
            ledger_blocks=ledger_blocks,
            references=mcp_reference_materials,
            style_content=style_content,
            platform_block=platform_block(project.platform_preset),
            generation_prompt=project.generation_prompt or '',
            target_word_count=target_word_count,
            word_soft_range=app_settings.chapter_word_soft_range,
            budget_chars=app_settings.chapter_context_budget_chars,
        ))
        prompt_chars = len(prompt.system) + len(prompt.user)
        st_prompt.done(prompt_chars=prompt_chars, trimmed=[k for k, v in prompt.report.items() if v.get("trimmed")])
        trace_reference("context_budget", "上下文预算", [
            {"title": key, "detail": f"{info['chars']} 字{'（已裁剪）' if info['trimmed'] else ''}"}
            for key, info in prompt.report.items()
        ], chars=prompt_chars)
        logger.info(f"🧮 正文提示词：system {len(prompt.system)} 字 + user {len(prompt.user)} 字；裁剪 {prompt.report}")

        max_tokens = getattr(ai_service, "default_max_tokens", None)
        if isinstance(max_tokens, int) and 0 < max_tokens < int(target_word_count * 1.2):
            job.progress(f'⚠️ 当前 Max Tokens（{max_tokens}）可能写不完 {target_word_count} 字，被截断时会自动续写；'
                         f'建议在设置中调大', 34)
        job.progress('🎨 AI开始创作章节内容...', 35)

        # 流式生成（content 事件逐块进任务日志：重连即可重建全文；进度每累计 ≥200 字发一次）
        st_llm = begin_stage("llm", "模型创作正文")
        full_content = ""
        last_progress_at = 0

        async def _stream(user_prompt: str) -> Optional[str]:
            nonlocal full_content, last_progress_at
            reset_stream_finish_reason()
            async for chunk in ai_service.generate_text_stream(
                prompt=user_prompt, system_prompt=prompt.system, creative=True,
            ):
                full_content += chunk
                job.publish({'type': 'content', 'content': chunk})
                if len(full_content) - last_progress_at >= 200:
                    last_progress_at = len(full_content)
                    generation_progress = min(35 + (len(full_content) / target_word_count) * 60, 95)
                    job.publish({'type': 'progress', 'message': f'🎨 AI 创作中… 已写出 {len(full_content)} 字',
                                 'progress': int(generation_progress), 'status': 'processing',
                                 'word_count': len(full_content)})
                await asyncio.sleep(0)
            return last_stream_finish_reason()

        finish_reason = await _stream(prompt.user)
        continuations = 0
        while finish_reason == "length" and continuations < MAX_CONTINUATIONS:
            continuations += 1
            job.progress(f'✂️ 正文被 Max Tokens 截断，自动续写（第 {continuations} 次）…',
                         int(min(35 + (len(full_content) / target_word_count) * 60, 95)))
            finish_reason = await _stream(
                build_continuation_prompt(prompt, full_content, target_word_count, chapter_number)
            )
        if finish_reason == "length":
            raise ValueError(
                f"正文连续 {MAX_CONTINUATIONS + 1} 次被 Max Tokens 截断，本章未保存。"
                f"请在「设置」中调大 Max Tokens（建议 ≥ 目标字数 × 2）后重试"
            )
        st_llm.done(chars=len(full_content), continuations=continuations)

        # 章纲遵循度审校：另起一次模型调用逐项核对（引文由程序核验）；报告附在候选稿上，失败不阻断
        adherence = None
        if options.adherence_review and has_reviewable_contract(chapter_outline):
            st_review = begin_stage("review", "章纲遵循度审校")
            job.progress('🔎 审校是否照章纲写…', 93)
            adherence = await review_candidate(
                ai_service, chapter_outline, full_content, render_narrative_tasks(planned_tasks_raw, chapter_number),
            )
            st_review.done(status=adherence.get("status"), passed=adherence.get("passed"),
                           issues=len(adherence.get("issues") or []))

        st_persist = begin_stage("persist", "存为候选稿 / 生成历史")

        # 生成期间章纲是否被改（重新读库，不用会话里的旧对象）
        fresh_outline = (await db_session.execute(
            select(ChapterOutline)
            .where(ChapterOutline.id == chapter_outline.id)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        outline_changed = outline_fingerprint(fresh_outline) != generation_outline_hash
        new_word_count = count_words(full_content)
        quality = ai_flavor_metrics.analyze_text(
            full_content,
            previous_text=(smart_context.get('recent_full') or '')[-4000:],
            target_word_count=target_word_count,
        )
        candidate = await create_candidate(
            db_session, current_chapter,
            content=full_content,
            source="ai_generate",
            base_hash=base_content_hash,
            outline_hash=generation_outline_hash,
            outline_changed=outline_changed,
            quality=quality,
            adherence=adherence,
            meta={"target_word_count": target_word_count, "continuations": continuations, "style_id": options.style_id},
        )
        db_session.add(GenerationHistory(
            project_id=current_chapter.project_id,
            chapter_id=current_chapter.id,
            prompt=f"创作章节: 第{chapter_number}章 {current_chapter.title}",
            generated_content=full_content[:500] if len(full_content) > 500 else full_content,
            model="default"
        ))
        await db_session.commit()

        logger.info(f"成功创作章节候选稿 {chapter_id}，共 {new_word_count} 字（候选 {candidate.id}）")
        job.publish({'type': 'progress', 'message': '✅ 候选稿已生成，采用后才写入正文', 'progress': 95,
                     'status': 'processing', 'word_count': new_word_count})
        st_persist.done(word_count=new_word_count, ai_flavor=quality["score"], outline_changed=outline_changed)
        return {
            'word_count': new_word_count,
            'candidate_id': candidate.id,
            'adopted': False,
            'outline_changed': outline_changed,
            'continuations': continuations,
            'quality': quality,
            'adherence': adherence,
        }


@router.post("/project/{project_id}/batch-write-stream", summary="服务端批量生成章节（后台任务 + SSE，可关浏览器）")
async def batch_generate_chapters(
    project_id: str,
    request: Request,
    batch_request: ChapterBatchRequest,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """逐章：生成（失败重试）→ 质检（AI 味 / 字数，必要时重写一次）→ 分析 → 一致性闸门；缺章纲时自动滚动规划。

    与单章生成共用互斥键（同一项目同时只跑一个正文任务）；已有正文的章节跳过，中断后同范围重新发起即续跑。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)
    if batch_request.to_chapter < batch_request.from_chapter:
        raise HTTPException(status_code=400, detail="结束章号不能小于起始章号")
    try:
        job = await start_batch_job(project_id=project_id, user_id=user_id, ai_service=user_ai_service,
                                    options=BatchOptions(**batch_request.model_dump()))
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


async def start_batch_job(*, project_id: str, user_id: str, ai_service: Any, options: BatchOptions, manager: Any = None):
    """启动服务端批量写作任务（批量接口与共创室「写正文」工具共用）；同项目已有正文任务 → AIJobConflictError。"""

    async def runner(job):
        extra: dict = {}
        isolated = None
        if options.pipeline:
            # 独立连接指向任务会话实际用的库（而不是配置里的地址）：拿不到（内存库等）就退回顺序模式
            async with job_session_factory(user_id)() as probe:
                url = probe.bind.url.render_as_string(hide_password=False)
            isolated = isolated_sqlite_engine(url)
            options.pipeline = isolated is not None
            job.meta["pipeline"] = options.pipeline
        if isolated is not None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            extra = {
                "analysis_session_factory": async_sessionmaker(isolated, class_=AsyncSession, expire_on_commit=False),
                "analyze_kwargs": {"engine": isolated},
            }
        try:
            return await run_batch(job, project_id=project_id, user_id=user_id, ai_service=ai_service,
                                   options=options, session_factory=job_session_factory(user_id), **extra)
        finally:
            if isolated is not None:
                await isolated.dispose()

    return await (manager or ai_jobs).start(
        kind=BATCH_KIND,
        title=f"批量生成第 {options.from_chapter}-{options.to_chapter} 章",
        user_id=user_id,
        project_id=project_id,
        scope=f"chapter_write:{project_id}",
        runner=runner,
        cancel_message=BATCH_CANCELLED_MESSAGE,
        meta={"from_chapter": options.from_chapter, "to_chapter": options.to_chapter,
              "pipeline": options.pipeline},  # 运行时拿不到独立连接会改成 False
    )


@router.post("/{chapter_id}/generate-stream", summary="AI创作章节内容（流式）")
async def generate_chapter_content_stream(
    chapter_id: str,
    request: Request,
    generate_request: ChapterGenerateRequest = ChapterGenerateRequest(),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据章纲、前情（层级摘要）、本章相关角色状态与叙事账本创作章节正文（流式返回），结果存为候选稿：
    正式正文不变，作者在候选面板采用后才写入（旧稿进历史版本）。
    要求：必须按顺序生成，确保前置章节都已完成

    请求体参数：
    - style_id: 可选，写作风格ID
    - target_word_count: 可选，目标字数；不传则用章纲 / 平台预设的字数
    - enable_mcp: 可选，是否启用MCP工具增强，默认True
    """
    async for temp_db in get_db(request):
        chapter = (await temp_db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        await verify_project_access(chapter.project_id, getattr(request.state, "user_id", None), temp_db)
        can_generate, error_msg, _previous = await check_prerequisites(temp_db, chapter)
        if not can_generate:
            raise HTTPException(status_code=400, detail=error_msg)
        break

    user_id = getattr(request.state, "user_id", "system")
    options = ChapterGenerateOptions.from_request(generate_request)

    async def runner(job):
        return await run_chapter_generation(job, chapter_id=chapter_id, user_id=user_id,
                                            ai_service=user_ai_service, options=options)

    try:
        job = await ai_jobs.start(
            kind="chapter_generate",
            title=f"生成第 {chapter.chapter_number} 章《{chapter.title}》",
            user_id=user_id,
            project_id=chapter.project_id,
            scope=f"chapter_write:{chapter.project_id}",
            runner=runner,
            cancel_message="已停止生成；没有产生候选稿，本章正文未变",
            meta={"chapter_id": chapter_id, "target_word_count": options.target_word_count},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


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

    # 失效判定：分析时的正文指纹与当前正文不一致 → 分析 / 记忆 / 审计结果已过期（只改标题不算）
    is_stale = analysis_is_stale(analysis, chapter_check)

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

@router.post("/{chapter_id}/regenerate-stream", summary="按去 AI 味提示词重写正文，结果存为候选稿（后台任务 + SSE）")
async def regenerate_chapter_stream(
    chapter_id: str,
    request: Request,
    regenerate_request: ChapterRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    """提示词只带用户勾选的项目去 AI 味提示词 + 本章原文（不带章纲 / 前文 / 设定），附专有名词表防止改名。

    mode=full 全文重写；mode=local 只重写 AI 味重的段落（自动检测或 paragraph_indices 指定），其余段落一字不动。
    完成后存为整章候选稿：正文与分析都不动；作者采用后才覆盖正文（原稿进历史版本，可恢复）并清掉本章旧分析。
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
    glossary = await _project_glossary(db, chapter.project_id)
    original = chapter.content
    local = regenerate_request.mode == "local"
    targets: list[int] = []
    _lines, para_lines = split_paragraph_lines(original)
    paragraphs = [_lines[i] for i in para_lines]
    if local:
        targets = sorted({
            i for i in (regenerate_request.paragraph_indices
                        if regenerate_request.paragraph_indices is not None
                        else ai_flavor_metrics.flagged_paragraph_indices(paragraphs))
            if 0 <= i < len(paragraphs)
        })
        if not targets:
            raise HTTPException(status_code=400, detail="没有检测到需要局部重写的段落（可改用全文重写）")
        prompt = build_local_rewrite_prompt(prompt_texts, paragraphs, targets, glossary)
    else:
        prompt = build_rewrite_prompt(prompt_texts, original, glossary)
    original_len = max(len(original), 1)
    project_id = chapter.project_id
    base_content_hash = content_hash(original)

    async def runner(job):
        """后台任务体：流式重写 → 存为候选稿。事件进任务日志，可回放。"""
        st_llm = begin_stage("llm", "模型按去 AI 味提示词重写" + (f"（局部 {len(targets)} 段）" if local else "正文"))
        job.progress("开始重写…", 5)
        full_content = ""
        accumulated = 0
        last_progress_at = 0
        expected = sum(len(paragraphs[i]) for i in targets) if local else original_len
        async for chunk in user_ai_service.generate_text_stream(prompt=prompt, creative=True):
            full_content += chunk
            accumulated += len(chunk)
            if not local:  # 局部模式输出是「[P编号] 段落」行，最后合并成全文再发
                job.publish({"type": "content", "content": chunk})
            if accumulated - last_progress_at >= 200:
                last_progress_at = accumulated
                job.publish({
                    "type": "progress", "message": f"重写中… 已写出 {accumulated} 字",
                    "progress": int(min(5 + accumulated / max(expected, 1) * 85, 90)), "status": "processing",
                    "word_count": accumulated,
                })
            await asyncio.sleep(0)
        st_llm.done(chars=accumulated)
        if not full_content.strip():
            raise ValueError("模型没有返回内容，正文未改动")
        rewritten = len(targets)
        if local:
            replacements = parse_local_rewrite(full_content, targets)
            if not replacements:
                raise ValueError("模型没有按「[P编号] 段落」格式返回，正文未改动")
            rewritten = len(replacements)
            full_content = merge_paragraphs(original, replacements)
            job.publish({"type": "content", "content": full_content})

        st_persist = begin_stage("persist", "存为候选稿")
        async with job_session_factory(user_id)() as db_session:
            target = (await db_session.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
            if not target:
                raise ValueError("章节不存在")
            quality = ai_flavor_metrics.analyze_text(full_content, previous_text="", target_word_count=None)
            candidate = await create_candidate(
                db_session, target,
                content=full_content,
                source="deai_rewrite",
                base_hash=base_content_hash,
                outline_hash=target.outline_hash,
                quality=quality,
                meta={"mode": regenerate_request.mode, "rewritten_paragraphs": rewritten if local else None},
            )
            await db_session.commit()
        new_wc = candidate.word_count
        st_persist.done(word_count=new_wc, candidate_id=candidate.id)
        logger.info(f"✅ 去 AI 味重写完成，已存为候选稿: {chapter_id}，{new_wc} 字（候选 {candidate.id}）")
        result = {"word_count": new_wc, "candidate_id": candidate.id, "quality": quality}
        if local:
            result["rewritten_paragraphs"] = rewritten
        return result

    try:
        job = await ai_jobs.start(
            kind="chapter_regenerate",
            title=f"去 AI 味{'局部' if local else ''}重写第 {chapter.chapter_number} 章《{chapter.title}》",
            user_id=user_id,
            project_id=project_id,
            scope=f"chapter_write:{project_id}",
            runner=runner,
            cancel_message="已停止重写；没有产生候选稿，正文未改动",
            meta={"chapter_id": chapter_id, "mode": regenerate_request.mode},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


async def _project_glossary(db: AsyncSession, project_id: str) -> list[str]:
    """专有名词表：角色 / 组织名及曾用名（重写时原样保留）。主角与重要角色排前面。"""
    rows = (await db.execute(
        select(Character.name, Character.aliases, Character.role_type).where(Character.project_id == project_id)
    )).all()
    names: list[str] = []
    for name, aliases, _role in sorted(rows, key=lambda r: _ROLE_ORDER.get((r[2] or "").lower(), 9)):
        names.append(name)
        names.extend(parse_json_list(aliases))
    return [n for n in dict.fromkeys(names) if n]


