"""章节历史版本：正文被替换（手动修改 / 采用候选稿 / 恢复旧版）之前的那一稿。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base
import uuid


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False, comment="本章内递增的版本号")
    content = Column(Text, nullable=False, comment="被替换前的正文")
    content_hash = Column(String(64), nullable=False, comment="正文指纹（去首尾空白、统一换行后的 sha256）")
    word_count = Column(Integer, default=0)
    reason = Column(String(30), nullable=False, comment="被什么替换：manual_edit / adopt_candidate / restore / assistant")
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<ChapterVersion(chapter_id={self.chapter_id}, version={self.version_number}, reason={self.reason})>"
