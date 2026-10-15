"""卷纲接口的请求体。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class VolumeUnitIn(BaseModel):
    title: str = ""
    chapter_start: Optional[int] = None
    chapter_end: Optional[int] = None
    story: str = ""
    turn: str = ""


class VolumeFields(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = None
    goal: Optional[str] = None
    climax: Optional[str] = None
    ending_hook: Optional[str] = None
    review_note: Optional[str] = None
    chapter_start: Optional[int] = Field(default=None, ge=1)
    chapter_end: Optional[int] = Field(default=None, ge=1)
    units: Optional[list[VolumeUnitIn]] = None
    threads: Optional[list[str]] = None


class VolumePlanRequest(BaseModel):
    total_chapters: Optional[int] = Field(default=None, ge=1, le=10000, description="全书章数；不填用项目设置")
    volume_count: Optional[int] = Field(default=None, ge=1, le=100, description="卷数；不填按篇幅估算")
    instruction: str = Field(default="", max_length=4000)
    model: Optional[str] = None


class VolumeGenerateRequest(BaseModel):
    instruction: str = Field(default="", max_length=4000)
    model: Optional[str] = None
