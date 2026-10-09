"""章纲数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
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

    # 旧字段（保留兼容）
    summary = Column(Text, comment="章节摘要（已废弃，保留兼容旧数据）")

    # 系统字段
    target_word_count = Column(Integer, default=3000, comment="目标字数")
    order_index = Column(Integer, comment="排序序号")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- V4.1 K2 桥段四章结构字段（详见 v4_design.md §3.2.2）----
    # bridge_id NULL → 走线性章纲模式（旧数据兼容）
    # bridge_id 非空 → 走桥段四章模式，bridge_position 决定 prompt 注入哪段位置约束
    bridge_id = Column(
        String(36),
        ForeignKey("plot_bridges.id", ondelete="SET NULL"),
        nullable=True,
        comment="所属桥段（K2 桥段四章模式），NULL = 线性章纲模式",
    )
    bridge_position = Column(
        String(20),
        nullable=True,
        comment="桥段内位置: intro/build/payoff/aftermath (对应 C1/C2/C3/C4)",
    )
    position_constraints = Column(
        Text,
        nullable=True,
        comment=(
            "位置约束 JSON 覆盖：{upper_word_count, lower_word_count, hook_required, "
            "hook_type, no_hook_at_end, ...} — 不填则用默认位置规则"
        ),
    )

    # 关联关系
    project = relationship("Project", back_populates="chapter_outlines")
    plot_line_links = relationship("ChapterOutlinePlotLineLink", back_populates="chapter_outline", cascade="all, delete-orphan")
    plot_card_links = relationship("PlotCardChapterOutlineLink", back_populates="chapter_outline", cascade="all, delete-orphan")
    bridge = relationship(
        "PlotBridge",
        back_populates="chapter_outlines",
        foreign_keys=[bridge_id],
    )
    
    def __repr__(self):
        return f"<ChapterOutline(id={self.id}, chapter_number={self.chapter_number}, title={self.title})>"
