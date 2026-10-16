"""作者对故事账本的修正：重新分析不会清掉，回放 / 对账时以作者为准。

- AuthorStateSignal：人物状态修正（生死 / 位置 / 境界 / 物品 / 伤势 / 目标 / 能力），和分析结算的连续性信号一起
  按章回放，同一章排在 AI 信号之后；chapter_number = 第几章结束时成立（写第 N+1 章起生效）
- PromiseAuthorLock：作者改过的伏笔 / 承诺锁住哪些字段；锁住的承诺不会被埋设章的重新分析改写或删掉
"""
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class AuthorStateSignal(Base):
    __tablename__ = "author_state_signals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False, index=True)
    signal_type = Column(String(30), nullable=False)
    character_name = Column(String(100), nullable=False, index=True)
    signal_key = Column(String(200), nullable=True)
    signal_value = Column(String(50), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PromiseAuthorLock(Base):
    __tablename__ = "promise_author_locks"

    promise_id = Column(String(36), ForeignKey("narrative_promises.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    fields = Column(JSON, nullable=False, default=list, comment='锁住的字段；["*"] = 作者新建，全部以作者为准')
    origin_title = Column(String(200), nullable=True, comment="作者改标题前 AI 起的标题（重新分析时按它对账认回同一条）")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
