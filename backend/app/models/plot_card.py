"""剧情卡片数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db_base import Base
import uuid


class PlotCard(Base):
    """剧情卡片表"""
    __tablename__ = "plot_cards"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_outline_id = Column(String(36), ForeignKey("chapter_outlines.id", ondelete="SET NULL"), nullable=True, comment="关联的章纲ID")
    title = Column(String(200), nullable=False, comment="卡片标题")
    content = Column(Text, comment="卡片内容描述")
    card_type = Column(String(50), default="plot", comment="卡片类型：plot(剧情)/character(角色)/scene(场景)/conflict(冲突)")
    order_index = Column(Integer, comment="排序序号")
    tags = Column(Text, comment="标签，JSON格式存储")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ========== 场景生成相关字段（新增）==========
    # 场景生成状态: pending(待生成) / generating(生成中) / completed(已完成) / rejected(已拒绝)
    generation_status = Column(
        String(20),
        default="pending",
        comment="场景生成状态: pending/generating/completed/rejected"
    )

    # 生成的正文内容（该卡片对应的章节正文片段）
    generated_content = Column(
        Text,
        nullable=True,
        comment="该场景生成的正文内容"
    )

    # 目标字数（该场景的目标字数）
    word_count_target = Column(
        Integer,
        default=500,
        comment="目标字数"
    )

    # 实际字数（生成后的实际字数）
    word_count_actual = Column(
        Integer,
        default=0,
        comment="实际生成字数"
    )

    # 生成顺序（在章节中的生成顺序，用于保证连贯性）
    generation_order = Column(
        Integer,
        default=0,
        comment="在章节中的生成顺序"
    )
    # ========== 场景生成相关字段结束 ==========

    # 关联关系
    project = relationship("Project", back_populates="plot_cards")
    chapter_outline_links = relationship("PlotCardChapterOutlineLink", back_populates="plot_card", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlotCard(id={self.id}, title={self.title}, type={self.card_type})>"

    def mark_completed(self, content: str, word_count: int):
        """标记场景生成完成"""
        self.generation_status = "completed"
        self.generated_content = content
        self.word_count_actual = word_count
