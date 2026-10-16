"""项目 ↔ 对标书（一个项目一本）：向导建项目与项目「仿写参考」页共用。只能关联自己的知识库来源；不 commit。

升级 2.0.x：旧的项目挂载（project_reference_packs，模型已删、表还在）启动时迁成对标书（migrate_reference_pack_links）。
"""
from __future__ import annotations

import json
from typing import Mapping, Optional

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.knowledge import KbProjectLink, KbSource
from app.models.project import Project

logger = get_logger(__name__)
LEGACY_LINK_TABLE = "project_reference_packs"

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


async def migrate_reference_pack_links(db: AsyncSession) -> int:
    """没设对标书、但 2.0.x 里挂过参考包的项目：把最早挂上的那本设为对标书（借鉴节奏）。

    书还没收进知识库就先导入（确定性转换，不调模型）；已设对标书的项目不动；幂等。返回迁了几个项目。
    """
    if not await db.run_sync(lambda s: inspect(s.connection()).has_table(LEGACY_LINK_TABLE)):
        return 0
    from app.services.knowledge.kb_import import import_dissect_task

    rows = (await db.execute(text(
        f"SELECT l.project_id, p.task_id FROM {LEGACY_LINK_TABLE} l JOIN reference_packs p ON p.id = l.pack_id "
        "ORDER BY l.attached_at"
    ))).all()
    seen: set[str] = set()
    migrated = 0
    for project_id, task_id in rows:
        if project_id in seen or not task_id:
            continue
        seen.add(project_id)
        project = await db.get(Project, project_id)
        if project is None or await db.get(KbProjectLink, project_id) is not None:
            continue
        source = (await db.execute(
            select(KbSource).where(KbSource.dissect_task_id == task_id, KbSource.user_id == project.user_id)
        )).scalars().first() or await import_dissect_task(db, task_id, project.user_id)
        if source is None:
            continue
        db.add(KbProjectLink(project_id=project_id, source_id=source.id, mode=DEFAULT_MODE))
        migrated += 1
    if migrated:
        await db.commit()
        logger.info("[知识库] 已把 %d 个项目挂载的参考包迁成对标书", migrated)
    return migrated
