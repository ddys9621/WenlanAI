"""项目数据模型"""
from sqlalchemy import Boolean, Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db_base import Base
import uuid


class Project(Base):
    """项目表"""
    __tablename__ = "projects"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True, comment="用户ID")
    title = Column(String(200), nullable=False, comment="项目标题")
    description = Column(Text, comment="项目简介")
    theme = Column(Text, comment="主题")
    genre = Column(String(50), comment="小说类型")
    target_words = Column(Integer, default=0, comment="目标字数")
    current_words = Column(Integer, default=0, comment="当前字数")
    status = Column(String(20), default="planning", comment="创作状态")
    wizard_status = Column(String(20), default="incomplete", comment="向导完成状态: incomplete/completed")
    wizard_step = Column(Integer, default=0, comment="向导当前步骤: 0-4（1 世界观 / 2 角色 / 3 故事大纲 / 4 剧情线；之后固定进入桥段规划）")

    # 世界构建字段
    world_time_period = Column(Text, comment="时间背景")
    world_location = Column(Text, comment="地理位置")
    world_atmosphere = Column(Text, comment="氛围基调")
    world_rules = Column(Text, comment="世界规则")
    generation_prompt = Column(Text, comment="最终提交提示词补充")
    
    # 项目配置
    chapter_count = Column(Integer, comment="章节数量")
    narrative_perspective = Column(String(50), comment="叙事视角：first_person/third_person/omniscient")
    character_count = Column(Integer, default=5, comment="角色数量")
    c3_hook_style = Column(
        String(20),
        default="none",
        server_default="none",
        comment="桥段 C3 兑现章末尾：none 不留钩子（默认，付费文）/ soft 收束+半钩（免费平台章末钩子）",
    )

    # DEPRECATED：工程化桥段流水线固定进入桥段规划，业务代码不再读写此列；保留仅为兼容旧库（不做 DROP COLUMN）
    enable_bridge_planning = Column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
        comment="[已废弃] 桥段规划开关，流水线固定启用；字段保留仅为兼容旧库",
    )

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关联关系
    story_outlines = relationship("StoryOutline", back_populates="project", cascade="all, delete-orphan")
    plot_cards = relationship("PlotCard", back_populates="project", cascade="all, delete-orphan")
    plot_lines = relationship("PlotLine", back_populates="project", cascade="all, delete-orphan")
    chapter_outlines = relationship("ChapterOutline", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Project(id={self.id}, title={self.title})>"
