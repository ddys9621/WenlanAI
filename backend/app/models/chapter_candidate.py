"""章节候选稿：AI 写出的正文先存这里，作者「采用」后才写入正式正文（批量生成过闸门后自动采用）。

mode：replace_all = 整章替换；append = 接在正文末尾；replace_range = 替换正文里一段原文（智能助笔改写 / 润色）。
base_content_hash 记录生成时的正文指纹：整章替换时正文已被改过要作者确认覆盖。
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db_base import Base
import uuid


def utcnow() -> datetime:
    """与 SQLite CURRENT_TIMESTAMP 同一时钟（UTC，无时区），且精确到微秒以便同一秒内的候选稿排序。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChapterCandidate(Base):
    __tablename__ = "chapter_candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)

    source = Column(String(30), nullable=False, default="ai_generate", comment="ai_generate / deai_rewrite / assistant")
    mode = Column(String(20), nullable=False, default="replace_all", comment="replace_all / append / replace_range")
    content = Column(Text, nullable=False, comment="候选正文（replace_range 时为替换后的那段）")
    word_count = Column(Integer, default=0)

    base_content_hash = Column(String(64), nullable=True, comment="生成时的正文指纹")
    range_start = Column(Integer, nullable=True)
    range_end = Column(Integer, nullable=True)
    original_text = Column(Text, nullable=True, comment="replace_range 被替换的原文")

    outline_hash = Column(String(64), nullable=True, comment="生成所依据的章纲指纹")
    outline_changed = Column(Boolean, default=False, comment="生成期间章纲被改过")

    status = Column(String(20), nullable=False, default="pending", index=True,
                    comment="pending / adopted / discarded / superseded")
    quality_json = Column(Text, nullable=True, comment="去 AI 味 / 字数质检")
    adherence_json = Column(Text, nullable=True, comment="章纲遵循度审校报告")
    meta_json = Column(Text, nullable=True, comment="生成参数：目标字数 / 续写次数 / 技能等")

    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ChapterCandidate(chapter_id={self.chapter_id}, source={self.source}, status={self.status})>"
