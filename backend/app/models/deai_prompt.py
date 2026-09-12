"""项目级去 AI 味提示词：只在「去 AI 味重写」时由用户勾选注入（services/deai_rewrite.py），首次生成不用。"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class DeaiPrompt(Base):
    """去 AI 味提示词表（每项目多条）"""
    __tablename__ = "deai_prompts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属项目")
    name = Column(String(100), nullable=False, comment="提示词名称")
    content = Column(Text, nullable=False, comment="提示词正文（原样拼进重写提示词）")
    order_index = Column(Integer, nullable=False, default=0, comment="排序序号（创建顺序递增）")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<DeaiPrompt(id={self.id}, project_id={self.project_id}, name={self.name})>"
