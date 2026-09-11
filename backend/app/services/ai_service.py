"""AI服务封装 - 统一的OpenAI和Claude接口"""
import asyncio
import contextlib
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional, AsyncGenerator, AsyncIterator, List, Dict, Any, Awaitable, Callable
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from app.config import settings as app_settings
from app.logger import get_logger
from app.services.generation_trace import current_trace, new_call_id
import httpx
import json

logger = get_logger(__name__)


# ============================================================
# 流式响应"零正文"与 finish_reason 透传
# ----------------------------------------------------------------
# 事故（2026-09，桥段填充）：推理模型 deepseek-v4-flash 经 OpenAI 兼容网关
# 流式返回时，8000 max_tokens 全部被 reasoning_content 消耗，content 一个字
# 没出、finish_reason=length。旧实现只打 WARNING 后正常结束流，
# generate_text_stream_collect 返回 {"content": "", "finish_reason": "stream_complete"}，
# 业务层最终报出误导性的"桥段数量不符：期望 [1, 2]，LLM 返回 []"；
# 直接消费流的章节/场景生成则会把空正文当成功落库（status=completed）。
# ----------------------------------------------------------------
# 设计：
# - 流结束时若一个正文 chunk 都没有 → 抛 AIEmptyResponseError（ValueError 子类，
#   与非流式路径 "AI返回了空内容" 的 except ValueError 兼容），消息直接给出
#   可操作的诊断（推理耗尽 max_tokens → 调大 Max Tokens / 换非推理模型）
# - 有正文但被截断（length）不抛：直接消费流的调用方已把内容推给了前端；
#   通过 ContextVar 把真实 finish_reason 交给 generate_text_stream_collect，
#   由 JSON 类业务层自行判定"截断即失败"
# - 用 ContextVar 而非实例属性：模块级单例 ai_service 会被多个请求并发共用；
#   async generator 与调用方共享同一 context，流结束后调用方即可读取
# ============================================================

_last_stream_finish_reason: ContextVar[Optional[str]] = ContextVar(
    "mumu_last_stream_finish_reason", default=None
)

# 推理过程观察钩子：_generate_openai_stream 每收到 reasoning delta 就回调累计字符数。
# 只给 generate_text_stream_events 用（桥段填充 UX 的"思考中 N 字"），不传思考文本本身。
_stream_reasoning_sink: ContextVar[Optional[Callable[[int], None]]] = ContextVar(
    "mumu_stream_reasoning_sink", default=None
)


@dataclass
class StreamEvent:
    """generate_text_stream_events 的事件。kind: content / reasoning / heartbeat / done。"""
    kind: str
    text: str = ""
    reasoning_chars: int = 0
    elapsed: float = 0.0
    finish_reason: Optional[str] = None


class AIEmptyResponseError(ValueError):
    """流式响应结束时没有任何正文（content）。

    Attributes:
        finish_reason: 上游给出的完成原因（openai: stop/length…；anthropic 已归一化 max_tokens→length）
        reasoning_chars: 期间收到的思考过程字符数（reasoning_content / reasoning），0 表示未见到
    """

    def __init__(self, message: str, *, finish_reason: Optional[str], reasoning_chars: int = 0):
        super().__init__(message)
        self.finish_reason = finish_reason
        self.reasoning_chars = reasoning_chars


def _empty_stream_error(
    *, model: str, max_tokens: int, finish_reason: Optional[str], reasoning_chars: int
) -> AIEmptyResponseError:
    """把"零正文"流的现场信息翻译成用户能直接采取行动的错误。"""
    if finish_reason == "length":
        if reasoning_chars:
            message = (
                f"模型 {model} 未输出任何正文：设置中的 Max Tokens（{max_tokens}）已被思考过程"
                f"（约 {reasoning_chars} 字符）全部耗尽。请在「设置」中调大 Max Tokens，"
                f"或改用非推理模型 / 关闭该模型的思考模式后重试"
            )
        else:
            message = (
                f"模型 {model} 未输出任何正文即达到 Max Tokens 上限（{max_tokens}）。"
                f"请在「设置」中调大 Max Tokens，或检查该网关是否把推理内容放在了非标准字段"
            )
    else:
        message = f"模型 {model} 返回了空内容（finish_reason: {finish_reason}），请检查 API 配置或稍后重试"
    return AIEmptyResponseError(message, finish_reason=finish_reason, reasoning_chars=reasoning_chars)


# ============================================================
# 重试机制（T2.3，2026-05-21 加入；T2.3.2 流式扩展）
# ----------------------------------------------------------------
# 触发原因：单章 27368 tokens 长正文调用 LLM 时 httpx 抛
# RemoteProtocolError: "Server disconnected without sending a
# response"，下游章节抽取段级失败但被业务层吞掉，导致 1/3 段
# 数据静默丢失。
# ----------------------------------------------------------------
# 设计：
# - 只重试"瞬时网络错误"和"服务端 5xx / 429"
# - 4xx（参数错、API key 错、prompt too long）一律不重试
# - 指数 backoff: 1s → 2s → 4s（总等待 7s，可接受）
# - T2.3.2 流式重试关键约束：只在"尚未输出任何 chunk"时重试，
#   一旦 yield 过内容再失败必须抛出（避免消费方收到重复开头）
# - Anthropic 非流式不加（AsyncAnthropic SDK 内置 max_retries=2），
#   流式仍接入（SDK 的 retry 只覆盖建连握手）
# ============================================================

RETRIABLE_HTTPX_ERRORS: tuple = (
    httpx.RemoteProtocolError,    # Server disconnected without sending a response
    httpx.ReadTimeout,             # 读超时
    httpx.ConnectTimeout,          # 连接超时
    httpx.WriteTimeout,            # 写超时
    httpx.PoolTimeout,             # 连接池超时
    httpx.ConnectError,            # DNS / TCP 连接失败
)
RETRIABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BASE_DELAY: float = 1.0


