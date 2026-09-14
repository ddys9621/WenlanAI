"""V3 仿写重构：参考包模型（独立资料库）

设计要点（参见 @/agent-docs/features/book_dissect_v3_imitation_design.md：4.1）：
- 一个 BookDissectTask 1:1 对应一个 ReferencePack
- 5 个 JSON 字段对应 7 个浏览 tab 中的 1-5 号（写作方法论 / 文风 / 结构手法 /
  角色塑造手法 / 世界观建模），均由 V3 阶段的 5 个新 generator 写入
- tab 0 概览取自任务元数据；tab 6 灵感语料直接复用 V2 现有的
  BookDissectChapterFact / BookDissectEntity / BookDissectEvent 表，不在此冗存
- status 跟踪生成进度，允许部分 generator 失败而不阻塞整体（在 generated_dimensions 记录哪些已就位）

V3.2 增量（synopsis 复活）：
- 行业最佳实践（NovelAI Lorebook / Sudowrite Story Bible / 主流 Hierarchical RAG）
  普遍把"故事类型骨架"作为粗粒度全局引导（写作 RAG 第 1 层）
- V2 SynopsisGenerator 当年走"复刻原书"错路被废弃；V3.2 重写为"抽类型骨架"
  （genre/premise/golden_finger/power_system 等抽象描述，禁出现具体专有名词）
- 新增 synopsis_json 列；与 5 个手法维度并列，用户可在 selector 选择是否启用

V3.2-P2 增量（entities/relations/events 模式三维度）：
- V2 已 LLM 抽好 entities/relations/events 完整数据，但其原始数据**含具体专有名词**，
  直接喂给 LLM 会引导复刻原书内容（违反 V3 哲学）
- 新增 3 个聚合统计维度，输出**类型分布 / 命名风格信号 / 节奏模式**等抽象特征，
  保留参考价值（让 LLM 知道"该题材常见角色类型分布""关系类型频谱""事件节奏"），
  不暴露具体名字（不出现 canonical_name）
- 这 3 维度由 pattern_generators 纯 SQL 聚合产出（无 LLM），写入下面 3 列
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db_base import Base


class ReferencePack(Base):
    """拆书 V3：参考包（仿写资料库的独立实体）"""

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

    # ---- 5 个 JSON 字段对应 7 tab 中的 1-5 号 ----
    methodology_json = Column(
        Text,
        nullable=True,
        comment="Tab1 写作方法论 JSON：金手指模式 / 钩子套路 / 打脸节奏 / 升级颗粒度 / 爽点密度",
    )
    style_json = Column(
        Text,
        nullable=True,
        comment="Tab2 文风范本 JSON：{prompt_content, name, description, traits...}",
    )
    structure_json = Column(
        Text,
        nullable=True,
        comment="Tab3 结构手法 JSON：开篇钩 / 中段冲突升级 / 结尾钩，含原书案例引用",
    )
    archetypes_json = Column(
        Text,
        nullable=True,
        comment="Tab4 角色塑造手法 JSON：主角/配角/反派的塑造模式与案例",
    )
    worldbuilding_json = Column(
        Text,
        nullable=True,
        comment="Tab5 世界观建模 JSON：时代设计 / 地点层级 / 规则平衡的建模思路与案例",
    )
    synopsis_json = Column(
        Text,
        nullable=True,
        comment=(
            "Tab6 故事类型骨架 JSON（V3.2 复活的 synopsis）："
            "genre_tag / core_premise / golden_finger_concept / power_system_overview / "
            "central_conflict / ultimate_goal / selling_points / target_audience_signals。"
            "严示「抽类型骨架不复刻内容」，作为 Story Bible 层用于全局引导。"
        ),
    )

    # ---- V3.2-P2：3 个聚合模式维度（不调 LLM，从 V2 表纯统计聚合产出） ----
    entities_json = Column(
        Text,
        nullable=True,
        comment=(
            "实体类型分布与命名信号 JSON："
            "{type_distribution, role_distribution, naming_style_signals, "
            "main_role_archetype_count}。"
            "禁含 canonical_name（仅给类型/数量/风格信号，避免引导 LLM 复刻原书人物）。"
        ),
    )
    relations_json = Column(
        Text,
        nullable=True,
        comment=(
            "关系类型频谱 JSON："
            "{category_distribution, top_relation_types, intra_protagonist_only_ratio}。"
            "禁含具体角色名，仅描述关系类型/类别在原书中的分布与频次。"
        ),
    )
    events_json = Column(
        Text,
        nullable=True,
        comment=(
            "事件节奏模式 JSON："
            "{type_distribution, importance_distribution, "
            "high_importance_chapter_density, total_chapters, total_events}。"
            "禁含具体事件标题/参与者，仅描述事件类型分布与跨章节节奏。"
        ),
    )

    # ---- V4.1 新增维度（桥段反推 + 角色档案，详见 v4_design.md §11）----
    bridges_json = Column(
        Text,
        nullable=True,
        comment=(
            "桥段范本库 JSON（V4.1 新增）："
            "{total_bridges_detected, standard_bridges, variant_bridges, "
            "bridge_types: [{type, count, typical_examples: [{chapters, goal, "
            "showoff_point, golden_finger_mode, chapter_summaries}]}], "
            "rhythm_stats, golden_finger_diversity}。"
            "由 BridgeDetector + BridgePatternAggregator 从 ChapterFact + Event 反推产出。"
        ),
    )
    character_archive_json = Column(
        Text,
        nullable=True,
        comment=(
            "完整角色档案 JSON（V4.1 新增）："
            "{protagonist_archetypes: [{name, intro_chapter, intro_technique, "
            "personality_arc, ability_progression, key_relationships, memorable_actions}], "
            "antagonist_progression, support_character_techniques}。"
            "由 CharacterArchiveBuilder 聚合 Entity + Relation + Event 产出。"
        ),
    )

    # ---- V4.4 K5 三档预压缩字段（详见 v4_design.md §10.1.1）----
    # 每维度三档：light≤200 token / medium≤600 token / deep≤1500 token
    # 由 DimensionPrecompressor 在拆书阶段一次性生成，运行时直接 SELECT 注入 prompt
    # 8 维度 × 3 档 = 24 个字段（corpus 不预压缩，依赖动态 BM25 检索）

    methodology_light = Column(Text, nullable=True, comment="V4.4 写作方法论 light 预压缩 ≤200 token")
    methodology_medium = Column(Text, nullable=True, comment="V4.4 写作方法论 medium 预压缩 ≤600 token")
    methodology_deep = Column(Text, nullable=True, comment="V4.4 写作方法论 deep 预压缩 ≤1500 token")

    style_light = Column(Text, nullable=True, comment="V4.4 文风范本 light 预压缩 ≤200 token")
    style_medium = Column(Text, nullable=True, comment="V4.4 文风范本 medium 预压缩 ≤600 token")
    style_deep = Column(Text, nullable=True, comment="V4.4 文风范本 deep 预压缩 ≤1500 token")

    structure_light = Column(Text, nullable=True, comment="V4.4 结构手法 light 预压缩 ≤200 token")
    structure_medium = Column(Text, nullable=True, comment="V4.4 结构手法 medium 预压缩 ≤600 token")
    structure_deep = Column(Text, nullable=True, comment="V4.4 结构手法 deep 预压缩 ≤1500 token")

    archetypes_light = Column(Text, nullable=True, comment="V4.4 角色塑造手法 light 预压缩 ≤200 token")
    archetypes_medium = Column(Text, nullable=True, comment="V4.4 角色塑造手法 medium 预压缩 ≤600 token")
    archetypes_deep = Column(Text, nullable=True, comment="V4.4 角色塑造手法 deep 预压缩 ≤1500 token")

    worldbuilding_light = Column(Text, nullable=True, comment="V4.4 世界观建模 light 预压缩 ≤200 token")
    worldbuilding_medium = Column(Text, nullable=True, comment="V4.4 世界观建模 medium 预压缩 ≤600 token")
    worldbuilding_deep = Column(Text, nullable=True, comment="V4.4 世界观建模 deep 预压缩 ≤1500 token")

    synopsis_light = Column(Text, nullable=True, comment="V4.4 全书弧线 light 预压缩 ≤200 token")
    synopsis_medium = Column(Text, nullable=True, comment="V4.4 全书弧线 medium 预压缩 ≤600 token")
    synopsis_deep = Column(Text, nullable=True, comment="V4.4 全书弧线 deep 预压缩 ≤1500 token")

    bridges_light = Column(Text, nullable=True, comment="V4.4 桥段范本 light 预压缩 ≤200 token")
    bridges_medium = Column(Text, nullable=True, comment="V4.4 桥段范本 medium 预压缩 ≤600 token")
    bridges_deep = Column(Text, nullable=True, comment="V4.4 桥段范本 deep 预压缩 ≤1500 token")

    character_archive_light = Column(Text, nullable=True, comment="V4.4 角色档案 light 预压缩 ≤200 token")
    character_archive_medium = Column(Text, nullable=True, comment="V4.4 角色档案 medium 预压缩 ≤600 token")
    character_archive_deep = Column(Text, nullable=True, comment="V4.4 角色档案 deep 预压缩 ≤1500 token")

    # ---- 流水线版本 ----
    pipeline_version = Column(
        Integer, nullable=False, default=2, server_default="2",
        comment="拆书流水线版本：2 = V2-V4 老包（只读，建议重新抽取）；5 = V5 拆书卡 / 情节单元 / 骨架",
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

    # ---- V4.4 K5 辅助方法：统一访问预压缩字段 ----
    DIMENSIONS_WITH_PRECOMPRESSION = (
        "methodology", "style", "structure", "archetypes",
        "worldbuilding", "synopsis", "bridges", "character_archive",
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
