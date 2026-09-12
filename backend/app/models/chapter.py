"""章节数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class Chapter(Base):
    """章节表"""
    __tablename__ = "chapters"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_outline_id = Column(String(36), ForeignKey("chapter_outlines.id", ondelete="SET NULL"), nullable=True, comment="关联的章纲ID")
    chapter_number = Column(Integer, nullable=False, comment="章节序号")
    title = Column(String(200), nullable=False, comment="章节标题")
    content = Column(Text, comment="章节内容")
    summary = Column(Text, comment="章节摘要")
    word_count = Column(Integer, default=0, comment="字数统计")
    status = Column(String(20), default="draft", comment="章节状态")
    version = Column(Integer, default=1, comment="版本号")
    parent_version_id = Column(String(36), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, comment="父版本ID")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<Chapter(id={self.id}, chapter_number={self.chapter_number}, title={self.title})>"