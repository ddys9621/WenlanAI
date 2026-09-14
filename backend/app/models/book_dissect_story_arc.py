"""拆书 V5：情节单元表。每个任务的全部单元逐条落库，供参考包「桥段库」tab 分页浏览；
注入用的聚合（典型单元 / 分布）另存 reference_packs.bridges_json。"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db_base import Base


class BookDissectStoryArc(Base):
    __tablename__ = "book_dissect_story_arcs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("book_dissect_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    arc_index = Column(Integer, nullable=False, comment="单元编号，1-based")
    start_chapter = Column(Integer, nullable=False)
    end_chapter = Column(Integer, nullable=False)
    title = Column(String(120), nullable=False, default="")
    payoff_type = Column(String(20), nullable=False, default="无强爽点")
    origin = Column(String(20), nullable=False, default="llm", comment="llm / fallback")
    arc_json = Column(Text, nullable=False, comment="StoryArc.to_dict() JSON")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("task_id", "arc_index", name="uq_story_arc_task_index"),
        Index("idx_story_arc_task_start", "task_id", "start_chapter"),
    )
