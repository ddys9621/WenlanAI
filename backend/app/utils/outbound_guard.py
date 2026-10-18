"""出站地址守卫（防 SSRF）：普通用户自填的 AI 接口地址、MCP 服务器地址只能连公网。

多用户部署时，任何登录用户都能填一个 base_url / server_url 让服务器替他发请求；不加限制就能借服务器
访问本机 127.0.0.1 上的其他服务、内网机器和云厂商元数据地址（169.254.169.254、100.100.100.200 …）。

- 管理员不受限：桌面版、单机自用登录的都是管理员，本机 Ollama / LM Studio / 本地 MCP 照常用
- 运维配置的地址放行：.env 里的 OPENAI / ANTHROPIC / GEMINI_BASE_URL（新用户的默认接口就是它）与 OUTBOUND_ALLOWED_HOSTS
- 真正的拦截在建 TCP 连接时：解析出的每个 IP 都得是公网地址，然后直连这个校验过的 IP——DNS 重绑定、
  跳转到内网的新连接一样被拦；走 HTTP(S)_PROXY 的请求由代理去连目标，只能在发请求前解析校验
- 保存设置时另做不查 DNS 的快速检查（IP 字面量、localhost），让作者当场看到原因
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import anyio
import httpcore
import httpx

from app.config import settings as app_settings
from app.logger import get_logger
from app.user_manager import user_manager

logger = get_logger(__name__)

_DEFAULT_PORTS = {"http": 80, "https": 443}
_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

AllowEntry = tuple[str, Optional[int]]  # (host, port)；port 为 None = 任意端口


class OutboundBlockedError(httpx.TransportError):
    """目标指向本机、内网或保留地址。

    继承 TransportError：现有的 `except httpx.RequestError` 照常接住；不在 ai_service 的可重试错误里（重试也一样）。
    """

    def __init__(self, host: str):
        self.host = host
        super().__init__(
            f"地址「{host}」指向本机、内网或保留地址，多用户部署下普通用户不能使用（防止服务器被借去访问内网）。"
            "请改用公网可访问的地址；确需使用内网服务请联系管理员。"
        )


def _literal_ip(host: str) -> Optional[str]:
    """IP 字面量（含 127.1、2130706433、0x7f.1 这类 getaddrinfo 也认的老式写法）→ 规范写法；不是 IP 返回 None。"""
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        pass
    if host and any(c.isdigit() for c in host) and all(c in "0123456789abcdefx." for c in host):
        try:
            return socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _normalize_host(value: str) -> str:
    host = value.strip().strip("[]").rstrip(".").lower()
    return _literal_ip(host) or host


def is_public_ip(value: str) -> bool:
    """公网单播地址才算数；IPv4 映射（::ffff:a.b.c.d）与 NAT64（64:ff9b::/96）按里面的 IPv4 判断。"""
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return is_public_ip(str(embedded))
    return ip.is_global and not ip.is_multicast


def _target(url: Optional[str]) -> Optional[tuple[str, int]]:
    """http(s) 地址的 (host, port)；空串、解析不了、不是 http(s) 的返回 None（这些本来就发不出请求）。"""
    text = (url or "").strip()
    if not text:
        return None
    try:
        parsed = httpx.URL(text)
    except (httpx.InvalidURL, TypeError, ValueError):
        return None
    if parsed.scheme not in _DEFAULT_PORTS or not parsed.host:
        return None
    return parsed.host, parsed.port or _DEFAULT_PORTS[parsed.scheme]


def _allow_entry(text: str) -> Optional[AllowEntry]:
    """白名单一项：host（任意端口）/ host:port / [v6]:port / 带协议的完整地址（没写端口取协议默认端口）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    if "://" in raw:
        target = _target(raw)
        return (_normalize_host(target[0]), target[1]) if target else None
    if raw.startswith("["):
        host, _, rest = raw[1:].partition("]")
        port_text = rest[1:] if rest.startswith(":") else ""
    elif raw.count(":") == 1:
        host, _, port_text = raw.partition(":")
    else:  # 纯主机名或不带方括号的 IPv6
        host, port_text = raw, ""
    if not host.strip() or (port_text and not port_text.isdigit()):
        logger.warning(f"出站白名单里的条目无效，已忽略: {text!r}")
        return None
    return _normalize_host(host), int(port_text) if port_text else None


