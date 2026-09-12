"""项目级 AI 偏好的请求 / 响应模型。所有覆盖字段可空：null = 跟随全局设置。"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class AIOverrideFields(BaseModel):
    """可按项目覆盖的字段（与 Settings 同名）；范围校验与设置页一致。"""
    model_config = ConfigDict(protected_namespaces=())

    llm_model: Optional[str] = Field(default=None, max_length=100, description="覆盖模型名；null=跟随全局")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    reasoning_enabled: Optional[bool] = None
    reasoning_effort: Optional[ReasoningEffort] = None
    thinking_budget_tokens: Optional[int] = Field(default=None, ge=0)

    @field_validator("llm_model")
    @classmethod
    def _strip_model(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None


class ProjectAIPreferenceUpdate(AIOverrideFields):
    """PUT 请求体：整体替换（未带 / null 的字段 = 跟随全局）。"""


class EffectiveAIConfig(BaseModel):
    """合并后的实际生效配置：带接口信息，不含密钥。"""
    model_config = ConfigDict(protected_namespaces=())

    api_provider: Optional[str] = None
    api_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    reasoning_enabled: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    thinking_budget_tokens: Optional[int] = None


class ProjectAIPreferenceResponse(BaseModel):
    project_id: str
    overrides: AIOverrideFields
    effective: EffectiveAIConfig
    global_defaults: EffectiveAIConfig
