"""故事账本 API 的请求体。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PromiseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: Optional[str] = Field(None, max_length=1000)
    promise_type: Literal["foreshadow", "promise", "mystery", "conflict"] = "foreshadow"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    source_chapter_number: int = Field(..., ge=1)
    deadline_chapter: Optional[int] = Field(None, ge=1)


class PromiseUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, max_length=1000)
    promise_type: Optional[Literal["foreshadow", "promise", "mystery", "conflict"]] = None
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None
    deadline_chapter: Optional[int] = Field(None, ge=0, description="0 = 清除计划回收章")
    status: Optional[Literal["open", "resolved", "abandoned"]] = None
    resolved_chapter_number: Optional[int] = Field(None, ge=1)
    note: Optional[str] = Field(None, max_length=1000)


class PromiseMerge(BaseModel):
    merge_ids: List[str] = Field(..., min_length=1, max_length=50)


class StateCorrectionCreate(BaseModel):
    character_name: str = Field("", max_length=100)
    chapter_number: int = Field(..., ge=1)
    signal_type: Literal["life_state", "location", "realm", "item", "injury", "goal", "ability", "story_time"]
    signal_key: Optional[str] = Field(None, max_length=200)
    signal_value: str = Field(..., max_length=30)
    note: Optional[str] = Field(None, max_length=500)


class BatchAnalyzeRequest(BaseModel):
    from_chapter: int = Field(1, ge=1)
    to_chapter: int = Field(..., ge=1)
    mode: Literal["missing", "stale", "all"] = "stale"
