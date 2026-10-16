"""项目 ↔ 对标书（一个项目一本）：向导建项目与项目「仿写参考」页共用。只能关联自己的知识库来源；不 commit。"""
from __future__ import annotations

import json
from typing import Mapping, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KbProjectLink, KbSource

MODES = ("follow", "borrow", "style", "off")
DEFAULT_MODE = "borrow"


async def set_project_link(db: AsyncSession, user_id: str, project_id: str, source_id: str, *,
                           mode: Optional[str] = DEFAULT_MODE,
                           volume_map: Optional[Mapping[str, int]] = None) -> Optional[KbProjectLink]:
    """来源不存在或不属于该用户 → None。volume_map=None 表示保持原来的卷对标表。"""
    source = await db.get(KbSource, source_id) if source_id else None
    if source is None or source.user_id != user_id:
        return None
    link = await db.get(KbProjectLink, project_id)
    if link is None:
        link = KbProjectLink(project_id=project_id)
        db.add(link)
    link.source_id = source_id
    link.mode = mode if mode in MODES else DEFAULT_MODE
    if volume_map is not None:
        link.volume_map = json.dumps({str(k): int(v) for k, v in volume_map.items()}, ensure_ascii=False)
    return link
