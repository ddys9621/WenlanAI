"""拆书结果（reference_packs 表）的 Schema：拆书页 GET /book-dissect/{task_id}/result 读它。

设计要点：
- 列表项 (ReferencePackSummary) 不返回维度 JSON 字段，避免列表加载过重
- 详情 (ReferencePackDetail) 一次返回全部维度内容
- 维度内部结构使用 Dict[str, Any]，便于 prompt 演进时灵活扩展

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
