"""故事大纲 Schema 定义"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime


class StoryOutlineBase(BaseModel):
    """故事大纲基础模型"""
    title: str = Field(..., description="大纲标题")
    content: Optional[str] = Field(None, description="故事前提内容(premise)")
    order_index: Optional[int] = Field(None, description="排序序号")


class StoryOutlineCreate(StoryOutlineBase):
    """创建故事大纲"""
    project_id: str = Field(..., description="项目ID")


class StoryOutlineUpdate(BaseModel):
    """更新故事大纲"""
    title: Optional[str] = Field(None, description="大纲标题")
    content: Optional[str] = Field(None, description="故事前提内容(premise)")
    status: Optional[str] = Field(None, description="状态: draft/published")
    version: Optional[int] = Field(None, description="当前版本号（用于乐观锁）")
    order_index: Optional[int] = Field(None, description="排序序号")


class StoryOutlineGenerateRequest(BaseModel):
    """谋篇页 AI 生成总纲：视角 / 章数 / 字数留空时按项目设置补齐"""
    narrative_perspective: Optional[str] = Field(None, description="叙事视角")
    chapter_count: Optional[int] = Field(None, ge=1, description="预估全书章数")
    target_words: Optional[int] = Field(None, ge=1, description="目标字数")
    requirements: Optional[str] = Field(None, description="作者的额外要求")
    enable_mcp: bool = Field(False, description="是否启用 MCP 工具检索参考资料")
    selected_plugins: List[str] = Field(default_factory=list, description="选择的 MCP 插件")


class StoryOutlineResponse(StoryOutlineBase):
    """故事大纲响应模型"""
    id: str
    project_id: str
    version: int
    status: str
    editor_id: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
