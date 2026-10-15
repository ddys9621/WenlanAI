"""关联关系相关的 Pydantic 模型（章纲侧的剧情卡片关联视图）。"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class PlotCardWithLinks(BaseModel):
    """剧情卡片及其关联信息"""
    id: str
    title: str
    content: Optional[str]
    card_type: str
    chapter_count: int = Field(..., description="关联的章纲数量")

    model_config = ConfigDict(from_attributes=True)
