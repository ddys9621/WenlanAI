"""导入导出服务"""
import json
from datetime import datetime
from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.project import Project
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.story_outline import StoryOutline
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.writing_style import WritingStyle
from app.models.generation_history import GenerationHistory
from app.models.world_rule import WorldRule
from app.models.plot_line import PlotLine
from app.models.chapter_outline import ChapterOutline
from app.models.plot_card import PlotCard
from app.models.plot_card_plot_line_link import PlotCardPlotLineLink
from app.models.plot_card_chapter_outline_link import PlotCardChapterOutlineLink
from app.models.chapter_outline_plot_line_link import ChapterOutlinePlotLineLink
from app.schemas.import_export import (
    ProjectExportData,
    ChapterExportData,
    CharacterExportData,
    OutlineExportData,
    RelationshipExportData,
    OrganizationExportData,
    OrganizationMemberExportData,
    WritingStyleExportData,
    GenerationHistoryExportData,
    WorldRuleExportData,
    PlotLineExportData,
    ChapterOutlineExportData,
    PlotCardExportData,
    ChapterOutlinePlotLineLinkExportData,
    PlotCardPlotLineLinkExportData,
    PlotCardChapterOutlineLinkExportData,
    ImportValidationResult,
    ImportResult
)
from app.logger import get_logger

logger = get_logger(__name__)


