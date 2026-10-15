"""行内补全请求模型。"""
from typing import Literal

from pydantic import BaseModel, Field

CompletionLength = Literal["sentence", "paragraph"]


class InlineCompletionRequest(BaseModel):
    prefix: str = Field("", max_length=20000, description="光标前的正文（前端只传结尾一段，服务端再截取）")
    suffix: str = Field("", max_length=5000, description="光标后的正文（前端只传开头一段）")
    length: CompletionLength = Field("paragraph", description="sentence 一句 / paragraph 补完当前段（段首则写一段）")
