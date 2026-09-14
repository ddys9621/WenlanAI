"""拆书功能的 Pydantic 模型

V1 采样式结果 schema（DissectResult / DissectProjectSchema 等）已随 V1 逻辑一同移除；
V2-V4 的浏览 schema（章节事实 / 字典 / 实体 / 关系 / 事件 / 概览）随实体图谱抽取核心一并移除。
前端只渲染 V5 视图（拆书卡 / 情节单元 / 参考包），老任务只读展示参考包。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 章节元信息
# ============================================================


class ChapterMetaSchema(BaseModel):
    """切分后的章节元信息（不含正文）"""
    number: int = Field(..., description="章节序号（按出现顺序重新编号，从 1 开始）")
    title: str = Field(..., description="纯标题（已剥离序号前缀）")
    raw_title: str = Field(..., description="原始标题行")
    word_count: int = Field(..., description="正文字数（粗略中文字符 + 英文单词数）")
    kind: str = Field(..., description="章节类型：chapter/special/english/preamble")


# ============================================================
# 拆书任务状态
# ============================================================


class BookDissectTaskResponse(BaseModel):
    """拆书任务的完整状态响应"""
    id: str
    user_id: str
    status: str = Field(..., description="pending/running/completed/failed/cancelled")
    progress: int = Field(0, description="0-100")
    stage: Optional[str] = Field(None, description="当前阶段")
    error_message: Optional[str] = None

    file_name: Optional[str] = None
    file_size: int = 0
    encoding: Optional[str] = None
    chapter_count: int = 0
    total_words: int = 0
    chapters_meta: Optional[List[ChapterMetaSchema]] = None

    # 引擎版本字段：老任务 2（V2-V4 知识图谱抽取，只读）；新任务统一为 5
    version: int = Field(default=2, description="拆书引擎版本：2 = V2-V4 老引擎；5 = V5 拆书卡 / 情节单元 / 骨架")
    extraction_phase: Optional[str] = Field(
        default=None,
        description="细粒度阶段：V5 为 splitting/cards/arcs/skeleton/style/pack/done；V2 老任务为 scanning/dictionary/extracting/aggregating/synthesizing",
    )
    chapters_total: int = Field(default=0, description="V2 计划逐章抽取的章节总数")
    chapters_extracted: int = Field(default=0, description="V2 已成功抽取的章节数")
    chapters_failed: int = Field(default=0, description="V2 抽取失败的章节数")
    sampling_mode: str = Field(default="all", description="V2 采样模式：all/every_n/key_only")
    sampling_param: int = Field(default=1, description="V2 采样参数")
    extraction_engine: str = Field(
        default="auto",
        description="V3.1 抽取引擎：auto/chunked/long_context",
    )
    chapters_per_request: int = Field(default=0, description="每次 LLM 请求抽取的章节数；0 = 自动规划")
    chapter_limit: int = Field(default=0, description="只抽取前 N 章；0 = 全部")
    job_id: Optional[str] = Field(
        default=None,
        description="正在运行的抽取对应的 ai_jobs 任务 id（前端据此接入通用 AI 任务弹窗 / 托盘）；未运行为 null",
    )

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 上传响应
# ============================================================


class BookDissectUploadResponse(BaseModel):
    """文件上传后立即返回的响应（不等 LLM）"""
    task_id: str = Field(..., description="任务 ID，后续轮询用")
    file_name: str
    file_size: int = Field(..., description="字节数")
    encoding: str = Field(..., description="识别出的编码")
    chapter_count: int
    total_words: int
    preview: List[ChapterMetaSchema] = Field(
        default_factory=list,
        description="前若干章预览（默认前 10 章），便于用户确认切分质量",
    )


# ============================================================
# 应用到向导请求 —— V3 R6 已废弃
# ============================================================
# ApplyToWizardRequest / ApplyToWizardResponse 已随 R6 移除。
# 端点 POST /api/book-dissect/{task_id}/apply-to-wizard 现统一返 410 Gone，
# 详见 @/backend/app/api/book_dissect.py 的 DEPRECATION_DETAIL。
#
# V1 采样式抽取 schema（DissectResult / DissectProjectSchema / DissectWorldSchema /
# DissectCharacterSchema / DissectOutlineSchema / DissectStyleSchema）已同步随 V1 逻辑移除。
# 老版 result_json 在 BookDissectTaskResponse 不再返回。


# ============================================================
# 启动抽取 / 分批预估
# ============================================================


class V2StartExtractionRequest(BaseModel):
    """V2 启动抽取的可选参数"""
    sampling_mode: str = Field(default="all", description="all / every_n / key_only")
    sampling_param: int = Field(default=1, description="例如 every_n 模式下的 N")
    extraction_engine: str = Field(
        default="auto",
        description="抽取引擎：auto(按模型上下文自动分批)/chunked(逐章)/long_context(整本一批)",
    )
    chapters_per_request: int = Field(
        default=0, ge=0,
        description="每次 LLM 请求抽取的章节数；0 = 按模型上下文 / Max Tokens 自动规划",
    )
    chapter_limit: int = Field(
        default=0, ge=0,
        description="只抽取前 N 章（先截取再采样）；0 = 全部章节",
    )


class ExtractionPlanResponse(BaseModel):
    """启动抽取前的分批预估（不调 LLM，按 chapters_meta 字数估算）"""
    chapter_count: int = Field(..., description="全书章节数")
    target_chapters: int = Field(..., description="按 chapter_limit + 采样选出的章节数")
    batch_count: int = Field(..., description="抽取阶段的 LLM 请求次数（未计失败重试）")
    mode: str = Field(..., description="single(逐章) / batched(分批) / one_shot(整本一批)")
    chapters_per_request: int = Field(..., description="实际生效的单批章数上限")
    max_chapters_by_output: int = Field(..., description="按 Max Tokens 估算单批最多可稳定输出的章数")
    model: str = Field(default="", description="当前模型名")
    context_window: int = Field(default=0, description="模型上下文窗口（0 = 未知，已按保守值规划）")
    max_tokens: int = Field(default=0, description="用户 Max Tokens 设置")
    dictionary_calls: int = Field(..., description="字典分类 LLM 调用次数；V5 流水线不做字典分类，恒为 0（保留字段兼容前端）")
    post_calls: int = Field(..., description="拆书卡之后的 LLM 调用估算：情节单元 + 阶段划分 + 骨架 / 人物谱 / 手册 + 文风定性与例句")
    arc_calls: int = Field(default=0, description="其中情节单元识别的轮数 = ceil(目标章数 / arc_window)")
    arc_window: int = Field(default=0, description="情节单元识别每轮喂的拆书卡数（按模型上下文 / Max Tokens 规划，8-60）")
    estimated_llm_calls: int = Field(
        ..., description="预计 LLM 调用总数下限 = batch_count + post_calls（不含批失败拆半重试与 JSON 二次修复）",
    )
    warnings: List[str] = Field(default_factory=list)


# ============================================================
# V5：拆书卡 / 情节单元
# ============================================================


class ChapterCardListItem(BaseModel):
    """拆书卡精简行（列表用，不含章纲正文）。"""
    chapter_number: int
    title: str = ""
    function_tags: List[str] = Field(default_factory=list)
    pace: str = "中"
    tension: int = 3
    ending_hook_type: str = "无"
    payoff_count: int = 0
    word_count: int = 0
    extraction_status: str = "success"


class ChapterCardDetail(BaseModel):
    """整张拆书卡（v5_types.ChapterCard 字段 + 抽取状态）。"""
    model_config = ConfigDict(extra="ignore")
    chapter_number: int
    title: str = ""
    outline: str = ""
    function_tags: List[str] = Field(default_factory=list)
    pace: str = "中"
    tension: int = 3
    emotion_tone: str = ""
    ending_hook_type: str = "无"
    ending_hook_text: str = ""
    payoff_points: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    characters: List[str] = Field(default_factory=list)
    protagonist_delta: str = "无"
    new_settings: List[str] = Field(default_factory=list)
    word_count: int = 0
    truncated_input: bool = False
    extraction_status: str = "success"
    extraction_error: Optional[str] = None


class StoryArcSchema(BaseModel):
    """情节单元（v5_types.StoryArc 字段）。"""
    model_config = ConfigDict(extra="ignore")
    arc_index: int
    start_chapter: int
    end_chapter: int
    title: str = ""
    function: str = ""
    boundary_reason: str = ""
    structure: str = ""
    protagonist_chain: str = ""
    emotion_curve: str = ""
    payoff: str = ""
    payoff_type: str = "无强爽点"
    golden_finger_usage: str = "无"
    character_changes: str = ""
    gains_costs: str = ""
    foreshadowing: str = ""
    chapter_roles: Dict[str, str] = Field(default_factory=dict)
    tension_peak_chapter: Optional[int] = None
    origin: str = "llm"