async def _call_with_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    context: str = "LLM",
) -> Any:
    """通用 retry helper：网络瞬断 / 5xx / 429 重试，4xx 不重试。

    Args:
        coro_factory: 无参 async 函数（lambda 或 async def），每次重试时调用
            生成新的 coroutine（关键：coroutine 不能复用，所以传 factory）
        max_retries: 最大尝试次数（含首次），3 = 首次 + 重试 2 次
        base_delay: 指数 backoff 基数（秒），实际延迟 = base * 2^attempt
        context: 日志标记（用于区分不同调用源，如 "OpenAI-deepseek-v3"）

    Returns:
        coro_factory() 的返回值

    Raises:
        非可重试异常：立即抛出
        可重试异常：达到 max_retries 后抛出最后一次的异常
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except RETRIABLE_HTTPX_ERRORS as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            # 4xx 错误（参数错 / API key 错 / 超长 prompt）不重试
            if exc.response.status_code not in RETRIABLE_STATUS_CODES:
                raise
            last_exc = exc

        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "⏳ [%s] LLM 瞬时失败 (尝试 %d/%d)，%.0fs 后重试: %s: %s",
                context, attempt + 1, max_retries, delay,
                type(last_exc).__name__, last_exc,
            )
            await asyncio.sleep(delay)

    # 所有尝试都失败 → 抛出最后一次的异常
    logger.error(
        "❌ [%s] LLM 重试 %d 次仍失败: %s: %s",
        context, max_retries,
        type(last_exc).__name__ if last_exc else "Unknown",
        last_exc,
    )
    assert last_exc is not None  # 类型守护
    raise last_exc


async def _stream_with_retry(
    stream_factory: Callable[[], AsyncIterator[str]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    context: str = "LLM-Stream",
) -> AsyncIterator[str]:
    """流式 retry helper：仅在尚未输出任何 chunk 时安全重试（T2.3.2）。

    关键设计：
    - chunks_yielded == 0 时失败 → 可以安全重试（消费方还没收到任何内容）
    - chunks_yielded > 0 时失败 → 立即抛出，绝不重试
      （否则消费方会收到重复的开头部分，对 SSE / 章节生成等场景是致命的）

    Args:
        stream_factory: 无参函数，每次调用返回一个全新的 async iterator
            （关键：每次 retry 必须重新建立流，不能复用同一个 iterator）
        max_retries: 最大尝试次数（含首次），3 = 首次 + 重试 2 次
        base_delay: 指数 backoff 基数（秒），实际延迟 = base * 2^attempt
        context: 日志标记（如 "OpenAI-Stream-deepseek-v3"）

    Yields:
        从底层流转发的文本 chunk

    Raises:
        非可重试异常 / 已输出 chunk 后的任何异常 / 达到 max_retries 后的异常
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_retries):
        chunks_yielded = 0
        try:
            async for chunk in stream_factory():
                chunks_yielded += 1
                yield chunk
            # 成功完成整个流
            return
        except RETRIABLE_HTTPX_ERRORS as exc:
            last_exc = exc
            if chunks_yielded > 0:
                logger.error(
                    "❌ [%s] 流式中途断（已输出 %d chunks），不重试避免重复内容: %s: %s",
                    context, chunks_yielded, type(exc).__name__, exc,
                )
                raise
        except httpx.HTTPStatusError as exc:
            # 4xx 立即抛；5xx/429 可重试（但只在 0 chunk 时）
            if exc.response.status_code not in RETRIABLE_STATUS_CODES:
                raise
            last_exc = exc
            if chunks_yielded > 0:
                logger.error(
                    "❌ [%s] 流式中途断（已输出 %d chunks），不重试避免重复内容: HTTP %d",
                    context, chunks_yielded, exc.response.status_code,
                )
                raise

        # 仅 0 chunk 失败到这里 → 准备 backoff 重试
        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "⏳ [%s] 流式连接瞬时失败 (尝试 %d/%d, 0 chunk)，%.0fs 后重试: %s: %s",
                context, attempt + 1, max_retries, delay,
                type(last_exc).__name__, last_exc,
            )
            await asyncio.sleep(delay)

    # 所有尝试都失败 → 抛出最后一次的异常
    logger.error(
        "❌ [%s] 流式重试 %d 次仍失败: %s: %s",
        context, max_retries,
        type(last_exc).__name__ if last_exc else "Unknown",
        last_exc,
    )
    assert last_exc is not None
    raise last_exc


# ============================================================
# Provider 归一化 / OpenAI 协议兼容工具
# ============================================================

# OpenAI 官方默认 Base URL（用户未填 base_url 时手写 HTTP 路径的兜底，
# 否则会拼出 "None/chat/completions"）
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _normalize_provider(provider: Optional[str]) -> Optional[str]:
    """归一化提供商标识。

    前端提供 openai / anthropic / custom 三个选项；"custom"（以及 azure 等
    任何 OpenAI 兼容网关）统一按 OpenAI 协议处理——请求路径 /chat/completions、
    Bearer 鉴权、SSE data: 行 + [DONE] 终止，与设置页"获取模型列表"的假设一致。
    此前 custom 会导致用户 key/base_url 被丢弃、生成分发直接抛
    "不支持的AI提供商: custom"，三个选项之一整体不可用。
    """
    if provider is None:
        return None
    p = provider.strip().lower()
    if not p:
        return None
    if p in ("openai", "anthropic"):
        return p
    logger.info(f"[AIService] provider='{provider}' 按 OpenAI 兼容协议处理")
    return "openai"


def _is_max_tokens_unsupported_error(body_text: str) -> bool:
    """判定 400 是否为官方新模型的 max_tokens 参数弃用错误。

    OpenAI o 系 / 新一代模型已弃用 max_tokens，要求 max_completion_tokens，
    典型报错：Unsupported parameter: 'max_tokens' is not supported with this
    model. Use 'max_completion_tokens' instead.
    """
    b = (body_text or "").lower()
    return "max_completion_tokens" in b and (
        "unsupported" in b or "not supported" in b or "instead" in b
    )


# ============================================================
# 思考 / 推理强度（reasoning effort / extended thinking）
# ----------------------------------------------------------------
# 统一档位 → 两家协议的落地方式（权威接口，2026-09 经 context7 核对）：
# - OpenAI（/chat/completions）：请求体加 reasoning_effort，取值
#   none|minimal|low|medium|high|xhigh|max，仅推理模型（GPT-5 / o 系列）支持。
# - Anthropic（messages）：thinking={"type":"enabled","budget_tokens":N}，
#   N 必须 >=1024 且 < max_tokens，且会计入 max_tokens；启用思考时
#   temperature 必须为默认值 1（不能传自定义温度），故本模块启用时直接丢弃温度。
# 用户可在设置里选统一档位（低/中/高…），也可对 Anthropic 直接手填 budget_tokens。
# ============================================================

# OpenAI reasoning_effort 合法取值（reasoning_effort 直接透传这些字符串）
VALID_REASONING_EFFORTS: tuple[str, ...] = (
    "none", "minimal", "low", "medium", "high", "xhigh", "max",
)

# 统一档位 → Anthropic budget_tokens 的换算（会再按 max_tokens 夹取）
_REASONING_EFFORT_TO_BUDGET: Dict[str, int] = {
    "none": 1024,
    "minimal": 1024,
    "low": 4096,
    "medium": 8192,
    "high": 16384,
    "xhigh": 24576,
    "max": 32000,
}


