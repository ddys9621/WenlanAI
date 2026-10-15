"""正文生成前的 MCP 规划：强制模型调一轮搜索工具收集背景资料，结果作为参考资料进正文提示词。

工具没触发、工具参数错误时降级为空资料（正文照常写）；其他异常抛 MCPPlanningFailedError。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.exceptions import MCPPlanningFailedError
from app.logger import get_logger
from app.services.ai_service import AIService

logger = get_logger(__name__)

MAX_REFERENCE_CHARS = 2000
_CONTEXT = "chapter_content_planning"
_INVALID_ARGUMENT_MARKERS = ("Invalid arguments", "-32602", "invalid_type")


def build_planning_prompt(title: str, genre: str, theme: str, chapter_outline: str) -> str:
    return f"""为《{title}》({genre})创作章节正文。主题：{theme[:100]}。本章纲要：{(chapter_outline or "暂无")[:300]}

请务必使用 web_search_exa 工具搜索1-2个关键背景资料，重点关注：{genre}题材的写作技巧、场景描写参考、相关专业知识。

工具调用示例：
{{
  "name": "web_search_exa",
  "arguments": {{
    "query": "{genre}小说写作技巧与场景描写"
  }}
}}

重要：必须调用工具获取最新信息，query 参数必须是具体的搜索关键词字符串（非空）。"""


def _empty_result(started: float) -> Dict[str, Any]:
    return {"reference_materials": "", "tools_used": [], "tool_calls_made": 0, "planning_time": time.time() - started}


async def plan_chapter_references(
    ai_service: AIService,
    *,
    title: str,
    genre: str,
    theme: str,
    chapter_outline: str,
    user_id: str,
    db_session,
    selected_plugins: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """返回 {reference_materials, tools_used, tool_calls_made, planning_time}；资料超过 MAX_REFERENCE_CHARS 截断。"""
    started = time.time()
    try:
        result = await ai_service.generate_text_with_mcp(
            prompt=build_planning_prompt(title, genre, theme, chapter_outline),
            user_id=user_id,
            db_session=db_session,
            enable_mcp=True,
            selected_plugins=selected_plugins,
            max_tool_rounds=1,
            tool_choice="required",
            context=_CONTEXT,
        )
    except Exception as e:
        if any(marker in str(e) for marker in _INVALID_ARGUMENT_MARKERS):
            logger.warning(f"⚠️ [MCP] 工具参数错误，降级为普通生成：{e}")
            return _empty_result(started)
        logger.error(f"❌ [MCP] 规划失败（{time.time() - started:.2f}s）：{e}")
        raise MCPPlanningFailedError(f"MCP 规划阶段失败: {e}") from e

    tool_calls_made = result.get("tool_calls_made", 0)
    if tool_calls_made == 0:
        logger.warning("⚠️ [MCP] 工具未被触发（模型不支持 Function Calling 或判断不需要工具），降级为普通生成")
        return _empty_result(started)

    references = result.get("content") or ""
    raw_chars = len(references)
    if raw_chars > MAX_REFERENCE_CHARS:
        references = references[:MAX_REFERENCE_CHARS] + "\n...(内容过长已截断)"
    tools_used = result.get("tools_used", [])
    planning_time = time.time() - started
    logger.info(
        f"[MCP] context={_CONTEXT} user_id={user_id} plugins={selected_plugins or []} tools_used={tools_used} "
        f"raw_chars={raw_chars} used_chars={len(references)} tool_calls={tool_calls_made} "
        f"planning_time={planning_time:.2f}s"
    )
    return {
        "reference_materials": references,
        "tools_used": tools_used,
        "tool_calls_made": tool_calls_made,
        "planning_time": planning_time,
    }
