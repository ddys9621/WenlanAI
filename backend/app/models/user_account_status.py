"""用户账号状态 - 禁用标志独立于 users 表。

旧版本用 users.trust_level == -1 表示「被管理员禁用」，一字段两用，启用时会把
Linux.do 的真实信任等级冲掉。这里把禁用状态迁到独立新表（只加表、不改旧表列，
对已发布的库安全），trust_level 回归「仅展示信任等级」的本意。
"""
from sqlalchemy import Column, String, Boolean, DateTime
from app.db_base import Base


class UserAccountStatus(Base):
    __tablename__ = "user_account_status"

    user_id = Column(String(100), primary_key=True, index=True, comment="用户ID")
    disabled = Column(Boolean, default=False, nullable=False, comment="是否被管理员禁用")
    disabled_at = Column(DateTime, nullable=True, comment="最近一次被禁用的时间")
    sessions_after = Column(DateTime, nullable=True, comment="早于此时刻签发的会话令牌一律失效（强制下线 / 重置密码 / 改密码时前移）")
