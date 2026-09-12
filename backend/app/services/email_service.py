"""邮箱注册支撑：验证码内存存储 + SMTP 发信（stdlib smtplib，放线程池里跑，不新增依赖）。

验证码只存内存：进程重启即失效，用户重新点「发送验证码」即可，不值得落库。
"""
from __future__ import annotations

import asyncio
import hmac
import secrets
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

from pydantic import BaseModel

from app.logger import get_logger
from app.services.auth_settings_service import AuthSettings, SmtpEncryption

logger = get_logger(__name__)

SMTP_TIMEOUT_SECONDS = 20
BRAND_NAME = "文澜 AI"  # 邮件主题/正文里的产品名，与前端品牌一致


class CooldownError(Exception):
    """冷却期内重复发送"""

    def __init__(self, remaining: int):
        super().__init__(f"请 {remaining} 秒后再试")
        self.remaining = remaining


@dataclass
class _CodeEntry:
    code: str
    issued_at: float
    expires_at: float
    attempts: int = 0


def _normalize(email: str) -> str:
    return email.strip().lower()


class EmailCodeStore:
    """按邮箱存一份 6 位数字验证码：TTL 过期、冷却限频、错误次数上限、校验成功即销毁。"""

    def __init__(
        self,
        ttl_seconds: int = 600,
        cooldown_seconds: int = 60,
        max_attempts: int = 5,
        now: Callable[[], float] = time.time,
    ):
        self.ttl_seconds = ttl_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_attempts = max_attempts
        self._now = now
        self._codes: dict[str, _CodeEntry] = {}

    def issue(self, email: str) -> str:
        self.cleanup()
        key = _normalize(email)
        now = self._now()
        existing = self._codes.get(key)
        if existing is not None:
            elapsed = now - existing.issued_at
            if elapsed < self.cooldown_seconds:
                raise CooldownError(int(round(self.cooldown_seconds - elapsed)))

        code = f"{secrets.randbelow(10 ** 6):06d}"
        self._codes[key] = _CodeEntry(code=code, issued_at=now, expires_at=now + self.ttl_seconds)
        return code

    def verify(self, email: str, code: str) -> bool:
        key = _normalize(email)
        entry = self._codes.get(key)
        if entry is None:
            return False
        if self._now() > entry.expires_at:
            del self._codes[key]
            return False
        if not hmac.compare_digest(entry.code, (code or "").strip()):
            entry.attempts += 1
            if entry.attempts >= self.max_attempts:
                del self._codes[key]
            return False
        del self._codes[key]
        return True

    def discard(self, email: str) -> None:
        """作废某邮箱的验证码（如邮件没发出去，让用户能立刻重试而不吃冷却）"""
        self._codes.pop(_normalize(email), None)

    def cleanup(self) -> None:
        now = self._now()
        for key in [k for k, e in self._codes.items() if now > e.expires_at]:
            del self._codes[key]

    def pending_count(self) -> int:
        return len(self._codes)


class SmtpConfig(BaseModel):
    host: str
    port: int = 465
    encryption: SmtpEncryption = "ssl"
    username: str = ""
    password: str = ""
    sender: str

    @classmethod
    def from_auth_settings(cls, settings: AuthSettings) -> "SmtpConfig":
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            encryption=settings.smtp_encryption,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.smtp_from,
        )


def build_message(cfg: SmtpConfig, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _send_sync(cfg: SmtpConfig, msg: EmailMessage) -> None:
    if cfg.encryption == "ssl":
        client = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS)
    else:
        client = smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS)
    with client:
        if cfg.encryption == "starttls":
            client.starttls()
        if cfg.username:
            client.login(cfg.username, cfg.password)
        client.send_message(msg)


async def send_email(cfg: SmtpConfig, to: str, subject: str, body: str) -> None:
    """发一封纯文本邮件；SMTP 异常原样抛给调用方决定怎么提示。"""
    await asyncio.to_thread(_send_sync, cfg, build_message(cfg, to, subject, body))
    logger.info(f"[邮件] 已发送至 {to}: {subject}")


# 全局实例
email_code_store = EmailCodeStore()