def _normalize_reasoning_effort(effort: Optional[str]) -> str:
    """归一化思考强度档位；非法值回落 medium。"""
    e = (effort or "").strip().lower()
    return e if e in VALID_REASONING_EFFORTS else "medium"


def _resolve_thinking_budget(
    effort: Optional[str], explicit_budget: Optional[int], max_tokens: int
) -> Optional[int]:
    """把「统一档位 / 手填预算」解析成 Anthropic 合法的 budget_tokens。

    规则（对齐官方约束 budget>=1024 且 budget<max_tokens）：
    - explicit_budget（用户手填）优先，否则按档位换算
    - 下界夹到 1024
    - 上界夹到 max_tokens-1（thinking 计入 max_tokens，需给正文留出空间）
    - 若 max_tokens 太小（<=1024）无法同时满足两个约束 → 返回 None（本次不启用思考）
    """
    if explicit_budget is not None and explicit_budget > 0:
        budget = int(explicit_budget)
    else:
        budget = _REASONING_EFFORT_TO_BUDGET.get(_normalize_reasoning_effort(effort), 8192)
    budget = max(budget, 1024)
    if max_tokens and budget >= max_tokens:
        budget = max_tokens - 1
    if budget < 1024:
        return None
    return budget


async def _traced_stream(inner: AsyncIterator[str], *, model: str, prompt_chars: int) -> AsyncGenerator[str, None]:
    """给底层流套上过程追踪。

    绑定了 GenerationTrace（后台任务里）时发 llm start / thinking / streaming / done / error；
    没绑定则原样透传，零开销。reasoning 计数通过 _stream_reasoning_sink 观察钩子取得；若上层
    （generate_text_stream_events 的生产者）已设置 sink，则串联调用、不抢占。
    """
    trace = current_trace()
    if trace is None:
        async for chunk in inner:
            yield chunk
        return

    call_id = new_call_id()
    started = time.monotonic()
    content_chars = 0
    reasoning_chars = 0
    prev_sink = _stream_reasoning_sink.get()

    def _sink(total: int) -> None:
        nonlocal reasoning_chars
        reasoning_chars = total
        if prev_sink is not None:
            prev_sink(total)
        trace.llm(
            call_id, "thinking" if content_chars == 0 else "streaming", model=model,
            reasoning_chars=total, content_chars=content_chars, elapsed=time.monotonic() - started,
        )

    token = _stream_reasoning_sink.set(_sink)
    trace.llm(call_id, "start", model=model, prompt_chars=prompt_chars)
    try:
        async for chunk in inner:
            if chunk:
                content_chars += len(chunk)
                trace.llm(call_id, "streaming", model=model, reasoning_chars=reasoning_chars,
                          content_chars=content_chars, elapsed=time.monotonic() - started)
            yield chunk
        trace.llm(call_id, "done", model=model, reasoning_chars=reasoning_chars, content_chars=content_chars,
                  elapsed=time.monotonic() - started,
                  finish_reason=_last_stream_finish_reason.get() or "stream_complete")
    except asyncio.CancelledError:
        raise
    except BaseException as exc:  # noqa: BLE001 - 记录后原样抛出
        trace.llm(call_id, "error", model=model, reasoning_chars=reasoning_chars, content_chars=content_chars,
                  elapsed=time.monotonic() - started, error=str(exc))
        raise
    finally:
        try:
            _stream_reasoning_sink.reset(token)
        except ValueError:
            # 生成器在别的 Context 里被 aclose（如 GC 收尾）：token 不可用，直接恢复旧值
            _stream_reasoning_sink.set(prev_sink)


