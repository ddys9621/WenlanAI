"""章节相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class ChapterCreate(BaseModel):
    """创建章节的请求模型"""
    project_id: str = Field(..., description="所属项目ID")
    chapter_outline_id: Optional[str] = Field(None, description="关联的章纲ID")
    title: str = Field(..., description="章节标题")
    chapter_number: int = Field(..., description="章节序号")
    content: Optional[str] = Field(None, description="章节内容")
    summary: Optional[str] = Field(None, description="章节摘要")
    status: Optional[str] = Field("draft", description="章节状态")


class ChapterUpdate(BaseModel):
    """更新章节的请求模型"""
    title: Optional[str] = None
    content: Optional[str] = None
    # chapter_number 不允许修改，只能通过大纲的重排序来调整
    summary: Optional[str] = None
    # word_count 自动计算，不允许手动修改
    status: Optional[str] = None


class ChapterResponse(BaseModel):
    """章节响应模型"""
    id: str
    project_id: str
    chapter_outline_id: Optional[str] = None
    title: str
    chapter_number: int
    content: Optional[str] = None
    summary: Optional[str] = None
    word_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ChapterListItem(BaseModel):
    """章节列表项：不带正文（列表页只用标题 / 字数 / 状态，正文按章单独拉，避免几百章全文一次下发）"""
    id: str
    project_id: str
    chapter_outline_id: Optional[str] = None
    title: str
    chapter_number: int
    summary: Optional[str] = None
    word_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChapterListResponse(BaseModel):
    """章节列表响应模型"""
    total: int
    items: list[ChapterListItem]


class ChapterGenerateRequest(BaseModel):
    """AI生成章节内容的请求模型"""
    style_id: Optional[int] = Field(None, description="写作风格ID，不提供则不使用任何风格")
    target_word_count: Optional[int] = Field(
        3000,
        description="目标字数，默认3000字",
        ge=500,   # 最小500字
        le=10000  # 最大10000字
    )
    enable_mcp: bool = Field(True, description="是否启用MCP工具增强（搜索参考资料）")
    auto_analyze: bool = Field(False, description="生成后是否自动排队分析（批量生成传True以累积记忆；单章默认False手动分析）")
    selected_plugins: Optional[List[str]] = Field(
        None,
        description="本次章节生成选择使用的MCP插件列表"
    )
    # R8 拆书参考包显式参数（任一为空则走 injector 默认）
    pack_ids: Optional[List[str]] = Field(None, description="显式选中的拆书参考包 ID 列表")
    dimensions: Optional[List[str]] = Field(None, description="显式选中的参考维度")
    strength: Optional[str] = Field(None, description="参考强度：light/medium/deep")
