"""拆书功能 API

- POST /api/book-dissect/upload  上传 txt/md → 切分 → 返回 task_id + 章节预览（不接 LLM）
- GET  /api/book-dissect/{task_id}  查询任务状态
- POST /api/book-dissect/{task_id}/extraction-plan  启动前预估分批 / 调用次数（不接 LLM）
- POST /api/book-dissect/{task_id}/start-extraction  启动抽取（跑在 AIJobManager 后台任务里，可停止）
- POST /api/book-dissect/{task_id}/cancel  手动停止运行中的抽取
- DELETE /api/book-dissect/{task_id}  删除任务并清理磁盘（运行中会先停止）

抽取任务注册在 ai_jobs（scope=book_dissect:{task_id}），托盘里也能看到 / 停止；
任务的持久状态仍以 book_dissect_tasks.status 为准（pending/running/completed/failed/cancelled）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import get_user_ai_service
from app.config import DATA_DIR
from app.database import get_db
from app.logger import get_logger
from app.models.book_dissect_chapter_fact import BookDissectChapterFact
from app.models.book_dissect_dictionary import BookDissectDictionary
from app.models.book_dissect_entity import BookDissectEntity
from app.models.book_dissect_event import BookDissectEvent
from app.models.book_dissect_relation import BookDissectRelation
from app.models.book_dissect_task import BookDissectTask
from app.models.project_reference_pack import ProjectReferencePack
from app.models.reference_pack import ReferencePack
from app.schemas.book_dissect import (
    BookDissectTaskResponse,
    BookDissectUploadResponse,
    ChapterMetaSchema,
    ExtractionPlanResponse,
    V2ChapterFactDetailSchema,
    V2ChapterFactSummarySchema,
    V2DictionaryEntrySchema,
    V2EntitySchema,
    V2EventSchema,
    V2OverviewResponse,
    V2RelationSchema,
    V2StartExtractionRequest,
)
from app.services.ai_jobs import AIJob, AIJobConflictError, ai_jobs
from app.services.ai_service import AIService
from app.services.book_dissect.batch_planner import plan_batches, select_target_indices
from app.services.book_dissect.chapter_splitter import split_bytes
from app.services.book_dissect.extractor_v2 import (
    CANCELLED_MESSAGE,
    run_extraction_v2_background,
)
from app.user_manager import User
from app.api.deps import require_login

logger = get_logger(__name__)

router = APIRouter(prefix="/book-dissect", tags=["拆书参考"])

# 上传文件大小上限：10 MB（按字节）
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 仅接受这些扩展名
ALLOWED_SUFFIXES = {".txt", ".md", ".markdown"}

# 上传文件持久化目录（含切分后的全文，供后续 LLM 抽取使用）
UPLOAD_DIR = DATA_DIR / "book_dissect_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 切分预览返回的最大章节数（仅截取前 N 章给前端）
PREVIEW_LIMIT = 10


def _validate_filename(name: str) -> None:
    """文件后缀校验。"""
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {', '.join(sorted(ALLOWED_SUFFIXES))} 文件",
        )


def _meta_from_chapter(ch) -> ChapterMetaSchema:
    return ChapterMetaSchema(
        number=ch.chapter_number,
        title=ch.title,
        raw_title=ch.raw_title,
        word_count=ch.word_count,
        kind=ch.kind,
    )


def _meta_dict_from_schema(meta: ChapterMetaSchema) -> dict:
    return meta.model_dump()


# ============================================================
# 上传 + 切分
# ============================================================


@router.post("/upload", response_model=BookDissectUploadResponse)
async def upload_book(
    request: Request,
    file: UploadFile = File(..., description="txt/md 小说文件，≤10MB"),
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """
    上传参考书：
    1. 校验文件类型与大小
    2. 编码识别 + 章节切分（不调用 LLM）
    3. 全文存盘（任务目录）
    4. 在 DB 创建 BookDissectTask 记录，stage=split_done

    返回 task_id 与章节预览，前端可立即展示给用户确认切分质量。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    _validate_filename(file.filename)

    # 读取并校验大小
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{len(raw)} 字节），上限 {MAX_UPLOAD_BYTES} 字节",
        )

    # 切分
    try:
        chapters, encoding = split_bytes(raw)
    except UnicodeDecodeError as e:
        logger.warning("拆书：编码识别失败 file=%s err=%s", file.filename, e)
        raise HTTPException(
            status_code=400,
            detail="文件编码无法识别，请确认是 UTF-8 / GBK / GB18030 编码的纯文本",
        )

    if not chapters:
        raise HTTPException(status_code=400, detail="文件内容为空或无法切分")

    # 持久化
    task_id = str(uuid.uuid4())
    storage_path = UPLOAD_DIR / f"{task_id}.txt"
    try:
        storage_path.write_bytes(raw)
    except OSError as e:
        logger.error("拆书：写入磁盘失败 path=%s err=%s", storage_path, e)
        raise HTTPException(status_code=500, detail="文件存储失败")

    # 元信息
    meta_list: List[ChapterMetaSchema] = [_meta_from_chapter(ch) for ch in chapters]
    chapters_meta_json = json.dumps(
        [_meta_dict_from_schema(m) for m in meta_list],
        ensure_ascii=False,
    )
    total_words = sum(ch.word_count for ch in chapters)

    # 入库（S1 阶段直接 status=completed, stage=split_done；S2 接入 LLM 后会改为 running）
    now = datetime.now()
    task = BookDissectTask(
        id=task_id,
        user_id=user.user_id,
        status="completed",
        progress=100,
        stage="split_done",
        file_name=file.filename,
        file_size=len(raw),
        encoding=encoding,
        storage_path=str(storage_path),
        chapter_count=len(chapters),
        total_words=total_words,
        chapters_meta=chapters_meta_json,
        result_json=None,
        started_at=now,
        completed_at=now,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info(
        "拆书上传完成: user=%s task=%s file=%s size=%d chapters=%d encoding=%s",
        user.user_id, task_id, file.filename, len(raw), len(chapters), encoding,
    )

    return BookDissectUploadResponse(
        task_id=task_id,
        file_name=file.filename,
        file_size=len(raw),
        encoding=encoding,
        chapter_count=len(chapters),
        total_words=total_words,
        preview=meta_list[:PREVIEW_LIMIT],
    )


# ============================================================
# 查询任务
# ============================================================


def _parse_chapters_meta(raw_json: Optional[str]) -> Optional[List[ChapterMetaSchema]]:
    if not raw_json:
        return None
    try:
        items = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    out: List[ChapterMetaSchema] = []
    for item in items:
        try:
            out.append(ChapterMetaSchema(**item))
        except Exception:
            continue
    return out


def _to_response(task: BookDissectTask) -> BookDissectTaskResponse:
    job = ai_jobs.current(_job_scope(task.id))
    return BookDissectTaskResponse(
        job_id=job.id if job is not None else None,
        id=task.id,
        user_id=task.user_id,
        status=task.status,
        progress=task.progress or 0,
        stage=task.stage,
        error_message=task.error_message,
        file_name=task.file_name,
        file_size=task.file_size or 0,
        encoding=task.encoding,
        chapter_count=task.chapter_count or 0,
        total_words=task.total_words or 0,
        chapters_meta=_parse_chapters_meta(task.chapters_meta),
        # 引擎版本：老任务可能为 1（仅用于识别），新任务统一为 2
        version=task.version or 2,
        extraction_phase=task.extraction_phase,
        chapters_total=task.chapters_total or 0,
        chapters_extracted=task.chapters_extracted or 0,
        chapters_failed=task.chapters_failed or 0,
        sampling_mode=task.sampling_mode or "all",
        sampling_param=task.sampling_param or 1,
        # V3.1 字段
        extraction_engine=(task.extraction_engine or "auto"),
        chapters_per_request=task.chapters_per_request or 0,
        chapter_limit=task.chapter_limit or 0,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


@router.get("/{task_id}", response_model=BookDissectTaskResponse)
async def get_task(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """查询拆书任务的当前状态、进度和结果。"""
    result = await db.execute(
        select(BookDissectTask).where(
            BookDissectTask.id == task_id,
            BookDissectTask.user_id == user.user_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return _to_response(task)


# ============================================================
# 列表（供前端显示历史拆书任务）
# ============================================================


@router.get("", response_model=List[BookDissectTaskResponse])
async def list_tasks(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的所有拆书任务，按创建时间倒序。"""
    result = await db.execute(
        select(BookDissectTask)
        .where(BookDissectTask.user_id == user.user_id)
        .order_by(BookDissectTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_to_response(t) for t in tasks]


# ============================================================
# 启动 LLM 抽取（S2+）
# ============================================================


def _job_scope(task_id: str) -> str:
    """ai_jobs 互斥键：同一拆书任务同时只跑一个抽取，不同任务可并行。"""
    return f"book_dissect:{task_id}"


@router.post("/{task_id}/start-extraction", response_model=BookDissectTaskResponse)
async def start_extraction(
    task_id: str,
    payload: Optional[V2StartExtractionRequest] = None,
    user: User = Depends(require_login),
    ai_service: AIService = Depends(get_user_ai_service),
    db: AsyncSession = Depends(get_db),
):
    """启动 LLM 抽取（分批抽取 + 全书聚合），跑在 ai_jobs 后台任务里，可随时 /cancel 停止。

    Body（可选）：
    - `sampling_mode`: "all" / "every_n" / "key_only"（默认 "all"）
    - `sampling_param`: int（every_n 模式下的 N，默认 1）
    - `extraction_engine`: "auto" / "chunked" / "long_context"（默认 "auto"）
    - `chapters_per_request`: 每次 LLM 请求抽取的章节数（默认 0 = 自动规划）
    - `chapter_limit`: 只抽取前 N 章（默认 0 = 全部）
    """
    task = await _ensure_task_owned(db, task_id, user.user_id)

    # 幂等校验：避免对正在跑的任务重复触发。
    # 已完成的任务允许重新抽取：流水线各阶段写库前都会先 delete 本 task 旧数据，
    # ReferencePack 走 upsert，重抽是幂等的（此前 409 强迫用户删任务重传全书）。
    if task.status == "running" or ai_jobs.current(_job_scope(task_id)) is not None:
        raise HTTPException(status_code=409, detail="任务正在运行中，请勿重复触发")

    # 校验全文文件仍然存在
    if not task.storage_path or not Path(task.storage_path).exists():
        raise HTTPException(status_code=400, detail="全文文件已丢失，请重新上传")

    opts = _normalize_extraction_options(payload, chapter_count=task.chapter_count or 0)

    # 立即标记 queued，避免前端轮询时短暂看到旧状态
    task.status = "running"
    task.stage = "queued"
    task.progress = 0
    task.error_message = None
    task.started_at = datetime.now()
    task.completed_at = None
    task.version = 2
    task.sampling_mode = opts["sampling_mode"]
    task.sampling_param = opts["sampling_param"]
    task.chapters_total = 0
    task.chapters_extracted = 0
    task.chapters_failed = 0
    task.extraction_phase = None
    task.extraction_engine = opts["extraction_engine"]  # V3.1
    task.chapters_per_request = opts["chapters_per_request"]
    task.chapter_limit = opts["chapter_limit"]
    await db.commit()
    await db.refresh(task)

    user_id = user.user_id

    async def runner(_job: AIJob) -> None:
        await run_extraction_v2_background(task_id=task_id, user_id=user_id, ai_service=ai_service)

    try:
        await ai_jobs.start(
            kind="book_dissect",
            title=f"拆书抽取：{task.file_name or task_id[:8]}",
            user_id=user_id,
            runner=runner,
            scope=_job_scope(task_id),
            cancel_message=CANCELLED_MESSAGE,
            meta={"task_id": task_id, **opts},
        )
    except AIJobConflictError as exc:
        # 与上面的 current() 预检之间被并发请求抢先：DB 已由对方置 running，本次不再改状态
        raise HTTPException(status_code=409, detail=str(exc))

    logger.info(
        "拆书V2：已排队 user=%s task=%s sampling=%s/%d engine=%s per_request=%d limit=%d",
        user_id, task_id, opts["sampling_mode"], opts["sampling_param"],
        opts["extraction_engine"], opts["chapters_per_request"], opts["chapter_limit"],
    )

    return _to_response(task)


@router.post("/{task_id}/cancel", response_model=BookDissectTaskResponse)
async def cancel_extraction(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """手动停止运行中的抽取。

    - 进程内有对应 ai_job：取消它，流水线的 CancelledError 分支把任务落库为 cancelled
    - 没有（服务重启后残留的 running）：直接落库修复，否则任务永远卡在 running 无法重抽
    已完成批次的章节事实保留；随后可「重新抽取」。
    """
    task = await _ensure_task_owned(db, task_id, user.user_id)
    if task.status != "running":
        raise HTTPException(status_code=409, detail="任务未在运行中")

    job = ai_jobs.current(_job_scope(task_id))
    if job is not None:
        await ai_jobs.cancel(job.id)
        await db.refresh(task)

    if task.status == "running":
        # 无进程内任务 / 流水线写终态失败：这里兜底落库
        task.status = "cancelled"
        task.error_message = CANCELLED_MESSAGE if job is not None else (
            "服务重启后任务已中断，已标记为停止；可重新抽取"
        )
        task.completed_at = datetime.now()
        await db.commit()
        await db.refresh(task)

    logger.info("拆书V2：已停止 user=%s task=%s job=%s", user.user_id, task_id, job.id if job else None)
    return _to_response(task)


def _normalize_extraction_options(
    payload: Optional[V2StartExtractionRequest],
    *,
    chapter_count: int,
) -> dict:
    """校验并归一化抽取参数（start-extraction 与 extraction-plan 共用）。"""
    sampling_mode = "all"
    sampling_param = 1
    extraction_engine = "auto"
    chapters_per_request = 0
    chapter_limit = 0
    if payload is not None:
        sampling_mode = payload.sampling_mode or "all"
        sampling_param = max(1, payload.sampling_param or 1)
        extraction_engine = (payload.extraction_engine or "auto").lower()
        chapters_per_request = max(0, payload.chapters_per_request or 0)
        chapter_limit = max(0, payload.chapter_limit or 0)

    if sampling_mode not in ("all", "every_n", "key_only"):
        raise HTTPException(
            status_code=400,
            detail=f"sampling_mode 非法值：{sampling_mode}（应为 all/every_n/key_only）",
        )
    if extraction_engine not in ("auto", "chunked", "long_context"):
        raise HTTPException(
            status_code=400,
            detail=f"extraction_engine 非法值：{extraction_engine}（应为 auto/chunked/long_context）",
        )
    # 截取到全书之外等价于不截取，归一为 0 便于前端 / 日志判断
    if chapter_count and chapter_limit >= chapter_count:
        chapter_limit = 0

    return {
        "sampling_mode": sampling_mode,
        "sampling_param": sampling_param,
        "extraction_engine": extraction_engine,
        "chapters_per_request": chapters_per_request,
        "chapter_limit": chapter_limit,
    }


# 抽取阶段之后固定的 LLM 调用：5 个手法维度 + synopsis + 冲突仲裁（桥段识别按爽点峰数量动态，不计）
_POST_EXTRACTION_LLM_CALLS = 7


@router.post("/{task_id}/extraction-plan", response_model=ExtractionPlanResponse)
async def preview_extraction_plan(
    task_id: str,
    payload: Optional[V2StartExtractionRequest] = None,
    user: User = Depends(require_login),
    ai_service: AIService = Depends(get_user_ai_service),
    db: AsyncSession = Depends(get_db),
):
    """启动前预估分批方案与 LLM 调用次数（不调 LLM，按 chapters_meta 的字数估算）。

    与 start-extraction 接收同一份 Body，前端调参时实时刷新预估。
    """
    task = await _ensure_task_owned(db, task_id, user.user_id)
    metas = _parse_chapters_meta(task.chapters_meta) or []
    chapter_count = len(metas) or (task.chapter_count or 0)
    opts = _normalize_extraction_options(payload, chapter_count=chapter_count)

    indices = select_target_indices(
        len(metas), opts["sampling_mode"], opts["sampling_param"],
        chapter_limit=opts["chapter_limit"],
    )
    plan = plan_batches(
        [metas[i].word_count for i in indices],
        model=getattr(ai_service, "default_model", None),
        max_tokens=getattr(ai_service, "default_max_tokens", None),
        extraction_engine=opts["extraction_engine"],
        chapters_per_request=opts["chapters_per_request"],
    )
    dictionary_calls = 1 if plan.batch_count > 1 else 0
    return ExtractionPlanResponse(
        chapter_count=chapter_count,
        target_chapters=plan.target_count,
        batch_count=plan.batch_count,
        mode=plan.mode,
        chapters_per_request=plan.chapters_per_request,
        max_chapters_by_output=plan.max_chapters_by_output,
        model=plan.model,
        context_window=plan.context_window,
        max_tokens=plan.output_budget_tokens,
        dictionary_calls=dictionary_calls,
        post_calls=_POST_EXTRACTION_LLM_CALLS,
        estimated_llm_calls=plan.batch_count + dictionary_calls + _POST_EXTRACTION_LLM_CALLS,
        warnings=plan.warnings,
    )


# ============================================================
# V2 浏览端点
# ============================================================


def _parse_json_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json_object(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get("/{task_id}/v2/overview", response_model=V2OverviewResponse)
async def v2_get_overview(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 任务概览（dashboard 顶部数据）。"""
    task = await _ensure_task_owned(db, task_id, user.user_id)
    result_json = task.result_json or "{}"
    try:
        result = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        result = {}

    return V2OverviewResponse(
        task_id=task.id,
        version=task.version or 2,
        extraction_phase=task.extraction_phase,
        chapters_total=task.chapters_total or 0,
        chapters_extracted=task.chapters_extracted or 0,
        chapters_failed=task.chapters_failed or 0,
        sampling_mode=task.sampling_mode or "all",
        sampling_param=task.sampling_param or 1,
        stats=result.get("stats") if isinstance(result.get("stats"), dict) else {},
        synopsis=result.get("synopsis") if isinstance(result.get("synopsis"), dict) else None,
    )


@router.get("/{task_id}/v2/chapters", response_model=List[V2ChapterFactSummarySchema])
async def v2_list_chapter_facts(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 章节事实摘要列表。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    result = await db.execute(
        select(BookDissectChapterFact)
        .where(BookDissectChapterFact.task_id == task_id)
        .order_by(BookDissectChapterFact.chapter_number)
    )
    rows = result.scalars().all()
    return [
        V2ChapterFactSummarySchema.model_validate(r) for r in rows
    ]


@router.get("/{task_id}/v2/chapters/{chapter_number}", response_model=V2ChapterFactDetailSchema)
async def v2_get_chapter_fact(
    task_id: str,
    chapter_number: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 章节事实详情。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    result = await db.execute(
        select(BookDissectChapterFact)
        .where(
            BookDissectChapterFact.task_id == task_id,
            BookDissectChapterFact.chapter_number == chapter_number,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="章节事实不存在")
    fact = _parse_json_object(row.fact_json)
    return V2ChapterFactDetailSchema(
        id=row.id,
        chapter_number=row.chapter_number,
        chapter_title=row.chapter_title,
        summary=row.summary,
        extraction_status=row.extraction_status or "pending",
        extraction_error=row.extraction_error,
        fact=fact,
        is_truncated=bool(row.is_truncated),
        segment_count=row.segment_count or 1,
    )


@router.get("/{task_id}/v2/dictionary", response_model=List[V2DictionaryEntrySchema])
async def v2_list_dictionary(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 实体字典。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    result = await db.execute(
        select(BookDissectDictionary)
        .where(BookDissectDictionary.task_id == task_id)
        .order_by(BookDissectDictionary.frequency.desc())
    )
    rows = result.scalars().all()
    return [
        V2DictionaryEntrySchema(
            id=r.id, name=r.name, entity_type=r.entity_type,
            aliases=_parse_json_list(r.aliases_json),
            frequency=r.frequency or 0,
            confidence=r.confidence or "medium",
            sample_context=r.sample_context,
            source=r.source,
        )
        for r in rows
    ]


@router.get("/{task_id}/v2/entities", response_model=List[V2EntitySchema])
async def v2_list_entities(
    task_id: str,
    entity_type: Optional[str] = None,
    slim: bool = False,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 全书实体（可按类型过滤）。

    slim=True 时不返回体积大的 profile 字段（仅用于列表视图），可显著减少网络传输；
    需要完整档案时请调用 ``GET /v2/entities/{entity_id}``。
    """
    await _ensure_task_owned(db, task_id, user.user_id)
    stmt = select(BookDissectEntity).where(BookDissectEntity.task_id == task_id)
    if entity_type:
        stmt = stmt.where(BookDissectEntity.entity_type == entity_type)
    stmt = stmt.order_by(BookDissectEntity.appearance_count.desc())
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        V2EntitySchema(
            id=r.id,
            canonical_name=r.canonical_name,
            entity_type=r.entity_type,
            aliases=_parse_json_list(r.aliases_json),
            profile={} if slim else _parse_json_object(r.profile_json),
            first_chapter=r.first_chapter,
            last_chapter=r.last_chapter,
            appearance_count=r.appearance_count or 0,
            role_type=r.role_type,
            parent_entity_id=r.parent_entity_id,
        )
        for r in rows
    ]


@router.get("/{task_id}/v2/entities/{entity_id}", response_model=V2EntitySchema)
async def v2_get_entity(
    task_id: str,
    entity_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 单个实体详情（包含完整 profile）。配合 slim 列表使用。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    result = await db.execute(
        select(BookDissectEntity).where(
            BookDissectEntity.task_id == task_id,
            BookDissectEntity.id == entity_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    return V2EntitySchema(
        id=row.id,
        canonical_name=row.canonical_name,
        entity_type=row.entity_type,
        aliases=_parse_json_list(row.aliases_json),
        profile=_parse_json_object(row.profile_json),
        first_chapter=row.first_chapter,
        last_chapter=row.last_chapter,
        appearance_count=row.appearance_count or 0,
        role_type=row.role_type,
        parent_entity_id=row.parent_entity_id,
    )


@router.get("/{task_id}/v2/relations", response_model=List[V2RelationSchema])
async def v2_list_relations(
    task_id: str,
    relation_category: Optional[str] = None,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 实体关系（可按类别过滤）。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    stmt = select(BookDissectRelation).where(BookDissectRelation.task_id == task_id)
    if relation_category:
        stmt = stmt.where(BookDissectRelation.relation_category == relation_category)
    stmt = stmt.order_by(BookDissectRelation.occurrence_count.desc())
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        V2RelationSchema(
            id=r.id,
            entity_a_id=r.entity_a_id,
            entity_b_id=r.entity_b_id,
            relation_type=r.relation_type,
            relation_category=r.relation_category,
            occurrence_count=r.occurrence_count or 1,
            first_chapter=r.first_chapter,
            evidence=_parse_json_list(r.evidence_json),
        )
        for r in rows
    ]


@router.get("/{task_id}/v2/events", response_model=List[V2EventSchema])
async def v2_list_events(
    task_id: str,
    importance: Optional[str] = None,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """V2 事件时间线（可按 importance 过滤）。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    stmt = select(BookDissectEvent).where(BookDissectEvent.task_id == task_id)
    if importance:
        stmt = stmt.where(BookDissectEvent.importance == importance)
    stmt = stmt.order_by(BookDissectEvent.chapter_number)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        V2EventSchema(
            id=r.id,
            chapter_number=r.chapter_number,
            event_type=r.event_type,
            title=r.title,
            description=r.description,
            actors=_parse_json_list(r.actors_json),
            location=r.location,
            importance=r.importance or "medium",
            evidence=r.evidence,
        )
        for r in rows
    ]


async def _ensure_task_owned(
    db: AsyncSession, task_id: str, user_id: str
) -> BookDissectTask:
    result = await db.execute(
        select(BookDissectTask).where(
            BookDissectTask.id == task_id,
            BookDissectTask.user_id == user_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return task


# ============================================================
# 删除（清理磁盘文件）
# ============================================================


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """删除拆书任务并清理磁盘全文 + 所有派生数据。

    SQLite 未启用 PRAGMA foreign_keys=ON，外键 ondelete=CASCADE 不生效，
    必须显式清理：ReferencePack（及其项目挂载）+ 5 张抽取数据表，
    否则会留下仍可被项目引用的孤儿参考包与孤儿抽取数据。
    """
    result = await db.execute(
        select(BookDissectTask).where(
            BookDissectTask.id == task_id,
            BookDissectTask.user_id == user.user_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")

    # 运行中先停掉后台任务，否则流水线会继续对已删的行写数据
    job = ai_jobs.current(_job_scope(task_id))
    if job is not None:
        await ai_jobs.cancel(job.id)
        await db.refresh(task)

    # 删磁盘文件（即使失败也继续删 DB 记录）
    if task.storage_path:
        path = Path(task.storage_path)
        if path.exists():
            try:
                path.unlink()
            except OSError as e:
                logger.warning("拆书：删除磁盘文件失败 path=%s err=%s", path, e)

    # 1. 参考包及其项目挂载（pack 与 task 1:1）
    pack_result = await db.execute(
        select(ReferencePack.id).where(ReferencePack.task_id == task_id)
    )
    pack_id = pack_result.scalar_one_or_none()
    if pack_id:
        await db.execute(
            delete(ProjectReferencePack).where(ProjectReferencePack.pack_id == pack_id)
        )
        await db.execute(delete(ReferencePack).where(ReferencePack.id == pack_id))

    # 2. 抽取数据表（relation 先于 entity，避免悬挂引用语义混乱）
    await db.execute(delete(BookDissectRelation).where(BookDissectRelation.task_id == task_id))
    await db.execute(delete(BookDissectEvent).where(BookDissectEvent.task_id == task_id))
    await db.execute(delete(BookDissectEntity).where(BookDissectEntity.task_id == task_id))
    await db.execute(delete(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task_id))
    await db.execute(delete(BookDissectDictionary).where(BookDissectDictionary.task_id == task_id))

    # 3. 任务本体
    await db.delete(task)
    await db.commit()
    logger.info(
        "拆书任务已删除: user=%s task=%s pack=%s（含派生数据）",
        user.user_id, task_id, pack_id or "-",
    )
    return {"message": "任务已删除", "task_id": task_id}


# ============================================================
# 一键填充新项目（apply-to-wizard）
# ============================================================


# V3 R6 废弃说明：保留接口路径仅用于发出 410 Gone 信号，避免老前端 / 脚本静默踩坑。
# 原路径 POST /api/book-dissect/{task_id}/apply-to-wizard 将拆书产物直接复刻为新项目，
# 在 V3 重构中被判定为"错路"（让用户照抄原书、丢弃了作者自己的创作意图）。
# 正确路径：从作者自己的项目起步 → 挂载参考包（ReferencePack）→ 章节编辑器中「一键仿写」。
# 详见：@/agent-docs/features/book_dissect_v3_imitation_design.md §6 R6
DEPRECATION_DETAIL = {
    "code": "apply_to_wizard_deprecated",
    "message": "拆书「一键创建项目」接口已废弃。该路径会直接复刻原书内容为新项目，不符合作者自主创作理念。",
    "migration": [
        "1. 在 《参考库》 页面查看本任务对应的参考包（ReferencePack）",
        "2. 在 《项目设置 · 参考库》 中把参考包挂载到你自己的项目",
        "3. 在项目章节编辑器点击 《一键仿写》，填写本次创作意图后生成草稿",
    ],
    "new_endpoints": [
        "POST /api/projects/{project_id}/reference-packs",
        "POST /api/projects/{project_id}/imitate-chapter-stream",
        "POST /api/projects/{project_id}/imitate-chapter-preview",
    ],
}


@router.post(
    "/{task_id}/apply-to-wizard",
    status_code=410,
    summary="[已废弃] 拆书一键创建项目",
    deprecated=True,
)
async def apply_to_wizard(
    task_id: str,
    user: User = Depends(require_login),
):
    """V3 R6：该接口已废弃。任何调用一律返 410 Gone 并携带迁移指引。

    保留路由者名与路径以便老前端 / 脚本查出废弃信号；后续可考虑彻底删除路由。
    """
    logger.info(
        "[V3-R6] 拦截已废弃的 apply_to_wizard 调用 user=%s task=%s",
        user.user_id, task_id,
    )
    raise HTTPException(status_code=410, detail=DEPRECATION_DETAIL)

