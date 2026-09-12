"""场景生成服务 - 简化版，复用原有完整上下文逻辑"""
from typing import List, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import (
    Project, ChapterOutline, PlotCard,
    Character, WritingStyle
)
from app.models.plot_card_chapter_outline_link import PlotCardChapterOutlineLink
from app.services.ai_service import AIService
from app.services.deai_history import load_project_prior
from app.services.deai_rules import build_write_block
from app.services.memory_service import MemoryService
from app.logger import get_logger

logger = get_logger(__name__)


class SceneGenerationService:
    """场景生成服务类 - 按剧情卡片分段生成章节内容"""

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        self.memory_service = MemoryService()

    async def get_plot_cards_for_chapter(
        self, db: AsyncSession, chapter_outline_id: str
    ) -> List[PlotCard]:
        """获取章纲关联的剧情卡片（按生成顺序排序）"""
        result = await db.execute(
            select(PlotCard)
            .join(PlotCardChapterOutlineLink)
            .where(PlotCardChapterOutlineLink.chapter_outline_id == chapter_outline_id)
            .order_by(PlotCard.generation_order, PlotCard.order_index)
        )
        return list(result.scalars().all())

    async def generate_scene_direct(
        self,
        db: AsyncSession,
        chapter_outline_id: str,
        plot_card_id: str,
        user_id: str,
        writing_style_id: Optional[str] = None,
        previous_generated_content: Optional[str] = None,
        # R8 拆书参考包显式参数（任一为空则走 injector 默认）
        pack_ids: Optional[List[str]] = None,
        dimensions: Optional[List[str]] = None,
        strength: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        直接生成场景内容，复用原有的完整上下文收集逻辑

        Args:
            db: 数据库会话
            chapter_outline_id: 章纲ID
            plot_card_id: 剧情卡片ID
            user_id: 用户ID
            writing_style_id: 写作风格ID
            previous_generated_content: 前端编辑器中已有的内容（用户可能已修改）

        Yields:
            str: 流式生成的内容片段
        """
        from app.services.prompt_service import prompt_service
        from app.services.world_rule_service import world_rule_service
        
        logger.info(f"🎬 [场景生成] 开始: outline={chapter_outline_id}, card={plot_card_id}")
        
        # 获取章纲
        outline_result = await db.execute(
            select(ChapterOutline).where(ChapterOutline.id == chapter_outline_id)
        )
        chapter_outline = outline_result.scalar_one_or_none()
        if not chapter_outline:
            raise ValueError(f"章纲不存在: {chapter_outline_id}")
        
        # 获取项目
        project_result = await db.execute(
            select(Project).where(Project.id == chapter_outline.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise ValueError("项目不存在")
        
        # 验证用户权限
        if project.user_id != user_id:
            raise ValueError("无权访问此项目")
        
        # 获取剧情卡片
        card_result = await db.execute(select(PlotCard).where(PlotCard.id == plot_card_id))
        plot_card = card_result.scalar_one_or_none()
        if not plot_card:
            raise ValueError(f"剧情卡片不存在: {plot_card_id}")
        
        # 获取所有场景卡片
        all_plot_cards = await self.get_plot_cards_for_chapter(db, chapter_outline_id)

        # ========== 复用原有的完整上下文收集逻辑 ==========

        # 1. 增强世界规则（使用语义检索）
        outline_text = chapter_outline.summary or chapter_outline.plot_points or ''
        query_text = f"{project.theme or ''} {project.genre or ''} {outline_text[:500]}"
        enhanced_world_rules = await world_rule_service.generate_rules_summary_with_search(
            db, project.id, query_text, limit=5
        )
        final_world_rules = project.world_rules or '未设定'
        if enhanced_world_rules:
            final_world_rules = f"{final_world_rules}\n\n{enhanced_world_rules}"

        # 2. 使用智能上下文构建（支持海量章节）
        from app.api.chapters import build_smart_chapter_context
        smart_context = await build_smart_chapter_context(
            db=db,
            project_id=project.id,
            current_chapter_number=chapter_outline.chapter_number,
            user_id=user_id
        )

        # 组装智能上下文
        outlines_context = ""
        if smart_context['story_skeleton']:
            outlines_context += smart_context['story_skeleton'] + "\n\n"
        if smart_context['relevant_history']:
            outlines_context += smart_context['relevant_history'] + "\n\n"
        if smart_context['recent_summary']:
            outlines_context += smart_context['recent_summary']

        # 日志输出统计信息
        stats = smart_context.get('stats', {})
        logger.info(f"📊 智能上下文统计:")
        logger.info(f"  - 前置章节总数: {stats.get('total_previous', 0)}")
        logger.info(f"  - 故事骨架采样: {stats.get('skeleton_samples', 0)}章")
        logger.info(f"  - 相关历史检索: {stats.get('relevant_history', 0)}章")
        logger.info(f"  - 近期章节概要: {stats.get('recent_summaries', 0)}章")
        logger.info(f"  - 上下文总长度: {len(outlines_context)}字符")

        # 3. 获取角色信息
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {c.name}({'组织' if c.is_organization else '角色'}, {c.role_type}): {c.personality[:100] if c.personality else ''}"
            for c in characters
        ])
        
        # 4. 获取写作风格
        style_content = ""
        if writing_style_id:
            style_result = await db.execute(
                select(WritingStyle).where(WritingStyle.id == int(writing_style_id))
            )
            style = style_result.scalar_one_or_none()
            if style:
                style_content = style.prompt_content or ""
                logger.info(f"使用写作风格: {style.name}")
        
        # 5. 构建记忆增强上下文
        memory_context = await self.memory_service.build_context_for_generation(
            user_id=user_id,
            project_id=project.id,
            current_chapter=chapter_outline.chapter_number,
            chapter_outline=chapter_outline.summary or '',
            character_names=[c.name for c in characters] if characters else None
        )
        logger.info(f"✅ 记忆上下文构建完成: {memory_context.get('stats', {})}")

        # 6. 构建剧情卡片上下文
        linked_cards_context = self._build_plot_cards_context(all_plot_cards, plot_card.id)

        # 7. 构建当前章节大纲内容
        current_outline_content = f"""
【章节标题】{chapter_outline.title}
【章节摘要】{chapter_outline.summary or '无'}
【剧情要点】{chapter_outline.plot_points or '无'}
【目标字数】{plot_card.word_count_target or 500}字（当前场景）
"""

        # 8. 使用智能上下文中的最近完整内容作为前置章节内容
        previous_content = smart_context.get('recent_full', '')

        # 9. 获取本章已生成的场景内容
        # 优先使用前端传入的内容（用户可能已修改），否则从数据库读取
        if previous_generated_content is not None:
            generated_scenes_content = previous_generated_content
            logger.info(f"📝 使用前端传入的已生成内容: {len(generated_scenes_content)} 字符")
        else:
            generated_scenes_content = self._get_generated_scenes_content(all_plot_cards, plot_card.id)
            logger.info(f"📝 从数据库读取已生成内容: {len(generated_scenes_content)} 字符")

        # 拆书参考注入（R5-S4）：把已挂载参考包的 style/methodology/corpus 注入场景生成
        # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
        dissect_user_segment = ""
        try:
            from app.services.reference_pack_injector import ReferencePackInjector
            _injector = ReferencePackInjector()
            _anchor = (
                f"{plot_card.title or ''} "
                f"{(plot_card.content or '')[:300]}"
            ).strip() or chapter_outline.title or "场景生成"
            _ref_block = await _injector.build_reference_block(
                db, project.id,
                scene="scene_generation",
                pack_ids=pack_ids,
                dimensions=dimensions,
                strength=strength,
                anchor_query=_anchor,
            )
            if _ref_block.user_segment:
                dissect_user_segment = _ref_block.user_segment
            if _ref_block.system_segment:
                style_content = (
                    f"{style_content}\n\n{_ref_block.system_segment}".strip()
                    if style_content
                    else _ref_block.system_segment
                )
            if not _ref_block.is_empty:
                logger.info(
                    f"📚 [R5-场景生成] 注入拆书参考包 {len(_ref_block.used_packs)} 个，"
                    f"维度={_ref_block.used_dimensions}，强度={_ref_block.used_strength}"
                )
        except ValueError:
            # 项目未挂载参考包 → 优雅跳过
            pass
        except Exception as _e:  # pragma: no cover - 防御性兜底
            logger.warning(f"[R5-场景生成] 拆书参考注入失败（已跳过）: {_e}")

        # 🆕 V4.1 K2 桥段位置约束（章纲含 bridge_id 时追加到 dissect_user_segment）
        try:
            from app.services.reference_pack import (
                build_v4_bridge_constraint_only,
                fetch_bridge_context,
            )
            if chapter_outline and getattr(chapter_outline, "bridge_id", None):
                _bridge_ctx = await fetch_bridge_context(db, chapter_outline)
                if _bridge_ctx:
                    _v4_bridge_seg = await build_v4_bridge_constraint_only(
                        db, project.id,
                        scene="scene_generation",
                        bridge_position=chapter_outline.bridge_position,
                        bridge_context=_bridge_ctx,
                        chapter_outline_id=chapter_outline.id,
                        target_word_count=plot_card.word_count_target or 500,
                    )
                    if _v4_bridge_seg:
                        dissect_user_segment = (
                            f"{dissect_user_segment}\n\n{_v4_bridge_seg}".strip()
                            if dissect_user_segment
                            else _v4_bridge_seg
                        )
                        logger.info(
                            f"🎯 [V4.1 K2 scene] 注入桥段约束 "
                            f"position={chapter_outline.bridge_position}"
                        )
        except Exception as _be:  # pragma: no cover
            logger.warning(f"[V4.1 K2 scene] 桥段约束注入失败（已跳过）: {_be}")

        # ========== 构建提示词 ==========

        # 去 AI 味规则块（与正文生成同一套：按章轮换的主推条目 + 模型家族先验 + 本项目最近几章诊断的高频信号）
        try:
            project_prior = await load_project_prior(db, project.id)
        except Exception as _pp:  # noqa: BLE001 - 先验缺失不影响生成
            logger.warning(f"[deai scene] 项目级先验加载失败（已跳过）: {_pp}")
            project_prior = ""
        deai_block = build_write_block(
            getattr(self.ai_service, "default_model", None),
            chapter_number=chapter_outline.chapter_number, project_prior=project_prior,
        )

        if previous_content or generated_scenes_content:
            base_prompt = prompt_service.get_chapter_generation_with_context_prompt(
                title=project.title,
                theme=project.theme or '',
                genre=project.genre or '',
                narrative_perspective=project.narrative_perspective or '第三人称',
                time_period=project.world_time_period or '未设定',
                location=project.world_location or '未设定',
                atmosphere=project.world_atmosphere or '未设定',
                rules=final_world_rules,
                characters_info=characters_info or '暂无角色信息',
                outlines_context=outlines_context,
                previous_content=previous_content,
                chapter_number=chapter_outline.chapter_number,
                chapter_title=chapter_outline.title,
                chapter_outline=current_outline_content,
                style_content=style_content,
                target_word_count=plot_card.word_count_target or 500,
                memory_context=memory_context,
                linked_cards_context=linked_cards_context,
                mcp_references=dissect_user_segment,
                deai_block=deai_block,
            )
        else:
            base_prompt = prompt_service.get_chapter_generation_prompt(
                title=project.title,
                theme=project.theme or '',
                genre=project.genre or '',
                narrative_perspective=project.narrative_perspective or '第三人称',
                time_period=project.world_time_period or '未设定',
                location=project.world_location or '未设定',
                atmosphere=project.world_atmosphere or '未设定',
                rules=final_world_rules,
                characters_info=characters_info or '暂无角色信息',
                outlines_context=outlines_context,
                chapter_number=chapter_outline.chapter_number,
                chapter_title=chapter_outline.title,
                chapter_outline=current_outline_content,
                style_content=style_content,
                target_word_count=plot_card.word_count_target or 500,
                memory_context=memory_context,
                linked_cards_context=linked_cards_context,
                mcp_references=dissect_user_segment,
                deai_block=deai_block,
            )

        # 追加当前场景的特定提示词
        scene_prompt = self._build_scene_specific_prompt(
            plot_card=plot_card,
            all_plot_cards=all_plot_cards,
            generated_scenes_content=generated_scenes_content
        )

        prompt = prompt_service.apply_project_generation_prompt(
            base_prompt + "\n\n" + scene_prompt,
            project.generation_prompt or ''
        )
        logger.info(f"📝 提示词构建完成，总长度: {len(prompt)} 字符")

        # 更新卡片状态为生成中
        plot_card.generation_status = "generating"
        await db.commit()

        # 流式生成
        generated_content = ""
        try:
            async for chunk in self.ai_service.generate_text_stream(
                prompt=prompt,
                temperature=0.7
            ):
                generated_content += chunk
                yield chunk

            # 计算字数并更新卡片状态
            word_count = len(generated_content)
            plot_card.mark_completed(generated_content, word_count)
            await db.commit()
            logger.info(f"✅ [场景生成] 完成: card={plot_card_id}, words={word_count}")

        except Exception as e:
            logger.error(f"❌ [场景生成] 失败: {e}")
            plot_card.generation_status = "pending"
            await db.commit()
            raise

    def _build_plot_cards_context(self, all_plot_cards: List[PlotCard], current_card_id: str) -> str:
        """构建剧情卡片上下文"""
        if not all_plot_cards:
            return ""

        cards_text = []
        for i, card in enumerate(all_plot_cards):
            status = "✓已完成" if card.generation_status == "completed" else ("→当前" if card.id == current_card_id else "待生成")
            card_type_label = {'plot': '剧情', 'character': '角色', 'scene': '场景', 'conflict': '冲突'}.get(card.card_type, '其他')
            content_preview = (card.content[:150] + "...") if card.content and len(card.content) > 150 else (card.content or "无内容")
            cards_text.append(f"【{card_type_label}卡片 {i+1}】[{status}] {card.title}\n{content_preview}")

        return "\n\n".join(cards_text)

    def _get_generated_scenes_content(self, all_plot_cards: List[PlotCard], current_card_id: str) -> str:
        """获取本章已生成的场景内容"""
        generated_contents = []
        for card in all_plot_cards:
            if card.id == current_card_id:
                break
            if card.generation_status == "completed" and card.generated_content:
                generated_contents.append(card.generated_content)
        return "\n\n".join(generated_contents)

    def _build_scene_specific_prompt(self, plot_card: PlotCard, all_plot_cards: List[PlotCard], generated_scenes_content: str) -> str:
        """构建当前场景的特定提示词"""
        current_scene_index = 0
        total_scenes = len(all_plot_cards)
        for i, card in enumerate(all_plot_cards):
            if card.id == plot_card.id:
                current_scene_index = i + 1
                break

        prompt = f"""
========== 【当前场景生成任务】 ==========

【场景序号】第 {current_scene_index} 个场景（共 {total_scenes} 个）
【场景标题】{plot_card.title}
【场景内容要点】
{plot_card.content or '无'}
【目标字数】{plot_card.word_count_target or 500}字左右
"""
        if generated_scenes_content:
            preview = generated_scenes_content[-2000:] if len(generated_scenes_content) > 2000 else generated_scenes_content
            prompt += f"\n【本章已生成内容】（请保持连贯，自然衔接）\n{preview}\n"

        prompt += """
【生成要求】
1. 严格按照场景内容要点展开
2. 字数控制在目标字数左右
3. 与前面已生成的内容自然衔接
4. 注意人物性格的一致性
5. 文风按上面「叙事与文风要求」：段落短、对话多、叙述用主角的口气、环境两句带过、书面词换成嘴上的词
6. 直接输出正文内容，不要任何解释或标注
7. 不要重复前面已生成的内容

请开始生成当前场景的正文："""
        return prompt


# 创建服务实例的工厂函数
