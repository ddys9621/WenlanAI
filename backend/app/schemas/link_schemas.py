"""关联关系相关的 Pydantic 模型（章纲 ↔ 剧情线手工关联 + 章纲侧的关联视图）。"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional


class UnlinkRequest(BaseModel):
    """取消关联请求"""
    ids: List[str] = Field(..., description="要取消关联的ID列表", min_length=1)


class LinkPlotLinesToChapterRequest(BaseModel):
    """章纲关联剧情线请求"""
    plot_line_ids: List[str] = Field(..., description="剧情线ID列表", min_length=1)
    role: str = Field("main", description="角色类型: main(主线)/sub(支线)/character(角色线)")


class PlotLineWithLinks(BaseModel):
    """剧情线及其关联信息"""
    id: str
    title: str
    description: Optional[str]
    line_type: str
    chapter_count: int = Field(..., description="关联的章纲数量")
    card_count: int = Field(..., description="关联的剧情卡片数量")
    link_id: Optional[str] = Field(None, description="章纲-剧情线关联ID（用于更新覆盖度）")
    timeline_data: Optional[dict] = Field(None, description="时间线数据（JSON格式）")
    timeline_coverage: Optional[dict] = Field(None, description="节点覆盖度数据（JSON格式）")

    model_config = ConfigDict(from_attributes=True)


class PlotCardWithLinks(BaseModel):
    """剧情卡片及其关联信息"""
    id: str
    title: str
    content: Optional[str]
    card_type: str
    plot_line_count: int = Field(..., description="关联的剧情线数量")
    chapter_count: int = Field(..., description="关联的章纲数量")

    model_config = ConfigDict(from_attributes=True)
