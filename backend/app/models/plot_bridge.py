"""V4.1 K2 桥段四章结构 - PlotBridge 模型（详见 v4_design.md §3.2.1）。

设计：一个桥段 ≈ 4 章，每章在桥段内有明确位置（C1/C2/C3/C4）。

字段：
- 桥段意图：goal / showoff_point / golden_finger_usage
- 4 章内容卡：c1_intro / c2_build / c3_payoff / c4_aftermath（4 段文本提示，
  桥段规划阶段 AI 生成，章纲展开阶段使用）
- 上下文衔接：prev_bridge_id / next_bridge_hook
- 状态：draft / ready / generating / completed

关联：
- 一个项目下 N 个桥段，按 order_index 排序
- 一个桥段挂 4 个 chapter_outline（chapter_outlines.bridge_id 反向关联）
- 可选属于一条 plot_line
"""
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db_base import Base


class PlotBridge(Base):
    """K2 桥段表 - 一个桥段约等于 4 章。"""

    __tablename__ = "plot_bridges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plot_line_id = Column(
        String(36),
        ForeignKey("plot_lines.id", ondelete="SET NULL"),
        nullable=True,
        comment="所属剧情线（可选，桥段可独立存在）",
    )

    # ---- V4.1 K2 分层契合：桥段 ↔ 剧情线节点（beat）绑定 ----
    # 设计：方案 C（分层契合）— 桥段是「主线节点的展开形式」，
    # 一个 beat 按 weight × estimated_chapters 分配章数，再按 4 章/桥段切成 N 个桥段。
    # 这些字段在 by_plot_line 规划模式下由 LLM 填充；free 模式下保持 NULL（向后兼容）。
    beat_index = Column(
        Integer,
        nullable=True,
        comment="所属节点 index（对应 PlotLine.timeline_data.beats[].index）；NULL 表示桥段不绑节点",
    )
    beat_coverage_start = Column(
        Float,
        nullable=True,
        comment="本桥段覆盖该节点的起始进度（0.0-1.0），用于章纲生成时推进 beat coverage",
    )
    beat_coverage_end = Column(
        Float,
        nullable=True,
        comment="本桥段覆盖该节点的结束进度（0.0-1.0）",
    )
    secondary_beats = Column(
        Text,
        nullable=True,
        comment="副线任务 JSON 数组：[{plot_line_id, line_title, line_type, beat_index, beat_title, beat_description, coverage_start, coverage_end}]，由 bridge_slot_planner 计算写入",
    )

    bridge_number = Column(
        Integer,
        nullable=False,
        comment="桥段序号（项目内全局递增）",
    )
    title = Column(
        String(200),
        nullable=False,
        comment="桥段标题，如『拜师云鹿书院』",
    )

    # ---- 核心字段：桥段意图 ----
    goal = Column(
        Text,
        nullable=False,
        comment="本桥段要解决的具体问题，如『求大儒收留家人』",
    )
    showoff_point = Column(
        Text,
        nullable=False,
        comment="装逼/爽点设计，如『即兴一首劝学诗征服大儒』",
    )
    payoff_type = Column(
        String(40),
        nullable=True,
        comment="兑现方式枚举（题材模板 payoff_types 之一，如 打脸 / 扮猪吃虎）；账本按类型统计避免长线套路重复",
    )
    golden_finger_usage = Column(
        Text,
        nullable=True,
        comment="本桥段如何使用金手指（如：诗词储备）",
    )

    # ---- 4 章内容卡（JSON 存储，简化挂载）----
    c1_intro = Column(
        Text,
        nullable=True,
        comment="C1 代入+信息差 设计：上半日常代入素材、下半信息差展示",
    )
    c2_build = Column(
        Text,
        nullable=True,
        comment="C2 拉扯+开装 设计：拉扯素材、章尾开装的具体动作",
    )
    c3_payoff = Column(
        Text,
        nullable=True,
        comment="C3 兑现爽点 设计：装逼的完整展开、配角反应",
    )
    c4_aftermath = Column(
        Text,
        nullable=True,
        comment="C4 善后+下一目标 设计：本桥段收尾事件、下一桥段引子",
    )

    # ---- 上下文衔接 ----
    prev_bridge_id = Column(
        String(36),
        ForeignKey("plot_bridges.id"),
        nullable=True,
        comment="上一桥段（用于 C1 代入处理）",
    )
    next_bridge_hook = Column(
        Text,
        nullable=True,
        comment="给下一桥段的钩子（C4 必须写）",
    )

    # ---- 生成溯源（2026-09 评审问题 H）----
    generation_meta = Column(
        Text,
        nullable=True,
        comment="本桥段最近一次 LLM 填充的 provenance JSON：模型/档位/题材模板/参考包维度/槽位填充与截断/业务输入/警告",
    )

    # ---- 状态 ----
    status = Column(
        String(20),
        default="draft",
        comment="draft / ready / generating / completed",
    )
    order_index = Column(Integer, nullable=True)

    # ---- 时间戳 ----
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ---- 关联关系 ----
    chapter_outlines = relationship(
        "ChapterOutline",
        back_populates="bridge",
        foreign_keys="[ChapterOutline.bridge_id]",
    )

    __table_args__ = (
        Index("idx_plot_bridge_project_order", "project_id", "order_index"),
        Index("idx_plot_bridge_project_number", "project_id", "bridge_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<PlotBridge(id={self.id[:8] if self.id else None}..., "
            f"number={self.bridge_number}, title={self.title!r})>"
        )
