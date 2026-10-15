"""剧情卡片相关的 Pydantic 模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
from datetime import datetime


class PlotCardBase(BaseModel):
    """剧情卡片基础模型"""
    title: str = Field(..., description="卡片标题", max_length=200)
    content: Optional[str] = Field(None, description="卡片内容描述")
    card_type: str = Field("plot", description="卡片类型：plot/character/scene/conflict")
    order_index: Optional[int] = Field(None, description="排序序号")
    tags: Optional[List[str]] = Field(None, description="标签列表")


class PlotCardCreate(PlotCardBase):
    """创建剧情卡片请求模型"""
    project_id: str = Field(..., description="项目ID")


class PlotCardUpdate(BaseModel):
    """更新剧情卡片请求模型"""
    title: Optional[str] = Field(None, description="卡片标题", max_length=200)
    content: Optional[str] = Field(None, description="卡片内容描述")
    card_type: Optional[str] = Field(None, description="卡片类型")
    order_index: Optional[int] = Field(None, description="排序序号")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    # 场景生成相关字段
    generation_status: Optional[str] = Field(None, description="场景生成状态: pending/generating/completed/rejected")
    generated_content: Optional[str] = Field(None, description="该场景生成的正文内容")
    word_count_target: Optional[int] = Field(None, description="目标字数")
    word_count_actual: Optional[int] = Field(None, description="实际生成字数")
    generation_order: Optional[int] = Field(None, description="在章节中的生成顺序")


class PlotCardResponse(PlotCardBase):
    """剧情卡片响应模型"""
    id: str = Field(..., description="卡片ID")
    project_id: str = Field(..., description="项目ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    # 关联统计字段 - 统一格式
    chapter_outlines: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="关联的章纲列表（用于统计）")
    chapter_outline_count: int = Field(0, description="关联的章纲数量")
    # 场景生成相关字段
    generation_status: Optional[str] = Field("pending", description="场景生成状态: pending/generating/completed/rejected")
    generated_content: Optional[str] = Field(None, description="该场景生成的正文内容")
    word_count_target: Optional[int] = Field(500, description="目标字数")
    word_count_actual: Optional[int] = Field(0, description="实际生成字数")
    generation_order: Optional[int] = Field(0, description="在章节中的生成顺序")

    model_config = ConfigDict(from_attributes=True, extra="allow")  # 允许额外字段


class PlotCardGenerateRequest(BaseModel):
    """生成剧情卡片请求模型"""
    project_id: str = Field(..., description="项目ID")
    outline_id: Optional[str] = Field(None, description="基于的大纲ID")
    story_outline_id: Optional[str] = Field(None, description="基于的大纲ID（兼容旧字段名）")
    chapter_outline_id: Optional[str] = Field(None, description="基于的章纲ID")
    prompt: Optional[str] = Field(None, description="生成提示词")
    card_type: str = Field("plot", description="要生成的卡片类型")
    count: int = Field(3, description="生成数量", ge=1, le=10)
    extend_from_card_id: Optional[str] = Field(None, description="基于现有卡片延伸")
    enable_mcp: bool = Field(False, description="是否启用MCP工具增强")
    selected_plugins: Optional[List[str]] = Field(None, description="选择的MCP插件列表")
    # R6/R8：拆书参考包注入（None=用项目挂载关系自动注入）
    pack_ids: Optional[List[str]] = Field(None, description="显式参考包 ID 列表")
    dimensions: Optional[List[str]] = Field(None, description="显式注入维度列表")
    strength: Optional[str] = Field(None, description="注入强度 light/medium/deep")


class PlotCardReorderRequest(BaseModel):
    """剧情卡片重排序请求模型"""
    orders: List[dict] = Field(..., description="排序列表，格式：[{id: str, order_index: int}]")


class PlotCardListResponse(BaseModel):
    """剧情卡片列表响应模型"""
    total: int = Field(..., description="总数量")
    items: List[PlotCardResponse] = Field(..., description="卡片列表")
