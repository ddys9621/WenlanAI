"""知识库（用户级、跨项目）：来源 kb_sources（一本参考书 / 一份资料）→ 条目 kb_entries。

- 条目按 (source_id, entry_key) 唯一：重新拆书按稳定键认回同一条
- body 原名版（给作者读）/ denamed_body 去名版（人名换成功能位，仿写注入用）
- generated_hash 记最近一次生成的内容；origin=author 的条目重新导入不覆盖，只标 upstream_changed
- SQLite 未开外键约束：删除来源时由调用方显式删条目
"""
import uuid

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, UniqueConstraint

from app.db_base import Base
from app.models.chapter_candidate import utcnow


class KbSource(Base):
    __tablename__ = "kb_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="dissect", comment="dissect 拆书 / manual 手工资料")
    title = Column(String(255), nullable=False, default="")
    author = Column(String(255), nullable=True)
    genre = Column(String(50), nullable=True)
    dissect_task_id = Column(String(36), nullable=True, unique=True, comment="kind=dissect 时对应的拆书任务")
    chapter_count = Column(Integer, nullable=False, default=0)
    total_words = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True, comment="作者备注")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class KbEntry(Base):
    __tablename__ = "kb_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), nullable=False, index=True)
    source_id = Column(String(36), nullable=False, index=True)
    entry_key = Column(String(120), nullable=False, comment="来源内稳定键：guide / synopsis / volume:2 / arc:12 / chapter:37 …")
    entry_type = Column(String(30), nullable=False)
    layer = Column(String(10), nullable=False, comment="index / fact / method / style")
    title = Column(String(255), nullable=False, default="")
    summary = Column(String(500), nullable=False, default="", comment="目录摘要：内容 + 何时读")
    body = Column(Text, nullable=False, default="")
    denamed_body = Column(Text, nullable=False, default="")
    data_json = Column(Text, nullable=True)
    tags = Column(Text, nullable=True, comment="JSON 数组")
    chapter_start = Column(Integer, nullable=True)
    chapter_end = Column(Integer, nullable=True)
    volume_index = Column(Integer, nullable=True)
    arc_index = Column(Integer, nullable=True)
    position = Column(Float, nullable=True, comment="全书相对位置 0-1（区间中点 / 全书章数）")
    sort_order = Column(Integer, nullable=False, default=0)
    search_text = Column(Text, nullable=False, default="", comment="NFKC 小写：键 + 标题 + 摘要 + 正文 + 标签")
    generated_hash = Column(String(64), nullable=False, default="")
    revision = Column(Integer, nullable=False, default=1)
    origin = Column(String(20), nullable=False, default="generated", comment="generated / author")
    status = Column(String(20), nullable=False, default="unreviewed", comment="unreviewed / confirmed")
    upstream_changed = Column(Integer, nullable=False, default=0, comment="作者版本之后拆书结果又变了")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("source_id", "entry_key", name="uq_kb_entry_source_key"),
        Index("idx_kb_entry_source_type", "source_id", "entry_type", "sort_order"),
    )


class KbProjectLink(Base):
    """项目的对标书：一个项目一本（主键就是 project_id），仿写方式决定生成时跟得多紧。"""

    __tablename__ = "kb_project_links"

    project_id = Column(String(36), primary_key=True)
    source_id = Column(String(36), nullable=False, index=True)
    mode = Column(String(10), nullable=False, default="borrow", comment="follow 跟写结构 / borrow 借鉴节奏 / style 只学文风 / off")
    volume_map = Column(Text, nullable=True, comment='作者指定的卷对标 JSON：{"本书卷号": 原书卷号}')
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class KnowledgeCitation(Base):
    """生成结果引用了哪条知识库条目：卷 / 单元（target_id = 卷id:单元序号）/ 章纲 / 候选稿。修订号不一致 = 过期。"""

    __tablename__ = "knowledge_citations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False)
    target_type = Column(String(20), nullable=False, comment="volume / unit / chapter_outline / chapter_candidate")
    target_id = Column(String(80), nullable=False)
    entry_id = Column(String(36), nullable=False)
    entry_revision = Column(Integer, nullable=False, default=1)
    source_id = Column(String(36), nullable=False)
    scene = Column(String(30), nullable=False, default="")
    label = Column(String(255), nullable=False, default="")
    reason = Column(String(500), nullable=False, default="")
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (Index("idx_kb_citation_target", "project_id", "target_type", "target_id"),)
