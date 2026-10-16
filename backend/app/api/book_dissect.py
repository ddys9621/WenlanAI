"""拆书功能 API

- POST /api/book-dissect/upload  上传 txt/md → 切分 → 返回 task_id + 章节预览（不接 LLM）
- GET  /api/book-dissect/{task_id}  查询任务状态
- POST /api/book-dissect/{task_id}/extraction-plan  启动前预估分批 / 调用次数（不接 LLM）
- POST /api/book-dissect/{task_id}/start-extraction  启动抽取（拆书卡 → 剧情单元 → 分卷 / 骨架 → 文风；跑在 AIJobManager 后台任务里，可停止）
- POST /api/book-dissect/{task_id}/cancel  手动停止运行中的抽取
- DELETE /api/book-dissect/{task_id}  删除任务并清理磁盘（运行中会先停止）

抽取任务注册在 ai_jobs（scope=book_dissect:{task_id}），托盘里也能看到 / 停止；
任务的持久状态仍以 book_dissect_tasks.status 为准（pending/running/completed/failed/cancelled）。
ai_jobs 只管本进程：同一 data 目录被多个后端实例共用时，另按 task 持 OS 文件锁（run_lock）判断
流水线是否真的在跑，start / cancel / delete 遇到别的进程持锁一律 409，不动 DB 状态。
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
from app.models.book_dissect_story_arc import BookDissectStoryArc
from app.models.book_dissect_task import BookDissectTask
from app.models.reference_pack import ReferencePack
from app.schemas.reference_pack import ReferencePackDetail
from app.schemas.book_dissect import (
    BookDissectTaskResponse,
    BookDissectUploadResponse,
    ChapterCardDetail,
    ChapterCardListItem,
    ChapterMetaSchema,
    ExtractionPlanResponse,
    StoryArcSchema,
    V2StartExtractionRequest,
)
from app.services.ai_jobs import AIJob, AIJobConflictError, ai_jobs
from app.services.ai_service import AIService
from app.services.book_dissect.batch_planner import plan_arc_window, plan_batches, select_target_indices
from app.services.book_dissect.chapter_splitter import split_bytes
from app.services.book_dissect.extractor_v5 import (
    CANCELLED_MESSAGE,
    run_extraction_v5_background,
)
from app.services.book_dissect.run_lock import is_run_locked, try_acquire_run_lock
from app.services.knowledge.kb_import import delete_dissect_source
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
        version=task.version or 5,
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


# 本进程没有 job 但 run_lock 被持有：流水线在另一个后端进程里跑着（同一 data 目录被多个实例共用）。
# 此时改 DB 状态 / 再启动 / 删除都会让两边互相踩数据（拆书卡表 UNIQUE(task_id, chapter_number) 冲突）。
OTHER_PROCESS_DETAIL = "任务正在另一个后端进程中抽取（同一数据目录被多个实例共用），请到该实例停止或等待其完成后再操作"


@router.post("/{task_id}/start-extraction", response_model=BookDissectTaskResponse)
async def start_extraction(
    task_id: str,
    payload: Optional[V2StartExtractionRequest] = None,
    user: User = Depends(require_login),
    ai_service: AIService = Depends(get_user_ai_service),
    db: AsyncSession = Depends(get_db),
):
    """启动 LLM 抽取（分批拆书卡 → 剧情单元 → 分卷 / 全书骨架 → 文风指纹 → 参考包），跑在 ai_jobs 后台任务里，可随时 /cancel 停止。

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

    # 跨进程互斥先于改状态：拿不到锁就什么都不动
    lock = try_acquire_run_lock(task_id)
    if lock is None:
        raise HTTPException(status_code=409, detail=OTHER_PROCESS_DETAIL)

    user_id = user.user_id

    async def runner(_job: AIJob) -> None:
        # 锁随流水线生命周期：正常结束 / 失败 / 取消都在这里释放；进程崩溃由 OS 回收
        try:
            await run_extraction_v5_background(task_id=task_id, user_id=user_id, ai_service=ai_service)
        finally:
            lock.release()

    try:
        # 立即标记 queued，避免前端轮询时短暂看到旧状态
        task.status = "running"
        task.stage = "queued"
        task.progress = 0
        task.error_message = None
        task.started_at = datetime.now()
        task.completed_at = None
        task.version = 5
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

        await ai_jobs.start(
            kind="book_dissect",
            title=f"拆书抽取：{task.file_name or task_id[:8]}",
            user_id=user_id,
            runner=runner,
            scope=_job_scope(task_id),
            cancel_message=CANCELLED_MESSAGE,
            meta={"task_id": task_id, **opts},
        )
    except BaseException as exc:
        # 没能把锁交给 runner（commit 失败 / 与并发请求抢 ai_jobs 失败）：这里释放，否则要等进程退出
        lock.release()
        if isinstance(exc, AIJobConflictError):
            # 与上面的 current() 预检之间被并发请求抢先：DB 已由对方置 running，本次不再改状态
            raise HTTPException(status_code=409, detail=str(exc))
        raise

    logger.info(
        "拆书V5：已排队 user=%s task=%s sampling=%s/%d engine=%s per_request=%d limit=%d",
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
    - 没有但 run_lock 被持有：流水线在另一个后端进程里跑，409（改状态只会让人再触发重抽撞库）
    - 都没有（服务重启后残留的 running）：直接落库修复，否则任务永远卡在 running 无法重抽
    已完成批次的章节事实保留；随后可「重新抽取」。
    """
    task = await _ensure_task_owned(db, task_id, user.user_id)
    if task.status != "running":
        raise HTTPException(status_code=409, detail="任务未在运行中")

    job = ai_jobs.current(_job_scope(task_id))
    if job is not None:
        await ai_jobs.cancel(job.id)
        await db.refresh(task)
    elif is_run_locked(task_id):
        raise HTTPException(status_code=409, detail=OTHER_PROCESS_DETAIL)

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


# V5 拆书卡之后的 LLM 调用估算（与 extractor_v5 各阶段对应）：
#   剧情单元 ≈ 目标章数 / 每轮窗口卡数（plan_arc_window 按模型上下文 / Max Tokens 规划，8-60 张）
#   分卷 ≈ 单元数 / 40（单元平均约 4 章 → 每 160 章一块）
#   骨架 / 人物功能谱 / 写法手册 3 次 + 文风定性 1 次 + 例句 3 章各 1 次
_V5_FIXED_POST_CALLS = 7


def _estimate_post_extraction_calls(
    target_chapters: int, *, model: Optional[str], max_tokens: Optional[int],
) -> tuple[int, int, int]:
    """返回 (拆书卡之后总调用数, 其中剧情单元轮数, 剧情单元每轮卡数)。"""
    arc_plan = plan_arc_window(target_chapters, model=model, max_tokens=max_tokens)
    if target_chapters <= 0:
        return 0, 0, arc_plan.window_new
    arc_calls = arc_plan.window_count(target_chapters)
    stage_calls = max(1, -(-target_chapters // 160))
    return arc_calls + stage_calls + _V5_FIXED_POST_CALLS, arc_calls, arc_plan.window_new


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
    post_calls, arc_calls, arc_window = _estimate_post_extraction_calls(
        plan.target_count,
        model=getattr(ai_service, "default_model", None),
        max_tokens=getattr(ai_service, "default_max_tokens", None),
    )
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
        dictionary_calls=0,  # V5 不再做实体扫描 / 字典分类
        post_calls=post_calls,
        arc_calls=arc_calls,
        arc_window=arc_window,
        estimated_llm_calls=plan.batch_count + post_calls,
        warnings=plan.warnings,
    )


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
# 浏览：拆书卡 / 剧情单元
# ============================================================


def _load_card(row: BookDissectChapterFact) -> dict:
    try:
        data = json.loads(row.fact_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


@router.get("/{task_id}/cards", response_model=List[ChapterCardListItem])
async def v5_list_cards(task_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    """拆书卡精简列表（不含章纲正文），按章号升序。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    rows = (await db.execute(
        select(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task_id).order_by(BookDissectChapterFact.chapter_number)
    )).scalars().all()
    out: List[ChapterCardListItem] = []
    for row in rows:
        card = _load_card(row)
        out.append(ChapterCardListItem(
            chapter_number=row.chapter_number, title=card.get("title") or row.chapter_title or "",
            function_tags=card.get("function_tags") or [], pace=card.get("pace") or "中", tension=int(card.get("tension") or 3),
            ending_hook_type=card.get("ending_hook_type") or "无", payoff_count=len(card.get("payoff_points") or []),
            word_count=int(card.get("word_count") or 0), extraction_status=row.extraction_status or "success",
        ))
    return out


@router.get("/{task_id}/cards/{chapter_number}", response_model=ChapterCardDetail)
async def v5_get_card(task_id: str, chapter_number: int, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    """整张拆书卡。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    row = (await db.execute(
        select(BookDissectChapterFact).where(
            BookDissectChapterFact.task_id == task_id, BookDissectChapterFact.chapter_number == chapter_number,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="该章没有拆书卡")
    card = _load_card(row)
    card.setdefault("chapter_number", row.chapter_number)
    return ChapterCardDetail(**card, extraction_status=row.extraction_status or "success", extraction_error=row.extraction_error)


@router.get("/{task_id}/arcs", response_model=List[StoryArcSchema])
async def v5_list_arcs(task_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    """剧情单元全量列表，按单元编号升序。"""
    await _ensure_task_owned(db, task_id, user.user_id)
    rows = (await db.execute(
        select(BookDissectStoryArc).where(BookDissectStoryArc.task_id == task_id).order_by(BookDissectStoryArc.arc_index)
    )).scalars().all()
    out: List[StoryArcSchema] = []
    for row in rows:
        try:
            data = json.loads(row.arc_json or "{}")
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("arc_index", row.arc_index)
        data.setdefault("start_chapter", row.start_chapter)
        data.setdefault("end_chapter", row.end_chapter)
        out.append(StoryArcSchema(**data))
    return out


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
    必须显式清理：ReferencePack（及其项目挂载）+ 拆书卡 / 剧情单元表，
    否则会留下仍可被项目引用的孤儿参考包与孤儿抽取数据。
    V2-V4 老引擎的 4 张实体图谱表已不再建模，但老库里可能仍有残表与残行，
    用原生 SQL 顺手清掉；表不存在（新库）时忽略。
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

    # 运行中先停掉后台任务，否则流水线会继续对已删的行写数据；跑在别的进程里的停不掉，只能拒绝
    job = ai_jobs.current(_job_scope(task_id))
    if job is not None:
        await ai_jobs.cancel(job.id)
        await db.refresh(task)
    elif is_run_locked(task_id):
        raise HTTPException(status_code=409, detail=OTHER_PROCESS_DETAIL)

    # 删磁盘文件（即使失败也继续删 DB 记录）
    if task.storage_path:
        path = Path(task.storage_path)
        if path.exists():
            try:
                path.unlink()
            except OSError as e:
                logger.warning("拆书：删除磁盘文件失败 path=%s err=%s", path, e)

    # 1. 拆书结果（各维度产物，pack 与 task 1:1）
    pack_result = await db.execute(
        select(ReferencePack.id).where(ReferencePack.task_id == task_id)
    )
    pack_id = pack_result.scalar_one_or_none()
    if pack_id:
        await db.execute(delete(ReferencePack).where(ReferencePack.id == pack_id))

    # 2. 抽取数据表：拆书卡 + 剧情单元
    await db.execute(delete(BookDissectChapterFact).where(BookDissectChapterFact.task_id == task_id))
    await db.execute(delete(BookDissectStoryArc).where(BookDissectStoryArc.task_id == task_id))
    await delete_dissect_source(db, task_id)

    # 3. 任务本体
    await db.delete(task)
    await db.commit()
    logger.info(
        "拆书任务已删除: user=%s task=%s pack=%s（含派生数据）",
        user.user_id, task_id, pack_id or "-",
    )
    return {"message": "任务已删除", "task_id": task_id}


def _loads_or(raw: Optional[str], default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


@router.get("/{task_id}/result", response_model=Optional[ReferencePackDetail],
            summary="拆书结果（全书骨架 / 文风 / 人物 / 写法 / 结构）；还没拆完返回 null")
async def get_result(task_id: str, user: User = Depends(require_login), db: AsyncSession = Depends(get_db)):
    task = (await db.execute(
        select(BookDissectTask.id).where(BookDissectTask.id == task_id, BookDissectTask.user_id == user.user_id)
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    pack = (await db.execute(
        select(ReferencePack).where(ReferencePack.task_id == task_id, ReferencePack.user_id == user.user_id)
    )).scalar_one_or_none()
    if pack is None:
        return None
    dims = _loads_or(pack.generated_dimensions, [])
    return ReferencePackDetail(
        id=pack.id, user_id=pack.user_id, task_id=pack.task_id, source_book_title=pack.source_book_title,
        status=pack.status, generated_dimensions=dims if isinstance(dims, list) else [],
        pipeline_version=pack.pipeline_version or 5, error_message=pack.error_message,
        synopsis=_loads_or(pack.synopsis_json, None), bridges=_loads_or(pack.bridges_json, None),
        style=_loads_or(pack.style_json, None), character_archive=_loads_or(pack.character_archive_json, None),
        methodology=_loads_or(pack.methodology_json, None), structure=_loads_or(pack.structure_json, None),
        created_at=pack.created_at, updated_at=pack.updated_at,
    )

