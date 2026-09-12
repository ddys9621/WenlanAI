"""去 AI 味提示词的请求 / 响应 Schema：name / content 去首尾空白，空白即 422。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _non_blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("不能为空")
    return value


class DeaiPromptCreate(BaseModel):
    name: str = Field(..., max_length=100, description="提示词名称")
    content: str = Field(..., description="提示词正文")

    @field_validator("name", "content")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _non_blank(v)


class DeaiPromptUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    content: Optional[str] = None

    @field_validator("name", "content")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return _non_blank(v)


class DeaiPromptResponse(BaseModel):
    id: str
    project_id: str
    name: str
    content: str
    order_index: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
