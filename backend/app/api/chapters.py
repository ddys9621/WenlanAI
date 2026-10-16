"""章节管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import defer
import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings as app_settings
from app.database import get_db
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate
from app.models.chapter_continuity_signal import ChapterContinuitySignal
from app.models.chapter_outline import ChapterOutline
from app.models.project import Project
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.models.writing_style import WritingStyle
from app.models.analysis_task import AnalysisTask
from app.models.memory import PlotAnalysis
from app.models.deai_prompt import DeaiPrompt
from app.schemas.chapter import (
    ChapterBatchRequest,
    ChapterCreate,
    ChapterDigestUpdate,
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
from app.services.chapter_analysis_jobs import analysis_scope, create_analysis_task, start_chapter_analysis
from app.services.chapter_analysis_jobs import schedule_index_rebuild_if_needed
from app.services.chapter_analysis_service import (  # noqa: F401 - analyze_chapter_background 供任务 / 测试从这里引用
    analyze_chapter_background,
    get_db_write_lock as _analysis_write_lock,
    load_analysis_inputs,
)
from app.services.chapter_entity_service import auto_create_entities
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
from app.services.chapter_mcp_planning import plan_chapter_references
from app.services.chapter_prompt_builder import ChapterPromptInput, build_chapter_prompt, build_continuation_prompt
from app.services.adherence_review_service import has_reviewable_contract, review_candidate
from app.services.chapter_candidate_service import create_candidate
from app.services.chapter_purge_service import purge_chapter_analysis, purge_chapter_vector_memory, purge_deleted_chapter
from app.services.chapter_readiness_service import (
    analysis_is_stale,
    analysis_statuses,
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
from app.services.generation_trace import begin_stage, trace_reference
from app.services.knowledge import kb_refs
from app.services.knowledge.kb_context import traced_kb_context
from app.services.world_map_context import chapter_map_reference
from app.services.chapter_consistency_service import chapter_consistency_service
from app.services.memory_service import memory_service
from app.services.narrative_state_service import narrative_state_service
from app.services.narrative_tasks import render_narrative_tasks, task_promise_ids
from app.services import chapter_digest_service, story_index_items
from app.services.story_recall_service import build_story_context, recall_keywords
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.utils.quote_anchor import locate_quote
from app.utils.text_utils import count_words
from app.api.deps import verify_project_access

router = APIRouter(prefix="/chapters", tags=["章节管理"])
logger = get_logger(__name__)

# 分析写库锁、实体入库已移到 services（chapter_analysis_service / chapter_entity_service）；保留旧名供测试与旧调用引用
async def get_db_write_lock(user_id: str):
    return _analysis_write_lock(user_id)


_auto_create_entities = auto_create_entities


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
    statuses = await analysis_statuses(
        db, project_id, is_running=lambda cid: ai_jobs.current(analysis_scope(cid)) is not None, chapters=chapters,
    )

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
        status = statuses.get(chapter.id)
        if status is not None:
            item.analysis_status, item.analysis_message = status["status"], status["message"]
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
    """删除章节：连同本章的分析、档案、账本（本章埋设且后文没用过的伏笔、状态信号、时间轴…）一起清掉。"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 1. 清理本章分析产物与账本（SQLite 没开外键级联，不清会留下「已删章节的人物死亡」这类孤儿信号继续影响后文）
    memory_count = await purge_deleted_chapter(db, chapter)
    
    # 3. 更新项目字数
    result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = result.scalar_one_or_none()
    if project:
        project.current_words = max(0, project.current_words - chapter.word_count)
    
    # 4. 删除章节
    project_id = chapter.project_id
    await db.delete(chapter)
    await db.commit()

    # 5. 检索索引（best-effort，提交之后清）
    if user_id:
        try:
            await memory_service.delete_chapter_memories(user_id=user_id, project_id=project_id, chapter_id=chapter_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ 检索索引清理失败（章节已删除）: {e}")

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


# 前文上下文（前情脉络 / 近期概要 / 相关旧事 / 最近全文）在 story_recall_service；保留旧名供生成流程与测试打桩
build_smart_chapter_context = build_story_context


async def _ensure_recall_index(user_id: Optional[str], db: AsyncSession, project_id: str) -> None:
    """检索索引为空而账本里有章节档案（刚换向量模型 / 刚导入 / 旧版升级）：后台重建一次，本章先只用人物 / 关键词召回。"""
    if not user_id or not memory_service.available:
        return
    try:
        if await memory_service.count(user_id, project_id) > 0:
            return
        await schedule_index_rebuild_if_needed(
            project_id=project_id, user_id=user_id, index_count=0,
            ledger_count=await story_index_items.project_item_count(db, project_id),
        )
    except Exception as exc:  # noqa: BLE001 - 只是优化召回，不能挡住写作
        logger.warning(f"⚠️ 检查检索索引失败: {exc}")


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


# 分析流水线在 chapter_analysis_service（两段式抽取 → 校验 → 一次性落库 → 刷新索引）；保留旧名供任务与测试引用
_load_analysis_inputs = load_analysis_inputs
_ROLE_ORDER = {"protagonist": 0, "antagonist": 1, "major": 2, "supporting": 3}


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
    kb_chapter: Optional[int] = None
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
            kb_chapter=getattr(req, "kb_chapter", None),
        )


