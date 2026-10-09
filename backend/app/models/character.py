"""角色数据模型"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class Character(Base):
    """角色表（包括角色和组织）"""
    __tablename__ = "characters"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 基本信息
    name = Column(String(100), nullable=False, comment="角色/组织名称")
    aliases = Column(Text, comment="曾用名(JSON数组)，改名时自动追加旧名；按名字匹配角色时与 name 一并比对")
    age = Column(String(50), comment="年龄")
    gender = Column(String(50), comment="性别")
    is_organization = Column(Boolean, default=False, comment="是否为组织")
    
    # 角色类型：protagonist(主角)/supporting(配角)/antagonist(反派)
    role_type = Column(String(50), comment="角色类型")
    
    # 角色详细信息
    personality = Column(Text, comment="性格特点/组织特性")
    background = Column(Text, comment="背景故事")
    appearance = Column(Text, comment="外貌描述")
    speech_style = Column(Text, comment="说话风格 / 口头禅 / 称呼习惯（角色声音卡，正文生成按出场角色注入）")
    relationships = Column(Text, comment="人物关系(JSON)")
    
    # 组织特有字段
    organization_type = Column(String(100), comment="组织类型")
    organization_purpose = Column(String(500), comment="组织目的")
    organization_members = Column(Text, comment="组织成员(JSON)")
    
    # 其他
    avatar_url = Column(String(500), comment="头像URL")
    traits = Column(Text, comment="特征标签(JSON)")
    
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        entity_type = "组织" if self.is_organization else "角色"
        return f"<Character(id={self.id}, name={self.name}, type={entity_type})>"