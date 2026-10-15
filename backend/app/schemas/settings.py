"""设置相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class SettingsBase(BaseModel):
    """设置基础模型"""
    model_config = ConfigDict(protected_namespaces=())
    
    api_provider: Optional[str] = Field(default="openai", description="API提供商")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    api_base_url: Optional[str] = Field(default=None, description="自定义API地址")
    llm_model: Optional[str] = Field(default="gpt-4", description="模型名称")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: Optional[int] = Field(default=2000, ge=1, description="最大token数")
    top_p: Optional[float] = Field(default=0.95, ge=0.0, le=1.0, description="核采样 top_p，<1 收敛候选词分布")
    frequency_penalty: Optional[float] = Field(default=0.3, ge=-2.0, le=2.0, description="频率惩罚，越高越抑制重复用词（降低 AI 味）")
    presence_penalty: Optional[float] = Field(default=0.3, ge=-2.0, le=2.0, description="存在惩罚，越高越鼓励引入新词/话题")
    sampling_enabled: Optional[bool] = Field(
        default=True,
        description="采样多样性开关：关闭后不传 top_p / 频率惩罚 / 存在惩罚（模型不支持这些参数时关闭）",
    )
    reasoning_enabled: Optional[bool] = Field(default=False, description="是否启用思考/推理模式（全局生效）")
    reasoning_effort: Optional[str] = Field(
        default="medium",
        description="统一思考强度档位，同时作为 OpenAI reasoning_effort：none|minimal|low|medium|high|xhigh|max",
    )
    thinking_budget_tokens: Optional[int] = Field(
        default=None, ge=0,
        description="Anthropic 思考预算 budget_tokens；为空则按强度档位自动换算，须 ≥1024 且 < max_tokens",
    )
    analysis_model: Optional[str] = Field(
        default=None,
        description="分析 / 实体抽取 / 剧情摘要专用模型（同一接口下的便宜快模型）；空 = 跟随主模型",
    )
    completion_model: Optional[str] = Field(
        default=None,
        description="编辑器行内补全专用模型（同一接口下响应快的模型）；空 = 跟随项目模型",
    )
    preferences: Optional[str] = Field(default=None, description="其他偏好设置(JSON)")


class SettingsCreate(SettingsBase):
    """创建设置请求模型"""
    pass


class SettingsUpdate(SettingsBase):
    """更新设置请求模型"""
    pass


class SettingsResponse(SettingsBase):
    """设置响应模型"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime