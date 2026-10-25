"""管理员操作审计 - 用户管理页的每次增 / 改 / 禁 / 启 / 重置密码 / 强制下线 / 删除都落一行。

新表，只加不改旧表；detail 是 JSON 文本，绝不写入密码明文。
"""
from sqlalchemy import Column, String, Text, DateTime, Index
from app.db_base import Base


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(String(36), primary_key=True, comment="uuid")
    actor_id = Column(String(100), nullable=False, index=True, comment="操作者 user_id")
    actor_name = Column(String(200), nullable=True, comment="操作者当时的显示名（快照）")
    action = Column(String(50), nullable=False, index=True, comment="user.create / user.update / user.disable / user.enable / user.reset_password / user.revoke_sessions / user.delete")
    target_id = Column(String(100), nullable=True, index=True, comment="被操作用户 user_id")
    target_name = Column(String(200), nullable=True, comment="被操作用户当时的显示名（快照，删除后仍可读）")
    detail = Column(Text, nullable=True, comment="JSON：改了哪些字段等，不含密码")
    created_at = Column(DateTime, nullable=False, comment="发生时间（本地）")

    __table_args__ = (
        Index("idx_admin_audit_created", "created_at"),
    )
