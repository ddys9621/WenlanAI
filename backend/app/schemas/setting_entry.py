"""世界设定条目的 Pydantic 模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class SettingEntryBase(BaseModel):
    """世界设定条目基础模型"""
    category: str = Field("other", max_length=50, description="分类：term 术语 / law 铁律 / faction 势力 / rule 规则 / other 其他")
    title: str = Field(..., min_length=1, max_length=200, description="条目名称")
    summary: Optional[str] = Field(None, max_length=2000, description="一句话简述（界面与 prompt 摘要用）")
    content: Optional[str] = Field(None, max_length=20000, description="详细设定（长文本）")
    order_index: int = Field(0, description="排序序号")


class SettingEntryCreate(SettingEntryBase):
    """创建世界设定条目请求模型"""
    pass


class SettingEntryUpdate(BaseModel):
    """更新世界设定条目请求模型"""
    category: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=2000)
    content: Optional[str] = Field(None, max_length=20000)
    order_index: Optional[int] = None


class SettingEntryResponse(SettingEntryBase):
    """世界设定条目响应模型"""
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SettingEntryListResponse(BaseModel):
    """世界设定条目列表响应模型"""
    total: int
    items: List[SettingEntryResponse]
