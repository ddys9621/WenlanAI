"""会话签名令牌。

旧实现把明文 user_id 直接写进 Cookie，任何人伪造 `Cookie: user_id=<目标>` 即可冒充该用户
（全站数据按 user_id 分区，等同越权读写任意账号）。这里改成用标准库 hmac 对
`user_id + 有效期` 签名的无状态令牌：服务端验签 + 验有效期，篡改或过期一律视为未登录。

令牌格式：``<user_id>|<exp_unix>|<hmac_sha256_hex>``
密钥：首次使用时随机生成并存入 system_settings（key="session_secret"），模块级缓存，
不随每次请求查库；无新依赖、无新表。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

from pydantic import BaseModel

from app.logger import get_logger
from app.services.system_settings_store import JsonSettingsStore

logger = get_logger(__name__)


class _SessionSecret(BaseModel):
    secret: str = ""


_secret_store = JsonSettingsStore("session_secret", _SessionSecret, "会话密钥")
_cached_secret: Optional[str] = None


def reset_secret_cache() -> None:
    """清掉内存里缓存的密钥（测试隔离、运行中轮换密钥时用）。"""
    global _cached_secret
    _cached_secret = None


async def get_session_secret() -> str:
    """取会话签名密钥：优先内存缓存，其次库里，都没有则生成一个并落库。"""
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    current = await _secret_store.get()
    if current.secret:
        _cached_secret = current.secret
        return _cached_secret

    generated = secrets.token_hex(32)
    await _secret_store.save(_SessionSecret(secret=generated))
    _cached_secret = generated
    logger.info("已生成新的会话签名密钥并存入 system_settings")
    return generated


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign_session(user_id: str, secret: str, expire_minutes: int) -> str:
    """签发令牌：``user_id|iat|exp|sig``，iat 是签发时刻（秒），供按 sessions_after 吊销。"""
    now = int(time.time())
    exp = now + expire_minutes * 60
    payload = f"{user_id}|{now}|{exp}"
    return f"{payload}|{_signature(payload, secret)}"


def parse_session(token: str, secret: str) -> Optional[tuple[str, int]]:
    """校验令牌，通过则返回 (user_id, iat)；验签失败 / 过期 / 旧格式一律返回 None。"""
    if not token or token.count("|") != 3:
        return None

    user_id, iat_raw, exp_raw, sig = token.rsplit("|", 3)
    payload = f"{user_id}|{iat_raw}|{exp_raw}"
    if not hmac.compare_digest(sig, _signature(payload, secret)):
        return None

    try:
        iat, exp = int(iat_raw), int(exp_raw)
    except (TypeError, ValueError):
        return None
    if exp < int(time.time()):
        return None

    return user_id, iat


def verify_session(token: str, secret: str) -> Optional[str]:
    """只要 user_id 的便捷封装（不含吊销判断，吊销由中间件按账号状态表判定）。"""
    parsed = parse_session(token, secret)
    return parsed[0] if parsed else None
