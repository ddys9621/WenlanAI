"""管理员操作审计：记录与分页读取。记录失败只记日志，不阻断管理操作本身。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logger import get_logger

logger = get_logger(__name__)

MAX_LIMIT = 200


async def _get_session() -> AsyncSession:
    from app.database import get_engine

    engine = await get_engine("_global_users_")
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


async def record(
    actor: Any,
    action: str,
    target: Any = None,
    target_id: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """落一行审计。actor / target 是 user_manager 的 User（取 user_id / display_name 快照）。"""
    from app.models.admin_audit_log import AdminAuditLog

    try:
        async with await _get_session() as session:
            session.add(AdminAuditLog(
                id=uuid.uuid4().hex,
                actor_id=getattr(actor, "user_id", str(actor)),
                actor_name=getattr(actor, "display_name", None),
                action=action,
                target_id=target_id or getattr(target, "user_id", None),
                target_name=getattr(target, "display_name", None),
                detail=json.dumps(detail or {}, ensure_ascii=False),
                created_at=datetime.now(),
            ))
            await session.commit()
    except Exception as e:  # 审计不能把管理操作本身拖垮
        logger.warning(f"写入管理员审计失败（{action}）: {e}")


def _row_to_dict(row) -> dict:
    try:
        detail = json.loads(row.detail) if row.detail else {}
    except ValueError:
        detail = {"raw": row.detail}
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_name": row.actor_name,
        "action": row.action,
        "target_id": row.target_id,
        "target_name": row.target_name,
        "detail": detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_logs(limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    """按时间倒序分页；返回 (total, items)。"""
    from app.models.admin_audit_log import AdminAuditLog

    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    async with await _get_session() as session:
        total = (await session.execute(select(func.count()).select_from(AdminAuditLog))).scalar_one()
        rows = (await session.execute(
            select(AdminAuditLog)
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )).scalars().all()
    return int(total), [_row_to_dict(r) for r in rows]
