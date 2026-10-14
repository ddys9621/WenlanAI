"""智能助笔请求模型。"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

AssistantSkill = Literal["continue", "rewrite", "polish", "review", "query"]


class AssistantSelection(BaseModel):
    start: int = Field(..., ge=0, description="选区在正文中的起始下标")
    end: int = Field(..., ge=0, description="选区结束下标（不含）")
    text: str = Field(..., min_length=1, max_length=8000, description="选区原文（须与正文逐字一致）")


class AssistantRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="作者的指令或问题")
    skill: Optional[AssistantSkill] = Field(None, description="显式选择的技能；不传由服务端判定")
    selection: Optional[AssistantSelection] = Field(None, description="正文选区（改写 / 润色必需）")
