"""用户禁用状态：独立于 trust_level（后者只作信任等级展示），存 user_account_status 表。

旧版本用 users.trust_level == -1 表示禁用，会冲掉真实信任等级；现迁出到独立表，
启用时不再动 trust_level，禁用即时生效（中间件每次请求查）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, NamedTuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logger import get_logger

logger = get_logger(__name__)


async def _get_session() -> AsyncSession:
    from app.database import get_engine

    engine = await get_engine("_global_users_")
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


class AccountStatus(NamedTuple):
    disabled: bool
    sessions_after: Optional[datetime]

    def token_revoked(self, iat: int) -> bool:
        """签发于 sessions_after 之前的令牌已被吊销（同一秒签发的仍有效，重置密码后立刻登录不受影响）。"""
        return self.sessions_after is not None and iat < int(self.sessions_after.timestamp())


async def get_status(user_id: str) -> AccountStatus:
    """一次取回禁用标志与会话吊销时刻（中间件每请求调用，只查一次）。"""
    from app.models.user_account_status import UserAccountStatus

    async with await _get_session() as session:
        row = await session.get(UserAccountStatus, user_id)
        if row is None:
            return AccountStatus(False, None)
        return AccountStatus(bool(row.disabled), row.sessions_after)


async def is_disabled(user_id: str) -> bool:
    """该用户是否被管理员禁用。"""
    return (await get_status(user_id)).disabled


async def revoke_sessions(user_id: str) -> None:
    """让该用户此刻之前签发的所有会话令牌失效（强制下线）。"""
    from app.models.user_account_status import UserAccountStatus

    async with await _get_session() as session:
        row = await session.get(UserAccountStatus, user_id)
        if row is None:
            row = UserAccountStatus(user_id=user_id, disabled=False)
            session.add(row)
        row.sessions_after = datetime.now()
        await session.commit()


async def set_disabled(user_id: str, disabled: bool) -> None:
    """设置禁用状态；禁用时记录 disabled_at，启用时清空。"""
    from app.models.user_account_status import UserAccountStatus

    async with await _get_session() as session:
        row = await session.get(UserAccountStatus, user_id)
        if row is None:
            row = UserAccountStatus(
                user_id=user_id,
                disabled=disabled,
                disabled_at=datetime.now() if disabled else None,
            )
            session.add(row)
        else:
            row.disabled = disabled
            row.disabled_at = datetime.now() if disabled else None
        await session.commit()


async def disabled_user_ids(user_ids: Iterable[str]) -> set[str]:
    """批量查询哪些 user_id 被禁用（给用户列表一次性取，避免 N+1）。"""
    from app.models.user_account_status import UserAccountStatus

    ids = [u for u in user_ids if u]
    if not ids:
        return set()
    async with await _get_session() as session:
        rows = await session.execute(
            select(UserAccountStatus.user_id).where(
                UserAccountStatus.user_id.in_(ids),
                UserAccountStatus.disabled == True,  # noqa: E712
            )
        )
        return {r[0] for r in rows}


def migrate_account_status_schema(connection) -> int:
    """user_account_status 是 2.4 新建的表；开发期已按旧定义建过的本地库补上 sessions_after 列。幂等。

    只针对这张本轮新建、尚未随版本发布的表；已发布的旧表仍遵守「不加列」的规矩。
    """
    cols = {row[1] for row in connection.execute(text("PRAGMA table_info(user_account_status)")).fetchall()}
    if not cols or "sessions_after" in cols:
        return 0
    connection.execute(text("ALTER TABLE user_account_status ADD COLUMN sessions_after DATETIME"))
    return 1


def migrate_legacy_disabled(connection) -> int:
    """旧库用 trust_level == -1 标记禁用：迁入 user_account_status.disabled，并把 trust_level 归 0。

    幂等：迁完 trust_level 不再有 -1，再次调用返回 0。在 create_all 之后调用（表已建）。
    """
    rows = connection.execute(text("SELECT user_id FROM users WHERE trust_level = -1")).fetchall()
    if not rows:
        return 0
    for (user_id,) in rows:
        exists = connection.execute(
            text("SELECT 1 FROM user_account_status WHERE user_id = :uid"), {"uid": user_id}
        ).first()
        if exists:
            connection.execute(
                text("UPDATE user_account_status SET disabled = 1 WHERE user_id = :uid"), {"uid": user_id}
            )
        else:
            connection.execute(
                text("INSERT INTO user_account_status (user_id, disabled) VALUES (:uid, 1)"), {"uid": user_id}
            )
    connection.execute(text("UPDATE users SET trust_level = 0 WHERE trust_level = -1"))
    return len(rows)
