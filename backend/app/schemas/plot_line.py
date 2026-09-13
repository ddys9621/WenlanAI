"""剧情线相关的 Pydantic 模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class PlotLineBase(BaseModel):
    """剧情线基础模型"""
    title: str = Field(..., description="剧情线标题", max_length=200)
    description: Optional[str] = Field(None, description="剧情线描述")
    line_type: str = Field("main", description="剧情线类型：main/sub/character")
    order_index: Optional[int] = Field(None, description="排序序号")
    estimated_chapters: Optional[int] = Field(None, description="预计章节数", ge=1)


class PlotLineCreate(PlotLineBase):
    """创建剧情线请求模型"""
    project_id: str = Field(..., description="项目ID")
    story_outline_id: Optional[str] = Field(None, description="关联的大纲ID")
    plot_cards: Optional[List[str]] = Field(None, description="关联的剧情卡片ID列表")
    timeline_data: Optional[Dict[str, Any]] = Field(None, description="时间线数据")


class PlotLineUpdate(BaseModel):
    """更新剧情线请求模型"""
    title: Optional[str] = Field(None, description="剧情线标题", max_length=200)
    description: Optional[str] = Field(None, description="剧情线描述")
    line_type: Optional[str] = Field(None, description="剧情线类型")
    order_index: Optional[int] = Field(None, description="排序序号")
    plot_cards: Optional[List[str]] = Field(None, description="关联的剧情卡片ID列表")
    timeline_data: Optional[Dict[str, Any]] = Field(None, description="时间线数据")
    estimated_chapters: Optional[int] = Field(None, description="预计章节数", ge=1)


class PlotLineResponse(PlotLineBase):
    """剧情线响应模型"""
    id: str = Field(..., description="剧情线ID")
    project_id: str = Field(..., description="项目ID")
    story_outline_id: Optional[str] = Field(None, description="关联的大纲ID")
    plot_cards: Optional[List[str]] = Field(None, description="关联的剧情卡片ID列表")
    timeline_data: Optional[Dict[str, Any]] = Field(None, description="时间线数据")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    # 关联统计字段
    chapter_outline_count: int = Field(0, description="关联的章纲数量")
    plot_card_count: int = Field(0, description="关联的剧情卡片数量")

    model_config = ConfigDict(from_attributes=True, extra="allow")  # 允许额外字段


class PlotLineGenerateRequest(BaseModel):
    """AI生成剧情线请求模型"""
    project_id: str = Field(..., description="项目ID")
    story_outline_id: Optional[str] = Field(None, description="基于的大纲ID")
    prompt: Optional[str] = Field(None, description="生成提示词")
    line_type: str = Field("main", description="要生成的剧情线类型")
    based_on_cards: Optional[List[str]] = Field(None, description="基于的剧情卡片ID列表")
    based_on_lines: Optional[List[str]] = Field(None, description="基于的剧情线ID列表，用于保持剧情连贯性")
    extend_existing: bool = Field(False, description="是否扩展现有剧情线")
    count: int = Field(3, ge=1, le=10, description="生成剧情线数量")
    enable_mcp: bool = Field(False, description="是否启用MCP工具增强")
    selected_plugins: Optional[List[str]] = Field(None, description="选择的MCP插件列表")
    # R8/R6：拆书参考包注入。三个字段都为 None 时走「项目挂载关系自动注入」（推荐默认）。
    # 用户在前端 ReferencePackSelector 显式覆盖时透传。
    pack_ids: Optional[List[str]] = Field(None, description="显式参考包 ID 列表；None=用项目所有挂载包")
    dimensions: Optional[List[str]] = Field(None, description="显式注入维度列表；None=用挂载包默认并集")
    strength: Optional[str] = Field(None, description="注入强度 light/medium/deep；None=用挂载包最深者")


class PlotLineReorderRequest(BaseModel):
    """剧情线重排序请求模型"""
    orders: List[dict] = Field(..., description="排序列表，格式：[{id: str, order_index: int}]")


class PlotLineListResponse(BaseModel):
    """剧情线列表响应模型"""
    total: int = Field(..., description="总数量")
    items: List[PlotLineResponse] = Field(..., description="剧情线列表")


# ============================================
# 时间线相关模型
# ============================================
