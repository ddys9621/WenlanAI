"""层级剧情摘要（长篇"前情脉络"的数据源）。

三级：unit（桥段 / 每 4 章）→ phase（阶段 / 每 16 章）→ volume（主线节点 ≈ 卷 / 每 64 章）。
写第 N 章时注入「已完成卷摘要 + 本卷已完成阶段摘要 + 本阶段已完成单元摘要 + 最近几章摘要」，
总长基本不随章数增长；取代旧的"每 50 章抽 1 章摘要"骨架。
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db_base import Base


class ArcSummary(Base):
    __tablename__ = "arc_summaries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(20), nullable=False, comment="unit / phase / volume")
    arc_key = Column(String(100), nullable=False, comment="bridge:12 / phase:3:2 / beat:3 / block4:9 / block16:2 / block64:0")
    chapter_start = Column(Integer, nullable=False)
    chapter_end = Column(Integer, nullable=False)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=False, comment="合并摘要")
    review = Column(Text, nullable=True, comment="卷末复盘（仅 volume）：计划 vs 实际偏差、下一卷要接住 / 回收什么")
    source_signature = Column(String(64), nullable=True, comment="子摘要指纹：子摘要变了就重新汇总")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "level", "arc_key", name="uq_arc_summary_key"),
        Index("idx_arc_summary_project_range", "project_id", "chapter_start", "chapter_end"),
    )
