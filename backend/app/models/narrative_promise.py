"""Narrative promise tracker for foreshadows, promises, mysteries and conflicts."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base
import uuid


class NarrativePromise(Base):
    __tablename__ = "narrative_promises"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    source_chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    source_chapter_number = Column(Integer, nullable=False, index=True)

    promise_type = Column(String(20), nullable=False, index=True)  # foreshadow/promise/mystery/conflict
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)

    owner_character_id = Column(String(36), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True)
    target_character_id = Column(String(36), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True)

    priority = Column(String(20), default="medium", index=True)
    status = Column(String(20), default="open", index=True)  # open/progressing/resolved/broken
    deadline_chapter = Column(Integer, nullable=True, index=True)
    last_activated_chapter = Column(Integer, nullable=True, index=True)

    resolved_chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
    resolved_chapter_number = Column(Integer, nullable=True)
    resolution_note = Column(Text, nullable=True)

    evidence_text = Column(Text, nullable=True)
    # 埋设章被重新分析 / 整章替换后待对账：按标题匹配复用原 ID（后面章节的回收记录、章纲任务引用都不断）
    needs_reconcile = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

