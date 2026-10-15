"""卷纲：总纲 → 卷纲 → 章纲 的中间层（参考岚笺谋篇：总纲扩写成卷纲，卷纲扩写成章纲）。

一卷 = 一段完整的故事阶段（新的舞台 / 对手 / 目标之一），内含若干剧情单元：
- units：剧情单元 JSON 列表 [{index, title, chapter_start, chapter_end, story, turn}]——一件完整的事，
  章数按事件大小定（不是等长切槽）；story 写起因 → 经过 → 结果，turn 写单元结束时局面怎样变化
- threads：本卷线索编排（感情线 / 支线 / 伏笔各推进到哪一步），JSON 字符串列表
- 确认状态与章纲同一套：AI 草拟为 draft，作者确认后 confirmed；上游（总纲）改了标 upstream_stale
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class Volume(Base):
    __tablename__ = "volumes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    volume_number = Column(Integer, nullable=False, comment="卷序号（从 1 起）")
    title = Column(String(200), nullable=False, default="", comment="卷名")
    chapter_start = Column(Integer, nullable=False, comment="起始章号")
    chapter_end = Column(Integer, nullable=False, comment="结束章号")
    summary = Column(Text, nullable=True, comment="本卷故事（自然段：谁在什么处境做了什么、别人怎样回应、结果如何）")
    goal = Column(Text, nullable=True, comment="本卷主角目标与核心冲突（主要对手 / 压力）")
    climax = Column(Text, nullable=True, comment="卷末高潮")
    ending_hook = Column(Text, nullable=True, comment="卷末状态与转入下一卷的钩子")
    units = Column(Text, nullable=True, comment="剧情单元 JSON：[{index,title,chapter_start,chapter_end,story,turn}]")
    threads = Column(Text, nullable=True, comment="线索编排 JSON 字符串列表：感情线 / 支线 / 伏笔本卷推进到哪")
    review_note = Column(Text, nullable=True, comment="上一卷卷末复盘回写的修正意见")

    review_status = Column(String(20), nullable=True, comment="draft = AI 草拟待确认；confirmed = 已确认")
    confirmed_at = Column(DateTime, nullable=True)
    upstream_stale = Column(Boolean, default=False, comment="总纲已修改，建议核对")
    upstream_reason = Column(Text, nullable=True, comment="上游改了什么")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_volume_project_number", "project_id", "volume_number"),)

    def __repr__(self) -> str:
        return f"<Volume(number={self.volume_number}, title={self.title!r}, {self.chapter_start}-{self.chapter_end})>"