class ImportExportService:
    """导入导出服务类"""

    SUPPORTED_VERSION = "1.1.0"
    
    @staticmethod
    async def export_project(
        project_id: str,
        db: AsyncSession,
        include_generation_history: bool = False,
        include_writing_styles: bool = True
    ) -> ProjectExportData:
        """
        导出项目完整数据
        
        Args:
            project_id: 项目ID
            db: 数据库会话
            include_generation_history: 是否包含生成历史
            include_writing_styles: 是否包含写作风格
            
        Returns:
            ProjectExportData: 导出的项目数据
        """
        logger.info(f"开始导出项目: {project_id}")
        
        # 获取项目基本信息
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 项目基本信息
        project_data = {
            "title": project.title,
            "description": project.description,
            "theme": project.theme,
            "genre": project.genre,
            "target_words": project.target_words,
            "current_words": project.current_words,
            "status": project.status,
            "world_time_period": project.world_time_period,
            "world_location": project.world_location,
            "world_atmosphere": project.world_atmosphere,
            "world_rules": project.world_rules,
            "generation_prompt": project.generation_prompt,
            "chapter_count": project.chapter_count,
            "narrative_perspective": project.narrative_perspective,
            "character_count": project.character_count,
            "c3_hook_style": project.c3_hook_style,
            "user_id": project.user_id,
            "created_at": project.created_at.isoformat() if project.created_at else None,
        }
        
        # 导出章节
        chapters = await ImportExportService._export_chapters(project_id, db)
        logger.info(f"导出章节数: {len(chapters)}")
        
        # 导出角色
        characters = await ImportExportService._export_characters(project_id, db)
        logger.info(f"导出角色数: {len(characters)}")
        
        # 导出大纲
        outlines = await ImportExportService._export_outlines(project_id, db)
        logger.info(f"导出大纲数: {len(outlines)}")
        
        # 导出关系
        relationships = await ImportExportService._export_relationships(project_id, db)
        logger.info(f"导出关系数: {len(relationships)}")
        
        # 导出组织详情
        organizations = await ImportExportService._export_organizations(project_id, db)
        logger.info(f"导出组织数: {len(organizations)}")
        
        # 导出组织成员
        org_members = await ImportExportService._export_organization_members(project_id, db)
        logger.info(f"导出组织成员数: {len(org_members)}")
        
        # 导出写作风格（可选）
        writing_styles = []
        if include_writing_styles:
            writing_styles = await ImportExportService._export_writing_styles(project_id, db)
            logger.info(f"导出写作风格数: {len(writing_styles)}")
        
        # 导出生成历史（可选）
        generation_history = []
        if include_generation_history:
            generation_history = await ImportExportService._export_generation_history(project_id, db)
            logger.info(f"导出生成历史数: {len(generation_history)}")

        # 导出世界规则
        world_rules = await ImportExportService._export_world_rules(project_id, db)
        logger.info(f"导出世界规则数: {len(world_rules)}")

        # 导出剧情线
        plot_lines = await ImportExportService._export_plot_lines(project_id, db)
        logger.info(f"导出剧情线数: {len(plot_lines)}")

        # 导出章节大纲
        chapter_outlines = await ImportExportService._export_chapter_outlines(project_id, db)
        logger.info(f"导出章节大纲数: {len(chapter_outlines)}")

        # 导出剧情卡片
        plot_cards = await ImportExportService._export_plot_cards(project_id, db)
        logger.info(f"导出剧情卡片数: {len(plot_cards)}")

        # 导出关联关系(v1.1.0新增)
        chapter_outline_plot_line_links = await ImportExportService._export_chapter_outline_plot_line_links(project_id, db)
        logger.info(f"导出章节大纲-剧情线关联数: {len(chapter_outline_plot_line_links)}")

        plot_card_plot_line_links = await ImportExportService._export_plot_card_plot_line_links(project_id, db)
        logger.info(f"导出剧情卡片-剧情线关联数: {len(plot_card_plot_line_links)}")

        plot_card_chapter_outline_links = await ImportExportService._export_plot_card_chapter_outline_links(project_id, db)
        logger.info(f"导出剧情卡片-章节大纲关联数: {len(plot_card_chapter_outline_links)}")

        export_data = ProjectExportData(
            version=ImportExportService.SUPPORTED_VERSION,
            export_time=datetime.utcnow().isoformat(),
            project=project_data,
            chapters=chapters,
            characters=characters,
            outlines=outlines,
            relationships=relationships,
            organizations=organizations,
            organization_members=org_members,
            writing_styles=writing_styles,
            generation_history=generation_history,
            world_rules=world_rules,
            plot_lines=plot_lines,
            chapter_outlines=chapter_outlines,
            plot_cards=plot_cards,
            chapter_outline_plot_line_links=chapter_outline_plot_line_links,
            plot_card_plot_line_links=plot_card_plot_line_links,
            plot_card_chapter_outline_links=plot_card_chapter_outline_links
        )

        logger.info(f"项目导出完成: {project_id}")
        return export_data
    
    @staticmethod
    async def _export_chapters(project_id: str, db: AsyncSession) -> List[ChapterExportData]:
        """导出章节"""
        result = await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_number)
        )
        chapters = result.scalars().all()

        # 获取章纲映射，用于恢复章节与章纲的关联
        outline_result = await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id)
        )
        outlines = outline_result.scalars().all()
        # 建立 id -> chapter_number 的映射
        outline_map = {o.id: o.chapter_number for o in outlines}

        return [
            ChapterExportData(
                title=ch.title,
                content=ch.content,
                summary=ch.summary,
                chapter_number=ch.chapter_number,
                word_count=ch.word_count or 0,
                status=ch.status,
                created_at=ch.created_at.isoformat() if ch.created_at else None,
                # v1.2.0新增：记录关联的章纲编号，用于导入时恢复关联
                chapter_outline_number=outline_map.get(ch.chapter_outline_id)
            )
            for ch in chapters
        ]
    
    @staticmethod
    async def _export_characters(project_id: str, db: AsyncSession) -> List[CharacterExportData]:
        """导出角色"""
        result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = result.scalars().all()
        
        exported = []
        for char in characters:
            # 解析traits JSON
            traits = None
            if char.traits:
                try:
                    traits = json.loads(char.traits) if isinstance(char.traits, str) else char.traits
                except:
                    traits = None
            
            exported.append(CharacterExportData(
                name=char.name,
                age=char.age,
                gender=char.gender,
                is_organization=char.is_organization or False,
                role_type=char.role_type,
                personality=char.personality,
                background=char.background,
                appearance=char.appearance,
                traits=traits,
                organization_type=char.organization_type,
                organization_purpose=char.organization_purpose,
                created_at=char.created_at.isoformat() if char.created_at else None
            ))
        
        return exported
    
    @staticmethod
    async def _export_outlines(project_id: str, db: AsyncSession) -> List[OutlineExportData]:
        """导出大纲"""
        result = await db.execute(
            select(StoryOutline)
            .where(StoryOutline.project_id == project_id)
            .order_by(StoryOutline.order_index)
        )
        outlines = result.scalars().all()
        
        return [
            OutlineExportData(
                title=ol.title,
                content=ol.content,
                order_index=ol.order_index,
                created_at=ol.created_at.isoformat() if ol.created_at else None
            )
            for ol in outlines
        ]
    
    @staticmethod
    async def _export_relationships(project_id: str, db: AsyncSession) -> List[RelationshipExportData]:
        """导出关系"""
        result = await db.execute(
            select(CharacterRelationship, Character)
            .join(Character, CharacterRelationship.character_from_id == Character.id)
            .where(CharacterRelationship.project_id == project_id)
        )
        relationships = result.all()
        
        exported = []
        for rel, char_from in relationships:
            # 获取目标角色名称
            target_result = await db.execute(
                select(Character).where(Character.id == rel.character_to_id)
            )
            char_to = target_result.scalar_one_or_none()
            
            if char_to:
                exported.append(RelationshipExportData(
                    source_name=char_from.name,
                    target_name=char_to.name,
                    relationship_name=rel.relationship_name,
                    intimacy_level=rel.intimacy_level or 50,
                    status=rel.status or "active",
                    description=rel.description,
                    started_at=rel.started_at
                ))
        
        return exported
    
    @staticmethod
    async def _export_organizations(project_id: str, db: AsyncSession) -> List[OrganizationExportData]:
        """导出组织详情"""
        result = await db.execute(
            select(Organization, Character)
            .join(Character, Organization.character_id == Character.id)
            .where(Organization.project_id == project_id)
        )
        organizations = result.all()
        
        exported = []
        for org, char in organizations:
            # 获取父组织名称
            parent_name = None
            if org.parent_org_id:
                parent_result = await db.execute(
                    select(Organization, Character)
                    .join(Character, Organization.character_id == Character.id)
                    .where(Organization.id == org.parent_org_id)
                )
                parent_data = parent_result.first()
                if parent_data:
                    parent_name = parent_data[1].name
            
            exported.append(OrganizationExportData(
                character_name=char.name,
                parent_org_name=parent_name,
                power_level=org.power_level or 50,
                member_count=org.member_count or 0,
                location=org.location,
                motto=org.motto,
                color=org.color
            ))
        
        return exported
    
    @staticmethod
    async def _export_organization_members(project_id: str, db: AsyncSession) -> List[OrganizationMemberExportData]:
        """导出组织成员"""
        result = await db.execute(
            select(OrganizationMember, Organization, Character)
            .join(Organization, OrganizationMember.organization_id == Organization.id)
            .join(Character, Organization.character_id == Character.id)
            .where(Organization.project_id == project_id)
        )
        members = result.all()
        
        exported = []
        for member, _org, org_char in members:
            # 获取成员角色名称
            char_result = await db.execute(
                select(Character).where(Character.id == member.character_id)
            )
            member_char = char_result.scalar_one_or_none()
            
            if member_char:
                exported.append(OrganizationMemberExportData(
                    organization_name=org_char.name,
                    character_name=member_char.name,
                    position=member.position,
                    rank=member.rank or 0,
                    status=member.status or "active",
                    joined_at=member.joined_at,
                    loyalty=member.loyalty or 50,
                    contribution=member.contribution or 0,
                    notes=member.notes
                ))
        
        return exported
    
    @staticmethod
    async def _export_writing_styles(project_id: str, db: AsyncSession) -> List[WritingStyleExportData]:
        """导出写作风格"""
        result = await db.execute(
            select(WritingStyle)
            .where(WritingStyle.project_id == project_id)
            .order_by(WritingStyle.order_index)
        )
        styles = result.scalars().all()
        
        return [
            WritingStyleExportData(
                name=style.name,
                style_type=style.style_type,
                preset_id=style.preset_id,
                description=style.description,
                prompt_content=style.prompt_content,
                order_index=style.order_index or 0
            )
            for style in styles
        ]
    
    @staticmethod
    async def _export_generation_history(project_id: str, db: AsyncSession) -> List[GenerationHistoryExportData]:
        """导出生成历史"""
        result = await db.execute(
            select(GenerationHistory, Chapter)
            .outerjoin(Chapter, GenerationHistory.chapter_id == Chapter.id)
            .where(GenerationHistory.project_id == project_id)
            .order_by(GenerationHistory.created_at.desc())
            .limit(100)  # 限制最多导出100条历史记录
        )
        histories = result.all()
        
        return [
            GenerationHistoryExportData(
                chapter_title=chapter.title if chapter else None,
                prompt=history.prompt,
                generated_content=history.generated_content,
                model=history.model,
                tokens_used=history.tokens_used,
                generation_time=history.generation_time,
                created_at=history.created_at.isoformat() if history.created_at else None
            )
            for history, chapter in histories
        ]

    @staticmethod
    async def _export_world_rules(project_id: str, db: AsyncSession) -> List[WorldRuleExportData]:
        """导出世界规则"""
        result = await db.execute(
            select(WorldRule)
            .where(WorldRule.project_id == project_id)
            .order_by(WorldRule.order_index)
        )
        rules = result.scalars().all()

        return [
            WorldRuleExportData(
                category=rule.category,
                key=rule.key,
                name=rule.name,
                summary=rule.summary,
                details=rule.details,
                order_index=rule.order_index or 0,
                created_at=rule.created_at.isoformat() if rule.created_at else None
            )
            for rule in rules
        ]

    @staticmethod
    async def _export_plot_lines(project_id: str, db: AsyncSession) -> List[PlotLineExportData]:
        """导出剧情线(含时间线节点)"""
        result = await db.execute(
            select(PlotLine)
            .where(PlotLine.project_id == project_id)
            .order_by(PlotLine.order_index)
        )
        lines = result.scalars().all()

        exported = []
        for line in lines:
            # 解析时间线节点数据
            timeline_data = None
            if line.timeline_data:
                try:
                    timeline_data = json.loads(line.timeline_data)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"剧情线 {line.title} 的 timeline_data 解析失败,跳过")

            exported.append(PlotLineExportData(
                name=line.title,
                description=line.description,
                line_type=line.line_type or "main",
                status="active",
                order_index=line.order_index or 0,
                timeline_data=timeline_data,
                created_at=line.created_at.isoformat() if line.created_at else None
            ))

        return exported

    @staticmethod
    async def _export_chapter_outlines(project_id: str, db: AsyncSession) -> List[ChapterOutlineExportData]:
        """导出章节大纲"""
        result = await db.execute(
            select(ChapterOutline)
            .where(ChapterOutline.project_id == project_id)
            .order_by(ChapterOutline.chapter_number)
        )
        outlines = result.scalars().all()

        exported = []
        for outline in outlines:
            # 解析 JSON 字段
            key_events = None
            if outline.key_events:
                try:
                    key_events = json.loads(outline.key_events)
                except:
                    key_events = None

            characters_involved = None
            if outline.characters_involved:
                try:
                    characters_involved = json.loads(outline.characters_involved)
                except:
                    characters_involved = None

            exported.append(ChapterOutlineExportData(
                chapter_number=outline.chapter_number,
                title=outline.title,
                summary=outline.summary,
                plot_points=outline.plot_points,
                key_events=key_events,
                characters_involved=characters_involved,
                target_word_count=outline.target_word_count or 3000,
                order_index=outline.order_index,
                # v1.2.0新增：导出完整字段
                scene=outline.scene,
                pov=outline.pov,
                emotional_arc=getattr(outline, 'emotional_arc', None),
                chapter_hook=getattr(outline, 'chapter_hook', None),
                created_at=outline.created_at.isoformat() if outline.created_at else None
            ))

        return exported

    @staticmethod
    async def _export_chapter_outline_plot_line_links(
        project_id: str,
        db: AsyncSession
    ) -> List[ChapterOutlinePlotLineLinkExportData]:
        """导出章节大纲-剧情线关联关系"""
        # 查询所有属于该项目的章节大纲-剧情线关联
        result = await db.execute(
            select(ChapterOutlinePlotLineLink, ChapterOutline, PlotLine)
            .join(ChapterOutline, ChapterOutlinePlotLineLink.chapter_outline_id == ChapterOutline.id)
            .join(PlotLine, ChapterOutlinePlotLineLink.plot_line_id == PlotLine.id)
            .where(ChapterOutline.project_id == project_id)
        )
        links = result.all()

        exported = []
        for link, outline, plot_line in links:
            # 解析时间线覆盖数据
            timeline_coverage = None
            if link.timeline_coverage:
                try:
                    timeline_coverage = json.loads(link.timeline_coverage)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"章节 {outline.chapter_number} 与剧情线 {plot_line.title} 的 timeline_coverage 解析失败")

            exported.append(ChapterOutlinePlotLineLinkExportData(
                chapter_outline_number=outline.chapter_number,
                plot_line_name=plot_line.title,
                role=link.role,
                order_index=link.order_index,
                timeline_coverage=timeline_coverage
            ))

        return exported

    @staticmethod
    async def _export_plot_cards(project_id: str, db: AsyncSession) -> List[PlotCardExportData]:
        """导出剧情卡片(兼容字段用于v1.0.0)"""
        # 获取项目的所有剧情卡片
        result = await db.execute(
            select(PlotCard)
            .where(PlotCard.project_id == project_id)
            .order_by(PlotCard.order_index)
        )
        cards = result.scalars().all()

        exported = []
        for card in cards:
            # 获取第一个关联的剧情线(兼容字段,用于v1.0.0)
            plot_line_result = await db.execute(
                select(PlotLine)
                .join(PlotCardPlotLineLink, PlotLine.id == PlotCardPlotLineLink.plot_line_id)
                .where(PlotCardPlotLineLink.plot_card_id == card.id)
                .limit(1)
            )
            plot_line = plot_line_result.scalar_one_or_none()

            # 获取第一个关联的章纲(兼容字段,用于v1.0.0)
            chapter_result = await db.execute(
                select(ChapterOutline)
                .join(PlotCardChapterOutlineLink, ChapterOutline.id == PlotCardChapterOutlineLink.chapter_outline_id)
                .where(PlotCardChapterOutlineLink.plot_card_id == card.id)
                .limit(1)
            )
            chapter = chapter_result.scalar_one_or_none()

            # 处理tags - 保持为JSON字符串格式
            tags = card.tags  # 直接使用原始的JSON字符串,不解析

            exported.append(PlotCardExportData(
                plot_line_name=plot_line.title if plot_line else None,
                chapter_outline_number=chapter.chapter_number if chapter else None,
                title=card.title,
                content=card.content,
                card_type=card.card_type or "event",
                order_index=card.order_index or 0,
                tags=tags,
                created_at=card.created_at.isoformat() if card.created_at else None
            ))

        return exported

    @staticmethod
    async def _export_plot_card_plot_line_links(
        project_id: str,
        db: AsyncSession
    ) -> List[PlotCardPlotLineLinkExportData]:
        """导出剧情卡片-剧情线关联关系"""
        # 查询所有属于该项目的剧情卡片-剧情线关联
        result = await db.execute(
            select(PlotCardPlotLineLink, PlotCard, PlotLine)
            .join(PlotCard, PlotCardPlotLineLink.plot_card_id == PlotCard.id)
            .join(PlotLine, PlotCardPlotLineLink.plot_line_id == PlotLine.id)
            .where(PlotCard.project_id == project_id)
        )
        links = result.all()

        exported = []
        for _link, card, plot_line in links:
            exported.append(PlotCardPlotLineLinkExportData(
                card_title=card.title,
                plot_line_name=plot_line.title
            ))

        return exported

    @staticmethod
    async def _export_plot_card_chapter_outline_links(
        project_id: str,
        db: AsyncSession
    ) -> List[PlotCardChapterOutlineLinkExportData]:
        """导出剧情卡片-章节大纲关联关系"""
        # 查询所有属于该项目的剧情卡片-章节大纲关联
        result = await db.execute(
            select(PlotCardChapterOutlineLink, PlotCard, ChapterOutline)
            .join(PlotCard, PlotCardChapterOutlineLink.plot_card_id == PlotCard.id)
            .join(ChapterOutline, PlotCardChapterOutlineLink.chapter_outline_id == ChapterOutline.id)
            .where(PlotCard.project_id == project_id)
        )
        links = result.all()

        exported = []
        for link, card, outline in links:
            exported.append(PlotCardChapterOutlineLinkExportData(
                card_title=card.title,
                chapter_outline_number=outline.chapter_number,
                usage_type=link.usage_type,
                usage_notes=link.usage_notes
            ))

        return exported

    @staticmethod
    def validate_import_data(data: Dict) -> ImportValidationResult:
        """
        验证导入数据
        
        Args:
            data: 导入的JSON数据
            
        Returns:
            ImportValidationResult: 验证结果
        """
        errors = []
        warnings = []
        statistics = {}
        
        # 检查版本
        version = data.get("version", "")
        if not version:
            errors.append("缺少版本信息")
        elif version not in ["1.0.0", "1.1.0"]:
            warnings.append(f"版本不匹配: 导入文件版本为 {version}, 当前支持版本为 1.0.0/1.1.0")
        elif version == "1.0.0":
            warnings.append("导入v1.0.0格式文件,部分关联关系可能无法完整还原(时间线节点、多对多关联)")
        
        # 检查必需字段
        if "project" not in data:
            errors.append("缺少项目信息")
        else:
            project = data["project"]
            if not project.get("title"):
                errors.append("项目标题不能为空")
        
        # 统计数据
        statistics = {
            "chapters": len(data.get("chapters", [])),
            "characters": len(data.get("characters", [])),
            "outlines": len(data.get("outlines", [])),
            "relationships": len(data.get("relationships", [])),
            "organizations": len(data.get("organizations", [])),
            "organization_members": len(data.get("organization_members", [])),
            "writing_styles": len(data.get("writing_styles", [])),
            "generation_history": len(data.get("generation_history", [])),
            "world_rules": len(data.get("world_rules", [])),
            "plot_lines": len(data.get("plot_lines", [])),
            "chapter_outlines": len(data.get("chapter_outlines", [])),
            "plot_cards": len(data.get("plot_cards", [])),
            # v1.1.0新增字段
            "chapter_outline_plot_line_links": len(data.get("chapter_outline_plot_line_links", [])),
            "plot_card_plot_line_links": len(data.get("plot_card_plot_line_links", [])),
            "plot_card_chapter_outline_links": len(data.get("plot_card_chapter_outline_links", []))
        }
        
        # 检查数据完整性
        if statistics["chapters"] == 0:
            warnings.append("项目没有章节数据")
        
        if statistics["characters"] == 0:
            warnings.append("项目没有角色数据")
        
        project_name = data.get("project", {}).get("title", "未知项目")
        
        return ImportValidationResult(
            valid=len(errors) == 0,
            version=version,
            project_name=project_name,
            statistics=statistics,
            errors=errors,
            warnings=warnings
        )
    
    @staticmethod
    async def import_project(
        data: Dict,
        db: AsyncSession,
        user_id: str
    ) -> ImportResult:
        """
        导入项目数据（创建新项目）
        
        Args:
            data: 导入的JSON数据
            db: 数据库会话
            user_id: 目标用户ID（导入后的项目归属）
            
        Returns:
            ImportResult: 导入结果
        """
        warnings = []
        statistics = {}
        
        try:
            # 验证数据
            validation = ImportExportService.validate_import_data(data)
            if not validation.valid:
                return ImportResult(
                    success=False,
                    message=f"数据验证失败: {', '.join(validation.errors)}",
                    statistics={},
                    warnings=validation.warnings
                )
            
            warnings.extend(validation.warnings)
            
            logger.info(f"开始导入项目: {validation.project_name}")
            
            # 创建项目
            project_data = data["project"]
            new_project = Project(
                user_id=user_id,  # 设置为当前用户ID
                title=project_data.get("title"),
                description=project_data.get("description"),
                theme=project_data.get("theme"),
                genre=project_data.get("genre"),
                target_words=project_data.get("target_words"),
                status=project_data.get("status", "planning"),
                world_time_period=project_data.get("world_time_period"),
                world_location=project_data.get("world_location"),
                world_atmosphere=project_data.get("world_atmosphere"),
                world_rules=project_data.get("world_rules"),
                generation_prompt=project_data.get("generation_prompt"),
                chapter_count=project_data.get("chapter_count"),
                narrative_perspective=project_data.get("narrative_perspective"),
                character_count=project_data.get("character_count"),
                c3_hook_style=project_data.get("c3_hook_style") or "none",
                current_words=project_data.get("current_words", 0),  # 保留原项目的字数
                wizard_step=4,  # 导入的项目设置为向导完成状态
                wizard_status="completed"  # 标记向导已完成
            )
            db.add(new_project)
            await db.flush()  # 获取project_id
            
            logger.info(f"创建项目成功: {new_project.id}")

            # 导入角色（包括组织）- 先导入，因为其他数据可能依赖角色
            char_mapping = await ImportExportService._import_characters(
                new_project.id, data.get("characters", []), db
            )
            statistics["characters"] = len(char_mapping)
            logger.info(f"导入角色数: {len(char_mapping)}")
            
            # 导入大纲
            outlines_count = await ImportExportService._import_outlines(
                new_project.id, data.get("outlines", []), db
            )
            statistics["outlines"] = outlines_count
            logger.info(f"导入大纲数: {outlines_count}")
            
            # 导入关系
            relationships_count = await ImportExportService._import_relationships(
                new_project.id, data.get("relationships", []), char_mapping, db
            )
            statistics["relationships"] = relationships_count
            logger.info(f"导入关系数: {relationships_count}")
            
            # 导入组织详情
            org_mapping = await ImportExportService._import_organizations(
                new_project.id, data.get("organizations", []), char_mapping, db
            )
            statistics["organizations"] = len(org_mapping)
            logger.info(f"导入组织数: {len(org_mapping)}")
            
            # 导入组织成员
            org_members_count = await ImportExportService._import_organization_members(
                data.get("organization_members", []), char_mapping, org_mapping, db
            )
            statistics["organization_members"] = org_members_count
            logger.info(f"导入组织成员数: {org_members_count}")
            
            # 导入写作风格
            styles_count = await ImportExportService._import_writing_styles(
                new_project.id, data.get("writing_styles", []), db
            )
            statistics["writing_styles"] = styles_count
            logger.info(f"导入写作风格数: {styles_count}")

            # 导入世界规则
            world_rules_count = await ImportExportService._import_world_rules(
                new_project.id, data.get("world_rules", []), db
            )
            statistics["world_rules"] = world_rules_count
            logger.info(f"导入世界规则数: {world_rules_count}")

            # 导入剧情线
            plot_line_mapping = await ImportExportService._import_plot_lines(
                new_project.id, data.get("plot_lines", []), db
            )
            statistics["plot_lines"] = len(plot_line_mapping)
            logger.info(f"导入剧情线数: {len(plot_line_mapping)}")

            # 导入章节大纲
            chapter_outline_mapping = await ImportExportService._import_chapter_outlines(
                new_project.id, data.get("chapter_outlines", []), db
            )
            statistics["chapter_outlines"] = len(chapter_outline_mapping)
            logger.info(f"导入章节大纲数: {len(chapter_outline_mapping)}")

            # 导入章节（在章纲之后导入，以便恢复关联）
            chapters_count = await ImportExportService._import_chapters(
                new_project.id,
                data.get("chapters", []),
                chapter_outline_mapping,  # 传递映射用于恢复关联
                db
            )
            statistics["chapters"] = chapters_count
            logger.info(f"导入章节数: {chapters_count}")

            # 导入章节大纲-剧情线关联(v1.1.0新增)
            chapter_outline_plot_line_links_count = 0
            if "chapter_outline_plot_line_links" in data:
                chapter_outline_plot_line_links_count = await ImportExportService._import_chapter_outline_plot_line_links(
                    data.get("chapter_outline_plot_line_links", []),
                    plot_line_mapping,
                    chapter_outline_mapping,
                    db
                )
                statistics["chapter_outline_plot_line_links"] = chapter_outline_plot_line_links_count
                logger.info(f"导入章节大纲-剧情线关联数: {chapter_outline_plot_line_links_count}")

            # 导入剧情卡片
            plot_card_mapping = await ImportExportService._import_plot_cards(
                new_project.id,
                data.get("plot_cards", []),
                plot_line_mapping,
                chapter_outline_mapping,
                db
            )
            statistics["plot_cards"] = len(plot_card_mapping)
            logger.info(f"导入剧情卡片数: {len(plot_card_mapping)}")

            # 导入剧情卡片-剧情线关联(v1.1.0新增)
            plot_card_plot_line_links_count = 0
            if "plot_card_plot_line_links" in data:
                plot_card_plot_line_links_count = await ImportExportService._import_plot_card_plot_line_links(
                    data.get("plot_card_plot_line_links", []),
                    plot_card_mapping,
                    plot_line_mapping,
                    db
                )
                statistics["plot_card_plot_line_links"] = plot_card_plot_line_links_count
                logger.info(f"导入剧情卡片-剧情线关联数: {plot_card_plot_line_links_count}")

            # 导入剧情卡片-章节大纲关联(v1.1.0新增)
            plot_card_chapter_outline_links_count = 0
            if "plot_card_chapter_outline_links" in data:
                plot_card_chapter_outline_links_count = await ImportExportService._import_plot_card_chapter_outline_links(
                    data.get("plot_card_chapter_outline_links", []),
                    plot_card_mapping,
                    chapter_outline_mapping,
                    db
                )
                statistics["plot_card_chapter_outline_links"] = plot_card_chapter_outline_links_count
                logger.info(f"导入剧情卡片-章节大纲关联数: {plot_card_chapter_outline_links_count}")

            # 提交事务
            await db.commit()
            
            logger.info(f"项目导入完成: {new_project.id}")
            
            return ImportResult(
                success=True,
                project_id=new_project.id,
                message="项目导入成功",
                statistics=statistics,
                warnings=warnings
            )
            
        except Exception as e:
            await db.rollback()
            logger.error(f"导入项目失败: {str(e)}", exc_info=True)
            return ImportResult(
                success=False,
                message=f"导入失败: {str(e)}",
                statistics=statistics,
                warnings=warnings
            )
    
    @staticmethod
    async def _import_chapters(
        project_id: str,
        chapters_data: List[Dict],
        chapter_outline_mapping: Dict[int, str],  # v1.2.0新增：章纲编号到ID的映射
        db: AsyncSession
    ) -> int:
        """导入章节"""
        count = 0
        for ch_data in chapters_data:
            # v1.2.0新增：通过章节号查找关联的章纲ID
            chapter_outline_id = None
            outline_number = ch_data.get("chapter_outline_number")
            if outline_number and chapter_outline_mapping:
                chapter_outline_id = chapter_outline_mapping.get(outline_number)

            chapter = Chapter(
                project_id=project_id,
                title=ch_data.get("title"),
                content=ch_data.get("content"),
                summary=ch_data.get("summary"),
                chapter_number=ch_data.get("chapter_number"),
                word_count=ch_data.get("word_count", 0),
                status=ch_data.get("status", "draft"),
                chapter_outline_id=chapter_outline_id  # v1.2.0新增：恢复章纲关联
            )
            db.add(chapter)
            count += 1

        return count
    
    @staticmethod
    async def _import_characters(
        project_id: str,
        characters_data: List[Dict],
        db: AsyncSession
    ) -> Dict[str, str]:
        """导入角色，返回名称到ID的映射"""
        char_mapping = {}
        
        for char_data in characters_data:
            # 处理traits
            traits = char_data.get("traits")
            if isinstance(traits, list):
                traits = json.dumps(traits, ensure_ascii=False)
            
            character = Character(
                project_id=project_id,
                name=char_data.get("name"),
                age=char_data.get("age"),
                gender=char_data.get("gender"),
                is_organization=char_data.get("is_organization", False),
                role_type=char_data.get("role_type"),
                personality=char_data.get("personality"),
                background=char_data.get("background"),
                appearance=char_data.get("appearance"),
                traits=traits,
                organization_type=char_data.get("organization_type"),
                organization_purpose=char_data.get("organization_purpose")
            )
            db.add(character)
            await db.flush()  # 获取ID
            char_mapping[char_data.get("name")] = character.id
        
        return char_mapping
    
    @staticmethod
    async def _import_outlines(
        project_id: str,
        outlines_data: List[Dict],
        db: AsyncSession
    ) -> int:
        """导入大纲"""
        count = 0
        for ol_data in outlines_data:
            outline = StoryOutline(
                project_id=project_id,
                title=ol_data.get("title"),
                content=ol_data.get("content"),
                order_index=ol_data.get("order_index")
            )
            db.add(outline)
            count += 1

        return count
    
    @staticmethod
    async def _import_relationships(
        project_id: str,
        relationships_data: List[Dict],
        char_mapping: Dict[str, str],
        db: AsyncSession
    ) -> int:
        """导入关系"""
        count = 0
        for rel_data in relationships_data:
            source_name = rel_data.get("source_name")
            target_name = rel_data.get("target_name")
            
            # 查找角色ID
            source_id = char_mapping.get(source_name)
            target_id = char_mapping.get(target_name)
            
            if source_id and target_id:
                relationship = CharacterRelationship(
                    project_id=project_id,
                    character_from_id=source_id,
                    character_to_id=target_id,
                    relationship_name=rel_data.get("relationship_name"),
                    intimacy_level=rel_data.get("intimacy_level", 50),
                    status=rel_data.get("status", "active"),
                    description=rel_data.get("description"),
                    started_at=rel_data.get("started_at")
                )
                db.add(relationship)
                count += 1
        
        return count
    
    @staticmethod
    async def _import_organizations(
        project_id: str,
        organizations_data: List[Dict],
        char_mapping: Dict[str, str],
        db: AsyncSession
    ) -> Dict[str, str]:
        """导入组织详情，返回名称到ID的映射"""
        org_mapping = {}
        
        # 第一遍：创建所有组织（不设置父组织）
        temp_orgs = []
        for org_data in organizations_data:
            char_name = org_data.get("character_name")
            char_id = char_mapping.get(char_name)
            
            if char_id:
                organization = Organization(
                    project_id=project_id,
                    character_id=char_id,
                    power_level=org_data.get("power_level", 50),
                    member_count=org_data.get("member_count", 0),
                    location=org_data.get("location"),
                    motto=org_data.get("motto"),
                    color=org_data.get("color")
                )
                db.add(organization)
                temp_orgs.append((organization, org_data.get("parent_org_name")))
        
        await db.flush()  # 获取所有组织的ID
        
        # 建立名称到ID的映射
        for org, _ in temp_orgs:
            # 通过character_id查找角色名
            result = await db.execute(
                select(Character).where(Character.id == org.character_id)
            )
            char = result.scalar_one_or_none()
            if char:
                org_mapping[char.name] = org.id
        
        # 第二遍：设置父组织关系
        for org, parent_name in temp_orgs:
            if parent_name:
                parent_id = org_mapping.get(parent_name)
                if parent_id:
                    org.parent_org_id = parent_id
        
        return org_mapping
    
    @staticmethod
    async def _import_organization_members(
        org_members_data: List[Dict],
        char_mapping: Dict[str, str],
        org_mapping: Dict[str, str],
        db: AsyncSession
    ) -> int:
        """导入组织成员"""
        count = 0
        for member_data in org_members_data:
            org_name = member_data.get("organization_name")
            char_name = member_data.get("character_name")
            
            org_id = org_mapping.get(org_name)
            char_id = char_mapping.get(char_name)
            
            if org_id and char_id:
                member = OrganizationMember(
                    organization_id=org_id,
                    character_id=char_id,
                    position=member_data.get("position"),
                    rank=member_data.get("rank", 0),
                    status=member_data.get("status", "active"),
                    joined_at=member_data.get("joined_at"),
                    loyalty=member_data.get("loyalty", 50),
                    contribution=member_data.get("contribution", 0),
                    notes=member_data.get("notes")
                )
                db.add(member)
                count += 1
        
        return count
    
    @staticmethod
    async def _import_writing_styles(
        project_id: str,
        styles_data: List[Dict],
        db: AsyncSession
    ) -> int:
        """导入写作风格"""
        count = 0
        for style_data in styles_data:
            style = WritingStyle(
                project_id=project_id,
                name=style_data.get("name"),
                style_type=style_data.get("style_type"),
                preset_id=style_data.get("preset_id"),
                description=style_data.get("description"),
                prompt_content=style_data.get("prompt_content"),
                order_index=style_data.get("order_index", 0)
            )
            db.add(style)
            count += 1

        return count

    @staticmethod
    async def _import_world_rules(
        project_id: str,
        rules_data: List[Dict],
        db: AsyncSession
    ) -> int:
        """导入世界规则"""
        from app.services.world_rule_service import world_rule_service

        count = 0
        imported_rules = []

        for rule_data in rules_data:
            rule = WorldRule(
                project_id=project_id,
                category=rule_data.get("category"),
                key=rule_data.get("key"),
                name=rule_data.get("name"),
                summary=rule_data.get("summary"),
                details=rule_data.get("details"),
                order_index=rule_data.get("order_index", 0)
            )
            db.add(rule)
            imported_rules.append(rule)
            count += 1

        # 刷新以获取ID
        await db.flush()

        # 向量化所有导入的规则
        for rule in imported_rules:
            try:
                await world_rule_service.upsert_rule_to_vector_db(rule)
            except Exception as e:
                logger.warning(f"⚠️ 规则向量化失败（不影响导入）: rule_id={rule.id}, error={str(e)}")

        logger.info(f"✅ 导入世界规则完成: {count} 条，已向量化")
        return count

    @staticmethod
    async def _import_plot_lines(
        project_id: str,
        lines_data: List[Dict],
        db: AsyncSession
    ) -> Dict[str, str]:
        """导入剧情线(含时间线节点)，返回名称到ID的映射"""
        mapping = {}
        for line_data in lines_data:
            # 处理时间线节点数据
            timeline_data = line_data.get("timeline_data")
            if timeline_data and isinstance(timeline_data, (list, dict)):
                # 将JSON结构序列化为字符串存入数据库
                timeline_data = json.dumps(timeline_data, ensure_ascii=False)

            line = PlotLine(
                project_id=project_id,
                title=line_data.get("name"),
                description=line_data.get("description"),
                line_type=line_data.get("line_type", "main"),
                order_index=line_data.get("order_index", 0),
                timeline_data=timeline_data
            )
            db.add(line)
            await db.flush()  # 获取ID
            mapping[line.title] = line.id

        return mapping

    @staticmethod
    async def _import_chapter_outlines(
        project_id: str,
        outlines_data: List[Dict],
        db: AsyncSession
    ) -> Dict[int, str]:
        """导入章节大纲，返回章节号到ID的映射"""
        mapping = {}
        for outline_data in outlines_data:
            # 还原为数据库中的 JSON 字符串格式
            key_events = outline_data.get("key_events")
            if isinstance(key_events, (list, dict)):
                key_events = json.dumps(key_events, ensure_ascii=False)

            characters_involved = outline_data.get("characters_involved")
            if isinstance(characters_involved, (list, dict)):
                characters_involved = json.dumps(characters_involved, ensure_ascii=False)

            outline = ChapterOutline(
                project_id=project_id,
                chapter_number=outline_data.get("chapter_number"),
                title=outline_data.get("title"),
                summary=outline_data.get("summary"),
                plot_points=outline_data.get("plot_points"),
                key_events=key_events,
                characters_involved=characters_involved,
                target_word_count=outline_data.get("target_word_count", 3000),
                order_index=outline_data.get("order_index"),
                # v1.2.0新增：导入完整字段
                scene=outline_data.get("scene"),
                pov=outline_data.get("pov"),
                emotional_arc=outline_data.get("emotional_arc"),
                chapter_hook=outline_data.get("chapter_hook")
            )
            db.add(outline)
            await db.flush()  # 获取ID
            mapping[outline.chapter_number] = outline.id

        return mapping

    @staticmethod
    async def _import_chapter_outline_plot_line_links(
        links_data: List[Dict],
        plot_line_mapping: Dict[str, str],
        chapter_outline_mapping: Dict[int, str],
        db: AsyncSession
    ) -> int:
        """导入章节大纲-剧情线关联关系"""
        count = 0
        for link_data in links_data:
            plot_line_name = link_data.get("plot_line_name")
            chapter_outline_number = link_data.get("chapter_outline_number")

            # 查找对应的ID
            plot_line_id = plot_line_mapping.get(plot_line_name)
            chapter_outline_id = chapter_outline_mapping.get(chapter_outline_number)

            if not plot_line_id or not chapter_outline_id:
                logger.warning(f"跳过章节大纲-剧情线关联: 章节{chapter_outline_number} - 剧情线{plot_line_name} (ID未找到)")
                continue

            # 处理时间线覆盖数据
            timeline_coverage = link_data.get("timeline_coverage")
            if timeline_coverage and isinstance(timeline_coverage, (list, dict)):
                timeline_coverage = json.dumps(timeline_coverage, ensure_ascii=False)

            link = ChapterOutlinePlotLineLink(
                chapter_outline_id=chapter_outline_id,
                plot_line_id=plot_line_id,
                role=link_data.get("role", "main"),
                order_index=link_data.get("order_index"),
                timeline_coverage=timeline_coverage
            )
            db.add(link)
            count += 1

        return count

    @staticmethod
    async def _import_plot_cards(
        project_id: str,
        cards_data: List[Dict],
        plot_line_mapping: Dict[str, str],
        chapter_outline_mapping: Dict[int, str],
        db: AsyncSession
    ) -> Dict[str, str]:
        """导入剧情卡片,返回标题到ID的映射(用于后续导入关联关系)"""
        mapping = {}
        for card_data in cards_data:
            # 处理tags字段
            tags = card_data.get("tags")
            if tags and isinstance(tags, (list, dict)):
                tags = json.dumps(tags, ensure_ascii=False)

            # 创建剧情卡片(只使用PlotCard模型真实存在的字段)
            card = PlotCard(
                project_id=project_id,
                title=card_data.get("title"),
                content=card_data.get("content"),
                card_type=card_data.get("card_type", "event"),
                order_index=card_data.get("order_index", 0),
                tags=tags
            )
            db.add(card)
            await db.flush()  # 获取ID
            mapping[card.title] = card.id

        return mapping

    @staticmethod
    async def _import_plot_card_plot_line_links(
        links_data: List[Dict],
        plot_card_mapping: Dict[str, str],
        plot_line_mapping: Dict[str, str],
        db: AsyncSession
    ) -> int:
        """导入剧情卡片-剧情线关联关系"""
        count = 0
        for link_data in links_data:
            card_title = link_data.get("card_title")
            plot_line_name = link_data.get("plot_line_name")

            # 查找对应的ID
            card_id = plot_card_mapping.get(card_title)
            plot_line_id = plot_line_mapping.get(plot_line_name)

            if not card_id or not plot_line_id:
                logger.warning(f"跳过剧情卡片-剧情线关联: 卡片'{card_title}' - 剧情线'{plot_line_name}' (ID未找到)")
                continue

            link = PlotCardPlotLineLink(
                plot_card_id=card_id,
                plot_line_id=plot_line_id
            )
            db.add(link)
            count += 1

        return count

    @staticmethod
    async def _import_plot_card_chapter_outline_links(
        links_data: List[Dict],
        plot_card_mapping: Dict[str, str],
        chapter_outline_mapping: Dict[int, str],
        db: AsyncSession
    ) -> int:
        """导入剧情卡片-章节大纲关联关系"""
        count = 0
        for link_data in links_data:
            card_title = link_data.get("card_title")
            chapter_outline_number = link_data.get("chapter_outline_number")

            # 查找对应的ID
            card_id = plot_card_mapping.get(card_title)
            chapter_outline_id = chapter_outline_mapping.get(chapter_outline_number)

            if not card_id or not chapter_outline_id:
                logger.warning(f"跳过剧情卡片-章节大纲关联: 卡片'{card_title}' - 章节{chapter_outline_number} (ID未找到)")
                continue

            link = PlotCardChapterOutlineLink(
                plot_card_id=card_id,
                chapter_outline_id=chapter_outline_id,
                usage_type=link_data.get("usage_type", "reference"),
                usage_notes=link_data.get("usage_notes")
            )
            db.add(link)
            count += 1

        return count
