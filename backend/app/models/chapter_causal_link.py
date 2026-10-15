"""Structured cause-event-effect-decision chain extracted from a chapter."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base
import uuid


class ChapterCausalLink(Base):
    __tablename__ = "chapter_causal_links"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False, index=True)

    cause = Column(Text, nullable=False)
    event = Column(Text, nullable=False)
    effect = Column(Text, nullable=False)
    decision = Column(Text, nullable=True)

    actor_ids = Column(JSON, nullable=True)
    target_ids = Column(JSON, nullable=True)

    importance_score = Column(Float, default=0.5)
    is_reversible = Column(Boolean, default=False)
    evidence_text = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

