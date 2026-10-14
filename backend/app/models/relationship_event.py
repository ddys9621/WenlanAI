"""Relationship delta log per chapter."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base
import uuid


class RelationshipEvent(Base):
    __tablename__ = "relationship_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False, index=True)

    character_from_id = Column(String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    character_to_id = Column(String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)

    delta = Column(Integer, nullable=False)
    reason_type = Column(String(50), nullable=True, index=True)
    reason_text = Column(Text, nullable=True)
    evidence_text = Column(Text, nullable=True)

    old_intimacy_level = Column(Integer, nullable=True)
    new_intimacy_level = Column(Integer, nullable=True)
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    # 分析显式给出的新状态（"" = 没给，沿用上一状态）；按章重放关系时用它，不用回放算出的 new_status
    requested_status = Column(String(20), nullable=True)
    created_relationship = Column(Integer, default=0)  # 0/1 for sqlite compatibility

    created_at = Column(DateTime, server_default=func.now())

