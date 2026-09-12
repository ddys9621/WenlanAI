"""项目级 AI 偏好：在用户全局 Settings 之上按项目覆盖模型与采样 / 思考参数。

所有覆盖列均可空：NULL = 跟随全局设置。接口 / 密钥 / base_url 不在此表——项目只换模型和参数，
接口始终复用设置页那一套。生效点见 api/settings.py::get_user_ai_service（读请求头 X-Project-Id）。
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db_base import Base


class ProjectAIPreference(Base):
    """项目 AI 偏好表（每项目一行）"""
    __tablename__ = "project_ai_preferences"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True, comment="项目ID（每项目一条）",
    )
    llm_model = Column(String(100), nullable=True, comment="覆盖模型名；NULL=跟随全局")
    temperature = Column(Float, nullable=True, comment="覆盖温度；NULL=跟随全局")
    max_tokens = Column(Integer, nullable=True, comment="覆盖最大 token；NULL=跟随全局")
    top_p = Column(Float, nullable=True, comment="覆盖核采样 top_p；NULL=跟随全局")
    frequency_penalty = Column(Float, nullable=True, comment="覆盖频率惩罚；NULL=跟随全局")
    presence_penalty = Column(Float, nullable=True, comment="覆盖存在惩罚；NULL=跟随全局")
    reasoning_enabled = Column(Boolean, nullable=True, comment="覆盖思考开关；NULL=跟随全局")
    reasoning_effort = Column(String(20), nullable=True, comment="覆盖思考强度档位；NULL=跟随全局")
    thinking_budget_tokens = Column(Integer, nullable=True, comment="覆盖 Anthropic 思考预算；NULL=跟随全局")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<ProjectAIPreference(project_id={self.project_id}, llm_model={self.llm_model})>"
