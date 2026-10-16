"""Linux.do OAuth2 客户端（授权码模式）。凭据由管理员后台配置、按请求从 AuthSettings 构造，不读 .env。"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.logger import get_logger

logger = get_logger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class LinuxDOOAuthService:
    """Linux.do Connect 的三步：授权地址 → code 换 token → token 拉用户信息"""

    AUTHORIZE_URL = "https://connect.linux.do/oauth2/authorize"
    API_BASES = ("https://connect.linuxdo.org", "https://connect.linux.do")
    TOKEN_PATH = "/oauth2/token"
    USERINFO_PATH = "/api/user"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout: float = 15.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.timeout = timeout
        self._transport = transport  # 测试注入 MockTransport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, transport=self._transport)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with self._client() as client:
            for base in self.API_BASES[:-1]:
                try:
                    return await client.request(method, base + path, **kwargs)
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    logger.warning(f"[Linux.do] {base} 连接失败，改试下一个地址: {type(e).__name__}: {e}")
            return await client.request(method, self.API_BASES[-1] + path, **kwargs)

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "read",
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def fetch_access_token(self, code: str) -> Optional[str]:
        """授权码换 access_token；任何失败返回 None（原因进日志）"""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        try:
            response = await self._request("POST", self.TOKEN_PATH, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            logger.warning(f"[Linux.do] 获取访问令牌网络异常: {type(e).__name__}: {e}")
            return None

        if response.status_code != 200:
            logger.warning(f"[Linux.do] 获取访问令牌失败: {response.status_code} {response.text[:200]}")
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning(f"[Linux.do] 令牌响应不是 JSON: {response.text[:200]}")
            return None
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            logger.warning(f"[Linux.do] 令牌响应缺少 access_token: {payload}")
            return None
        return token

    async def fetch_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """拉取用户信息（id / username / name / avatar_url / trust_level）；失败返回 None"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": _BROWSER_UA,  # 真实浏览器 UA，避免被 Cloudflare 拦截
        }
        try:
            response = await self._request("GET", self.USERINFO_PATH, headers=headers)
        except httpx.HTTPError as e:
            logger.warning(f"[Linux.do] 获取用户信息网络异常: {type(e).__name__}: {e}")
            return None

        if response.status_code != 200:
            logger.warning(f"[Linux.do] 获取用户信息失败: {response.status_code} {response.text[:200]}")
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning(f"[Linux.do] 用户信息响应不是 JSON: {response.text[:200]}")
            return None
        if not isinstance(payload, dict):
            logger.warning(f"[Linux.do] 用户信息响应格式异常: {payload!r}")
            return None
        return payload