class AIService:
    """AI服务统一接口 - 支持从用户设置或全局配置初始化"""

    # 类级默认值：__init__ 会用实例值覆盖；测试里用 AIService.__new__(...) 构造的
    # "裸实例"（不走 __init__）也能安全落到"未启用思考"的默认，避免 AttributeError。
    reasoning_enabled: bool = False
    reasoning_effort: str = "medium"
    thinking_budget_tokens: Optional[int] = None

    def __init__(
        self,
        api_provider: Optional[str] = None,
        api_key: Optional[str] = None,
        api_base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
        reasoning_enabled: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        thinking_budget_tokens: Optional[int] = None,
    ):
        """
        初始化AI客户端（优化并发性能）
        
        Args:
            api_provider: API提供商 (openai/anthropic)，为None时使用全局配置
            api_key: API密钥，为None时使用全局配置
            api_base_url: API基础URL，为None时使用全局配置
            default_model: 默认模型，为None时使用全局配置
            default_temperature: 默认温度，为None时使用全局配置
            default_max_tokens: 默认最大tokens，为None时使用全局配置
            reasoning_enabled: 是否启用思考/推理，为None时使用全局配置
            reasoning_effort: 统一思考强度档位 / OpenAI reasoning_effort，为None时使用全局配置
            thinking_budget_tokens: Anthropic 思考预算，为None时按档位自动换算
        """
        # 保存用户设置或使用全局配置
        # provider 先归一化（custom 等 OpenAI 兼容标识 → "openai"），
        # 否则下方 `api_provider == "openai"` 判断会把用户 key/base_url 全部丢弃
        api_provider = _normalize_provider(api_provider)
        self.api_provider = (
            api_provider
            or _normalize_provider(app_settings.default_ai_provider)
            or "openai"
        )
        self.default_model = default_model or app_settings.default_model
        # 使用 is not None 判断，允许 temperature=0 的有效值
        self.default_temperature = default_temperature if default_temperature is not None else app_settings.default_temperature
        self.default_max_tokens = default_max_tokens if default_max_tokens is not None else app_settings.default_max_tokens

        # 思考/推理强度（全局生效）：4 个生成入口都会读取这三个字段
        self.reasoning_enabled = (
            reasoning_enabled if reasoning_enabled is not None
            else app_settings.default_reasoning_enabled
        )
        self.reasoning_effort = _normalize_reasoning_effort(
            reasoning_effort if reasoning_effort is not None
            else app_settings.default_reasoning_effort
        )
        self.thinking_budget_tokens = (
            thinking_budget_tokens if thinking_budget_tokens is not None
            else app_settings.default_thinking_budget_tokens
        )

        # 标记资源是否已关闭
        self._closed = False

        # 初始化OpenAI客户端
        openai_key = api_key if api_provider == "openai" else app_settings.openai_api_key
        if openai_key:
            try:
                limits = httpx.Limits(
                    max_keepalive_connections=50,
                    max_connections=100,
                    keepalive_expiry=30.0
                )
                
                http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=60.0, read=180.0, write=60.0, pool=60.0),
                    limits=limits,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                
                client_kwargs = {
                    "api_key": openai_key,
                    "http_client": http_client
                }
                
                base_url = api_base_url if api_provider == "openai" else app_settings.openai_base_url
                if base_url:
                    client_kwargs["base_url"] = base_url
                
                self.openai_client = AsyncOpenAI(**client_kwargs)
                self.openai_http_client = http_client
                self.openai_api_key = openai_key
                # 手写 HTTP 路径的 base：未配置时兜底官方地址（否则拼出 "None/chat/completions"），
                # 并去掉尾部斜杠避免 "…/v1//chat/completions"
                self.openai_base_url = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
                logger.info("✅ OpenAI客户端初始化成功")
            except Exception as e:
                logger.error(f"OpenAI客户端初始化失败: {e}")
                self.openai_client = None
                self.openai_http_client = None
                self.openai_api_key = None
                self.openai_base_url = None
        else:
            self.openai_client = None
            self.openai_http_client = None
            self.openai_api_key = None
            self.openai_base_url = None
            # 只有当用户明确选择OpenAI作为提供商时才警告
            if self.api_provider == "openai":
                logger.warning("⚠️ OpenAI API key未配置，但被设置为当前AI提供商")
        
        # 初始化Anthropic客户端
        self.anthropic_http_client = None
        anthropic_key = api_key if api_provider == "anthropic" else app_settings.anthropic_api_key
        if anthropic_key:
            try:
                limits = httpx.Limits(
                    max_keepalive_connections=50,
                    max_connections=100,
                    keepalive_expiry=30.0
                )
                
                http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=60.0, read=180.0, write=60.0, pool=60.0),
                    limits=limits,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                
                client_kwargs = {
                    "api_key": anthropic_key,
                    "http_client": http_client
                }
                
                base_url = api_base_url if api_provider == "anthropic" else app_settings.anthropic_base_url
                if base_url:
                    client_kwargs["base_url"] = base_url
                
                self.anthropic_client = AsyncAnthropic(**client_kwargs)
                self.anthropic_http_client = http_client
                logger.info("✅ Anthropic客户端初始化成功")
            except Exception as e:
                logger.error(f"Anthropic客户端初始化失败: {e}")
                self.anthropic_client = None
                self.anthropic_http_client = None
        else:
            self.anthropic_client = None
            # 只有当用户明确选择Anthropic作为提供商时才警告
            if self.api_provider == "anthropic":
                logger.warning("⚠️ Anthropic API key未配置，但被设置为当前AI提供商")
    
    async def generate_text(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成文本（支持工具调用）

        max_tokens 不作为参数暴露：统一取用户设置（self.default_max_tokens），调用方不得覆盖。
        
        Args:
            prompt: 用户提示词
            provider: AI提供商 (openai/anthropic)
            model: 模型名称
            temperature: 温度参数
            system_prompt: 系统提示词
            tools: 可用工具列表（MCP工具格式）
            tool_choice: 工具选择策略 (auto/required/none)
            response_format: 响应格式约束，例如 {"type": "json_object"} 强制 JSON 输出
                             （DeepSeek/Qwen/OpenAI 兼容；Anthropic 会被忽略）
            
        Returns:
            Dict包含:
            - content: 文本内容（如果没有工具调用）
            - tool_calls: 工具调用列表（如果AI决定调用工具）
            - finish_reason: 完成原因
        """
        # 调用方可能显式传 "custom"（如设置页测试连接），此处同样归一化
        provider = _normalize_provider(provider) or self.api_provider
        model = model or self.default_model
        # 使用 is not None 判断，允许 temperature=0 的有效值
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = self.default_max_tokens

        trace = current_trace()
        call_id = new_call_id() if trace is not None else ""
        started = time.monotonic()
        if trace is not None:
            trace.llm(call_id, "start", model=model, prompt_chars=len(prompt) + len(system_prompt or ""))
        try:
            if provider == "openai":
                result = await self._generate_openai_with_tools(
                    prompt, model, temperature, max_tokens, system_prompt, tools, tool_choice,
                    response_format=response_format,
                )
            elif provider == "anthropic":
                # Anthropic 不支持 response_format，需要 JSON 强制请使用 tool_use 模式
                if response_format:
                    logger.debug("Anthropic provider 忽略 response_format 参数")
                result = await self._generate_anthropic_with_tools(
                    prompt, model, temperature, max_tokens, system_prompt, tools, tool_choice
                )
            else:
                raise ValueError(f"不支持的AI提供商: {provider}")
        except Exception as exc:
            if trace is not None:
                trace.llm(call_id, "error", model=model, elapsed=time.monotonic() - started, error=str(exc))
            raise
        if trace is not None:
            trace.llm(
                call_id, "done", model=model, content_chars=len(result.get("content") or ""),
                elapsed=time.monotonic() - started, finish_reason=result.get("finish_reason"),
                tool_calls=len(result.get("tool_calls") or []),
            )
        return result
    
    async def generate_text_stream(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本

        max_tokens 不作为参数暴露：统一取用户设置（self.default_max_tokens），调用方不得覆盖。
        
        Args:
            prompt: 用户提示词
            provider: AI提供商
            model: 模型名称
            temperature: 温度参数
            system_prompt: 系统提示词
            
        Yields:
            生成的文本片段
        """
        # 同 generate_text：显式传入的 "custom" 也按 OpenAI 兼容协议归一化
        provider = _normalize_provider(provider) or self.api_provider
        model = model or self.default_model
        # 使用 is not None 判断，允许 temperature=0 的有效值
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = self.default_max_tokens

        if provider == "openai":
            inner = self._generate_openai_stream(prompt, model, temperature, max_tokens, system_prompt)
        elif provider == "anthropic":
            inner = self._generate_anthropic_stream(prompt, model, temperature, max_tokens, system_prompt)
        else:
            raise ValueError(f"不支持的AI提供商: {provider}")
        async for chunk in _traced_stream(inner, model=model, prompt_chars=len(prompt) + len(system_prompt or "")):
            yield chunk

    async def generate_text_stream_collect(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """流式生成 + 累积内容 = 一次性返完整 content（取代 generate_text 用于长 JSON 输出）。

        设计目的：
        - 中转代理网关常对非流式请求 30-60s 就 504/断连（首字节没到就掐）
        - 流式请求只要持续有 chunk 到 client，timeout 计时器就重置，可输出 10+ 分钟
        - 本方法对调用方提供与 `generate_text` 完全一致的返回格式（{"content", "finish_reason"}），
          但底层走 `generate_text_stream`，自动免疫中转代理 timeout 问题
        - 已内置 `_stream_with_retry`：未输出任何 chunk 时可安全重试，已输出后中途断直接抛
          （避免重复内容污染 JSON 解析）

        Args:
            prompt / provider / model / temperature / system_prompt: 同 generate_text
            context: 仅用于日志标记（不影响逻辑），便于排查跨调用方的流式累积日志

        Returns:
            {"content": <累积后的完整文本>, "finish_reason": <上游真实完成原因>}
            finish_reason 取 OpenAI 语义（"stop" / "length" …，anthropic 的 max_tokens 已归一化为
            "length"）；底层流未提供时退回 "stream_complete"。业务层对 JSON 输出应把
            "length" 视为失败（内容被 max_tokens 截断，json_repair 补全括号也只是残缺数据）。

        Raises:
            AIEmptyResponseError: 流结束却没有任何正文（典型：推理模型把 max_tokens 全耗在思考上）
            其余底层流式异常原样抛出；调用方应像 `generate_text` 一样捕获并处理。
        """
        label = context or f"stream-collect-{model or self.default_model}"
        accumulated_chunks: list[str] = []
        chunk_count = 0
        # 先清空，避免同一 context 内上一次调用的 finish_reason 残留到本次
        _last_stream_finish_reason.set(None)
        async for chunk in self.generate_text_stream(
            prompt=prompt,
            provider=provider,
            model=model,
            temperature=temperature,
            system_prompt=system_prompt,
        ):
            if chunk:
                accumulated_chunks.append(chunk)
                chunk_count += 1

        content = "".join(accumulated_chunks)
        finish_reason = _last_stream_finish_reason.get() or "stream_complete"
        logger.info(
            "✅ [%s] 流式累积完成: chunks=%d, content_len=%d, finish_reason=%s",
            label, chunk_count, len(content), finish_reason,
        )
        return {
            "content": content,
            "finish_reason": finish_reason,
        }

    async def generate_text_stream_events(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        *,
        heartbeat_interval: float = 1.0,
        reasoning_min_interval: float = 0.5,
    ) -> AsyncGenerator[StreamEvent, None]:
        """把底层流拆成事件：content / reasoning（节流）/ heartbeat（静默超时）/ done。

        设计：底层 generate_text_stream 在独立 Task 里跑，通过 Queue 交给消费方，
        这样推理模型思考阶段（可能 60-100s 没有任何正文）消费方仍能按节奏拿到
        reasoning 计数或 heartbeat，把"还活着"传给前端。
        - reasoning 字符数来自 _stream_reasoning_sink（生产者任务内设置，同一 context）
        - finish_reason 由生产者任务在流结束后读 _last_stream_finish_reason（子任务 context 独立，
          不能在消费方读）
        - 底层异常在消费方 re-raise；消费方提前退出 → 取消生产者
        """
        queue: asyncio.Queue = asyncio.Queue()
        started = time.monotonic()
        reasoning_total = 0
        last_reasoning_emit = float("-inf")

        def _sink(total: int) -> None:
            nonlocal reasoning_total, last_reasoning_emit
            reasoning_total = total
            now = time.monotonic()
            if now - last_reasoning_emit >= reasoning_min_interval:
                last_reasoning_emit = now
                queue.put_nowait(("reasoning", total))

        async def _producer() -> None:
            _stream_reasoning_sink.set(_sink)
            _last_stream_finish_reason.set(None)
            try:
                async for chunk in self.generate_text_stream(
                    prompt=prompt, provider=provider, model=model,
                    temperature=temperature, system_prompt=system_prompt,
                ):
                    if chunk:
                        queue.put_nowait(("content", chunk))
                queue.put_nowait(("done", _last_stream_finish_reason.get() or "stream_complete"))
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - 交给消费方 re-raise
                queue.put_nowait(("error", exc))

        task = asyncio.create_task(_producer())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    yield StreamEvent("heartbeat", reasoning_chars=reasoning_total, elapsed=time.monotonic() - started)
                    continue
                elapsed = time.monotonic() - started
                if kind == "content":
                    yield StreamEvent("content", text=payload, reasoning_chars=reasoning_total, elapsed=elapsed)
                elif kind == "reasoning":
                    yield StreamEvent("reasoning", reasoning_chars=payload, elapsed=elapsed)
                elif kind == "done":
                    yield StreamEvent("done", reasoning_chars=reasoning_total, elapsed=elapsed, finish_reason=payload)
                    return
                else:
                    raise payload
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _generate_openai_with_tools(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """使用OpenAI生成文本（支持工具调用）"""
        if not self.openai_http_client:
            raise ValueError("OpenAI客户端未初始化，请检查API key配置")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            logger.info(f"🔵 开始调用OpenAI API（支持工具调用）")
            logger.info(f"  - 模型: {model}")
            logger.info(f"  - 工具数量: {len(tools) if tools else 0}")
            
            url = f"{self.openai_base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            # 思考/推理强度：启用时透传 reasoning_effort（仅推理模型 GPT-5 / o 系列生效）
            if self.reasoning_enabled:
                payload["reasoning_effort"] = self.reasoning_effort
                logger.info(f"  - reasoning_effort: {self.reasoning_effort}")

            # 响应格式约束（DeepSeek/Qwen/OpenAI 兼容）：
            # 传 {"type": "json_object"} 后模型必返合法 JSON，大幅减少未转义引号等问题
            if response_format:
                payload["response_format"] = response_format
                logger.info(f"  - response_format: {response_format}")

            # 添加工具参数
            if tools:
                payload["tools"] = tools
                logger.info(f"  - 工具数量: {len(tools)}")
                logger.info(f"  - 工具列表: {[t.get('function', {}).get('name') for t in tools]}")
                # 调试：打印第一个工具的完整定义
                if tools:
                    logger.debug(f"  - 第一个工具定义: {tools[0]}")
                if tool_choice:
                    if tool_choice == "required":
                        payload["tool_choice"] = "required"
                        logger.info(f"  - tool_choice: required（强制调用工具）")
                    elif tool_choice == "auto":
                        payload["tool_choice"] = "auto"
                        logger.info(f"  - tool_choice: auto（AI自行决定）")
                    elif tool_choice == "none":
                        payload["tool_choice"] = "none"
                        logger.info(f"  - tool_choice: none（禁用工具）")

            # T2.3: 用 retry helper 包裹 HTTP 请求，瞬时失败自动重试 3 次
            async def _do_request():
                resp = await self.openai_http_client.post(url, headers=headers, json=payload)
                # 官方新模型弃用 max_tokens：400 时自动换 max_completion_tokens 重发一次
                if (
                    resp.status_code == 400
                    and "max_tokens" in payload
                    and _is_max_tokens_unsupported_error(resp.text)
                ):
                    payload["max_completion_tokens"] = payload.pop("max_tokens")
                    logger.warning(
                        f"⚠️ 模型 {model} 不支持 max_tokens，已自动换用 max_completion_tokens 重试"
                    )
                    resp = await self.openai_http_client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                return resp

            response = await _call_with_retry(
                _do_request, context=f"OpenAI-{model}-tools",
            )

            data = response.json()

            logger.info(f"✅ OpenAI API调用成功")
            logger.debug(f"  - 完整API响应: {data}")
            
            if not data.get('choices'):
                logger.error(f"❌ API返回的choices为空")
                logger.error(f"  - 完整响应: {data}")
                logger.error(f"  - 响应键: {list(data.keys())}")
                raise ValueError(f"API返回的响应格式错误：choices字段为空。完整响应: {data}")
            
            choice = data['choices'][0]
            message = choice.get('message', {})
            finish_reason = choice.get('finish_reason')
            
            # 检查是否有工具调用
            tool_calls = message.get('tool_calls')
            if tool_calls:
                logger.info(f"🔧 AI请求调用 {len(tool_calls)} 个工具")
                for tc in tool_calls:
                    logger.info(f"   - {tc.get('function', {}).get('name')}: {tc.get('function', {}).get('arguments', '')[:100]}")
                return {
                    "tool_calls": tool_calls,
                    "content": message.get('content', ''),
                    "finish_reason": finish_reason
                }

            # 没有工具调用，返回普通内容
            content = message.get('content', '')
            if content:
                logger.info(f"AI返回文本内容（finish_reason={finish_reason}，长度={len(content)}字符）")
                return {
                    "content": content,
                    "finish_reason": finish_reason
                }
            else:
                raise ValueError(f"AI返回了空内容（finish_reason: {finish_reason}）")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ OpenAI API调用失败 (HTTP {e.response.status_code})")
            logger.error(f"  - 错误信息: {e.response.text}")
            raise Exception(f"API返回错误 ({e.response.status_code}): {e.response.text}")
        except Exception as e:
            logger.error(f"❌ OpenAI API调用失败: {str(e)}")
            raise

    async def _generate_anthropic_with_tools(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[str, Any]:
        """使用Anthropic生成文本（支持工具调用）"""
        if not self.anthropic_client:
            raise ValueError("Anthropic客户端未初始化，请检查API key配置")
        
        try:
            logger.info(f"🔵 开始调用Anthropic API（支持工具调用）")
            logger.info(f"  - 模型: {model}")
            logger.info(f"  - 工具数量: {len(tools) if tools else 0}")
            
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            }

            # 思考模式：启用且能满足 budget 约束时加 thinking；官方要求此时 temperature 必须为默认(1)，故不再传温度
            thinking_budget = (
                _resolve_thinking_budget(self.reasoning_effort, self.thinking_budget_tokens, max_tokens)
                if self.reasoning_enabled else None
            )
            if thinking_budget is not None:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
                logger.info(f"  - thinking: enabled, budget_tokens={thinking_budget}（温度已按官方要求置默认）")
            else:
                if self.reasoning_enabled:
                    logger.warning(
                        f"⚠️ 已启用思考但 max_tokens({max_tokens}) 无法容纳 budget_tokens(>=1024)，本次跳过思考"
                    )
                kwargs["temperature"] = temperature

            if system_prompt:
                kwargs["system"] = system_prompt
            
            # 添加工具参数
            if tools:
                kwargs["tools"] = tools
                thinking_on = "thinking" in kwargs
                if tool_choice == "required":
                    if thinking_on:
                        # Anthropic 约束：扩展思考下不支持强制工具（any / 指定工具），必须 auto，
                        # 否则接口 400。此处自动降级，保证 MCP + Claude + 思考三者可共存。
                        kwargs["tool_choice"] = {"type": "auto"}
                        logger.info("  - thinking 已启用：tool_choice 由 required 降级为 auto（Anthropic 约束）")
                    else:
                        kwargs["tool_choice"] = {"type": "any"}
                elif tool_choice == "auto":
                    kwargs["tool_choice"] = {"type": "auto"}
            
            response = await self.anthropic_client.messages.create(**kwargs)
            
            # 检查是否有工具调用
            tool_calls = []
            content_text = ""
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": block.input
                        }
                    })
                elif block.type == "text":
                    content_text += block.text
            
            if tool_calls:
                logger.info(f"🔧 AI请求调用 {len(tool_calls)} 个工具")
                return {
                    "tool_calls": tool_calls,
                    "content": content_text,
                    "finish_reason": response.stop_reason
                }
            
            return {
                "content": content_text,
                "finish_reason": response.stop_reason
            }
            
        except Exception as e:
            logger.error(f"❌ Anthropic API调用失败: {str(e)}")
            raise

    async def _generate_openai_stream(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str]
    ) -> AsyncGenerator[str, None]:
        """使用OpenAI流式生成文本（T2.3.2 已接入流式 retry）"""
        if not self.openai_http_client:
            raise ValueError("OpenAI客户端未初始化，请检查API key配置")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        logger.info(f"🔵 开始调用OpenAI流式API（直接HTTP请求）")
        logger.info(f"  - 模型: {model}")
        logger.info(f"  - Prompt长度: {len(prompt)} 字符")
        logger.info(f"  - 最大tokens: {max_tokens}")

        url = f"{self.openai_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        # 思考/推理强度：启用时透传 reasoning_effort（仅推理模型 GPT-5 / o 系列生效）
        if self.reasoning_enabled:
            payload["reasoning_effort"] = self.reasoning_effort
            logger.info(f"  - reasoning_effort: {self.reasoning_effort}")

        max_tokens_swapped = False

        async def _stream_once() -> AsyncIterator[str]:
            """单次建流 + 转发 chunk 的内部生成器。每次 retry 都会重新调用。"""
            nonlocal max_tokens_swapped
            async with self.openai_http_client.stream(
                'POST', url, headers=headers, json=payload,
            ) as response:
                if response.status_code == 400 and not max_tokens_swapped and "max_tokens" in payload:
                    # 官方新模型弃用 max_tokens：读取错误体判定后换参重开一次流
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    if _is_max_tokens_unsupported_error(body):
                        max_tokens_swapped = True
                        payload["max_completion_tokens"] = payload.pop("max_tokens")
                        logger.warning(
                            f"⚠️ 模型 {model} 不支持 max_tokens，已自动换用 max_completion_tokens 重开流"
                        )
                        async for chunk in _stream_once():
                            yield chunk
                        return
                response.raise_for_status()
                logger.info(f"✅ OpenAI流式API连接成功，开始接收数据...")

                chunk_count = 0
                has_content = False
                reasoning_chars = 0
                finish_reason = None

                async for line in response.aiter_lines():
                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if not data.get('choices'):
                        continue
                    choice = data['choices'][0]
                    delta = choice.get('delta', {})
                    finish_reason = choice.get('finish_reason') or finish_reason

                    # 推理模型：只取 content，思考过程不进正文（仅统计长度用于诊断 / UX 计数）。
                    # DeepSeek/SiliconFlow/火山用 reasoning_content，OpenRouter 用 reasoning
                    reasoning_delta = len(delta.get('reasoning_content') or '') + len(delta.get('reasoning') or '')
                    if reasoning_delta:
                        reasoning_chars += reasoning_delta
                        sink = _stream_reasoning_sink.get()
                        if sink is not None:
                            sink(reasoning_chars)
                    content = delta.get('content', '')
                    if content:
                        chunk_count += 1
                        has_content = True
                        yield content

                _last_stream_finish_reason.set(finish_reason)

                if not has_content:
                    err = _empty_stream_error(
                        model=model, max_tokens=max_tokens,
                        finish_reason=finish_reason, reasoning_chars=reasoning_chars,
                    )
                    logger.error(f"❌ 流式响应未返回任何正文: {err}")
                    raise err

                if finish_reason == 'length':
                    logger.warning(
                        f"⚠️  流式输出达到 max_tokens 上限被截断（设置中的 Max Tokens = {max_tokens}），"
                        f"如需更长输出请在设置中调大"
                    )

                logger.info(
                    f"✅ OpenAI流式生成完成，共接收 {chunk_count} 个chunk，完成原因: {finish_reason}"
                )

        try:
            async for chunk in _stream_with_retry(
                _stream_once, context=f"OpenAI-Stream-{model}",
            ):
                yield chunk
        except httpx.TimeoutException as e:
            logger.error(f"❌ OpenAI流式API超时")
            logger.error(f"  - 错误: {str(e)}")
            logger.error(f"  - 提示: 请检查网络连接或考虑缩短prompt长度")
            raise TimeoutError(f"AI服务超时（180秒），请稍后重试或减少上下文长度") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ OpenAI流式API调用失败 (HTTP {e.response.status_code})")
            try:
                body_preview = await e.response.aread()
            except Exception:
                body_preview = b"(unable to read body)"
            logger.error(f"  - 错误信息: {body_preview}")
            raise
        except Exception as e:
            logger.error(f"❌ OpenAI流式API调用失败: {str(e)}")
            logger.error(f"  - 错误类型: {type(e).__name__}")
            raise
    
    async def _generate_anthropic_stream(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str]
    ) -> AsyncGenerator[str, None]:
        """使用Anthropic流式生成文本（T2.3.2 已接入流式 retry）"""
        if not self.anthropic_client:
            raise ValueError("Anthropic客户端未初始化，请检查API key配置")

        logger.info(f"🔵 开始调用Anthropic流式API")
        logger.info(f"  - 模型: {model}")
        logger.info(f"  - Prompt长度: {len(prompt)} 字符")
        logger.info(f"  - 最大tokens: {max_tokens}")

        stream_kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        # 思考模式：启用且能满足 budget 约束时加 thinking；官方要求此时 temperature 必须为默认(1)，故不再传温度
        thinking_budget = (
            _resolve_thinking_budget(self.reasoning_effort, self.thinking_budget_tokens, max_tokens)
            if self.reasoning_enabled else None
        )
        if thinking_budget is not None:
            stream_kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            logger.info(f"  - thinking: enabled, budget_tokens={thinking_budget}（温度已按官方要求置默认）")
        else:
            if self.reasoning_enabled:
                logger.warning(
                    f"⚠️ 已启用思考但 max_tokens({max_tokens}) 无法容纳 budget_tokens(>=1024)，本次跳过思考"
                )
            stream_kwargs["temperature"] = temperature

        # 官方语义：system 可省略；不要传空串占位
        if system_prompt:
            stream_kwargs["system"] = system_prompt

        async def _stream_once() -> AsyncIterator[str]:
            """单次建流 + 转发 chunk 的内部生成器。每次 retry 都会重新调用。"""
            async with self.anthropic_client.messages.stream(**stream_kwargs) as stream:
                logger.info(f"✅ Anthropic流式API连接成功，开始接收数据...")
                chunk_count = 0
                async for text in stream.text_stream:
                    chunk_count += 1
                    yield text

                # 归一化到 OpenAI 语义：max_tokens → length，其余（end_turn/stop_sequence…）原样
                try:
                    stop_reason = (await stream.get_final_message()).stop_reason
                except Exception:  # 网关连 message_start 都没回时 SDK 断言失败：拿不到 stop_reason 不影响后续判定
                    stop_reason = None
                finish_reason = "length" if stop_reason == "max_tokens" else stop_reason
                _last_stream_finish_reason.set(finish_reason)

                if chunk_count == 0:
                    err = _empty_stream_error(
                        model=model, max_tokens=max_tokens, finish_reason=finish_reason, reasoning_chars=0,
                    )
                    logger.error(f"❌ Anthropic流式响应未返回任何正文: {err}")
                    raise err
                logger.info(f"✅ Anthropic流式生成完成，共接收 {chunk_count} 个chunk，完成原因: {finish_reason}")

        try:
            async for chunk in _stream_with_retry(
                _stream_once, context=f"Anthropic-Stream-{model}",
            ):
                yield chunk
        except httpx.TimeoutException as e:
            logger.error(f"❌ Anthropic流式API超时")
            logger.error(f"  - 错误: {str(e)}")
            raise TimeoutError(f"AI服务超时（180秒），请稍后重试或减少上下文长度") from e
        except Exception as e:
            logger.error(f"❌ Anthropic流式API调用失败: {str(e)}")
            logger.error(f"  - 错误类型: {type(e).__name__}")
            raise
    
    async def generate_text_with_mcp(
        self,
        prompt: str,
        user_id: str,
        db_session,
        enable_mcp: bool = True,
        selected_plugins: Optional[List[str]] = None,
        max_tool_rounds: int = 3,
        tool_choice: str = "auto",
        context: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        context_prefix = f"[{context}] " if context else ""
        logger.info(f"{context_prefix}generate_text_with_mcp 开始调用: tool_choice={tool_choice}, enable_mcp={enable_mcp}")
        """
        支持MCP工具的AI文本生成（非流式）
        
        Args:
            prompt: 用户提示词
            user_id: 用户ID，用于获取MCP工具
            db_session: 数据库会话
            enable_mcp: 是否启用MCP增强
            selected_plugins: 指定使用的插件名称列表
            max_tool_rounds: 最大工具调用轮次
            tool_choice: 工具选择策略（auto/required/none）
            context: 调用上下文标识（用于日志标记）
            **kwargs: 其他AI参数（provider, model, temperature等）
        
        Returns:
            {
                "content": "AI生成的最终文本",
                "tool_calls_made": 2,  # 实际调用的工具次数
                "tools_used": ["exa_search", "filesystem_read"],
                "finish_reason": "stop",
                "mcp_enhanced": True
            }
        """
        from app.services.mcp_tool_service import mcp_tool_service, MCPToolServiceError
        
        # 初始化返回结果
        result = {
            "content": "",
            "tool_calls_made": 0,
            "tools_used": [],
            "finish_reason": "",
            "mcp_enhanced": False
        }
        
        # 1. 获取MCP工具（如果启用）
        tools = None
        if enable_mcp:
            try:
                tools = await mcp_tool_service.get_user_enabled_tools(
                    user_id=user_id,
                    db_session=db_session,
                    plugin_names=selected_plugins
                )
                if tools:
                    context_prefix = f"[{context}] " if context else ""
                    logger.info(f"{context_prefix}MCP增强: 加载了 {len(tools)} 个工具")
                    result["mcp_enhanced"] = True
            except MCPToolServiceError as e:
                logger.error(f"获取MCP工具失败，降级为普通生成: {e}")
                tools = None
        
        # 2. 工具调用循环
        conversation_history = [
            {"role": "user", "content": prompt}
        ]
        
        for round_num in range(max_tool_rounds):
            context_prefix = f"[{context}] " if context else ""
            logger.info(f"{context_prefix}MCP工具调用轮次: {round_num + 1}/{max_tool_rounds}")
            
            # 调试日志
            if round_num == 0:
                logger.info(f"{context_prefix}工具数量: {len(tools) if tools else 0}")
                logger.info(f"{context_prefix}tool_choice: {tool_choice}")
            
            # 调用AI
            ai_response = await self.generate_text(
                prompt=conversation_history[-1]["content"],
                tools=tools if round_num == 0 else None,  # 只在第一轮传递工具
                tool_choice=tool_choice if round_num == 0 else None,
                **kwargs
            )
            
            # 检查是否有工具调用
            tool_calls = ai_response.get("tool_calls", [])
            context_prefix = f"[{context}] " if context else ""
            logger.info(f"{context_prefix}AI响应检查: tool_calls数量={len(tool_calls)}, finish_reason={ai_response.get('finish_reason', 'unknown')}")
            
            if not tool_calls:
                # AI返回最终内容
                if round_num == 0 and tool_choice == "required":
                    # 第一轮强制工具调用失败
                    logger.warning(f"{context_prefix}⚠️ 第一轮强制工具调用失败！AI未调用工具，直接返回内容")
                    logger.warning(f"{context_prefix}   finish_reason={ai_response.get('finish_reason')}")
                    logger.warning(f"{context_prefix}   内容预览: {ai_response.get('content', '')[:200]}")
                else:
                    # 后续轮次正常返回最终内容
                    logger.info(f"{context_prefix}AI完成任务，返回最终内容（长度：{len(ai_response.get('content', ''))} 字符）")

                result["content"] = ai_response.get("content", "")
                result["finish_reason"] = ai_response.get("finish_reason", "stop")
                break
            
            # 3. 执行工具调用
            logger.info(f"AI请求调用 {len(tool_calls)} 个工具")
            
            try:
                tool_results = await mcp_tool_service.execute_tool_calls(
                    user_id=user_id,
                    tool_calls=tool_calls,
                    db_session=db_session
                )
                
                # 记录使用的工具
                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    if tool_name not in result["tools_used"]:
                        result["tools_used"].append(tool_name)
                
                result["tool_calls_made"] += len(tool_calls)
                
                # 4. 构建工具上下文
                tool_context = await mcp_tool_service.build_tool_context(
                    tool_results,
                    format="markdown"
                )
                
                # 5. 更新对话历史
                conversation_history.append({
                    "role": "assistant",
                    "content": ai_response.get("content", ""),
                    "tool_calls": tool_calls
                })
                
                for tool_result in tool_results:
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_result["tool_call_id"],
                        "content": tool_result["content"]
                    })
                
                # 6. 构建下一轮提示
                next_prompt = (
                    f"{prompt}\n\n"
                    f"{tool_context}\n\n"
                    f"请基于以上工具查询结果，继续完成任务。"
                )
                conversation_history.append({
                    "role": "user",
                    "content": next_prompt
                })
                
            except Exception as e:
                logger.error(f"执行MCP工具失败: {e}", exc_info=True)
                # 降级：返回当前AI响应
                result["content"] = ai_response.get("content", "")
                result["finish_reason"] = "tool_error"
                break
        
        else:
            # 达到最大轮次
            logger.warning(f"达到MCP最大调用轮次 {max_tool_rounds}")
            result["content"] = conversation_history[-1].get("content", "")
            result["finish_reason"] = "max_rounds"
        
        return result

    async def close(self):
        """关闭所有HTTP客户端连接，释放资源

        应在应用关闭时调用此方法，防止HTTP连接泄漏
        """
        if self._closed:
            return

        self._closed = True

        if self.openai_http_client:
            try:
                await self.openai_http_client.aclose()
                logger.info("✅ OpenAI HTTP客户端已关闭")
            except Exception as e:
                logger.error(f"关闭OpenAI HTTP客户端失败: {e}")

        if self.anthropic_http_client:
            try:
                await self.anthropic_http_client.aclose()
                logger.info("✅ Anthropic HTTP客户端已关闭")
            except Exception as e:
                logger.error(f"关闭Anthropic HTTP客户端失败: {e}")


# 创建全局AI服务实例
ai_service = AIService()


def create_user_ai_service(
    api_provider: str,
    api_key: str,
    api_base_url: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    reasoning_enabled: Optional[bool] = None,
    reasoning_effort: Optional[str] = None,
    thinking_budget_tokens: Optional[int] = None,
) -> AIService:
    """
    根据用户设置创建AI服务实例
    
    Args:
        api_provider: API提供商
        api_key: API密钥
        api_base_url: API基础URL
        model_name: 模型名称
        temperature: 温度参数
        max_tokens: 最大tokens
        reasoning_enabled: 是否启用思考/推理（全局生效）
        reasoning_effort: 统一思考强度档位 / OpenAI reasoning_effort
        thinking_budget_tokens: Anthropic 思考预算（空=按档位自动换算）
        
    Returns:
        AIService实例
    """
    return AIService(
        api_provider=api_provider,
        api_key=api_key,
        api_base_url=api_base_url,
        default_model=model_name,
        default_temperature=temperature,
        default_max_tokens=max_tokens,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        thinking_budget_tokens=thinking_budget_tokens,
    )