def parse_allowed_hosts(entries: Iterable[str]) -> frozenset[AllowEntry]:
    return frozenset(entry for entry in map(_allow_entry, entries or ()) if entry)


async def _resolve(host: str, port: int) -> list[str]:
    """DNS 解析（测试里替换它）：去重后的地址，保持系统给的优先顺序。"""
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


@dataclass(frozen=True)
class OutboundGuard:
    """一个普通用户请求的出站策略：只放行公网地址与白名单。"""

    allowed: frozenset[AllowEntry] = frozenset()

    def allows(self, host: str, port: Optional[int]) -> bool:
        key = _normalize_host(host)
        return (key, None) in self.allowed or (port is not None and (key, port) in self.allowed)

    def check_static(self, url: Optional[str]) -> None:
        """保存设置时的快速检查（不查 DNS）：只认得出 IP 字面量与 localhost；域名解析到内网的留给建连时拦。"""
        target = _target(url)
        if target is None or self.allows(*target):
            return
        host = _normalize_host(target[0])
        ip = _literal_ip(host)
        if host in _LOCAL_NAMES or host.endswith(".localhost") or (ip is not None and not is_public_ip(ip)):
            raise OutboundBlockedError(target[0])

    async def public_addresses(self, host: str, port: int) -> list[str]:
        """解析出的地址必须全是公网地址（有一个不是就整体拒绝），返回校验过的地址；解析失败抛 OSError。"""
        addresses = await _resolve(host, port)
        if not addresses or not all(is_public_ip(address) for address in addresses):
            raise OutboundBlockedError(host)
        return addresses

    async def precheck(self, url: str) -> None:
        """建连前的完整检查（静态 + DNS），用于给出清楚的报错；解析失败不算拦截，交给真正的连接去报错。"""
        self.check_static(url)
        target = _target(url)
        if target is None or self.allows(*target):
            return
        try:
            await self.public_addresses(*target)
        except OSError:
            return


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    """httpcore 网络后端：每个新 TCP 连接先解析校验，再直连校验过的 IP（TLS 的 SNI / 证书校验仍按原域名）。"""

    def __init__(self, guard: OutboundGuard, inner: Optional[httpcore.AsyncNetworkBackend] = None):
        self._guard = guard
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        targets = [host]
        if not self._guard.allows(host, port):
            try:
                with anyio.fail_after(timeout):
                    targets = await self._guard.public_addresses(host, port)
            except TimeoutError as exc:  # TimeoutError 也是 OSError，先接
                raise httpcore.ConnectTimeout(f"DNS 解析超时: {host}") from exc
            except OSError as exc:  # 解析失败保持 httpcore 的 ConnectError：调用方原有的重试 / 报错不变
                raise httpcore.ConnectError(str(exc)) from exc
        error: Optional[Exception] = None
        for target in targets:
            try:
                return await self._inner.connect_tcp(
                    target, port, timeout=timeout, local_address=local_address, socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise OutboundBlockedError(path)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _GuardedTransport(httpx.AsyncHTTPTransport):
    """直连目标：httpx 默认 transport，只把连接池的网络后端换成守卫过的。

    httpx 没有公开 network_backend 参数，这里替换内部的 _pool（handle_async_request / aclose 都只用它）；
    升级 httpx 后要跑 tests/test_outbound_guard.py 回归。
    """

    def __init__(self, guard: OutboundGuard, *, limits: httpx.Limits, trust_env: bool):
        ssl_context = httpx.create_ssl_context(trust_env=trust_env)
        super().__init__(verify=ssl_context, limits=limits, trust_env=trust_env)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=GuardedNetworkBackend(guard),
        )


