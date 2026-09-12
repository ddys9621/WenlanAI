"""设置数据模型"""
from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class Settings(Base):
    """设置表"""
    __tablename__ = "settings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), nullable=False, unique=True, index=True, comment="用户ID")
    api_provider = Column(String(50), default="openai", comment="API提供商")
    api_key = Column(String(500), comment="API密钥")
    api_base_url = Column(String(500), comment="自定义API地址")
    llm_model = Column(String(100), default="gpt-4", comment="模型名称")
    temperature = Column(Float, default=0.7, comment="温度参数")
    max_tokens = Column(Integer, default=2000, comment="最大token数")
    # 采样多样性参数（降低"AI 味"/困惑度检测）
    top_p = Column(Float, default=0.95, comment="核采样 top_p，<1 收敛候选词分布")
    frequency_penalty = Column(Float, default=0.3, comment="频率惩罚 -2~2，越高越抑制重复用词")
    presence_penalty = Column(Float, default=0.3, comment="存在惩罚 -2~2，越高越鼓励引入新词/话题")
    # 思考/推理强度（全局生效）：OpenAI 走 reasoning_effort，Anthropic 走 thinking.budget_tokens
    reasoning_enabled = Column(Boolean, nullable=False, default=False, comment="是否启用思考/推理模式")
    reasoning_effort = Column(String(20), default="medium", comment="统一思考强度档位/OpenAI reasoning_effort: none|minimal|low|medium|high|xhigh|max")
    thinking_budget_tokens = Column(Integer, nullable=True, comment="Anthropic 思考预算 budget_tokens；为空则按强度档位自动换算")
    preferences = Column(Text, comment="其他偏好设置(JSON)")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
    )
    
    def __repr__(self):
        return f"<Settings(id={self.id}, user_id={self.user_id}, api_provider={self.api_provider})>"