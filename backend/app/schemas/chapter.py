"""章节相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict, computed_field
from typing import Optional, List
from datetime import datetime

from app.services.chapter_version_service import content_hash as _content_hash


class ChapterCreate(BaseModel):
    """创建章节的请求模型"""
    project_id: str = Field(..., description="所属项目ID")
    chapter_outline_id: Optional[str] = Field(None, description="关联的章纲ID")
    title: str = Field(..., description="章节标题")
    chapter_number: int = Field(..., description="章节序号")
    content: Optional[str] = Field(None, description="章节内容")
    summary: Optional[str] = Field(None, description="章节摘要")
    status: Optional[str] = Field("draft", description="章节状态")


class ChapterUpdate(BaseModel):
    """更新章节的请求模型"""
    title: Optional[str] = None
    content: Optional[str] = None
    # chapter_number 不允许修改，只能通过大纲的重排序来调整
    summary: Optional[str] = None
    # word_count 自动计算，不允许手动修改
    status: Optional[str] = None
    base_hash: Optional[str] = Field(
        None, max_length=64,
        description="编辑器自动保存：所依据的正文指纹（上次载入 / 保存时的 content_hash）；与当前正文不符返回 409",
    )


class ChapterResponse(BaseModel):
    """章节响应模型"""
    id: str
    project_id: str
    chapter_outline_id: Optional[str] = None
    title: str
    chapter_number: int
    content: Optional[str] = None
    summary: Optional[str] = None
    word_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        """正文指纹：编辑器自动保存时作为 base_hash 回传"""
        return _content_hash(self.content)


class ChapterListItem(BaseModel):
    """章节列表项：不带正文（列表页只用标题 / 字数 / 状态，正文按章单独拉，避免几百章全文一次下发）"""
    id: str
    project_id: str
    chapter_outline_id: Optional[str] = None
    title: str
    chapter_number: int
    summary: Optional[str] = None
    word_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime
    # 写作链路状态（列表页标记用）
    outline_changed: bool = False  # 正文写完（采用）后章纲又改过
    outline_review_status: Optional[str] = None  # 关联章纲：draft = AI 草拟待确认
    outline_upstream_stale: bool = False  # 关联章纲的上游（桥段 / 剧情线 / 故事大纲）已改
    pending_candidates: int = 0  # 待采用的候选稿数
    analysis_status: Optional[str] = None  # missing / ok / stale / failed / running；无正文为 None
    analysis_message: Optional[str] = None  # 失败原因 / 降级说明

    model_config = ConfigDict(from_attributes=True)


class ChapterDigestUpdate(BaseModel):
    """作者改章节档案：不传的项不改。"""
    summary: Optional[str] = Field(None, max_length=1000)
    end_state: Optional[str] = Field(None, max_length=500)


class ChapterListResponse(BaseModel):
    """章节列表响应模型"""
    total: int
    items: list[ChapterListItem]


class ChapterGenerateRequest(BaseModel):
    """AI生成章节内容的请求模型"""
    style_id: Optional[int] = Field(None, description="写作风格ID，不提供则不使用任何风格")
    target_word_count: Optional[int] = Field(
        3000,
        description="目标字数，默认3000字",
        ge=500,   # 最小500字
        le=10000  # 最大10000字
    )
    enable_mcp: bool = Field(True, description="是否启用MCP工具增强（搜索参考资料）")
    adherence_review: bool = Field(True, description="写完后另起一次模型调用审校章纲遵循度，报告附在候选稿上")
    selected_plugins: Optional[List[str]] = Field(
        None,
        description="本次章节生成选择使用的MCP插件列表"
    )
    kb_chapter: Optional[int] = Field(None, ge=1, description="仿写参考：本次对标原书第几章（留空按章纲引用 / 位置自动对位）")


class ChapterBatchRequest(BaseModel):
    """服务端批量生成（后台任务，关掉浏览器也不停）。已有正文的章节自动跳过，中断后用同样范围重新发起即可续跑。"""
    from_chapter: int = Field(..., ge=1, description="起始章号（含）")
    to_chapter: int = Field(..., ge=1, description="结束章号（含）")
    pause_on_critical: bool = Field(True, description="分析出严重一致性问题时暂停")
    quality_gate: bool = Field(True, description="AI 味分过高 / 字数严重不足时自动重写一次")
    ai_flavor_threshold: int = Field(60, ge=10, le=100, description="AI 味分阈值（越高越宽松）")
    max_retries: int = Field(2, ge=0, le=5, description="单章生成失败的自动重试次数")
    pipeline: bool = Field(False, description="流水线：第 N 章分析与第 N+1 章生成并行（需文件型 SQLite，否则自动退回顺序）")
    auto_expand: bool = Field(True, description="缺章纲时自动填充 / 展开覆盖该章的桥段（滚动规划）")
    style_id: Optional[int] = Field(None, description="写作风格ID")
    enable_mcp: bool = Field(False, description="是否启用 MCP 参考资料（批量默认关闭：慢且容易失败）")
    target_word_count: Optional[int] = Field(None, ge=500, le=10000, description="统一字数；不传按章纲 / 平台预设")
    require_confirmed_outline: bool = Field(False, description="只写已确认的章纲：遇到 AI 草拟 / 上游已改的章纲就停")
    adherence_gate: bool = Field(True, description="章纲遵循度审校不通过（漏写关键事件 / 抢跑 / 新增设定）时重写一次")
