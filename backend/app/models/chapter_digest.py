"""章节档案：每章一条摘要 + 章末状态，是前情脉络 / 近期概要 / 层级摘要 / 规划「实际进展」的地基。

source=ai 时重新分析直接覆盖；作者改过（source=author）就不再覆盖，AI 的新结果放进 ai_summary / ai_end_state
作为建议，作者采用或忽略。content_hash 是 AI 分析时的正文指纹：和当前正文对不上 = 档案可能过期。
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class ChapterDigest(Base):
    __tablename__ = "chapter_digests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    summary = Column(Text, nullable=False, default="")
    end_state = Column(Text, nullable=True)
    source = Column(String(10), nullable=False, default="ai", comment="ai / author")
    ai_summary = Column(Text, nullable=True, comment="作者版本在用时，AI 最新一次分析的摘要（建议）")
    ai_end_state = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True, comment="AI 分析时的正文指纹")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
