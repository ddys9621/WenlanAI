"""拆书 LLM 调用的失败分类与重试节奏。

一本书要调几十到几百次模型，失败按性质分开处理，不再一律「拆半 / 判失败」：
- fatal：鉴权失败 / 余额不足 / 模型不存在 / 地址被出站守卫拦下 / 客户端没配好 —— 重试只会继续失败，
  立即中止整个任务（已抽的拆书卡保留，修好后「继续抽取」）。以前会被当成可拆分的错误，每批 N 章打出 2N-1 次必败请求
- rate_limited：429 —— 按 Retry-After（没有就按 RATE_LIMIT_DELAYS）等一会儿原样重试，不拆半（拆半只会让请求更多）
- context_overflow：输入超出模型上下文 —— 多章批拆半；单章无解
- rejected：其余 4xx（多半是内容被接口安全审核拒绝）—— 多章批拆半找出那一章，单章不重试
- truncated：推理把 Max Tokens 耗光、一个字没出 —— 多章批拆半，单章换精简要求再试
- network：断流 / 超时 / 5xx / 网关瞬时错误 / 零正文被掐断 —— 原样重试
- unknown：其它异常 —— 保持老行为（不额外重试）
ai_service 的流式重试只在「还没收到任何内容」时重开，中途断流、坏 JSON 都要在这一层兜住。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

import httpx

logger = logging.getLogger(__name__)
T = TypeVar("T")

# 网络类失败的重试间隔（秒）
NETWORK_RETRY_DELAYS: tuple[float, ...] = (5.0, 15.0)
# 限流等待（秒）：没有 Retry-After 时按顺序用；都用完仍限流就交给调用方
RATE_LIMIT_DELAYS: tuple[float, ...] = (20.0, 40.0, 60.0)
RETRY_AFTER_CAP = 120.0

_AUTH_HINTS = ("invalid api key", "invalid_api_key", "incorrect api key", "api key not valid", "invalid token",
               "unauthorized", "无效的令牌", "令牌无效", "api key 无效")
_BALANCE_HINTS = ("insufficient_quota", "insufficient quota", "insufficient balance", "insufficient_balance",
                  "exceeded your current quota", "quota exceeded", "余额不足", "欠费", "额度不足", "额度已用尽")
_MODEL_HINTS = ("model_not_found", "model not found", "does not exist", "no such model", "unknown model",
                "invalid model", "模型不存在")
_CONTEXT_HINTS = ("context length", "context_length", "maximum context", "context window", "too many tokens",
                  "prompt is too long", "input is too long", "reduce the length", "超出上下文", "上下文长度", "超过最大长度")
_RATE_HINTS = ("rate limit", "rate_limit", "ratelimit", "too many requests", "请求过于频繁", "限流", "访问频率")
_CONTENT_HINTS = ("inappropriate", "content_filter", "content filter", "content policy", "content management",
                  "moderation", "sensitive", "data_inspection", "responsibleai", "safety", "violat",
                  "敏感", "审核", "违规", "不合规")
_NETWORK_CLASS_NAMES = ("APIConnectionError", "APITimeoutError")


class ExtractionAborted(RuntimeError):
    """流水线中止：任务已（或将）落 failed，抛给 ai_jobs 标失败。"""


class ExtractionFatal(ExtractionAborted):
    """重试也没用的失败（鉴权 / 余额 / 模型 / 持续限流 / 连续失败熔断）：中止整个任务，已抽的拆书卡保留，可继续抽取。"""


@dataclass(frozen=True)
class LLMFailure:
    kind: str                       # fatal / rate_limited / context_overflow / rejected / truncated / network / unknown
    reason: str                     # 给作者看的人话
    retry_after: Optional[float] = None


def _status_of(exc: BaseException) -> Optional[int]:
    for candidate in (getattr(exc, "status_code", None), getattr(getattr(exc, "response", None), "status_code", None)):
        if isinstance(candidate, int) and 100 <= candidate <= 599:
            return candidate
    return None


def _response_text(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        return str(response.text or "")[:2000]
    except Exception:  # noqa: BLE001 - 流式响应没读完时 .text 会抛
        return ""


def _detail(exc: BaseException) -> str:
    """优先取响应体里 OpenAI 风格的 error.message，其次异常文本；压成一行。"""
    body = _response_text(exc).strip()
    if body.startswith("{"):
        try:
            data = json.loads(body)
            err = data.get("error") if isinstance(data, dict) else None
            message = err.get("message") if isinstance(err, dict) else err
            if message:
                body = str(message)
        except (ValueError, AttributeError):
            pass
    text = " ".join((body or str(exc) or type(exc).__name__).split())
    return text[:160]


def _retry_after(exc: BaseException) -> Optional[float]:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        value = float(headers.get("retry-after")) if headers is not None else None
    except (TypeError, ValueError):
        return None
    return None if value is None else max(0.0, min(value, RETRY_AFTER_CAP))


def _has(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def classify_llm_error(exc: BaseException) -> LLMFailure:
    from app.services.ai_service import AIEmptyResponseError
    from app.utils.outbound_guard import OutboundBlockedError

    if isinstance(exc, OutboundBlockedError):
        return LLMFailure("fatal", f"AI 接口地址被出站地址守卫拦下：{_detail(exc)}")
    if isinstance(exc, ValueError) and "未初始化" in str(exc):
        return LLMFailure("fatal", "AI 客户端没配好：请在「设置」里填写 API Key 和接口地址")

    status = _status_of(exc)
    text = f"{exc} {_response_text(exc)}".lower()
    http = f"（HTTP {status}）" if status else ""
    detail = _detail(exc)

    if _has(text, _BALANCE_HINTS) or status == 402:
        return LLMFailure("fatal", f"AI 接口余额或额度不足{http}：充值或换个接口后再继续")
    if (status in (401, 403) and not _has(text, _CONTENT_HINTS)) or (status is None and _has(text, _AUTH_HINTS)):
        return LLMFailure("fatal", f"AI 接口鉴权失败{http}：请检查「设置」里的 API Key 和接口地址")
    if status == 404 or (status in (None, 400) and _has(text, _MODEL_HINTS)):
        return LLMFailure("fatal", f"模型不存在或当前 Key 无权使用{http}：请检查「设置」里的模型名和接口地址")
    if status == 429 or _has(text, _RATE_HINTS):
        return LLMFailure("rate_limited", f"AI 接口限流{http}：{detail}", _retry_after(exc))
    if isinstance(exc, (httpx.TransportError, TimeoutError, asyncio.TimeoutError)) or type(exc).__name__ in _NETWORK_CLASS_NAMES:
        return LLMFailure("network", f"网络或接口暂时出错：{detail}")
    if status in (None, 400, 413, 422) and _has(text, _CONTEXT_HINTS):
        return LLMFailure("context_overflow", f"输入超出模型上下文{http}：{detail}")
    if status is not None and 400 <= status < 500:
        if _has(text, _CONTENT_HINTS):
            return LLMFailure("rejected", f"内容被接口安全审核拒绝{http}：{detail}")
        return LLMFailure("rejected", f"请求被接口拒绝{http}：{detail}")
    if status is not None and status >= 500:
        return LLMFailure("network", f"接口暂时出错{http}：{detail}")
    if isinstance(exc, AIEmptyResponseError) and exc.finish_reason == "length":
        return LLMFailure("truncated", f"模型没有输出正文就用完了 Max Tokens：{detail}")
    if status is None and _has(text, _CONTENT_HINTS):
        return LLMFailure("rejected", f"内容被接口安全审核拒绝：{detail}")
    if isinstance(exc, ValueError) and getattr(exc, "retriable", None) is not None:
        return LLMFailure("network", f"模型返回异常：{detail}")
    return LLMFailure("unknown", f"{type(exc).__name__}: {detail}")


async def pause(seconds: float) -> None:
    """重试前等待；单测打桩成不等。"""
    await asyncio.sleep(seconds)


async def call_with_retry(fn: Callable[[], Awaitable[T]], *, label: str) -> T:
    """网络类失败按 NETWORK_RETRY_DELAYS 重试、限流按 Retry-After / RATE_LIMIT_DELAYS 等待重试；
    致命错误抛 ExtractionFatal 中止任务；其余失败（和重试用完的）原样抛给调用方按老规矩降级。"""
    network_tries = rate_tries = 0
    while True:
        try:
            return await fn()
        except ExtractionAborted:
            raise
        except Exception as exc:
            failure = classify_llm_error(exc)
            if failure.kind == "fatal":
                raise ExtractionFatal(failure.reason) from exc
            if failure.kind == "network" and network_tries < len(NETWORK_RETRY_DELAYS):
                delay = NETWORK_RETRY_DELAYS[network_tries]
                network_tries += 1
            elif failure.kind == "rate_limited" and rate_tries < len(RATE_LIMIT_DELAYS):
                delay = failure.retry_after if failure.retry_after is not None else RATE_LIMIT_DELAYS[rate_tries]
                rate_tries += 1
            else:
                raise
            logger.warning("%s %s；%.0f 秒后重试", label, failure.reason, delay)
            await pause(delay)
