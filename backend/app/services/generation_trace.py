"""生成过程追踪：把"阶段 / 工具调用 / 参考资料 / LLM 进度"作为事件送给当前后台任务。

用 ContextVar 绑定到 asyncio Task（ai_jobs.AIJobManager._run 里绑定；create_task 的子任务复制上下文，
自动继承），AIService / MCPToolService / ReferencePackInjector / WorldRuleService 这些共享入口只需调用
模块级 trace_* 函数：没绑定（普通请求、单测）时全部 no-op，零侵入；绑定了就自动出现在前端弹窗的
"过程"面板（stage 时间线 / 工具调用 / 参考资料 / 模型思考计数）。

只传计数 / 标题 / 参数摘要，不传思考文本与 prompt 正文（用户决策 2026-09-09 / 2026-09-11）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

Sink = Callable[[dict[str, Any]], None]
LLM_LIVE_PHASES = ("thinking", "streaming")
ARGS_PREVIEW_LIMIT = 120
ERROR_TEXT_LIMIT = 200


def new_call_id() -> str:
    return uuid.uuid4().hex[:8]


def preview_args(args: Any, limit: int = ARGS_PREVIEW_LIMIT) -> str:
    """工具参数摘要：JSON 序列化后截断；不可序列化的退回 str()。"""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    return text if len(text) <= limit else text[:limit] + "…"


def _short_error(exc: Any) -> str:
    return str(exc)[:ERROR_TEXT_LIMIT]


class GenerationTrace:
    """一次生成任务的过程事件出口；sink 通常是 AIJob.publish。"""

    def __init__(self, sink: Sink, *, llm_min_interval: float = 0.5):
        self._sink = sink
        self._llm_min_interval = llm_min_interval
        self._llm_last_emit: dict[str, float] = {}

    def emit(self, event: dict[str, Any]) -> None:
        try:
            self._sink(event)
        except Exception as exc:  # noqa: BLE001 - 追踪失败不能影响生成本身
            logger.warning("[GenerationTrace] sink 失败，事件丢弃: %s", exc)

    def stage(
        self, name: str, label: str, status: str = "running", *,
        elapsed: Optional[float] = None, detail: Optional[dict[str, Any]] = None, error: Any = None,
    ) -> None:
        event: dict[str, Any] = {"type": "stage", "name": name, "label": label, "status": status}
        if elapsed is not None:
            event["elapsed"] = round(elapsed, 2)
        if detail:
            event["detail"] = dict(detail)
        if error:
            event["error"] = _short_error(error)
        self.emit(event)

    def progress(self, message: str, progress: int, status: str = "processing") -> None:
        self.emit({"type": "progress", "message": message, "progress": int(progress), "status": status})

    def tool_call(
        self, call_id: str, *, tool: str, plugin: str, status: str,
        args_preview: Optional[str] = None, elapsed_ms: Optional[float] = None,
        result_chars: Optional[int] = None, error: Any = None,
    ) -> None:
        event: dict[str, Any] = {"type": "tool_call", "call_id": call_id, "tool": tool, "plugin": plugin, "status": status}
        if args_preview is not None:
            event["args_preview"] = args_preview
        if elapsed_ms is not None:
            event["elapsed_ms"] = int(elapsed_ms)
        if result_chars is not None:
            event["result_chars"] = int(result_chars)
        if error:
            event["error"] = _short_error(error)
        self.emit(event)

    def reference(self, kind: str, label: str, items: Iterable[dict[str, Any]], **extra: Any) -> None:
        items = list(items)
        self.emit({"type": "reference", "kind": kind, "label": label, "items": items, "count": len(items), **extra})

    def llm(
        self, call_id: str, phase: str, *, model: str,
        reasoning_chars: int = 0, content_chars: int = 0, elapsed: float = 0.0,
        finish_reason: Optional[str] = None, prompt_chars: Optional[int] = None,
        tool_calls: Optional[int] = None, error: Any = None,
    ) -> bool:
        """thinking / streaming 按 llm_min_interval 节流（每个 call_id 独立计时）；start / done / error 直发。返回是否已发出。"""
        if phase in LLM_LIVE_PHASES:
            now = time.monotonic()
            if now - self._llm_last_emit.get(call_id, float("-inf")) < self._llm_min_interval:
                return False
            self._llm_last_emit[call_id] = now
        event: dict[str, Any] = {
            "type": "llm", "call_id": call_id, "phase": phase, "model": model,
            "reasoning_chars": int(reasoning_chars), "content_chars": int(content_chars), "elapsed": round(elapsed, 2),
        }
        if finish_reason is not None:
            event["finish_reason"] = finish_reason
        if prompt_chars is not None:
            event["prompt_chars"] = int(prompt_chars)
        if tool_calls is not None:
            event["tool_calls"] = int(tool_calls)
        if error:
            event["error"] = _short_error(error)
        if phase in ("done", "error"):
            self._llm_last_emit.pop(call_id, None)
        self.emit(event)
        return True


# ---------------- 上下文绑定 ----------------

_current: ContextVar[Optional[GenerationTrace]] = ContextVar("mumu_generation_trace", default=None)


def current_trace() -> Optional[GenerationTrace]:
    return _current.get()


def bind_trace(trace: GenerationTrace) -> Token:
    return _current.set(trace)


def reset_trace(token: Token) -> None:
    _current.reset(token)


# ---------------- 便捷函数：未绑定时 no-op ----------------

def trace_stage(name: str, label: str, status: str = "running", **kw: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.stage(name, label, status, **kw)


def trace_progress(message: str, progress: int, status: str = "processing") -> None:
    trace = current_trace()
    if trace is not None:
        trace.progress(message, progress, status)


def trace_reference(kind: str, label: str, items: Iterable[dict[str, Any]], **extra: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.reference(kind, label, items, **extra)


def trace_tool_call(call_id: str, **kw: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.tool_call(call_id, **kw)


def trace_llm(call_id: str, phase: str, **kw: Any) -> bool:
    trace = current_trace()
    return trace.llm(call_id, phase, **kw) if trace is not None else False


@dataclass
class StageHandle:
    """stage_scope 交给业务代码的句柄：note() 补充明细，skip() 把该阶段标为跳过。"""
    name: str
    label: str
    status: str = "running"
    detail: dict[str, Any] = field(default_factory=dict)

    def note(self, **detail: Any) -> None:
        self.detail.update(detail)

    def skip(self, reason: str = "") -> None:
        self.status = "skipped"
        self.detail = {"reason": reason} if reason else {}


@contextlib.asynccontextmanager
async def stage_scope(name: str, label: str) -> AsyncIterator[StageHandle]:
    """业务层标注一个阶段：进入发 running；正常退出发 done（或 handle.skip 后的 skipped）；异常发 error / cancelled 并原样抛出。"""
    trace = current_trace()
    handle = StageHandle(name, label)
    started = time.monotonic()
    if trace is not None:
        trace.stage(name, label, "running")
    try:
        yield handle
    except asyncio.CancelledError:
        if trace is not None:
            trace.stage(name, label, "cancelled", elapsed=time.monotonic() - started, detail=handle.detail)
        raise
    except Exception as exc:
        if trace is not None:
            trace.stage(name, label, "error", elapsed=time.monotonic() - started, detail=handle.detail, error=exc)
        raise
    if trace is not None:
        final = "done" if handle.status == "running" else handle.status
        trace.stage(name, label, final, elapsed=time.monotonic() - started, detail=handle.detail)
