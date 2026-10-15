"""导入导出相关的Pydantic模型"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ExportOptions(BaseModel):
    """导出选项"""
    include_generation_history: bool = Field(False, description="是否包含生成历史")
    include_writing_styles: bool = Field(True, description="是否包含写作风格")


class ChapterExportData(BaseModel):
    """章节导出数据"""
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    chapter_number: int
    word_count: int = 0
    status: str = "draft"
    created_at: Optional[str] = None
    # v1.2.0新增：用于恢复章节与章纲的关联
    chapter_outline_number: Optional[int] = None


class CharacterExportData(BaseModel):
    """角色导出数据"""
    name: str
    age: Optional[str] = None
    gender: Optional[str] = None
    is_organization: bool = False
    role_type: Optional[str] = None
    personality: Optional[str] = None
    background: Optional[str] = None
    appearance: Optional[str] = None
    speech_style: Optional[str] = None
    traits: Optional[List[str]] = None
    organization_type: Optional[str] = None
    organization_purpose: Optional[str] = None
    created_at: Optional[str] = None


class OutlineExportData(BaseModel):
    """大纲导出数据"""
    title: str
    content: Optional[str] = None
    order_index: Optional[int] = None
    created_at: Optional[str] = None


class RelationshipExportData(BaseModel):
    """关系导出数据"""
    source_name: str
    target_name: str
    relationship_name: Optional[str] = None
    intimacy_level: int = 50
    status: str = "active"
    description: Optional[str] = None
    started_at: Optional[str] = None


class OrganizationExportData(BaseModel):
    """组织详情导出数据"""
    character_name: str
    parent_org_name: Optional[str] = None
    power_level: int = 50
    member_count: int = 0
    location: Optional[str] = None
    motto: Optional[str] = None
    color: Optional[str] = None


class OrganizationMemberExportData(BaseModel):
    """组织成员导出数据"""
    organization_name: str
    character_name: str
    position: str
    rank: int = 0
    status: str = "active"
    joined_at: Optional[str] = None
    loyalty: int = 50
    contribution: int = 0
    notes: Optional[str] = None


class WritingStyleExportData(BaseModel):
    """写作风格导出数据"""
    name: str
    style_type: str
    preset_id: Optional[str] = None
    description: Optional[str] = None
    prompt_content: str
    order_index: int = 0


class GenerationHistoryExportData(BaseModel):
    """生成历史导出数据"""
    chapter_title: Optional[str] = None
    prompt: Optional[str] = None
    generated_content: Optional[str] = None
    model: Optional[str] = None
    tokens_used: Optional[int] = None
    generation_time: Optional[float] = None
    created_at: Optional[str] = None


class WorldRuleExportData(BaseModel):
    """世界规则导出数据"""
    category: str
    key: str
    name: str
    summary: Optional[str] = None
    details: Optional[str] = None
    order_index: int = 0
    created_at: Optional[str] = None


class ChapterOutlineExportData(BaseModel):
    """章节大纲导出数据"""
    chapter_number: int
    title: str
    summary: Optional[str] = None
    plot_points: Optional[str] = None
    key_events: Optional[List[str]] = None
    characters_involved: Optional[List[str]] = None
    target_word_count: int = 3000
    order_index: Optional[int] = None
    # v1.2.0新增：完整字段导出
    scene: Optional[str] = None
    pov: Optional[str] = None
    emotional_arc: Optional[str] = None
    chapter_hook: Optional[str] = None
    narrative_tasks: Optional[Any] = None  # 本章叙事任务（伏笔 / 承诺），JSON 结构
    # 章节契约 + 卷纲归属（按卷序号关联，导入时挂到新卷上）
    entry_state: Optional[str] = None
    exit_state: Optional[str] = None
    forbidden: Optional[List[str]] = None
    volume_number: Optional[int] = None
    unit_index: Optional[int] = None
    created_at: Optional[str] = None


class VolumeExportData(BaseModel):
    """卷纲导出数据（剧情单元 / 线索编排原样带上）"""
    volume_number: int
    title: str = ""
    chapter_start: int
    chapter_end: int
    summary: Optional[str] = None
    goal: Optional[str] = None
    climax: Optional[str] = None
    ending_hook: Optional[str] = None
    units: List[Dict[str, Any]] = []
    threads: List[str] = []
    review_note: Optional[str] = None
    review_status: Optional[str] = None


class PlotCardExportData(BaseModel):
    """剧情卡片导出数据"""
    title: str
    content: Optional[str] = None
    card_type: str = "event"
    order_index: int = 0
    tags: Optional[str] = None  # JSON格式标签
    created_at: Optional[str] = None


class PlotCardChapterOutlineLinkExportData(BaseModel):
    """剧情卡片-章节大纲关联导出数据"""
    card_title: str
    chapter_outline_number: int
    usage_type: Optional[str] = "reference"
    usage_notes: Optional[str] = None


class ProjectExportData(BaseModel):
    """项目完整导出数据"""
    version: str = "2.0.0"
    export_time: str
    project: Dict[str, Any]
    chapters: List[ChapterExportData] = []
    characters: List[CharacterExportData] = []
    outlines: List[OutlineExportData] = []
    relationships: List[RelationshipExportData] = []
    organizations: List[OrganizationExportData] = []
    organization_members: List[OrganizationMemberExportData] = []
    writing_styles: List[WritingStyleExportData] = []
    generation_history: List[GenerationHistoryExportData] = []
    # v1.0.0 字段
    world_rules: List[WorldRuleExportData] = []
    volumes: List[VolumeExportData] = []
    chapter_outlines: List[ChapterOutlineExportData] = []
    plot_cards: List[PlotCardExportData] = []
    plot_card_chapter_outline_links: List[PlotCardChapterOutlineLinkExportData] = []


class ImportValidationResult(BaseModel):
    """导入验证结果"""
    valid: bool
    version: str
    project_name: Optional[str] = None
    statistics: Dict[str, int] = {}
    errors: List[str] = []
    warnings: List[str] = []


class ImportResult(BaseModel):
    """导入结果"""
    success: bool
    project_id: Optional[str] = None
    message: str
    statistics: Dict[str, int] = {}
    warnings: List[str] = []