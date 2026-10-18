"""项目自定义提示词：只存作者改过的条目（services/project_prompts 登记的 key），没有行 = 跟随系统默认。"""
from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.db_base import Base
from app.models.chapter_candidate import utcnow


class ProjectPromptOverride(Base):
    __tablename__ = "project_prompt_overrides"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, comment="所属项目")
    prompt_key = Column(String(64), primary_key=True, comment="提示词条目 key")
    content = Column(Text, nullable=False, comment="作者改写后的提示词")
    default_hash = Column(String(40), nullable=True, comment="保存时系统默认文本的指纹，对不上 = 默认已变")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, comment="最后保存时间")

    def __repr__(self):
        return f"<ProjectPromptOverride(project_id={self.project_id}, prompt_key={self.prompt_key})>"
