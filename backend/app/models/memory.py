"""长期记忆数据模型 - 支持向量检索和剧情分析"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Float, JSON
from sqlalchemy.sql import func
from app.db_base import Base
import uuid


class StoryMemory(Base):
    """故事记忆表 - 存储结构化的故事片段和元数据"""
    __tablename__ = "story_memories"
    
    id = Column(String(100), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # 记忆类型
    memory_type = Column(String(50), nullable=False, index=True, comment="""
    记忆类型:
    - plot_point: 情节点
    - character_event: 角色事件
    - world_detail: 世界观细节
    - hook: 钩子(悬念/冲突)
    - foreshadow: 伏笔
    - dialogue: 重要对话
    - scene: 场景描写
    """)
    
    # 记忆内容
    title = Column(String(200), comment="记忆标题/简述")
    content = Column(Text, nullable=False, comment="记忆内容摘要(100-500字)")
    full_context = Column(Text, comment="完整上下文(可选,用于详细记录)")
    
    # 关联信息
    related_characters = Column(JSON, comment="涉及角色ID列表: ['char_id_1', 'char_id_2']")
    related_locations = Column(JSON, comment="涉及地点列表: ['地点1', '地点2']")
    tags = Column(JSON, comment="标签列表: ['悬念', '转折', '伏笔', '高潮']")
    
    # 重要性评分 (用于过滤和排序)
    importance_score = Column(Float, default=0.5, comment="重要性评分 0.0-1.0")
    
    # 时间线定位
    story_timeline = Column(Integer, nullable=False, index=True, comment="故事时间线位置(章节序号)")
    chapter_position = Column(Integer, default=0, comment="章节内位置(字符位置)")
    text_length = Column(Integer, default=0, comment="文本长度(字符数)")
    
    # 伏笔相关字段
    is_foreshadow = Column(Integer, default=0, comment="伏笔状态: 0=普通记忆, 1=已埋下伏笔, 2=伏笔已回收")
    foreshadow_resolved_at = Column(String(100), ForeignKey("chapters.id", ondelete="SET NULL"), comment="伏笔回收的章节ID")
    foreshadow_strength = Column(Float, comment="伏笔强度 0.0-1.0")
    
    # 向量数据库关联
    vector_id = Column(String(100), unique=True, comment="向量数据库中的唯一ID")
    embedding_model = Column(String(100), default="paraphrase-multilingual-MiniLM-L12-v2", comment="使用的embedding模型")
    
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<StoryMemory(id={self.id[:8]}, type={self.memory_type}, title={self.title})>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "memory_type": self.memory_type,
            "title": self.title,
            "content": self.content,
            "related_characters": self.related_characters,
            "related_locations": self.related_locations,
            "tags": self.tags,
            "importance_score": self.importance_score,
            "story_timeline": self.story_timeline,
            "is_foreshadow": self.is_foreshadow,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class PlotAnalysis(Base):
    """剧情分析表 - 存储AI分析的章节结构和剧情元素"""
    __tablename__ = "plot_analysis"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # 剧情结构分析
    plot_stage = Column(String(50), comment="剧情阶段: 开端/发展/高潮/结局/过渡")
    conflict_level = Column(Integer, comment="冲突强度 1-10")
    conflict_types = Column(JSON, comment="冲突类型列表: ['人与人', '人与己', '人与环境']")
    
    # 情感分析
    emotional_tone = Column(String(100), comment="主导情感: 紧张/温馨/悲伤/激昂/平静")
    emotional_intensity = Column(Float, comment="情感强度 0.0-1.0")
    emotional_curve = Column(JSON, comment="情感曲线: {start: 0.3, middle: 0.7, end: 0.5}")
    
    # 钩子分析 (Hook Analysis)
    hooks = Column(JSON, comment="""钩子列表 - 吸引读者的元素: [
        {
            "type": "悬念|情感|冲突|认知",
            "content": "具体内容",
            "strength": 8,
            "position": "开头|中段|结尾"
        }
    ]""")
    hooks_count = Column(Integer, default=0, comment="钩子数量")
    hooks_avg_strength = Column(Float, comment="钩子平均强度")
    
    # 伏笔分析 (Foreshadowing Analysis)
    foreshadows = Column(JSON, comment="""伏笔列表: [
        {
            "content": "伏笔内容",
            "type": "planted|resolved",
            "strength": 7,
            "subtlety": 8,
            "reference_chapter": 3
        }
    ]""")
    foreshadows_planted = Column(Integer, default=0, comment="本章埋下的伏笔数量")
    foreshadows_resolved = Column(Integer, default=0, comment="本章回收的伏笔数量")
    
    # 关键情节点 (Plot Points)
    plot_points = Column(JSON, comment="""情节点列表: [
        {
            "content": "情节点描述",
            "importance": 0.9,
            "type": "revelation|conflict|resolution|transition",
            "impact": "对故事的影响描述"
        }
    ]""")
    plot_points_count = Column(Integer, default=0, comment="情节点数量")
    
    # 角色状态追踪 (Character State Tracking)
    character_states = Column(JSON, comment="""角色状态变化: [
        {
            "character_id": "xxx",
            "character_name": "张三",
            "state_before": "犹豫不决",
            "state_after": "坚定信念",
            "psychological_change": "内心描述",
            "key_event": "触发事件",
            "relationship_changes": {"李四": "关系变化"}
        }
    ]""")
    
    # 场景和氛围
    scenes = Column(JSON, comment="场景列表: [{location: '地点', atmosphere: '氛围', duration: '时长'}]")
    pacing = Column(String(50), comment="节奏: slow|moderate|fast|varied")
    
    # 质量评分
    overall_quality_score = Column(Float, comment="整体质量评分 0.0-10.0")
    pacing_score = Column(Float, comment="节奏评分 0.0-10.0")
    engagement_score = Column(Float, comment="吸引力评分 0.0-10.0")
    coherence_score = Column(Float, comment="连贯性评分 0.0-10.0")
    
    # 文本分析报告
    analysis_report = Column(Text, comment="完整的文字分析报告")
    suggestions = Column(JSON, comment="改进建议列表: ['建议1', '建议2']")
    
    # 统计信息
    word_count = Column(Integer, comment="章节字数")
    dialogue_ratio = Column(Float, comment="对话占比 0.0-1.0")
    description_ratio = Column(Float, comment="描写占比 0.0-1.0")

    # 分析时的正文指纹：正文改了（指纹不一致）分析结果才算过期；旧记录为空时退回按时间判断
    content_hash = Column(String(64), nullable=True, comment="分析时的正文指纹")

    created_at = Column(DateTime, server_default=func.now(), comment="分析时间")
    
    def __repr__(self):
        return f"<PlotAnalysis(chapter_id={self.chapter_id[:8]}, stage={self.plot_stage}, quality={self.overall_quality_score})>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "plot_stage": self.plot_stage,
            "conflict_level": self.conflict_level,
            "conflict_types": self.conflict_types or [],
            "emotional_tone": self.emotional_tone,
            "emotional_intensity": self.emotional_intensity or 0.0,
            "hooks": self.hooks or [],
            "hooks_count": self.hooks_count or 0,
            "foreshadows": self.foreshadows or [],
            "foreshadows_planted": self.foreshadows_planted or 0,
            "foreshadows_resolved": self.foreshadows_resolved or 0,
            "plot_points": self.plot_points or [],
            "plot_points_count": self.plot_points_count or 0,
            "character_states": self.character_states or [],
            "scenes": self.scenes or [],
            "pacing": self.pacing,
            "overall_quality_score": self.overall_quality_score or 0.0,
            "pacing_score": self.pacing_score or 0.0,
            "engagement_score": self.engagement_score or 0.0,
            "coherence_score": self.coherence_score or 0.0,
            "analysis_report": self.analysis_report,
            "suggestions": self.suggestions or [],
            "dialogue_ratio": self.dialogue_ratio or 0.0,
            "description_ratio": self.description_ratio or 0.0,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }