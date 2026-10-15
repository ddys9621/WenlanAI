"""参考包 API Schema

设计要点：
- 列表项 (ReferencePackSummary) 不返回维度 JSON 字段，避免列表加载过重
- 详情 (ReferencePackDetail) 一次返回全部维度内容
- 维度内部结构使用 Dict[str, Any]，便于 prompt 演进时灵活扩展
- 项目挂载关联使用独立的 schema，包含默认引用配置

维度集合：synopsis（全书骨架 ≈ 总纲）/ bridges（剧情单元库）/ style / character_archive / methodology / structure / corpus。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 参考包列表 / 详情
# ============================================================


class ReferencePackSummary(BaseModel):
    """参考包列表项（不含 5 tab 详细内容，列表加载用）"""

    id: str
    user_id: str
    task_id: str
    source_book_title: str
    status: Literal["generating", "ready", "partial", "failed"]
    generated_dimensions: List[str] = Field(
        default_factory=list,
        description="已成功生成的维度（synopsis/bridges/style/character_archive/methodology/structure）",
    )
    pipeline_version: int = Field(default=5, description="拆书流水线版本（参考包内容格式）")
    error_message: Optional[str] = None
    attached_project_count: int = Field(
        default=0,
        description="已挂载到的项目数（便于用户判断是否仍在使用）",
    )
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReferencePackDetail(BaseModel):
    """参考包详情（含全部维度内容；详情页一次返回）"""

    id: str
    user_id: str
    task_id: str
    source_book_title: str
    status: Literal["generating", "ready", "partial", "failed"]
    generated_dimensions: List[str] = Field(default_factory=list)
    pipeline_version: int = Field(default=5, description="拆书流水线版本（参考包内容格式）")
    error_message: Optional[str] = None

    # 六个维度
    synopsis: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "全书骨架（≈ 原书的总纲）：genre_tag / premise / main_plot / main_conflict / golden_finger（没有为「无」）/ "
            "selling_points / main_tropes / growth_route / power_system / ultimate_goal / volumes / high_points / "
            "long_foreshadowing / opening_strategy"
        ),
    )
    bridges: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "剧情单元库：arc_count / avg_arc_length / arc_length_distribution / payoff_type_distribution / payoff_density / "
            "typical_arcs / role_pattern / unit_rhythm / relief_after_strong；全部剧情单元走 /book-dissect/{task_id}/arcs"
        ),
    )
    style: Optional[Dict[str, Any]] = Field(
        None,
        description="文风指纹：name / description / prompt_content / traits / dialogue_style / narration_habits / avoid_list / metrics / examples",
    )
    character_archive: Optional[Dict[str, Any]] = Field(
        None,
        description="人物功能谱：protagonist（含 advantage 核心优势）/ allies / antagonists / function_slots",
    )
    methodology: Optional[Dict[str, Any]] = Field(
        None,
        description="写法手册：opening_pattern / volume_rhythm / unit_design / tension_rhythm / growth_progression / advantage_usage",
    )
    structure: Optional[Dict[str, Any]] = Field(
        None,
        description="结构统计（无 LLM）：节奏 / 钩子 / 兑现密度 / 张力十分位 / 剧情单元长度与强弱",
    )

    attached_project_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


# ============================================================
# 项目挂载关联
# ============================================================


# 7 个引用维度：6 个参考包 JSON 维度 + corpus（拆书卡检索）
# 注意：必须与前端 @/frontend/src/types/reference_pack.ts 的 ReferenceDimension 保持一致，
# 否则 deep 档挂载会 422（请求校验）/500（响应校验）。
ReferenceDimension = Literal[
    "synopsis", "bridges", "style", "character_archive", "methodology", "structure",
    "corpus",
]
ReferenceStrength = Literal["light", "medium", "deep"]


class AttachReferencePackRequest(BaseModel):
    """挂载参考包到项目的请求 body"""

    pack_id: str = Field(..., description="要挂载的参考包 ID")
    default_dimensions: Optional[List[ReferenceDimension]] = Field(
        default=None,
        description="默认引用维度（一键仿写弹板的初始勾选状态）；省略则按 strength 推断",
    )
    default_strength: ReferenceStrength = Field(
        default="medium",
        description="默认参考强度：light(仅文风) / medium(文风+方法论) / deep(全维度)",
    )


class UpdateAttachmentRequest(BaseModel):
    """更新已挂载参考包的默认配置（PATCH）"""

    default_dimensions: Optional[List[ReferenceDimension]] = None
    default_strength: Optional[ReferenceStrength] = None


class ProjectReferencePackResponse(BaseModel):
    """项目已挂载参考包列表项（含来源参考包元信息）"""

    id: str = Field(..., description="挂载关联表主键")
    project_id: str
    pack_id: str
    pack_summary: ReferencePackSummary = Field(..., description="冗存参考包元信息便于前端展示")
    default_dimensions: List[ReferenceDimension] = Field(default_factory=list)
    default_strength: ReferenceStrength = "medium"
    attached_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 操作响应
# ============================================================


class AttachReferencePackResponse(BaseModel):
    """挂载成功响应"""

    attachment_id: str
    project_id: str
    pack_id: str
    default_dimensions: List[ReferenceDimension]
    default_strength: ReferenceStrength
