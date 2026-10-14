"""候选稿接口的请求模型。"""
from typing import Optional

from pydantic import BaseModel, Field


class CandidateAdoptRequest(BaseModel):
    content: Optional[str] = Field(None, description="作者在候选面板里改过的文本；不传则用候选原文")
    force: bool = Field(False, description="正文在生成后被修改过时仍然覆盖（当前正文会先存入历史版本）")
    auto_analyze: bool = Field(False, description="采用后自动排队分析本章")
