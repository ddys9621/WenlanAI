"""故事大纲数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db_base import Base
import uuid


class StoryOutline(Base):
    """故事大纲表 - 故事前提大纲"""
    __tablename__ = "story_outlines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False, comment="大纲标题")
    content = Column(Text, comment="故事前提内容(premise)")
    version = Column(Integer, default=1, comment="版本号")
    status = Column(String(20), default="published", comment="状态: draft/published")
    editor_id = Column(String(36), comment="最后编辑者ID")
    is_active = Column(Boolean, default=True, comment="是否为当前激活版本")
    order_index = Column(Integer, comment="排序序号")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    project = relationship("Project", back_populates="story_outlines")

    def __repr__(self):
        return f"<StoryOutline(id={self.id}, title={self.title}, version={self.version})>"
