"""章节去 AI 味重写的请求 Schema。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChapterRegenerateRequest(BaseModel):
    """去 AI 味重写：只带项目提示词 id（按勾选顺序），后端拼「提示词 + 原文」重写并直接覆盖正文，随后清掉本章旧分析。"""
    prompt_ids: List[str] = Field(..., min_length=1, description="项目去 AI 味提示词 id，按注入顺序")
    mode: Literal["full", "local"] = Field(
        "full",
        description="full 全文重写；local 只重写检测出 AI 味重的段落（其余段落一字不动）",
    )
    paragraph_indices: Optional[List[int]] = Field(
        None, description="local 模式下指定要重写的段落下标（0 起）；不传则自动检测",
    )
