"""关系管理相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime


# ============ 关系类型相关 ============

class RelationshipTypeResponse(BaseModel):
    """关系类型响应模型"""
    id: int
    name: str
    category: str
    reverse_name: Optional[str] = None
    intimacy_range: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============ 角色关系相关 ============

class CharacterRelationshipBase(BaseModel):
    """角色关系基础模型"""
    relationship_type_id: Optional[int] = Field(None, description="关系类型ID")
    relationship_name: Optional[str] = Field(None, description="自定义关系名称")
    intimacy_level: int = Field(50, ge=-100, le=100, description="亲密度：-100到100")
    status: str = Field("active", description="状态：active/broken/past/complicated")
    description: Optional[str] = Field(None, description="关系描述")
    started_at: Optional[str] = Field(None, description="关系开始时间（故事时间）")
    ended_at: Optional[str] = Field(None, description="关系结束时间")


class CharacterRelationshipCreate(CharacterRelationshipBase):
    """创建角色关系的请求模型"""
    project_id: str = Field(..., description="项目ID")
    character_from_id: str = Field(..., description="角色A的ID")
    character_to_id: str = Field(..., description="角色B的ID")


class CharacterRelationshipUpdate(BaseModel):
    """更新角色关系的请求模型"""
    relationship_type_id: Optional[int] = None
    relationship_name: Optional[str] = None
    intimacy_level: Optional[int] = Field(None, ge=-100, le=100)
    status: Optional[str] = None
    description: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class CharacterRelationshipResponse(CharacterRelationshipBase):
    """角色关系响应模型"""
    id: str
    project_id: str
    character_from_id: str
    character_to_id: str
    source: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============ 组织相关 ============

class OrganizationBase(BaseModel):
    """组织基础模型"""
    parent_org_id: Optional[str] = Field(None, description="父组织ID")
    level: int = Field(0, description="组织层级")
    power_level: int = Field(50, ge=0, le=100, description="势力等级")
    location: Optional[str] = Field(None, description="所在地")
    motto: Optional[str] = Field(None, description="组织宗旨")
    color: Optional[str] = Field(None, description="代表颜色")


class OrganizationCreate(OrganizationBase):
    """创建组织的请求模型"""
    character_id: str = Field(..., description="关联的角色ID（组织记录）")
    project_id: str = Field(..., description="项目ID")


class OrganizationUpdate(BaseModel):
    """更新组织的请求模型"""
    parent_org_id: Optional[str] = None
    level: Optional[int] = None
    power_level: Optional[int] = Field(None, ge=0, le=100)
    location: Optional[str] = None
    motto: Optional[str] = None
    color: Optional[str] = None


class OrganizationResponse(OrganizationBase):
    """组织响应模型"""
    id: str
    character_id: str
    project_id: str
    member_count: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class OrganizationDetailResponse(BaseModel):
    """组织详情响应（包含基本信息）"""
    id: str
    character_id: str
    name: str
    type: Optional[str] = None
    purpose: Optional[str] = None
    member_count: int
    power_level: int
    location: Optional[str] = None
    motto: Optional[str] = None
    color: Optional[str] = None


# ============ 组织成员相关 ============

class OrganizationMemberBase(BaseModel):
    """组织成员基础模型"""
    position: str = Field(..., description="职位名称")
    rank: int = Field(0, description="职位等级")
    status: str = Field("active", description="状态：active/retired/expelled/deceased")
    joined_at: Optional[str] = Field(None, description="加入时间（故事时间）")
    left_at: Optional[str] = Field(None, description="离开时间")
    loyalty: int = Field(50, ge=0, le=100, description="忠诚度")
    contribution: int = Field(0, ge=0, le=100, description="贡献度")
    notes: Optional[str] = Field(None, description="备注")


class OrganizationMemberCreate(OrganizationMemberBase):
    """创建组织成员的请求模型"""
    character_id: str = Field(..., description="角色ID")


class OrganizationMemberUpdate(BaseModel):
    """更新组织成员的请求模型"""
    position: Optional[str] = None
    rank: Optional[int] = None
    status: Optional[str] = None
    joined_at: Optional[str] = None
    left_at: Optional[str] = None
    loyalty: Optional[int] = Field(None, ge=0, le=100)
    contribution: Optional[int] = Field(None, ge=0, le=100)
    notes: Optional[str] = None


class OrganizationMemberResponse(OrganizationMemberBase):
    """组织成员响应模型"""
    id: str
    organization_id: str
    character_id: str
    source: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberDetailResponse(BaseModel):
    """组织成员详情响应（包含角色信息）"""
    id: str
    character_id: str
    character_name: str
    position: str
    rank: int
    loyalty: int
    contribution: int
    status: str
    joined_at: Optional[str] = None
    left_at: Optional[str] = None
    notes: Optional[str] = None


# ============ AI 生成组织 ============

class OrganizationGenerateRequest(BaseModel):
    """AI生成组织的请求模型（服务层 organization_generation_service 与 API 共用）"""
    project_id: str = Field(..., description="项目ID")
    name: Optional[str] = Field(None, description="组织名称")
    organization_type: Optional[str] = Field(None, description="组织类型")
    background: Optional[str] = Field(None, description="组织背景")
    requirements: Optional[str] = Field(None, description="特殊要求")
    enable_mcp: bool = Field(False, description="是否启用MCP工具增强（搜索组织架构参考）")
    selected_plugins: List[str] = Field(default_factory=list, description="选择的MCP插件列表")
