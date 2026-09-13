"""项目相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ProjectBase(BaseModel):
    """项目基础模型"""
    title: str = Field(..., description="项目标题")
    description: Optional[str] = Field(None, description="项目描述")
    theme: Optional[str] = Field(None, description="主题")
    genre: Optional[str] = Field(None, description="小说类型")
    target_words: Optional[int] = Field(None, description="目标字数")
    generation_prompt: Optional[str] = Field(None, description="最终提交提示词补充")
    narrative_perspective: Optional[str] = Field(None, description="叙事视角")
    chapter_count: Optional[int] = Field(None, ge=1, description="chapter count")
    character_count: Optional[int] = Field(None, ge=1, description="character count")


class ProjectCreate(ProjectBase):
    """创建项目的请求模型"""
    pass


class ProjectUpdate(BaseModel):
    """更新项目的请求模型"""
    title: Optional[str] = None
    description: Optional[str] = None
    theme: Optional[str] = None
    genre: Optional[str] = None
    target_words: Optional[int] = None
    status: Optional[str] = None
    # wizard_status 和 wizard_step 只能通过向导API修改，普通更新不允许
    world_time_period: Optional[str] = None
    world_location: Optional[str] = None
    world_atmosphere: Optional[str] = None
    world_rules: Optional[str] = None
    generation_prompt: Optional[str] = None
    chapter_count: Optional[int] = None
    narrative_perspective: Optional[str] = None
    character_count: Optional[int] = None
    c3_hook_style: Optional[str] = Field(None, pattern="^(none|soft)$", description="桥段 C3 章末：none 不留钩子 / soft 半钩")
    # current_words 由章节内容自动计算，不允许手动修改


class ProjectResponse(ProjectBase):
    """项目响应模型"""
    id: str  # UUID字符串
    status: str
    current_words: int
    wizard_status: Optional[str] = None
    wizard_step: Optional[int] = None
    world_time_period: Optional[str] = None
    world_location: Optional[str] = None
    world_atmosphere: Optional[str] = None
    world_rules: Optional[str] = None
    generation_prompt: Optional[str] = None
    chapter_count: Optional[int] = None
    narrative_perspective: Optional[str] = None
    character_count: Optional[int] = None
    c3_hook_style: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProjectListResponse(BaseModel):
    """项目列表响应模型"""
    total: int
    items: list[ProjectResponse]
