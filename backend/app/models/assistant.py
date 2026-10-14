"""全局智能助笔（参考岚笺 GlobalAssistantHost）：每个项目一份可续接的对话、每轮处理记录、字段修改候选。

- AssistantSession：一段对话（新建对话时旧的归档，任务记录里仍可回看）
- AssistantMessage：对话消息（作者 / 助笔），助笔回复附处理记录、候选、提问
- AssistantRun：处理一条作者要求的一次运行（可多步调用工具；需要作者决定时暂停等待回答）
- AssistantFieldCandidate：对某一项内容的修改候选（记下修改前 / 修改后；作者应用才写入，可撤销）
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db_base import Base
from app.models.chapter_candidate import utcnow
import uuid


def _id() -> str:
    return str(uuid.uuid4())


class AssistantSession(Base):
    __tablename__ = "assistant_sessions"

    id = Column(String(36), primary_key=True, default=_id)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    title = Column(String(200), nullable=False, default="新对话")
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(String(36), primary_key=True, default=_id)
    session_id = Column(String(36), ForeignKey("assistant_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="user / assistant")
    content = Column(Text, nullable=False, default="")
    meta_json = Column(Text, nullable=True, comment="处理记录 / 候选 / 提问 / 回答 / 页面")
    created_at = Column(DateTime, default=utcnow)


class AssistantRun(Base):
    __tablename__ = "assistant_runs"

    id = Column(String(36), primary_key=True, default=_id)
    session_id = Column(String(36), ForeignKey("assistant_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    goal = Column(Text, nullable=False, comment="作者本轮要求")
    goal_message_id = Column(String(36), nullable=True, comment="作者这条要求的消息 ID（之前的消息才算历史）")
    page_json = Column(Text, nullable=True, comment="发起时作者所在页面")
    status = Column(String(20), nullable=False, default="running", index=True,
                    comment="running / waiting_input / completed / failed / cancelled")
    message = Column(String(500), nullable=True, comment="状态说明")
    steps_json = Column(Text, nullable=True, comment="处理记录：每步工具、参数摘要与结果")
    question_json = Column(Text, nullable=True, comment="等待作者回答的问题")
    step_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AssistantFieldCandidate(Base):
    __tablename__ = "assistant_field_candidates"

    id = Column(String(36), primary_key=True, default=_id)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    run_id = Column(String(36), nullable=True, index=True)
    field_id = Column(String(80), nullable=False)
    target_id = Column(String(36), nullable=False)
    target_label = Column(String(300), nullable=False)
    page = Column(String(60), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="candidate", index=True,
                    comment="candidate / applied / undone / rejected")
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime, nullable=True)