class _ProxyPreflightTransport(httpx.AsyncBaseTransport):
    """经 HTTP(S)_PROXY 的请求：目标由代理去连，只能发请求前在本机解析校验（这条路上防不住 DNS 重绑定）。"""

    def __init__(self, guard: OutboundGuard, inner: httpx.AsyncBaseTransport):
        self._guard = guard
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, port = request.url.host, request.url.port or _DEFAULT_PORTS.get(request.url.scheme, 80)
        if not self._guard.allows(host, port):
            try:
                await self._guard.public_addresses(host, port)
            except OSError as exc:  # 本机解析不了就校验不了，不交给代理
                raise httpx.ConnectError(str(exc), request=request) from exc
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _environment_proxies() -> dict[str, Optional[str]]:
    """与 httpx.AsyncClient(trust_env=True) 默认读取的代理一致（传了自定义 transport 后 httpx 不再自己读）。"""
    from httpx._utils import get_environment_proxies

    return get_environment_proxies()


def guarded_async_client(
    guard: OutboundGuard, *, limits: httpx.Limits = _DEFAULT_LIMITS, trust_env: bool = True, **kwargs: Any,
) -> httpx.AsyncClient:
    """用法同 httpx.AsyncClient(**kwargs)，但每个新连接都过守卫；HTTP(S)_PROXY / NO_PROXY 照旧生效。"""
    mounts: dict[str, Optional[httpx.AsyncBaseTransport]] = {}
    if trust_env:
        for pattern, proxy in _environment_proxies().items():
            mounts[pattern] = None if proxy is None else _ProxyPreflightTransport(
                guard, httpx.AsyncHTTPTransport(proxy=proxy, limits=limits, trust_env=trust_env),
            )
    return httpx.AsyncClient(
        transport=_GuardedTransport(guard, limits=limits, trust_env=trust_env),
        mounts=mounts,
        trust_env=trust_env,
        **kwargs,
    )


def mcp_http_client_factory(guard: OutboundGuard):
    """MCP SDK 的 httpx_client_factory；默认值与 mcp.shared._httpx_utils.create_mcp_http_client 一致。"""

    def factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        return guarded_async_client(
            guard,
            follow_redirects=True,
            timeout=timeout if timeout is not None else httpx.Timeout(30.0),
            headers=headers,
            auth=auth,
        )

    return factory


def blocked_cause(exc: Optional[BaseException]) -> Optional[OutboundBlockedError]:
    """SDK 会把底层异常包成自己的 APIConnectionError("Connection error.")：顺着异常链找回守卫给的原因。"""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, OutboundBlockedError):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def _configured_allowlist() -> frozenset[AllowEntry]:
    """运维自己配的地址：.env 里的三个 AI 接口（新用户的默认接口就是它）+ OUTBOUND_ALLOWED_HOSTS。"""
    base_urls = [app_settings.openai_base_url, app_settings.anthropic_base_url, app_settings.gemini_base_url]
    return parse_allowed_hosts([url for url in base_urls if url] + list(app_settings.outbound_allowed_hosts or []))


def outbound_guard_for(user: Any) -> Optional[OutboundGuard]:
    """当前用户的出站守卫；守卫关闭或管理员返回 None（不限制）。拿不到用户信息按普通用户处理。"""
    if not app_settings.outbound_guard_enabled or getattr(user, "is_admin", False) is True:
        return None
    return OutboundGuard(allowed=_configured_allowlist())


async def outbound_guard_for_user_id(user_id: Optional[str]) -> Optional[OutboundGuard]:
    """只有 user_id 时（MCP 注册表加载插件）查一次用户；查不到或查询出错一律按普通用户处理。"""
    if not app_settings.outbound_guard_enabled:
        return None
    user = None
    if user_id:
        try:
            user = await user_manager.get_user(user_id)
        except Exception as exc:  # noqa: BLE001 - 查不到就按普通用户收紧，不能放行
            logger.warning(f"出站守卫查询用户 {user_id} 失败，按普通用户处理: {exc}")
    return outbound_guard_for(user)
