"""智能助笔的写入核对。

本项目所有会话共用一个 SQLite 连接（database.get_engine 用 StaticPool）：别的请求收尾时会在这个连接上 ROLLBACK，
恰好落在本任务「已写、未提交」之间时，刚写的内容会被一并回滚，而 commit 不会报错。
所以每次提交后从库里读回核对，没写进去就重写（写入须可重复执行），几次都不行再报错，不假装成功。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

logger = get_logger(__name__)

WRITE_ATTEMPTS = 4


class PersistError(RuntimeError):
    """多次重写仍没写进数据库。"""


async def write_verified(
    db: AsyncSession,
    write: Callable[[], Awaitable[object]],
    verify: Callable[[], Awaitable[bool]],
    what: str,
) -> None:
    for attempt in range(1, WRITE_ATTEMPTS + 1):
        await write()
        await db.commit()
        if await verify():
            return
        logger.warning(f"[智能助笔] {what}提交后读回不一致（多半被同一连接上的其他请求回滚），第 {attempt} 次重写")
        await asyncio.sleep(0.02 * attempt)
    raise PersistError(f"{what}没能写进数据库（被同时进行的其他操作打断），请重试")
