"""全局智能助笔（参考岚笺 GlobalAssistantHost）：每个项目一份可续接的对话、每轮处理记录、字段修改候选。

- AssistantSession：一段对话（新建对话时旧的归档，任务记录里仍可回看）
- AssistantMessage：对话消息（作者 / 助笔），助笔回复附处理记录、候选、提问
- AssistantRun：处理一条作者要求的一次运行（可多步调用工具；需要作者决定时暂停等待回答）
- AssistantFieldCandidate：对某一项内容的修改候选（记下修改前 / 修改后；作者应用才写入，可撤销）
- AssistantTeamSetting：共创室成员的模型设置（每个项目每位成员一行；没有行 = 跟随项目模型）
- AssistantContextSetting：共创室的上下文上限（每个项目一行；没有行 / 空 = 自动按模型查窗口）
- AssistantSessionSummary：对话的前情摘要（装不下的较早对话由模型压成一段，覆盖到某条消息为止）
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

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


class AssistantEntityCandidate(Base):
    """新建对象候选（角色 / 组织 / 设定条目）：工具只记下要新建的内容，作者「应用」才真正建行。

    与 AssistantFieldCandidate（改既有字段）互补：这张表管「从无到有创建新对象」，
    payload_json 存拟建对象的各字段；应用后 created_entity_id 记下新建行的 id。
    """
    __tablename__ = "assistant_entity_candidates"

    id = Column(String(36), primary_key=True, default=_id)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    run_id = Column(String(36), nullable=True, index=True)
    entity_type = Column(String(30), nullable=False, comment="character / organization / setting_entry")
    payload_json = Column(Text, nullable=True, comment="拟新建对象的各字段（JSON）")
    label = Column(String(300), nullable=False, comment="展示用标题，如 新建角色「秦尘」")
    page = Column(String(60), nullable=True, comment="应用后可去查看的页面")
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="candidate", index=True,
                    comment="candidate / applied / rejected")
    created_entity_id = Column(String(36), nullable=True, comment="应用后新建行的 id")
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime, nullable=True)


class AssistantTeamSetting(Base):
    __tablename__ = "assistant_team_settings"
    __table_args__ = (UniqueConstraint("project_id", "member_id", name="uq_assistant_team_member"),)

    id = Column(String(36), primary_key=True, default=_id)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id = Column(String(40), nullable=False, comment="共创室成员 ID：editor / world / character / outline / chapter / writer / reviewer")
    model = Column(String(100), nullable=True, comment="该成员用的模型；空 = 跟随项目模型")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AssistantContextSetting(Base):
    __tablename__ = "assistant_context_settings"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    context_window = Column(Integer, nullable=True, comment="上下文上限（token）；空 = 自动按成员用的模型查窗口")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AssistantSessionSummary(Base):
    __tablename__ = "assistant_session_summaries"

    session_id = Column(String(36), ForeignKey("assistant_sessions.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    summary = Column(Text, nullable=False, default="")
    covered_until_id = Column(String(36), nullable=False, comment="摘要覆盖到的最后一条消息")
    covered_count = Column(Integer, nullable=False, default=0, comment="摘要覆盖了对话开头的多少条消息")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
