"""去 AI 味诊断相关的请求 Schema。"""
from typing import List, Literal

from pydantic import BaseModel, Field


class DeaiReviewFeedbackRequest(BaseModel):
    """用户在修订弹窗里对一份诊断报告的勾选记录（免费的假阳性标注，见 deai_history）。"""
    mode: Literal["patch", "rewrite"] = Field("patch", description="patch=去 AI 味润色页签；rewrite=整章重写页签的重写方向")
    candidates: List[int] = Field(default_factory=list, description="当时展示为可勾选的 finding 下标（result.findings 里的位置）")
    selected: List[int] = Field(default_factory=list, description="用户最终勾着带入的 finding 下标")
