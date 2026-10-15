"""章纲相关的 Pydantic 模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Optional, List, Dict
from datetime import datetime


class ChapterOutlineBase(BaseModel):
    """章纲基础模型 - 专业网文版"""
    chapter_number: int = Field(..., description="章节序号", ge=1)
    title: str = Field(..., description="章节标题", max_length=200)
    # 场景信息（新增）
    scene: Optional[str] = Field(None, description="场景地点，如'拳击场→后台'", max_length=200)
    pov: Optional[str] = Field(None, description="视角角色名", max_length=100)
    # 剧情信息
    plot_points: Optional[str] = Field(None, description="剧情要点（含情感变化），300-400字")
    # 章节契约：开头承接 / 写到哪停 / 不能提前发生的事
    entry_state: Optional[str] = Field(None, description="进入状态：本章开头人物 / 地点 / 局势（承接上一章结尾）")
    exit_state: Optional[str] = Field(None, description="退出状态：最后一个关键事件完成后停在哪")
    # 旧字段（保留兼容）
    summary: Optional[str] = Field(None, description="章节摘要（已废弃，保留兼容旧数据）")
    # 系统字段
    target_word_count: int = Field(3000, description="目标字数", ge=500, le=10000)
    order_index: Optional[int] = Field(None, description="排序序号")


class ChapterOutlineCreate(ChapterOutlineBase):
    """创建章纲请求模型"""
    project_id: str = Field(..., description="项目ID")
    key_events: Optional[List[str]] = Field(None, description="关键事件列表，最后一条为章末钩子")
    characters_involved: Optional[List[str]] = Field(None, description="涉及角色名称列表")
    forbidden: Optional[List[str]] = Field(None, description="禁止事项：本章不能提前发生 / 揭晓的事")
    volume_id: Optional[str] = Field(None, description="所属卷纲")
    unit_index: Optional[int] = Field(None, description="所属剧情单元序号", ge=1)


class ChapterOutlineUpdate(BaseModel):
    """更新章纲请求模型"""
    chapter_number: Optional[int] = Field(None, description="章节序号", ge=1)
    title: Optional[str] = Field(None, description="章节标题", max_length=200)
    # 场景信息（新增）
    scene: Optional[str] = Field(None, description="场景地点", max_length=200)
    pov: Optional[str] = Field(None, description="视角角色名", max_length=100)
    # 剧情信息
    plot_points: Optional[str] = Field(None, description="剧情要点（含情感变化）")
    entry_state: Optional[str] = Field(None, description="进入状态")
    exit_state: Optional[str] = Field(None, description="退出状态")
    forbidden: Optional[List[str]] = Field(None, description="禁止事项")
    # 旧字段（保留兼容）
    summary: Optional[str] = Field(None, description="章节摘要（已废弃）")
    # 系统字段
    target_word_count: Optional[int] = Field(None, description="目标字数", ge=500, le=10000)
    order_index: Optional[int] = Field(None, description="排序序号")
    key_events: Optional[List[str]] = Field(None, description="关键事件列表，最后一条为章末钩子")
    characters_involved: Optional[List[str]] = Field(None, description="涉及角色名称列表")


class ChapterOutlineResponse(ChapterOutlineBase):
    """章纲响应模型"""
    id: str = Field(..., description="章纲ID")
    project_id: str = Field(..., description="项目ID")
    key_events: Optional[List[str]] = Field(None, description="关键事件列表，最后一条为章末钩子")
    characters_involved: Optional[List[str]] = Field(None, description="涉及角色名称列表")
    forbidden: Optional[List[str]] = Field(None, description="禁止事项")
    narrative_tasks: Optional[Dict[str, Any]] = Field(
        None, description="本章叙事任务：{resolve:[{promise_id,title,how}], advance:[...], plant:[{title,content,payoff_after}]}",
    )
    review_status: str = Field("confirmed", description="draft = AI 草拟待确认；confirmed = 已确认")
    confirmed_at: Optional[datetime] = Field(None, description="确认时间")
    upstream_stale: bool = Field(False, description="上游（卷纲 / 总纲）已修改，建议核对")
    upstream_reason: Optional[str] = Field(None, description="上游改了什么")
    volume_id: Optional[str] = Field(None, description="所属卷纲")
    unit_index: Optional[int] = Field(None, description="所属剧情单元序号")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    plot_cards: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="关联的剧情卡片列表（用于统计）")
    plot_card_count: int = Field(0, description="关联的剧情卡片数量")

    model_config = ConfigDict(from_attributes=True, extra="allow")  # 允许额外字段


class ChapterOutlineReorderRequest(BaseModel):
    """章纲重排序请求模型"""
    orders: List[dict] = Field(..., description="排序列表，格式：[{id: str, order_index: int, chapter_number: int}]")


class ChapterOutlineListResponse(BaseModel):
    """章纲列表响应模型"""
    total: int = Field(..., description="总数量")
    items: List[ChapterOutlineResponse] = Field(..., description="章纲列表")


class ChapterOutlineBatchCreateRequest(BaseModel):
    """批量创建章纲请求模型"""
    project_id: str = Field(..., description="项目ID")
    outlines: List[ChapterOutlineCreate] = Field(..., description="章纲列表")
