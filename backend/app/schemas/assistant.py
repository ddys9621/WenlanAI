"""全局智能助笔请求模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.writing_assistant import AssistantSelection


class AssistantPage(BaseModel):
    """作者发消息时所在的页面（只用来带上下文，不是权限边界）。"""
    page: str = Field("", max_length=60, description="页面路由，如 chapter-analysis / characters")
    label: str = Field("", max_length=120, description="页面名称，如「章节写作 · 第 3 章《旧宅》」")
    chapter_id: Optional[str] = Field(None, max_length=36)
    character_id: Optional[str] = Field(None, max_length=36)
    outline_id: Optional[str] = Field(None, max_length=36)
    location_id: Optional[str] = Field(None, max_length=36)
    selection: Optional[AssistantSelection] = Field(None, description="章节正文里选中的那段（须与正文逐字一致）")


class AssistantSendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    page: AssistantPage = Field(default_factory=AssistantPage)


class AuthorAnswer(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    choices: List[str] = Field(default_factory=list, max_length=8)
    text: str = Field("", max_length=4000)
    skipped: bool = False


class AssistantAnswerRequest(BaseModel):
    answers: List[AuthorAnswer] = Field(..., min_length=1, max_length=3)