MAX_CONTINUATIONS = 2


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
        st_ctx = begin_stage("context", "加载章纲 / 世界规则 / 角色")
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
        st_ctx.done(characters=len(characters), style=bool(style_content))

        st_smart = begin_stage("smart_context", "组装前情脉络 / 近期剧情 / 相关旧事 / 上一章正文")
        char_ctx = await build_character_context(db_session, project.id, chapter_number, chapter_outline, characters)
        map_ref = await chapter_map_reference(
            db_session, project.id, chapter_number,
            scene=chapter_outline.scene, text=current_outline_content, character_names=char_ctx.names,
        )
        if map_ref.items:
            trace_reference("world_map", "世界地图", map_ref.items)
        retrieval_query = build_query_text(chapter_outline, char_ctx.involved or char_ctx.names)
        involved_ids = [c.id for c in char_ctx.selected if getattr(c, "id", None)]
        await _ensure_recall_index(current_user_id, db_session, project.id)
        smart_context = await build_smart_chapter_context(
            db=db_session,
            project_id=project.id,
            current_chapter_number=chapter_number,
            user_id=current_user_id,
            query_text=retrieval_query,
            involved_ids=involved_ids,
            keywords=recall_keywords(char_ctx, chapter_outline),
        )
        stats = smart_context.get('stats') or {}
        st_smart.done(previous_chapters=stats.get('total_previous', 0), context_chars=stats.get('total_length', 0),
                      arc_covered_until=stats.get('arc_covered_until', 0), relevant=stats.get('relevant_history', 0))

        st_mem = begin_stage("memory", "角色状态卡 / 视角信息边界 / 叙事账本")
        planned_tasks_raw = getattr(chapter_outline, "narrative_tasks", None)
        state_context = await narrative_state_service.build_generation_context(
            db=db_session,
            project_id=project.id,
            current_chapter=chapter_number,
            pov_character_name=char_ctx.pov_name,
            character_names=char_ctx.names,
            focus_promise_ids=task_promise_ids(planned_tasks_raw),
            character_ids=involved_ids,
        )
        state_context = state_context if isinstance(state_context, dict) else {}
        # 视角信息边界是硬约束：进「出场角色与状态」，不和账本一起被裁
        pov_knowledge = state_context.get("pov_known_info") or ""
        ledger_blocks = {k: v for k, v in state_context.items() if isinstance(v, str) and k != "pov_known_info"}
        st_mem.done(characters=len(char_ctx.selected), ledger_blocks=len([v for v in ledger_blocks.values() if v]))
        trace_reference("memory", "前情与记忆", [
            {"title": "层级摘要覆盖", "detail": f"至第 {stats.get('arc_covered_until', 0)} 章"},
            {"title": "近期章节概要", "detail": f"{stats.get('recent_summaries', 0)} 章"},
            {"title": "相关旧事", "detail": f"{stats.get('relevant_history', 0)} 条"},
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
            planning_result = await plan_chapter_references(
                ai_service,
                title=project.title,
                genre=project.genre or '未知',
                theme=project.theme or '未知',
                chapter_outline=current_outline_content,
                user_id=current_user_id,
                db_session=db_session,
                selected_plugins=options.selected_plugins,
            )
            mcp_reference_materials = planning_result.get("reference_materials", "")
            tools_used = planning_result.get("tools_used", [])
            job.progress(f'✅ MCP工具调用成功（{planning_result.get("tool_calls_made", 0)}次）', 32)
            st_mcp.done(tools=len(tools_used), chars=len(mcp_reference_materials))

        # 仿写参考：对标章的章卡 + 同类片段进「仿写参考」节，参考文风进 system（排在通用写法之前）
        st_ref = begin_stage("knowledge", "组装仿写参考")
        kb = await traced_kb_context(db_session, project.id, "chapter", outline=chapter_outline,
                                     kb_chapter=options.kb_chapter)
        if kb.is_empty:
            st_ref.skip("项目没有对标书")
        else:
            job.progress(f'📚 已注入仿写参考《{kb.source_title}》', 33)
            st_ref.done(source=kb.source_title, entries=len(kb.refs), style=bool(kb.style))

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
            narrative_tasks=render_narrative_tasks(planned_tasks_raw, chapter_number),
            structure_requirements=structure_requirements,
            hook_policy=volume_hook_policy(_volume_ctx),
            story_so_far=smart_context.get('story_skeleton', ''),
            recent_summaries=smart_context.get('recent_summary', ''),
            relevant_history=smart_context.get('relevant_history', ''),
            recent_full=smart_context.get('recent_full', ''),
            character_cards=char_ctx.cards_text,
            pov_knowledge=pov_knowledge,
            absent_characters=char_ctx.absent_text,
            organizations=char_ctx.organizations_text,
            story_time=char_ctx.story_time_text,
            world_map=map_ref.text,
            ledger_blocks=ledger_blocks,
            references=mcp_reference_materials,
            imitation=kb.text,
            imitation_style=kb.style,
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
        await kb_refs.save_all_citations(db_session, project.id, kb.refs, kb.scene, "chapter_candidate", candidate.id)
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


async def _owned_chapter(db: AsyncSession, chapter_id: str, request: Request) -> Chapter:
    chapter = (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, getattr(request.state, "user_id", None), db)
    return chapter


async def _refresh_chapter_index(user_id: Optional[str], db: AsyncSession, chapter: Chapter) -> None:
    """档案 / 伏笔被作者改过后刷新本章检索索引（best-effort）。"""
    if not user_id:
        return
    try:
        items = await story_index_items.chapter_items(db, chapter.project_id, chapter.id)
        await memory_service.refresh_chapter(user_id, chapter.project_id, chapter.id, items)
    except Exception as exc:  # noqa: BLE001 - 索引可重建
        logger.warning(f"⚠️ 刷新章节索引失败: {exc}")


STATE_SIGNAL_LABELS = {
    "life_state": "生死", "location": "位置", "realm": "境界", "item": "物品", "injury": "伤势", "goal": "目标",
    "ability": "能力", "story_time": "故事时间",
}


@router.get("/{chapter_id}/analysis", summary="获取章节分析结果")
async def get_chapter_analysis(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """本章分析结果：档案（摘要 / 章末状态 / 作者版本与 AI 建议）、本章结算出的人物状态变化、伏笔动作、
    时间轴 / 因果 / 关系、一致性问题、最近一次分析任务的状态。没分析过也没有档案 → 404（前端按「未分析」显示）。"""
    chapter_check = await _owned_chapter(db, chapter_id, request)
    analysis = (await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id))).scalar_one_or_none()
    digest = await chapter_digest_service.get_digest(db, chapter_id)
    if analysis is None and digest is None:
        raise HTTPException(status_code=404, detail="该章节暂无分析结果")

    latest_task = (await db.execute(
        select(AnalysisTask).where(AnalysisTask.chapter_id == chapter_id).order_by(AnalysisTask.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    signals = (await db.execute(
        select(ChapterContinuitySignal).where(
            ChapterContinuitySignal.chapter_id == chapter_id, ChapterContinuitySignal.signal_type != "presence",
        )
    )).scalars().all()
    visualization_payload = await chapter_consistency_service.build_chapter_visualization_payload(db=db, chapter=chapter_check)
    return {
        "chapter_id": chapter_id,
        "analyzed": analysis is not None,
        # 失效判定：分析时的正文指纹与当前正文不一致 → 分析 / 档案 / 审计结果已过期（只改标题不算）
        "is_stale": analysis_is_stale(analysis, chapter_check) if analysis is not None else False,
        "content_updated_at": chapter_check.updated_at.isoformat() if chapter_check.updated_at else None,
        "analysis": analysis.to_dict() if analysis is not None else None,
        "digest": chapter_digest_service.digest_view(digest, chapter_check),
        "state_changes": [
            {
                "signal_type": s.signal_type, "label": STATE_SIGNAL_LABELS.get(s.signal_type, s.signal_type),
                "character_name": s.character_name, "signal_key": s.signal_key, "signal_value": s.signal_value,
                "evidence": s.evidence_text,
            }
            for s in signals
        ],
        "narrative_state": {
            "causal_links": visualization_payload["causal_links"],
            "promises": visualization_payload["promises"],
            "timeline_events": visualization_payload["timeline_events"],
            "relationship_graph": visualization_payload["relationship_graph"],
        },
        "consistency_audit": visualization_payload["consistency_audit"],
        "task": {
            "status": latest_task.status, "message": latest_task.error_message,
            "completed_at": latest_task.completed_at.isoformat() if latest_task.completed_at else None,
        } if latest_task is not None else None,
        "created_at": analysis.created_at.isoformat() if analysis is not None and analysis.created_at else None,
    }


@router.get("/{chapter_id}/annotations", summary="获取章节标注数据")
async def get_chapter_annotations(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """正文标注（钩子 / 伏笔 / 关键转折）：按分析时记下的原文引句在当前正文里重新定位，找不到的 position=-1。"""
    chapter = await _owned_chapter(db, chapter_id, request)
    analysis = (await db.execute(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id))).scalar_one_or_none()
    annotations = []
    for item in (analysis.annotation_items() if analysis is not None else []):
        position, length = locate_quote(chapter.content or "", item["quote"])
        annotations.append({
            "id": item["id"], "type": item["type"], "title": item["title"],
            "content": item["note"] or item["title"], "importance": item["importance"],
            "position": position, "length": length, "tags": [],
            "metadata": {"quote": item["quote"]},
        })
    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "word_count": chapter.word_count or 0,
        "annotations": annotations,
        "has_analysis": analysis is not None,
        "summary": {
            "total_annotations": len(annotations),
            "hooks": sum(1 for a in annotations if a["type"] == "hook"),
            "foreshadows": sum(1 for a in annotations if a["type"] == "foreshadow"),
            "plot_points": sum(1 for a in annotations if a["type"] == "plot_point"),
            "located": sum(1 for a in annotations if a["position"] >= 0),
        },
    }


@router.get("/{chapter_id}/digest", summary="章节档案（摘要 + 章末状态）")
async def get_chapter_digest(chapter_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await _owned_chapter(db, chapter_id, request)
    return {"digest": chapter_digest_service.digest_view(await chapter_digest_service.get_digest(db, chapter_id), chapter)}


@router.put("/{chapter_id}/digest", summary="作者修改章节档案（之后重新分析不覆盖，AI 结果作为建议）")
async def update_chapter_digest(
    chapter_id: str, body: ChapterDigestUpdate, request: Request, db: AsyncSession = Depends(get_db),
):
    chapter = await _owned_chapter(db, chapter_id, request)
    if body.summary is not None and not body.summary.strip():
        raise HTTPException(status_code=400, detail="摘要不能为空")
    await chapter_digest_service.author_update(db, chapter, summary=body.summary, end_state=body.end_state)
    await db.commit()
    await _refresh_chapter_index(getattr(request.state, "user_id", None), db, chapter)
    return {"digest": chapter_digest_service.digest_view(await chapter_digest_service.get_digest(db, chapter_id), chapter)}


@router.post("/{chapter_id}/digest/accept", summary="采用 AI 新分析的档案（回到 AI 版本）")
async def accept_chapter_digest(chapter_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await _owned_chapter(db, chapter_id, request)
    await chapter_digest_service.accept_suggestion(db, chapter)
    await db.commit()
    await _refresh_chapter_index(getattr(request.state, "user_id", None), db, chapter)
    return {"digest": chapter_digest_service.digest_view(await chapter_digest_service.get_digest(db, chapter_id), chapter)}


@router.post("/{chapter_id}/digest/dismiss", summary="忽略 AI 新分析的档案建议（保留作者版本）")
async def dismiss_chapter_digest(chapter_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await _owned_chapter(db, chapter_id, request)
    await chapter_digest_service.dismiss_suggestion(db, chapter)
    await db.commit()
    return {"digest": chapter_digest_service.digest_view(await chapter_digest_service.get_digest(db, chapter_id), chapter)}


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


