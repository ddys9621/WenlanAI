"""章纲数据模型"""
from sqlalchemy import Boolean, Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db_base import Base
import uuid


class ChapterOutline(Base):
    """章纲表 - 专业网文版"""
    __tablename__ = "chapter_outlines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False, comment="章节序号")
    title = Column(String(200), nullable=False, comment="章节标题")

    # 场景信息（新增）
    scene = Column(String(200), comment="场景地点，如'拳击场→后台'")
    pov = Column(String(100), comment="视角角色名")

    # 剧情信息
    plot_points = Column(Text, comment="剧情要点（含情感变化），300-400字")
    key_events = Column(Text, comment="关键事件，JSON格式，最后一条为章末钩子")
    characters_involved = Column(Text, comment="涉及角色，JSON格式")
    narrative_tasks = Column(
        Text,
        comment="本章叙事任务 JSON：{resolve:[{promise_id,title,how}], advance:[...], plant:[{title,content,payoff_after}]}",
    )

    # 章节契约（参考岚笺）：正文开头承接什么、写到哪就停、本章不能提前发生什么
    entry_state = Column(Text, nullable=True, comment="进入状态：本章开头人物 / 地点 / 局势（承接上一章结尾）")
    exit_state = Column(Text, nullable=True, comment="退出状态：最后一个关键事件完成后停在哪")
    forbidden = Column(Text, nullable=True, comment="禁止事项 JSON 列表：本章不能提前发生 / 揭晓的事")

    # 确认与上游过期：保存 ≠ 确认；AI 草拟为 draft，作者确认后 confirmed；上游（卷纲 / 总纲）改了标过期
    review_status = Column(String(20), nullable=True, comment="draft = AI 草拟待确认；confirmed / 空 = 已确认")
    confirmed_at = Column(DateTime, nullable=True)
    upstream_stale = Column(Boolean, default=False, comment="上游已修改，建议核对")
    upstream_reason = Column(Text, nullable=True, comment="上游改了什么")

    # 旧字段（保留兼容）
    summary = Column(Text, comment="章节摘要（已废弃，保留兼容旧数据）")

    # 系统字段
    target_word_count = Column(Integer, default=3000, comment="目标字数")
    order_index = Column(Integer, comment="排序序号")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 卷纲归属：总纲 → 卷纲（剧情单元）→ 章纲 ----
    volume_id = Column(
        String(36),
        ForeignKey("volumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属卷纲；NULL = 未挂卷（作者手建）",
    )
    unit_index = Column(Integer, nullable=True, comment="所属剧情单元序号（Volume.units[].index）")

    # 关联关系
    project = relationship("Project", back_populates="chapter_outlines")

    def __repr__(self):
        return f"<ChapterOutline(id={self.id}, chapter_number={self.chapter_number}, title={self.title})>"
