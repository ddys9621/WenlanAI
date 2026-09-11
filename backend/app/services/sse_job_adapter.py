"""SSE 生成器 → ai_jobs runner 适配器。

向导四步（world_building / characters / outline / plot_lines）都是"产出 SSE 文本"的 async generator
（`data: {json}\\n\\n`，见 app.utils.sse_response）。要让它们跑在通用后台任务上又不改那两千行生成器，
这里把生成器产出解析回事件并转发进任务：
- progress → job.publish（最新态）；chunk / content → content 日志（可回放重建全文）
- result → 记为任务结果（由管理器发 result 事件，不重复转发）；done / 心跳注释行 → 忽略
- error → 抛 SSEGeneratorError（管理器转 error 事件，文案 / code 透传）
- 其它类型（partial / meta …）原样 publish（场景级事件）
生成器内部的 generate_text_stream / MCP / 参考包调用运行在任务 Task 里，llm / tool_call / reference 事件自动上报。
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable, Optional

from app.services.ai_jobs import AIJob, Runner

logger = logging.getLogger(__name__)

GeneratorFactory = Callable[[Any], AsyncIterator[str]]   # (db_session) -> SSE 文本流


class SSEGeneratorError(RuntimeError):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code


def parse_sse_chunk(chunk: str) -> list[dict[str, Any]]:
    """一段 SSE 文本可能含多条消息；只取 `data:` 行，忽略注释（心跳）与非 JSON。"""
    events: list[dict[str, Any]] = []
    for line in chunk.split("\n"):
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def make_sse_generator_runner(factory: GeneratorFactory, *, session_factory: Callable[[], Any]) -> Runner:
    async def runner(job: AIJob) -> Optional[Any]:
        result: Optional[Any] = None
        async with session_factory() as db:
            async for chunk in factory(db):
                for event in parse_sse_chunk(chunk):
                    kind = event.get("type")
                    if kind == "progress":
                        job.publish({**event, "status": event.get("status") or "processing"})
                    elif kind in ("chunk", "content"):
                        job.publish({"type": "content", "content": event.get("content", "")})
                    elif kind == "result":
                        result = event.get("data")
                    elif kind == "error":
                        message = event.get("error") or event.get("message") or "生成失败"
                        raise SSEGeneratorError(str(message), int(event.get("code") or 500))
                    elif kind == "done":
                        continue
                    else:
                        job.publish(event)
        return result

    return runner
