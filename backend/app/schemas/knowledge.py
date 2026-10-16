"""知识库 API Schema：来源（书架）/ 条目摘要与详情 / 作者修改 / 检索结果。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class KbSourceOut(BaseModel):
    id: str
    kind: str
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    dissect_task_id: Optional[str] = None
    chapter_count: int = 0
    total_words: int = 0
    notes: Optional[str] = None
    entry_counts: Dict[str, int] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class KbSourceUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    author: Optional[str] = Field(None, max_length=255)
    genre: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=20000)


class KbEntrySummaryOut(BaseModel):
    id: str
    source_id: str
    entry_key: str
    entry_type: str
    layer: str
    title: str
    summary: str
    chapter_start: Optional[int] = None
    chapter_end: Optional[int] = None
    volume_index: Optional[int] = None
    arc_index: Optional[int] = None
    origin: str
    status: str
    upstream_changed: bool = False
    revision: int = 1


class KbEntryOut(KbEntrySummaryOut):
    body: str
    denamed_body: str
    data: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    position: Optional[float] = None


class KbEntryUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, max_length=200000)
    denamed_body: Optional[str] = Field(None, max_length=200000)


class KbSearchHit(KbEntrySummaryOut):
    source_title: str


class KbSearchOut(BaseModel):
    items: List[KbSearchHit]
    total: int


KbMode = Literal["follow", "borrow", "style", "off"]
KbScene = Literal["worldview", "characters", "story_outline", "volume_skeleton", "volume_detail", "unit_outline", "chapter"]


class KbProjectLinkIn(BaseModel):
    source_id: str
    mode: KbMode = "borrow"
    volume_map: Dict[str, int] = Field(default_factory=dict, description="本书卷号 → 原书卷号；空 = 按全书位置自动对齐")


class KbSourceVolume(BaseModel):
    index: int
    title: str
    chapter_start: int
    chapter_end: int


class KbProjectLinkOut(BaseModel):
    source_id: str
    source_title: str
    mode: KbMode
    volume_map: Dict[str, int] = Field(default_factory=dict)
    source_chapter_count: int = 0
    source_volumes: List[KbSourceVolume] = Field(default_factory=list)
    dissected_range: Optional[List[int]] = None


class KbProjectLinkView(BaseModel):
    link: Optional[KbProjectLinkOut] = None


class KbPreviewIn(BaseModel):
    scene: KbScene
    volume_id: Optional[str] = None
    unit_index: Optional[int] = None
    chapter_outline_id: Optional[str] = None
    kb_chapter: Optional[int] = Field(None, ge=1)


class KbRefOut(BaseModel):
    key: str
    entry_id: str
    entry_type: str
    label: str
    prompt_label: str
    reason: str


class KbPreviewOut(BaseModel):
    scene: str
    mode: str
    text: str
    style: str
    ref_instruction: str
    refs: List[KbRefOut]


class KbCitationOut(BaseModel):
    entry_id: str
    source_id: str
    label: str
    reason: str
    scene: str
    stale: bool
