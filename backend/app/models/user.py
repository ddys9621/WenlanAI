"""
用户数据模型 - 存储用户基本信息
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.db_base import Base


class User(Base):
    """用户模型 - 存储OAuth和本地用户信息"""
    __tablename__ = "users"
    
    user_id = Column(String(100), primary_key=True, index=True, comment="用户ID，格式：linuxdo_{id} / local_{id} / admin_created_{id} / email_{id}")
    username = Column(String(100), nullable=False, index=True, comment="用户名")
    display_name = Column(String(200), nullable=False, comment="显示名称")
    avatar_url = Column(String(500), nullable=True, comment="头像URL")
    trust_level = Column(Integer, default=0, comment="信任等级（仅用于显示）")
    is_admin = Column(Boolean, default=False, comment="是否为管理员")
    linuxdo_id = Column(String(100), nullable=False, unique=True, index=True, comment="LinuxDO用户ID或本地用户ID")
    email = Column(String(200), nullable=True, comment="邮箱（邮箱注册用户，小写；唯一索引见 idx_users_email）")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    last_login = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="最后登录时间")

    __table_args__ = (
        Index("idx_users_email", "email", unique=True),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "trust_level": self.trust_level,
            "is_admin": self.is_admin,
            "linuxdo_id": self.linuxdo_id,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class UserPassword(Base):
    """用户密码模型 - 存储用户密码信息"""
    __tablename__ = "user_passwords"
    
    user_id = Column(String(100), primary_key=True, index=True, comment="用户ID")
    username = Column(String(100), nullable=False, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希（scrypt 加盐；旧库可能是无盐 SHA256，登录验证时就地升级）")
    has_custom_password = Column(Boolean, default=False, comment="是否为自定义密码")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")