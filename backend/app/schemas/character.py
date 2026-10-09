"""角色相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class CharacterBase(BaseModel):
    """角色基础模型"""
    name: str = Field(..., description="角色/组织姓名")
    age: Optional[str] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    is_organization: bool = Field(False, description="是否为组织")
    role_type: Optional[str] = Field(None, description="角色类型：protagonist/supporting/antagonist")
    personality: Optional[str] = Field(None, description="性格特点/组织特性")
    background: Optional[str] = Field(None, description="背景故事")
    appearance: Optional[str] = Field(None, description="外貌特征")
    speech_style: Optional[str] = Field(None, description="说话风格 / 口头禅 / 称呼习惯（角色声音卡）")
    relationships: Optional[str] = Field(None, description="人际关系(JSON)")
    organization_type: Optional[str] = Field(None, description="组织类型")
    organization_purpose: Optional[str] = Field(None, description="组织目的")
    organization_members: Optional[str] = Field(None, description="组织成员(JSON)")
    traits: Optional[str] = Field(None, description="特征标签(JSON)")


class CharacterCreate(BaseModel):
    """手动创建角色的请求模型"""
    project_id: str = Field(..., description="项目ID")
    name: str = Field(..., description="角色/组织姓名")
    age: Optional[str] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    is_organization: bool = Field(False, description="是否为组织")
    role_type: Optional[str] = Field("supporting", description="角色类型：protagonist/supporting/antagonist")
    personality: Optional[str] = Field(None, description="性格特点/组织特性")
    background: Optional[str] = Field(None, description="背景故事")
    appearance: Optional[str] = Field(None, description="外貌特征")
    speech_style: Optional[str] = Field(None, description="说话风格 / 口头禅 / 称呼习惯（角色声音卡）")
    relationships: Optional[str] = Field(None, description="人际关系(JSON)")
    organization_type: Optional[str] = Field(None, description="组织类型")
    organization_purpose: Optional[str] = Field(None, description="组织目的")
    organization_members: Optional[str] = Field(None, description="组织成员(JSON)")
    traits: Optional[str] = Field(None, description="特征标签(JSON)")
    avatar_url: Optional[str] = Field(None, description="头像URL")
    
    # 组织额外字段
    power_level: Optional[int] = Field(None, description="组织势力等级(0-100)")
    location: Optional[str] = Field(None, description="组织所在地")
    motto: Optional[str] = Field(None, description="组织格言/口号")
    color: Optional[str] = Field(None, description="组织代表颜色")


class CharacterUpdate(BaseModel):
    """更新角色的请求模型"""
    name: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    is_organization: Optional[bool] = None
    role_type: Optional[str] = None
    personality: Optional[str] = None
    background: Optional[str] = None
    appearance: Optional[str] = None
    speech_style: Optional[str] = None
    relationships: Optional[str] = None
    organization_type: Optional[str] = None
    organization_purpose: Optional[str] = None
    organization_members: Optional[str] = None
    traits: Optional[str] = None


class CharacterResponse(CharacterBase):
    """角色响应模型"""
    id: str
    project_id: str
    aliases: Optional[str] = Field(None, description="曾用名(JSON数组)，改名时自动追加旧名")
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # 组织额外字段（从Organization表关联）
    power_level: Optional[int] = Field(None, description="组织势力等级(0-100)")
    location: Optional[str] = Field(None, description="组织所在地")
    motto: Optional[str] = Field(None, description="组织格言/口号")
    color: Optional[str] = Field(None, description="组织代表颜色")
    member_names: Optional[List[str]] = Field(
        None,
        description="组织在籍成员名（按 OrganizationMember 读时派生；无成员关系记录时回退到 organization_members 快照）",
    )
    
    model_config = ConfigDict(from_attributes=True)


class CharacterGenerateRequest(BaseModel):
    """AI生成角色的请求模型"""
    project_id: str = Field(..., description="项目ID")
    name: Optional[str] = Field(None, description="角色名称")
    role_type: Optional[str] = Field(None, description="角色类型")
    background: Optional[str] = Field(None, description="角色背景")
    requirements: Optional[str] = Field(None, description="特殊要求")
    enable_mcp: bool = Field(False, description="是否启用MCP工具增强（搜索人物原型参考）")
    selected_plugins: List[str] = Field(default_factory=list, description="选择的MCP插件列表")
    # R8 拆书参考包显式参数（任一为空则走 injector 默认）
    pack_ids: Optional[List[str]] = Field(None, description="显式选中的拆书参考包 ID 列表")
    dimensions: Optional[List[str]] = Field(None, description="显式选中的参考维度")
    strength: Optional[str] = Field(None, description="参考强度：light/medium/deep")


class CharacterListResponse(BaseModel):
    """角色列表响应模型"""
    total: int
    items: List[CharacterResponse]