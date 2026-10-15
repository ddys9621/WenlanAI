"""参考包模型：一次拆书产出的资料包（独立资料库，可挂载到多个项目）。

- 一个 BookDissectTask 1:1 对应一个 ReferencePack
- 6 个维度 JSON 与作者自己的规划链对应：synopsis（全书骨架 ≈ 总纲）/ bridges（剧情单元库）/ methodology（写法手册）
  / structure（结构统计）/ character_archive（人物功能谱）/ style（文风指纹）；拆书卡检索（corpus）直接读拆书卡表
- 每维度另存 light / medium / deep 三档预压缩文本（dimension_compressor 在抽取完成时生成），运行时直接注入
- status 跟踪生成进度，允许部分维度失败而不阻塞整体（generated_dimensions 记录哪些已就位）
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class ReferencePack(Base):
    """参考包（仿写资料库的独立实体）"""

    __tablename__ = "reference_packs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="参考包ID")
    user_id = Column(String(50), nullable=False, index=True, comment="所有者用户ID")
    task_id = Column(
        String(36),
        ForeignKey("book_dissect_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="所属拆书任务（1:1）",
    )
    source_book_title = Column(
        String(255),
        nullable=False,
        comment="来源书标题（冗存自任务的 file_name 或用户自定义，方便资料库列表显示）",
    )

    # ---- 6 个维度 JSON ----
    methodology_json = Column(
        Text,
        nullable=True,
        comment="写法手册 JSON：开篇 / 分卷节奏 / 剧情单元设计 / 张弛节奏 / 成长颗粒度 / 特殊能力用法",
    )
    style_json = Column(
        Text,
        nullable=True,
        comment="文风指纹 JSON：{prompt_content, name, description, traits, metrics, examples...}",
    )
    structure_json = Column(
        Text,
        nullable=True,
        comment="结构统计 JSON（无 LLM）：节奏 / 章末钩子 / 张力十分位 / 剧情单元长度与强弱",
    )
    synopsis_json = Column(
        Text,
        nullable=True,
        comment="全书骨架 JSON（≈ 原书的总纲）：梗概 / 全书主线 / 特殊能力（可为「无」）/ 卖点 / 分卷 / 高光 / 长线伏笔",
    )

    bridges_json = Column(
        Text,
        nullable=True,
        comment="剧情单元库 JSON（键名沿用 bridges）：单元数 / 长度分布 / 兑现方式 / 强弱交替 / 典型单元",
    )
    character_archive_json = Column(
        Text,
        nullable=True,
        comment="人物功能谱 JSON：主角（含核心优势）/ 盟友 / 对手 / 功能位",
    )

    # ---- 三档预压缩：每维度 light≤200 token / medium≤600 token / deep≤1500 token（6 维 × 3 档 = 18 个字段）----

    methodology_light = Column(Text, nullable=True, comment="写作方法论 light 预压缩 ≤200 token")
    methodology_medium = Column(Text, nullable=True, comment="写作方法论 medium 预压缩 ≤600 token")
    methodology_deep = Column(Text, nullable=True, comment="写作方法论 deep 预压缩 ≤1500 token")

    style_light = Column(Text, nullable=True, comment="文风范本 light 预压缩 ≤200 token")
    style_medium = Column(Text, nullable=True, comment="文风范本 medium 预压缩 ≤600 token")
    style_deep = Column(Text, nullable=True, comment="文风范本 deep 预压缩 ≤1500 token")

    structure_light = Column(Text, nullable=True, comment="结构手法 light 预压缩 ≤200 token")
    structure_medium = Column(Text, nullable=True, comment="结构手法 medium 预压缩 ≤600 token")
    structure_deep = Column(Text, nullable=True, comment="结构手法 deep 预压缩 ≤1500 token")

    synopsis_light = Column(Text, nullable=True, comment="全书弧线 light 预压缩 ≤200 token")
    synopsis_medium = Column(Text, nullable=True, comment="全书弧线 medium 预压缩 ≤600 token")
    synopsis_deep = Column(Text, nullable=True, comment="全书弧线 deep 预压缩 ≤1500 token")

    bridges_light = Column(Text, nullable=True, comment="剧情单元库 light 预压缩 ≤200 token")
    bridges_medium = Column(Text, nullable=True, comment="剧情单元库 medium 预压缩 ≤600 token")
    bridges_deep = Column(Text, nullable=True, comment="剧情单元库 deep 预压缩 ≤1500 token")

    character_archive_light = Column(Text, nullable=True, comment="角色档案 light 预压缩 ≤200 token")
    character_archive_medium = Column(Text, nullable=True, comment="角色档案 medium 预压缩 ≤600 token")
    character_archive_deep = Column(Text, nullable=True, comment="角色档案 deep 预压缩 ≤1500 token")

    # ---- 流水线版本 ----
    pipeline_version = Column(
        Integer, nullable=False, default=5, server_default="5",
        comment="拆书流水线版本（参考包内容格式）",
    )

    # ---- 生成状态 ----
    status = Column(
        String(20),
        nullable=False,
        default="generating",
        comment="生成状态：generating(生成中) / ready(就绪) / partial(部分维度失败) / failed(全部失败)",
    )
    generated_dimensions = Column(
        Text,
        nullable=True,
        comment="JSON 数组：已成功生成的维度列表，如 ['methodology','style','bridges','character_archive']",
    )
    error_message = Column(Text, nullable=True, comment="失败信息（partial/failed 时填充）")

    # ---- 统一访问预压缩字段 ----
    DIMENSIONS_WITH_PRECOMPRESSION = (
        "methodology", "style", "structure", "synopsis", "bridges", "character_archive",
    )
    STRENGTH_LEVELS = ("light", "medium", "deep")

    def get_precompressed(self, dimension: str, strength: str) -> str | None:
        """读取指定维度+档位的预压缩文本。

        Args:
            dimension: 维度名（methodology/style/.../character_archive）
            strength: 档位（light/medium/deep）

        Returns:
            预压缩文本，未生成则返回 None
        """
        if dimension not in self.DIMENSIONS_WITH_PRECOMPRESSION:
            return None
        if strength not in self.STRENGTH_LEVELS:
            return None
        return getattr(self, f"{dimension}_{strength}", None)

    # ---- 时间戳 ----
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_reference_pack_user_status", "user_id", "status"),
        Index("idx_reference_pack_task", "task_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ReferencePack(id={self.id[:8] if self.id else None}..., "
            f"book={self.source_book_title!r}, status={self.status})>"
        )
