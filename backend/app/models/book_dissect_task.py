"""拆书任务模型 - 追踪上传参考书 → 拆解为创作素材的整个流程

与 AnalysisTask 的区别：
- 不挂任何项目/章节外键，因为拆书时项目尚未创建
- 全文不入库，落到磁盘 storage_path，只在 chapters_meta 存元信息
- result_json 仅存 V2 网文专有产物（项目骨架 / 文风 / 概览统计）
完整的角色 / 地点 / 关系 / 事件走专用表（见 book_dissect_entity / relation / event 等）
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class BookDissectTask(Base):
    """
    拆书任务表

    状态流转: pending -> running -> completed/failed/cancelled（cancelled = 用户手动停止，可重新抽取）
    阶段切片（V2）: splitting -> scanning -> dictionary -> extracting -> aggregating -> synthesizing -> done
    """
    __tablename__ = "book_dissect_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="任务ID")
    user_id = Column(String(50), nullable=False, index=True, comment="用户ID")

    # 任务状态
    status = Column(String(20), nullable=False, default='pending',
                    comment="任务状态: pending/running/completed/failed/cancelled")
    progress = Column(Integer, default=0, comment="进度 0-100")
    stage = Column(String(50), nullable=True,
                   comment="当前阶段：splitting/scanning/dictionary/extracting/aggregating/synthesizing/done")
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
                         comment="V2 网文专有产物（项目骨架/文风/概览统计）")

    # 引擎版本字段（仍保留以识别存量老任务；新任务统一为 2）
    version = Column(Integer, default=2, comment="拆书引擎版本；当前仅使用 V2")
    extraction_phase = Column(String(50), nullable=True,
                              comment="V2 细粒度阶段：scanning/dictionary/extracting/aggregating/synthesizing")
    chapters_total = Column(Integer, default=0, comment="V2 计划逐章抽取的章节总数（采样模式可少于 chapter_count）")
    chapters_extracted = Column(Integer, default=0, comment="V2 已成功抽取的章节数")
    chapters_failed = Column(Integer, default=0, comment="V2 抽取失败的章节数")
    sampling_mode = Column(String(20), default="all",
                           comment="V2 采样模式：all(全部)/every_n(每隔N章)/key_only(关键章节)")
    sampling_param = Column(Integer, default=1, comment="V2 采样参数（如 every_n 模式下的 N）")

    # V3.1 字段
    extraction_engine = Column(String(20), default="auto",
                               comment="V3.1 抽取引擎：auto(按上下文自动分批)/chunked(逐章)/long_context(整本一批)")

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
