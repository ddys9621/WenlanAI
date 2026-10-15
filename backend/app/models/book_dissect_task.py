"""拆书任务模型 - 追踪上传参考书 → 拆解为创作素材的整个流程

与 AnalysisTask 的区别：
- 不挂任何项目/章节外键，因为拆书时项目尚未创建
- 全文不入库，落到磁盘 storage_path，只在 chapters_meta 存元信息
- result_json 只存抽取结果概览（参考包 ID / 生成的维度 / 章节与单元计数）
拆书卡在 book_dissect_chapter_facts，剧情单元在 book_dissect_story_arcs，各维度产物在 reference_packs
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class BookDissectTask(Base):
    """
    拆书任务表

    状态流转: pending -> running -> completed/failed/cancelled（cancelled = 用户手动停止，可重新抽取）
    阶段: split_done -> queued -> splitting -> cards -> arcs -> skeleton -> style -> pack -> done
    """
    __tablename__ = "book_dissect_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="任务ID")
    user_id = Column(String(50), nullable=False, index=True, comment="用户ID")

    # 任务状态
    status = Column(String(20), nullable=False, default='pending',
                    comment="任务状态: pending/running/completed/failed/cancelled")
    progress = Column(Integer, default=0, comment="进度 0-100")
    stage = Column(String(50), nullable=True,
                   comment="当前阶段：split_done/queued/splitting/cards/arcs/skeleton/style/pack/done")
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 上传文件信息
    file_name = Column(String(255), nullable=True, comment="原始文件名")
    file_size = Column(Integer, default=0, comment="文件字节数")
    encoding = Column(String(20), nullable=True, comment="识别出的编码：utf-8/gbk/gb18030 等")
    storage_path = Column(String(500), nullable=True, comment="全文磁盘存储路径")

    # 切分元信息（不含正文）
    chapter_count = Column(Integer, default=0, comment="切分出的章节数")
    total_words = Column(Integer, default=0, comment="全书字数（粗略）")
    chapters_meta = Column(Text, nullable=True,
                           comment="章节元信息 JSON: [{number, title, raw_title, word_count, kind}, ...]")

    # 拆解结果（完成后填充）
    result_json = Column(Text, nullable=True,
                         comment="抽取结果概览 JSON：pack_id / generated_dimensions / 章节与单元计数")

    # 抽取流水线版本（与参考包 pipeline_version 一致）
    version = Column(Integer, default=5, comment="拆书流水线版本")
    extraction_phase = Column(String(50), nullable=True, comment="细粒度阶段（同 stage）")
    chapters_total = Column(Integer, default=0, comment="计划抽取拆书卡的章节总数（采样模式可少于 chapter_count）")
    chapters_extracted = Column(Integer, default=0, comment="已成功抽出拆书卡的章节数")
    chapters_failed = Column(Integer, default=0, comment="抽取失败的章节数")
    sampling_mode = Column(String(20), default="all",
                           comment="采样模式：all(全部)/every_n(每隔N章)/key_only(关键章节)")
    sampling_param = Column(Integer, default=1, comment="采样参数（如 every_n 模式下的 N）")

    extraction_engine = Column(String(20), default="auto",
                               comment="抽取引擎：auto(按上下文自动分批)/chunked(逐章)/long_context(整本一批)")

    # 分批抽取字段
    chapters_per_request = Column(Integer, default=0,
                                  comment="每次 LLM 请求抽取的章节数；0 = 按模型上下文 / Max Tokens 自动规划")
    chapter_limit = Column(Integer, default=0,
                           comment="只抽取前 N 章（在采样之前截取）；0 = 全部章节")

    # 时间戳
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    started_at = Column(DateTime, nullable=True, comment="开始执行时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    __table_args__ = (
        Index('idx_book_dissect_user_status', 'user_id', 'status'),
        Index('idx_book_dissect_status', 'status'),
    )

    def __repr__(self):
        return (
            f"<BookDissectTask(id={self.id[:8]}..., user={self.user_id}, "
            f"status={self.status}, stage={self.stage}, progress={self.progress})>"
        )
