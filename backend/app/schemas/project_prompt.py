"""项目自定义提示词的请求 Schema：content 去首尾空白；允许空串（= 这一段不用）。"""
from pydantic import BaseModel, Field, field_validator


class ProjectPromptSave(BaseModel):
    content: str = Field(..., description="作者改写后的提示词")

    @field_validator("content")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()
