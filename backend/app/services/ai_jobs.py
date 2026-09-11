"""通用 AI 后台任务（进程内）。

从桥段填充的 BridgeFillJobManager（agent-docs/plans/2026-09-09-bridge-fill-ux.md）泛化而来：任何一次
AI 生成（角色 / 组织 / 剧情线 / 桥段填充 / 章纲展开 / 正文 / 分析…）都跑在独立 asyncio Task 里，
寿命独立于 HTTP 连接；事件带序号写进任务日志，SSE 端点可从任意序号回放再续尾；"最新态"事件
（progress / llm / thinking / partial）只留最后一份快照，回放不重播几百条中间态。

约束：状态只在内存（桌面版单进程）；各业务表的 status 仍是唯一持久状态，任务中断 = 业务层自己
保证幂等 / 可续跑。同一 scope（默认 kind:project_id）同时只允许一个 running 任务。

事件发布是同步的（publish / finish 不 await）：Python 3.11+ 任务被 cancel 后再 await 会立刻再次抛
CancelledError，取消路径上必须能无 await 地写下"已停止"事件。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# 只保留最新快照的事件类型（回放时不重播中间态）
LIVE_EVENT_TYPES = ("progress", "llm", "thinking", "partial")
TERMINAL_STATUSES = ("done", "error", "cancelled")
# 终态任务在内存里保留多久（托盘"最近完成" + 晚到的重连），超过即被 gc
TERMINAL_RETENTION_SECONDS = 600.0
DEFAULT_CANCEL_MESSAGE = "已停止任务"

Runner = Callable[["AIJob"], Awaitable[Any]]


class AIJobConflictError(RuntimeError):
    """同一 scope 已有任务在运行。"""


@dataclass
class AIJob:
    id: str
    kind: str
    title: str
    user_id: str
    project_id: Optional[str]
    scope: Optional[str]
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Any = None
    seq: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)
    live: dict[str, dict[str, Any]] = field(default_factory=dict)
    cancel_message: str = DEFAULT_CANCEL_MESSAGE
    task: Optional[asyncio.Task] = None
    # 每次变更 set 后换一个新 Event：等待方先取引用再 wait，不会漏事件
    _changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def snapshot(self) -> dict[str, Any]:
        """给 GET /api/ai-jobs[/{id}]：页面挂载时恢复托盘 / 横幅并决定是否重连。"""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "project_id": self.project_id,
            "scope": self.scope,
            "meta": dict(self.meta),
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
            "seq": self.seq,
            "error": self.error,
            "result": self.result,
            "last_progress": self.live.get("progress"),
            "live": dict(self.live),
        }

    def _notify(self) -> None:
        waiter, self._changed = self._changed, asyncio.Event()
        waiter.set()

    def publish(self, event: dict[str, Any]) -> None:
        self.seq += 1
        event = {**event, "seq": self.seq}
        if event["type"] in LIVE_EVENT_TYPES:
            self.live[event["type"]] = event
        else:
            self.log.append(event)
        self._notify()

    def progress(self, message: str, progress: int, status: str = "processing") -> None:
        self.publish({"type": "progress", "message": message, "progress": int(progress), "status": status})

    def finish(self, status: str, error: Optional[str] = None) -> None:
        self.status = status
        self.error = error
        self.finished_at = time.time()
        self._notify()


class AIJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, AIJob] = {}

    # ---------------- 查询 ----------------

    def get(self, job_id: str) -> Optional[AIJob]:
        return self._jobs.get(job_id)

    def current(self, scope: str) -> Optional[AIJob]:
        """该 scope 正在运行的任务（终态不算）。"""
        for job in self._jobs.values():
            if job.scope == scope and not job.is_terminal:
                return job
        return None

    def list_for_user(self, user_id: str, *, project_id: Optional[str] = None) -> list[AIJob]:
        """用户的任务：running 优先，其次按开始时间倒序；终态只含保留期内的。"""
        self.gc()
        jobs = [
            j for j in self._jobs.values()
            if j.user_id == user_id and (project_id is None or j.project_id == project_id)
        ]
        jobs.sort(key=lambda j: (j.is_terminal, -j.started_at))
        return jobs

    def gc(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        stale = [
            jid for jid, j in self._jobs.items()
            if j.is_terminal and j.finished_at is not None and now - j.finished_at > TERMINAL_RETENTION_SECONDS
        ]
        for jid in stale:
            del self._jobs[jid]
        return len(stale)

    # ---------------- 启动 / 取消 ----------------

    async def start(
        self,
        *,
        kind: str,
        title: str,
        user_id: str,
        project_id: Optional[str] = None,
        runner: Runner,
        scope: Optional[str] = "",
        meta: Optional[dict[str, Any]] = None,
        cancel_message: str = DEFAULT_CANCEL_MESSAGE,
    ) -> AIJob:
        """启动任务。scope="" 用默认互斥键 kind:project_id（无项目则 kind:user_id）；scope=None 不互斥。"""
        self.gc()
        if scope == "":
            scope = f"{kind}:{project_id or user_id}"
        if scope is not None and self.current(scope) is not None:
            raise AIJobConflictError(f"「{title}」已有任务在运行，请等待完成或先停止")
        job = AIJob(
            id=str(uuid.uuid4()), kind=kind, title=title, user_id=user_id, project_id=project_id,
            scope=scope, meta=dict(meta or {}), cancel_message=cancel_message,
        )
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, runner), name=f"ai-job:{kind}:{job.id[:8]}")
        return job

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.is_terminal or job.task is None:
            return False
        job.task.cancel()
        try:
            await job.task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 取消路径上的异常已在 _run 内记录
            pass
        if not job.is_terminal:
            # 任务在跑出第一步之前就被取消：_run 的 except 分支没机会执行，这里补终态
            job.publish({"type": "error", "error": job.cancel_message, "code": 499})
            job.finish("cancelled")
        return True

    async def shutdown(self) -> None:
        """应用退出：取消所有运行中的任务（业务表状态由各 runner 自行保证可续跑）。"""
        for job in list(self._jobs.values()):
            if not job.is_terminal:
                await self.cancel(job.id)

    # ---------------- 事件回放 + 续尾 ----------------

    async def events(self, job_id: str, since: int = 0) -> AsyncIterator[dict[str, Any]]:
        job = self._jobs.get(job_id)
        if job is None:
            yield {"type": "error", "error": "任务不存在或已过期", "code": 404, "seq": 0}
            return
        last = since
        while True:
            waiter = job._changed
            pending = [e for e in job.log if e["seq"] > last]
            pending += [e for e in job.live.values() if e["seq"] > last]
            pending.sort(key=lambda e: e["seq"])
            terminal = job.is_terminal
            if not pending:
                if terminal:
                    return
                await waiter.wait()
                continue
            for e in pending:
                yield e
                last = e["seq"]

    # ---------------- runner ----------------

    async def _run(self, job: AIJob, runner: Runner) -> None:
        try:
            result = await runner(job)
            if result is not None:
                job.result = result
                job.publish({"type": "result", "data": result})
            job.progress("完成", 100, "success")
            job.publish({"type": "done"})
            job.finish("done")
        except asyncio.CancelledError:
            logger.info("[AIJob] %s(%s) 已取消", job.kind, job.id)
            job.publish({"type": "error", "error": job.cancel_message, "code": 499})
            job.finish("cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转 error 事件
            logger.error("[AIJob] %s(%s) 失败: %s", job.kind, job.id, exc, exc_info=True)
            job.publish({"type": "error", "error": f"{job.title}失败: {exc}", "code": 500})
            job.finish("error", str(exc))


class JobSession:
    """`async with job_session_factory(user_id)() as db`：后台任务用的会话，引擎按 user_id 惰性获取。

    任务寿命超过请求，不能复用 Depends(get_db) 的会话（请求结束即关闭）。
    与 book_dissect/extractor_v2._create_task_session 同一套路（原 plot_bridges._JobSession 搬到这里）。
    """

    def __init__(self, user_id: str):
        self._user_id = user_id
        self._session: Optional[AsyncSession] = None

    async def __aenter__(self) -> AsyncSession:
        from app.database import get_engine  # 延迟导入：避免 services 层在 import 时就拉起数据库模块

        engine = await get_engine(self._user_id)
        self._session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()
        return self._session

    async def __aexit__(self, *exc) -> bool:
        if self._session is not None:
            await self._session.close()
        return False


def job_session_factory(user_id: str) -> Callable[[], JobSession]:
    return lambda: JobSession(user_id)


ai_jobs = AIJobManager()
