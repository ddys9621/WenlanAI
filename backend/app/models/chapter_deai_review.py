"""章节去 AI 味诊断结果（sepia review）：每次诊断一行，最新一行为当前报告。"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db_base import Base


class ChapterDeaiReview(Base):
    __tablename__ = "chapter_deai_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)

    model_name = Column(String(100), nullable=True, comment="诊断时用户所用模型")
    model_family = Column(String(20), nullable=True, comment="识别出的模型家族（claude/gpt/gemini/deepseek/kimi），无表为空")
    content_hash = Column(String(40), nullable=False, comment="诊断时正文 sha1；正文变了报告即过期（stale）")
    findings_count = Column(Integer, nullable=False, default=0, comment="待改信号条数（不含人类正向标记）")
    result = Column(JSON, nullable=False, comment="deai_review_service.run_deai_review 的完整结果")

    created_at = Column(DateTime, server_default=func.now())
