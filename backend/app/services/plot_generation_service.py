"""剧情生成服务"""
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.models import Project, StoryOutline, PlotCard, PlotLine
from app.models.character import Character
from app.services.plot_prompts import PlotPromptService
from app.services.ai_service import AIService
from app.services.bridge_slot_planner import VALID_MODES, primary_quota
from app.services.generation_trace import stage_scope
from app.services.sub_line_anchors import normalize_sub_line_anchors
from app.services.world_rule_service import WorldRuleService
from app.services.prompt_service import prompt_service as project_prompt_service
from app.logger import get_logger
from app.utils.plot_line_types import normalize_plot_line_type

logger = get_logger(__name__)


class PlotGenerationService:
    """剧情生成服务类"""

    def __init__(self, ai_service: AIService):
        self.prompt_service = PlotPromptService()
        self.ai_service = ai_service

    def _safe_preview(self, value, limit: int = 200) -> str:
        """安全地预览任意值，避免切片操作导致的类型错误"""
        if value is None:
            return "None"
        elif isinstance(value, str):
            return value[:limit]
        else:
            return str(value)[:limit]

    async def _enhance_world_rules(
        self,
        db: AsyncSession,
        project_id: str,
        base_rules: Optional[str],
        query: Optional[str] = None
    ) -> str:
        """
        增强世界规则：将基础 world_rules 与世界规则明细合并

        Args:
            db: 数据库会话
            project_id: 项目ID
            base_rules: 基础世界规则文本（来自 Project.world_rules）
            query: 可选的查询文本，用于语义检索相关规则

        Returns:
            增强后的世界规则文本
        """
        parts = []

        # 1. 基础世界规则
        if base_rules:
            parts.append(base_rules)

        # 2. 世界规则明细（智能检索或全部）
        if query:
            # 使用语义检索获取最相关的规则
            from app.services.world_rule_service import world_rule_service
            rules_summary = await world_rule_service.generate_rules_summary_with_search(
                db, project_id, query, limit=5
            )
        else:
            # 降级：返回所有规则
            rules_summary = await WorldRuleService.generate_rules_summary_text(db, project_id)

        if rules_summary:
            parts.append(rules_summary)

        return "\n\n".join(parts) if parts else ""

    async def _plan_with_mcp(
        self,
        context_type: str,
        project_data: Dict[str, Any],
        outline_content: Optional[str],
        user_id: str,
        db_session: AsyncSession,
        selected_plugins: Optional[List[str]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        chapter_outline: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        MCP 规划阶段：收集参考资料
        
        Args:
            context_type: 上下文类型 ("plot_card" | "plot_line" | "chapter_outline")
            project_data: 项目数据
            outline_content: 大纲内容
            user_id: 用户ID
            db_session: 数据库会话
            selected_plugins: 选择的插件列表
            provider: AI 提供商
            model: AI 模型
            
        Returns:
            {
                "reference_materials": str,  # 参考资料文本
                "tools_used": List[str],     # 使用的工具列表
                "tool_calls_made": int,      # 工具调用次数
                "planning_time": float       # 规划耗时（秒）
            }
            
        Raises:
            MCPToolNotTriggeredError: 工具未被触发
            MCPPlanningFailedError: 规划阶段失败
        """
        import time
        start_time = time.time()
        
        logger.info(f"🔍 [{context_type}] MCP 规划阶段开始")
        logger.info(f"  - 选择的插件: {selected_plugins or '全部'}")
        
        # 构建资料收集提示词
        planning_prompt = self._build_planning_prompt(
            context_type=context_type,
            project_data=project_data,
            outline_content=outline_content,
            chapter_outline=chapter_outline
        )
        
        try:
            # 调用 MCP 增强的 AI（强制使用工具）
            result = await self.ai_service.generate_text_with_mcp(
                prompt=planning_prompt,
                user_id=user_id,
                db_session=db_session,
                enable_mcp=True,
                selected_plugins=selected_plugins,
                max_tool_rounds=1,  # 从2轮减少到1轮，减少工具调用次数
                tool_choice="required",  # 强制调用工具
                context=f"{context_type}_planning",
                provider=provider,
                model=model
            )
            
            planning_time = time.time() - start_time

            # 验证工具是否被触发
            tool_calls_made = result.get('tool_calls_made', 0)
            if tool_calls_made == 0:
                # 降级处理：工具未触发时不报错，返回空参考资料
                logger.warning(f"⚠️ [{context_type}] MCP 工具未被触发，降级为普通生成")
                logger.info(f"  - 可能原因: 模型不支持 Function Calling 或 AI 判断不需要工具")
                logger.info(f"  - 规划耗时: {planning_time:.2f}s")

                return {
                    "reference_materials": "",
                    "tools_used": [],
                    "tool_calls_made": 0,
                    "planning_time": planning_time
                }

            # 提取参考资料
            reference_materials = result.get('content', '')
            tools_used = result.get('tools_used', [])

            # 记录原始参考资料长度（截断前）
            raw_chars = len(reference_materials) if isinstance(reference_materials, str) else 0

            # 限制参考资料长度（避免 prompt 过长，影响 LLM 响应速度）
            max_length = 2000  # 统一截断长度为 2000 字符
            if isinstance(reference_materials, str) and len(reference_materials) > max_length:
                logger.warning(f"⚠️ [{context_type}] 参考资料过长（{raw_chars}字符），截断至{max_length}字符")
                reference_materials = reference_materials[:max_length] + "\n...(内容过长已截断)"

            # 记录实际使用的参考资料长度（截断后）
            used_chars = len(reference_materials) if isinstance(reference_materials, str) else 0

            # 统一日志：记录参考资料使用情况
            logger.info(
                f"[MCP] context={context_type}_planning user_id={user_id} "
                f"plugins={selected_plugins or []} tools_used={tools_used} "
                f"raw_chars={raw_chars} used_chars={used_chars} "
                f"tool_calls={tool_calls_made} planning_time={planning_time:.2f}s"
            )

            return {
                "reference_materials": reference_materials,
                "tools_used": tools_used,
                "tool_calls_made": tool_calls_made,
                "planning_time": planning_time
            }
            
        except Exception as e:
            planning_time = time.time() - start_time
            error_str = str(e)

            # 检测 MCP 参数错误（-32602: Invalid arguments）
            if "Invalid arguments" in error_str or "-32602" in error_str or "invalid_type" in error_str:
                logger.warning(f"⚠️ [{context_type}] MCP 工具参数错误，降级为普通生成")
                logger.info(f"  - 错误详情: {error_str}")
                logger.info(f"  - 规划耗时: {planning_time:.2f}s")

                # 降级处理：返回空参考资料
                return {
                    "reference_materials": "",
                    "tools_used": [],
                    "tool_calls_made": 0,
                    "planning_time": planning_time
                }

            # 其他错误记录详细日志
            logger.error(f"❌ [{context_type}] MCP 规划失败: {e}")
            logger.error(f"  - 耗时: {planning_time:.2f}s")
            logger.error(f"  - 调试信息: outline_content类型={type(outline_content)}, project_data类型={type(project_data)}")
            logger.error(f"  - outline_content值: {self._safe_preview(outline_content, 100)}")

            # 其他严重错误包装为 MCPPlanningFailedError
            from app.exceptions import MCPPlanningFailedError
            raise MCPPlanningFailedError(f"MCP 规划阶段失败: {str(e)}") from e
    
    def _build_planning_prompt(
        self,
        context_type: str,
        project_data: Dict[str, Any],
        outline_content: Optional[str],
        chapter_outline: Optional[str] = None
    ) -> str:
        """构建 MCP 规划阶段的提示词

        Args:
            context_type: 上下文类型（plot_card/plot_line/chapter_outline/chapter_content）
            project_data: 项目数据
            outline_content: 大纲内容
            chapter_outline: 章纲内容（仅 chapter_content 时使用）
        """

        title = project_data.get('title', '未命名')
        genre = project_data.get('genre', '未知')
        theme = project_data.get('theme', '未知')
        
        if context_type == "plot_card":
            return f"""请使用搜索工具查询以下内容：

题材：{genre}
主题：{theme[:100]}
查询目标：该题材的特色、经典案例、现实参考

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{genre}题材小说特色" 或 "{theme[:50]}主题经典案例"

请立即调用工具。"""
        
        elif context_type == "plot_line":
            return f"""请使用搜索工具查询以下内容：

题材：{genre}
主题：{theme[:100]}
查询目标：该类型小说的故事结构、经典作品参考

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{genre}小说故事结构" 或 "{theme[:50]}主题经典作品"

请立即调用工具。"""
        
        elif context_type == "chapter_outline":
            return f"""请使用搜索工具查询以下内容：

题材：{genre}
主题：{theme[:100]}
查询目标：该类型小说的章节结构、节奏控制技巧

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{genre}小说章节结构" 或 "小说节奏控制技巧"

请立即调用工具。"""

        elif context_type == "chapter_content":
            # 章节正文生成的 MCP 规划
            chapter_text = "暂无"
            if chapter_outline:
                if isinstance(chapter_outline, str):
                    chapter_text = chapter_outline[:300]
                elif isinstance(chapter_outline, dict):
                    chapter_text = str(chapter_outline)[:300]
                else:
                    chapter_text = str(chapter_outline)[:300]

            return f"""为《{title}》({genre})创作章节正文。主题：{theme[:100]}。本章纲要：{chapter_text}

请务必使用 web_search_exa 工具搜索1-2个关键背景资料，重点关注：{genre}题材的写作技巧、场景描写参考、相关专业知识。

工具调用示例：
{{
  "name": "web_search_exa",
  "arguments": {{
    "query": "{genre}小说写作技巧与场景描写"
  }}
}}

重要：必须调用工具获取最新信息，query 参数必须是具体的搜索关键词字符串（非空）。"""

        else:
            return f"""请为小说《{title}》（题材：{genre}，主题：{theme}）搜索相关背景资料。"""
    
    async def generate_plot_cards(
        self,
        db: AsyncSession,
        project_id: str,
        outline_id: str,  # 改为必填
        chapter_outline_id: Optional[str] = None,
        card_type: str = "plot",
        count: int = 3,
        extend_from_card_id: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        enable_mcp: bool = False,
        selected_plugins: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        # R6/R8：拆书参考包注入。三者都 None 时走「项目挂载关系自动注入」。
        pack_ids: Optional[List[str]] = None,
        dimensions: Optional[List[str]] = None,
        strength: Optional[str] = None,
    ) -> List[PlotCard]:
        """生成剧情卡片（必须基于大纲）

        过程追踪（后台任务里绑定了 GenerationTrace 时）：context → [mcp] → reference_pack → llm → persist；
        世界规则检索 / MCP 工具 / 参考包 / LLM 进度由共享入口自动上报。
        """
        
        async with stage_scope("context", "加载项目 / 大纲 / 世界规则") as st:
            # 获取项目信息
            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()
            if not project:
                raise ValueError("项目不存在")

            # 获取大纲内容（必填）
            outline_result = await db.execute(select(StoryOutline).where(StoryOutline.id == outline_id))
            outline = outline_result.scalar_one_or_none()
            if not outline:
                raise ValueError(f"故事大纲不存在: {outline_id}")

            # 验证大纲属于该项目
            if outline.project_id != project_id:
                raise ValueError("大纲不属于该项目")

            outline_content = outline.content
            if not outline_content:
                raise ValueError("大纲内容为空，无法生成剧情卡片")

            # 构建查询文本（用于智能检索世界规则）
            query_text = f"{project.theme or ''} {project.genre or ''} {outline_content[:500]}"

            # 增强世界规则（使用语义检索）
            enhanced_world_rules = await self._enhance_world_rules(
                db, project_id, project.world_rules, query=query_text
            )

            project_data = {
                "title": project.title,
                "genre": project.genre,
                "theme": project.theme,
                "target_words": project.target_words,
                "narrative_perspective": project.narrative_perspective,
                "world_time_period": project.world_time_period,
                "world_location": project.world_location,
                "world_atmosphere": project.world_atmosphere,
                "world_rules": enhanced_world_rules,
                "generation_prompt": project.generation_prompt
            }
            
            # 获取章纲内容（优先级高于大纲）
            if chapter_outline_id:
                from app.models.chapter_outline import ChapterOutline
                chapter_outline_result = await db.execute(select(ChapterOutline).where(ChapterOutline.id == chapter_outline_id))
                chapter_outline = chapter_outline_result.scalar_one_or_none()
                if chapter_outline:
                    # 使用章纲内容，如果有大纲内容则合并
                    chapter_content = f"第{chapter_outline.chapter_number}章：{chapter_outline.title}\n{chapter_outline.summary or ''}"
                    if outline_content:
                        outline_content = f"{outline_content}\n\n【章纲详情】\n{chapter_content}"
                    else:
                        outline_content = chapter_content
            
            # 获取延伸基础内容
            extend_from = None
            if extend_from_card_id:
                card_result = await db.execute(select(PlotCard).where(PlotCard.id == extend_from_card_id))
                base_card = card_result.scalar_one_or_none()
                if base_card:
                    extend_from = f"{base_card.title}: {base_card.content}"
            st.note(outline_chars=len(outline_content), world_rules_chars=len(enhanced_world_rules or ""))
        
        # 生成 Prompt
        prompt = self.prompt_service.generate_plot_card_prompt(
            project_data=project_data,
            outline_content=outline_content,
            card_type=card_type,
            extend_from=extend_from,
            custom_prompt=custom_prompt
        )
        
        logger.info(f"生成剧情卡片 Prompt: {self._safe_preview(prompt)}...")
        
        try:
            import time
            total_start_time = time.time()
            
            # 调用 AI 生成（两段式：先工具、后生成）
            logger.info(f"📋 [剧情卡片生成] 参数检查:")
            logger.info(f"  - enable_mcp: {enable_mcp}")
            logger.info(f"  - user_id: {user_id}")
            logger.info(f"  - selected_plugins: {selected_plugins}")
            logger.info(f"  - provider: {provider}")
            logger.info(f"  - model: {model}")
            
            # 参数验证
            if enable_mcp and not user_id:
                logger.warning(f"⚠️ [剧情卡片生成] enable_mcp=True 但 user_id 为空，降级为基础模式")
                enable_mcp = False
            
            # 最终使用的 prompt
            final_prompt = prompt
            
            if enable_mcp and user_id:
                logger.info(f"🚀 [剧情卡片生成] 使用 MCP 两段式增强模式")
                
                # ========== 阶段 1: MCP 规划（资料收集）==========
                async with stage_scope("mcp", "MCP 规划收集资料") as st:
                    planning_result = await self._plan_with_mcp(
                        context_type="plot_card",
                        project_data=project_data,
                        outline_content=outline_content,
                        user_id=user_id,
                        db_session=db,
                        selected_plugins=selected_plugins,
                        provider=provider,
                        model=model
                    )
                    
                    # 拼接参考资料到 prompt
                    reference_materials = planning_result['reference_materials']
                    final_prompt = f"""{prompt}

【参考资料】
以下是通过 MCP 工具收集的真实背景资料，请参考这些信息生成更真实的剧情卡片：

{reference_materials}

请结合上述资料，生成符合要求的剧情卡片。"""
                    st.note(tools=len(planning_result.get("tools_used") or []), chars=len(reference_materials))

                logger.info(f"📚 [剧情卡片生成] MCP 参考资料已拼接到 prompt")

            # ========== R6：拆书参考包注入（无论是否启用 MCP 都尝试）==========
            # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
            async with stage_scope("reference_pack", "组装拆书参考包") as st:
                try:
                    from app.services.reference_pack_injector import ReferencePackInjector
                    _injector = ReferencePackInjector()
                    _anchor = (
                        f"{project.theme or ''} {project.genre or ''} "
                        f"{(extend_from or '')[:200]} {outline_content[:300]}"
                    ).strip() or "剧情卡片"
                    _ref_block = await _injector.build_reference_block(
                        db, project_id,
                        scene="plot_card",
                        pack_ids=pack_ids,
                        dimensions=dimensions,
                        strength=strength,
                        fallback_dimensions=("synopsis", "structure", "methodology"),
                        anchor_query=_anchor,
                    )
                    if _ref_block.user_segment:
                        final_prompt = f"{final_prompt}\n\n{_ref_block.user_segment}"
                        logger.info(
                            "[R6-剧情卡片] 已注入参考包：dims=%s strength=%s 字符=%d",
                            _ref_block.used_dimensions,
                            _ref_block.used_strength,
                            len(_ref_block.user_segment),
                        )
                        st.note(dimensions="、".join(_ref_block.used_dimensions), strength=_ref_block.used_strength)
                    else:
                        st.skip("参考包无可用内容")
                except ValueError:
                    logger.info("[R6-剧情卡片] 项目未挂载参考包或无可用维度，跳过注入")
                    st.skip("项目未挂载参考包或无可用维度")
                except Exception as _e:  # pragma: no cover - 防御性兜底
                    logger.warning("[R6-剧情卡片] 拆书参考注入失败（已跳过）：%s", _e)
                    st.skip("注入失败，已跳过")

            # ========== 阶段 2: 内容生成 ==========
            final_prompt = project_prompt_service.apply_project_generation_prompt(
                final_prompt,
                project.generation_prompt or ''
            )
            logger.info(f"📝 [剧情卡片生成] 内容生成阶段开始")
            logger.info(f"  - Prompt 长度: {len(final_prompt)} 字符")
            
            generation_start_time = time.time()
            
            async with stage_scope("llm", "模型生成剧情卡") as st:
                # 流式累积调 LLM（免疫中转代理 30s 网关 timeout，与桥段规划路径一致）
                response = await self.ai_service.generate_text_stream_collect(
                    prompt=final_prompt,
                    provider=provider,
                    model=model,
                    temperature=0.8,
                    context=f"PlotCardGen-{model or 'default'}"
                )
                ai_content = response if isinstance(response, str) else response.get("content", "")
                st.note(content_chars=len(ai_content))
            
            generation_time = time.time() - generation_start_time
            total_time = time.time() - total_start_time
            
            logger.info(f"✅ [剧情卡片生成] 内容生成完成")
            logger.info(f"  - 生成耗时: {generation_time:.2f}s")
            logger.info(f"  - 总耗时: {total_time:.2f}s")
            
            async with stage_scope("persist", "写入卡片 / 关联章纲") as st:
                # 解析 AI 响应
                cards_data = self._parse_ai_response(ai_content, "plot_cards")
                
                # 创建卡片对象
                created_cards = []
                for i, card_data in enumerate(cards_data[:count]):
                    # 获取当前最大排序序号
                    max_order_result = await db.execute(
                        select(PlotCard.order_index).where(PlotCard.project_id == project_id)
                        .order_by(PlotCard.order_index.desc()).limit(1)
                    )
                    max_order = max_order_result.scalar() or 0
                    
                    # 处理标签
                    tags_json = None
                    if card_data.get("tags"):
                        tags_json = json.dumps(card_data["tags"], ensure_ascii=False)
                    
                    card = PlotCard(
                        project_id=project_id,
                        title=card_data.get("title", f"剧情卡片 {i+1}"),
                        content=card_data.get("content", ""),
                        card_type=card_data.get("card_type", card_type),
                        order_index=max_order + i + 1,
                        tags=tags_json
                    )
                    
                    db.add(card)
                    created_cards.append(card)
                
                await db.commit()

                # 刷新对象以获取生成的 ID
                for card in created_cards:
                    await db.refresh(card)

                # 如果指定了章纲，自动创建关联
                if chapter_outline_id:
                    from app.models import PlotCardChapterOutlineLink
                    import uuid

                    for card in created_cards:
                        # 检查是否已存在关联（防止重复）
                        existing_link_result = await db.execute(
                            select(PlotCardChapterOutlineLink).where(
                                PlotCardChapterOutlineLink.plot_card_id == card.id,
                                PlotCardChapterOutlineLink.chapter_outline_id == chapter_outline_id
                            )
                        )
                        existing_link = existing_link_result.scalar_one_or_none()

                        if not existing_link:
                            # 创建新关联
                            link = PlotCardChapterOutlineLink(
                                id=str(uuid.uuid4()),
                                plot_card_id=card.id,
                                chapter_outline_id=chapter_outline_id,
                                usage_type="reference"  # 默认为参考类型
                            )
                            db.add(link)
                            logger.info(f"  - 自动关联剧情卡片 {card.title} 到章纲 {chapter_outline_id}")

                    await db.commit()
                st.note(cards=len(created_cards))

            logger.info(f"成功生成 {len(created_cards)} 个剧情卡片")
            return created_cards
            
        except Exception as e:
            logger.error(f"生成剧情卡片失败: {str(e)}")
            await db.rollback()
            raise
    
    async def _prepare_plot_line_context(
        self,
        db: AsyncSession,
        project_id: str,
        based_on_lines: Optional[List[str]] = None
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """准备剧情线上下文信息
        
        Returns:
            tuple: (historical_context, previous_line_summary)
        """
        historical_context = ""
        previous_line_summary = None
        
        # 如果用户指定了参考剧情线
        if based_on_lines:
            # 查询指定的剧情线，按order_index排序
            lines_result = await db.execute(
                select(PlotLine).where(
                    PlotLine.id.in_(based_on_lines),
                    PlotLine.project_id == project_id
                ).order_by(PlotLine.order_index.asc())
            )
            reference_lines = lines_result.scalars().all()
            
            if reference_lines:
                # 构建历史背景摘要
                historical_parts = []
                for line in reference_lines:
                    summary = f"【{line.title}】{line.description or '暂无描述'}"
                    historical_parts.append(summary)
                
                historical_context = "\n".join(historical_parts)
                
                # 最后一条作为直接参考的上一剧情线
                last_line = reference_lines[-1]
                previous_line_summary = {
                    "title": last_line.title,
                    "description": last_line.description or "",
                    "timeline_data": last_line.timeline_data
                }
        else:
            # 如果未指定，自动查找项目中最新的剧情线
            latest_line_result = await db.execute(
                select(PlotLine).where(PlotLine.project_id == project_id)
                .order_by(PlotLine.order_index.desc()).limit(1)
            )
            latest_line = latest_line_result.scalar_one_or_none()
            
            if latest_line:
                historical_context = f"【{latest_line.title}】{latest_line.description or '暂无描述'}"
                previous_line_summary = {
                    "title": latest_line.title,
                    "description": latest_line.description or "",
                    "timeline_data": latest_line.timeline_data
                }
        
        return historical_context, previous_line_summary

    async def _load_main_timeline(self, db: AsyncSession, project_id: str) -> Optional[Dict[str, Any]]:
        """主线时间轴（供支线 prompt）：节点 index/标题/权重/描述 + 槽位规划器算出的章区间 + 最大高潮节点。

        无主线或主线无节点 → None（调用方回退到旧 prompt）。章区间算不出（主线缺 estimated_chapters）→ None 字段。
        """
        from app.services.bridge_slot_planner import (
            BridgePlanningPreconditionError,
            compute_bridge_slots,
            parse_plot_line,
        )
        result = await db.execute(
            select(PlotLine).where(PlotLine.project_id == project_id, PlotLine.line_type == "main")
            .order_by(PlotLine.order_index)
        )
        main = next((m for m in (parse_plot_line(l) for l in result.scalars().all()) if m.beats), None)
        if main is None:
            return None
        ranges: Dict[int, tuple] = {}
        total_bridges: Optional[int] = None
        try:
            plan = compute_bridge_slots([main])
            total_bridges = plan.total_bridges
            for s in plan.slots:
                lo, hi = ranges.get(s.beat_index, (s.chapter_start, s.chapter_end))
                ranges[s.beat_index] = (min(lo, s.chapter_start), max(hi, s.chapter_end))
        except BridgePlanningPreconditionError:
            pass
        return {
            "id": main.id,
            "title": main.title,
            "estimated_chapters": main.estimated_chapters,
            "total_bridges": total_bridges,
            "climax_beat": max(main.beats, key=lambda b: b.weight).index,
            "beats": [
                {
                    "index": b.index, "title": b.title, "weight": b.weight, "description": b.description,
                    "chapter_start": ranges.get(b.index, (None, None))[0],
                    "chapter_end": ranges.get(b.index, (None, None))[1],
                }
                for b in main.beats
            ],
        }

    async def _calculate_beats_coverage(
        self,
        db: AsyncSession,
        plot_line_id: str,
        beats: list
    ) -> dict:
        """
        计算剧情线各节点的覆盖进度

        Args:
            db: 数据库会话
            plot_line_id: 剧情线ID
            beats: 节点列表

        Returns:
            包含覆盖信息的字典：
            {
                "beats": [{"index": 1, "title": "...", "description": "...", "coverage": 0.8}, ...],
                "total_progress": 0.45
            }
        """
        from app.models import ChapterOutlinePlotLineLink

        # 初始化每个节点的覆盖度为 0
        beats_coverage = []
        for beat in beats:
            beats_coverage.append({
                "index": beat.get("index"),
                "key": beat.get("key"),
                "title": beat.get("title"),
                "description": beat.get("description", ""),
                "weight": beat.get("weight", 0),
                "coverage": 0.0
            })

        # 查询该剧情线的所有章节关联
        links_result = await db.execute(
            select(ChapterOutlinePlotLineLink).where(
                ChapterOutlinePlotLineLink.plot_line_id == plot_line_id
            )
        )
        links = links_result.scalars().all()

        # 汇总每个节点的覆盖度
        for link in links:
            if link.timeline_coverage:
                try:
                    coverage_data = json.loads(link.timeline_coverage)
                    beats_covered = coverage_data.get("beats_covered", [])

                    for beat_cov in beats_covered:
                        beat_index = beat_cov.get("beat_index")
                        coverage = beat_cov.get("coverage", 0)

                        # 找到对应的节点并累加覆盖度（上限 1.0）
                        for bc in beats_coverage:
                            if bc["index"] == beat_index:
                                bc["coverage"] = min(bc["coverage"] + coverage, 1.0)
                                break
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"解析 timeline_coverage 失败: {str(e)}")

        # 计算总进度（加权平均）
        total_progress = sum(bc["coverage"] * bc["weight"] for bc in beats_coverage)

        return {
            "beats": beats_coverage,
            "total_progress": total_progress
        }

    async def _generate_beats_for_lines_with_ai(
        self,
        project_data: Dict[str, Any],
        lines: List[Dict[str, Any]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dissect_ref_block: str = "",
        main_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, List[Dict[str, Any]]]:
        """
        逐条生成剧情线的节点（beats）- 避免API超时

        Args:
            project_data: 项目基础信息
            lines: 剧情线列表，每项包含 index, title, description, line_type
            provider: AI 提供商
            model: AI 模型
            dissect_ref_block: R6 拆书参考包 user_segment（由调用方一次性算好后透传，
                避免每条 beat 重复查库）。空串=不注入。
            main_ctx: 主线时间轴（_load_main_timeline）；非空且该线带锚点区间时走支线节点 prompt，
                节点校验失败会就地清掉该线的 mode / anchor 字段（退化为均匀铺满）。

        Returns:
            index -> beats 的映射字典
        """
        if not lines:
            return {}

        logger.info(f"🔹 [阶段 2] 开始逐条生成节点，剧情线数量: {len(lines)}")

        index_to_beats = {}
        import time
        import re

        for line in lines:
            line_index = line.get("index", 0)
            line_title = line.get("title", "未命名")
            
            logger.info(f"  📝 生成剧情线 {line_index} 的节点: {line_title}")

            try:
                # 构建单条剧情线的 Prompt（支线锚定：有主线时间轴且本线带锚点区间 → 支线节点 prompt）
                anchored_request = (
                    main_ctx is not None
                    and line.get("mode") in VALID_MODES
                    and line.get("anchor_start_beat") is not None
                )
                if anchored_request:
                    quota = primary_quota(
                        line.get("estimated_chapters"),
                        main_ctx.get("total_bridges") or len(main_ctx["beats"]) * 4,
                    )
                    prompt = self.prompt_service.generate_sub_line_beats_prompt(
                        project_data=project_data, line=line, main_ctx=main_ctx, quota=quota,
                    )
                else:
                    prompt = self.prompt_service.generate_single_line_beats_prompt(
                        project_data=project_data,
                        line=line
                    )

                # R6：拼拆书参考包 user_segment（节点生成主要受益于 structure / synopsis 维度）
                if dissect_ref_block:
                    prompt = f"{prompt}\n\n{dissect_ref_block}"

                prompt = project_prompt_service.apply_project_generation_prompt(
                    prompt,
                    project_data.get("generation_prompt") or ''
                )

                start_time = time.time()

                # 流式累积调 LLM（免疫中转代理 timeout）
                response = await self.ai_service.generate_text_stream_collect(
                    prompt=prompt,
                    provider=provider,
                    model=model,
                    temperature=0.7,
                    context=f"PlotLineBeats-{model or 'default'}"
                )

                generation_time = time.time() - start_time
                logger.info(f"    - 耗时: {generation_time:.2f}s")

                # 解析响应
                ai_content = response if isinstance(response, str) else response.get("content", "")

                # 提取 JSON 数组
                json_match = re.search(r'```json\s*(\[.*?\])\s*```', ai_content, re.DOTALL)
                if not json_match:
                    json_match = re.search(r'(\[.*?\])', ai_content, re.DOTALL)

                if not json_match:
                    logger.warning(f"    ⚠️ 无法提取JSON，跳过")
                    continue

                beats_data = json.loads(json_match.group(1))

                if not isinstance(beats_data, list):
                    logger.warning(f"    ⚠️ 返回格式错误，跳过")
                    continue

                # 校验并归一化 beats 结构
                normalized_beats = self._validate_and_normalize_beats(
                    beats_data, line_index=line_index
                )
                if normalized_beats and anchored_request:
                    ok = normalize_sub_line_anchors(
                        normalized_beats,
                        mode=line.get("mode"),
                        anchor_start_beat=line.get("anchor_start_beat"),
                        anchor_end_beat=line.get("anchor_end_beat"),
                        main_beat_indices=[int(r["index"]) for r in main_ctx["beats"]],
                    )
                    if not ok:
                        logger.warning(f"    ⚠️ 支线锚点校验失败，剥掉锚点退化为均匀铺满: {line_title}")
                        line["mode"] = None
                        line["anchor_start_beat"] = None
                        line["anchor_end_beat"] = None
                if normalized_beats:
                    index_to_beats[line_index] = normalized_beats
                    logger.info(f"    ✅ 成功生成 {len(normalized_beats)} 个节点")
                else:
                    logger.warning(f"    ⚠️ 节点校验失败，跳过")

            except json.JSONDecodeError as e:
                logger.error(f"    ❌ JSON解析失败: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"    ❌ 生成失败: {str(e)}")
                continue

        logger.info(f"✅ [阶段 2] 节点生成完成，成功 {len(index_to_beats)}/{len(lines)} 条")
        return index_to_beats

    def _validate_and_normalize_beats(
        self, beats: List[Dict[str, Any]], line_index: int = 0
    ) -> Optional[List[Dict[str, Any]]]:
        """
        校验并归一化 beats 结构

        Args:
            beats: 节点列表
            line_index: 剧情线索引（用于日志）

        Returns:
            归一化后的 beats 列表，校验失败返回 None
        """
        # 检查基本结构
        if not beats or len(beats) < 3 or len(beats) > 15:
            logger.warning(f"⚠️ [阶段 2] 剧情线 {line_index} 节点校验失败: 数量异常 ({len(beats) if beats else 0})")
            return None

        total_weight = 0.0
        required_fields = ["index", "key", "title", "description", "weight"]

        for i, beat in enumerate(beats):
            # 检查必需字段
            missing_fields = [key for key in required_fields if key not in beat]
            if missing_fields:
                logger.warning(f"⚠️ [阶段 2] 剧情线 {line_index} 节点 {i+1} 缺少字段: {missing_fields}")
                return None

            # 检查权重类型，尝试转换
            weight = beat.get("weight", 0)
            if isinstance(weight, str):
                try:
                    weight = float(weight)
                    beat["weight"] = weight
                except ValueError:
                    return None

            if not isinstance(weight, (int, float)):
                return None

            # 权重为 0 或负数时，设置默认值
            if weight <= 0:
                beat["weight"] = 1.0 / len(beats)
                weight = beat["weight"]

            total_weight += weight

        # 归一化权重（自动修正总权重偏离）
        if total_weight > 0 and (total_weight < 0.8 or total_weight > 1.2):
            for beat in beats:
                beat["weight"] = beat["weight"] / total_weight

        return beats



    async def generate_plot_lines(
        self,
        db: AsyncSession,
        project_id: str,
        outline_id: Optional[str] = None,
        line_type: str = "main",
        based_on_cards: Optional[List[str]] = None,
        based_on_lines: Optional[List[str]] = None,
        custom_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        count: int = 3,
        enable_mcp: bool = False,
        selected_plugins: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        # R6/R8：拆书参考包注入。三者都 None 时走「项目挂载关系自动注入」。
        pack_ids: Optional[List[str]] = None,
        dimensions: Optional[List[str]] = None,
        strength: Optional[str] = None,
        # 支线篇幅预算上限（章）：向导按全书 40% 均分下发；None = 不夹紧
        sub_budget_cap: Optional[int] = None,
    ) -> List[PlotLine]:
        """生成剧情线

        过程追踪（后台任务里绑定了 GenerationTrace 时）：context → reference_pack → line-{i}（每条结构，含 MCP 规划）
        → beats → persist；世界规则检索 / MCP 工具 / 参考包 / LLM 进度由共享入口自动上报。
        """
        
        # 获取项目信息
        line_type = normalize_plot_line_type(line_type)

        async with stage_scope("context", "加载项目 / 大纲 / 世界规则 / 角色") as st:
            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()
            if not project:
                raise ValueError("项目不存在")

            # 获取大纲内容（用于语义检索）
            outline_content = None
            if outline_id:
                outline_result = await db.execute(select(StoryOutline).where(StoryOutline.id == outline_id))
                outline = outline_result.scalar_one_or_none()
                if outline:
                    outline_content = outline.content

            # 构建查询文本（用于智能检索世界规则）
            query_parts = [project.theme or "", project.genre or ""]
            if outline_content:
                query_parts.append(outline_content[:500])  # 限制长度
            query_text = " ".join(query_parts)

            # 增强世界规则（使用语义检索）
            enhanced_world_rules = await self._enhance_world_rules(
                db, project_id, project.world_rules, query=query_text
            )

            project_data = {
                "title": project.title,
                "genre": project.genre,
                "theme": project.theme,
                "target_words": project.target_words,
                "narrative_perspective": project.narrative_perspective,
                "world_time_period": project.world_time_period,
                "world_location": project.world_location,
                "world_atmosphere": project.world_atmosphere,
                "world_rules": enhanced_world_rules,
                "generation_prompt": project.generation_prompt
            }
        
            # 获取角色信息（限制数量以控制 token）
            characters_result = await db.execute(
                select(Character).where(
                    Character.project_id == project_id,
                    Character.is_organization == False
                ).limit(10)
            )
            characters = characters_result.scalars().all()
            project_data["characters"] = [
                {
                    "name": char.name,
                    "role_type": char.role_type,
                    "personality": char.personality,
                    "background": char.background
                } for char in characters if char.name
            ]
        
            # 获取组织信息
            organizations_result = await db.execute(
                select(Character).where(
                    Character.project_id == project_id,
                    Character.is_organization == True
                ).limit(5)
            )
            organizations = organizations_result.scalars().all()
            project_data["organizations"] = [
                {
                    "name": org.name,
                    "organization_type": org.organization_type,
                    "organization_purpose": org.organization_purpose,
                    "personality": org.personality
                } for org in organizations if org.name
            ]

            # 获取相关剧情卡片
            plot_cards = None
            if based_on_cards:
                cards_result = await db.execute(
                    select(PlotCard).where(PlotCard.id.in_(based_on_cards))
                )
                cards = cards_result.scalars().all()
                plot_cards = [{"title": card.title, "content": card.content} for card in cards]
        
            # 准备剧情线上下文（历史背景和上一条剧情线）
            historical_context, previous_line_summary = await self._prepare_plot_line_context(
                db, project_id, based_on_lines
            )

            # 支线锚定：项目已有带节点的主线时 → 支线在主线时间轴上生成（不再"承接"主线）
            main_ctx: Optional[Dict[str, Any]] = None
            existing_subs: List[Dict[str, Any]] = []
            if line_type != "main":
                main_ctx = await self._load_main_timeline(db, project_id)
                if main_ctx is not None:
                    from app.services.bridge_slot_planner import parse_plot_line
                    subs_result = await db.execute(
                        select(PlotLine).where(PlotLine.project_id == project_id, PlotLine.line_type != "main")
                        .order_by(PlotLine.order_index)
                    )
                    for s in subs_result.scalars().all():
                        sd = parse_plot_line(s)
                        existing_subs.append({
                            "title": sd.title, "description": s.description or "", "mode": sd.mode,
                            "anchor_start_beat": sd.anchor_start_beat, "anchor_end_beat": sd.anchor_end_beat,
                        })
            st.note(characters=len(project_data["characters"]), organizations=len(project_data["organizations"]),
                    outline_chars=len(outline_content or ""), anchored_to_main=main_ctx is not None)
        
        logger.info(f"📋 [剧情线生成] 开始两阶段生成流程")
        logger.info(f"  - 项目ID: {project_id}")
        logger.info(f"  - 生成数量: {count}")
        logger.info(f"  - 历史背景: {'有' if historical_context else '无'}")
        logger.info(f"  - 上一剧情线: {'有' if previous_line_summary else '无'}")

        try:
            import time
            total_start_time = time.time()

            # 参数验证
            if enable_mcp and not user_id:
                logger.warning(f"⚠️ [剧情线生成] enable_mcp=True 但 user_id 为空，降级为基础模式")
                enable_mcp = False

            # ========== R6：拆书参考包注入 ==========
            # 项目挂了 pack 自动用，无需用户每次去 selector 选；用户显式传 R8 字段则覆盖。
            # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
            dissect_ref_block = ""
            async with stage_scope("reference_pack", "组装拆书参考包") as st:
                try:
                    from app.services.reference_pack_injector import ReferencePackInjector
                    _injector = ReferencePackInjector()
                    _anchor = (
                        f"{project.theme or ''} {project.genre or ''} "
                        f"{(outline_content or '')[:300]}"
                    ).strip() or "剧情线生成"
                    _ref_block = await _injector.build_reference_block(
                        db, project_id,
                        scene="plot_line",
                        pack_ids=pack_ids,
                        dimensions=dimensions,
                        strength=strength,
                        # 剧情线生成关注故事骨架/结构/方法论；corpus/style 主要给章节正文用，可由 default_dimensions 决定是否启用
                        fallback_dimensions=("synopsis", "structure", "methodology"),
                        anchor_query=_anchor,
                    )
                    if _ref_block.user_segment:
                        dissect_ref_block = _ref_block.user_segment
                        logger.info(
                            "[R6-剧情线] 已注入参考包：dims=%s strength=%s 字符=%d",
                            _ref_block.used_dimensions,
                            _ref_block.used_strength,
                            len(dissect_ref_block),
                        )
                        st.note(dimensions="、".join(_ref_block.used_dimensions), strength=_ref_block.used_strength)
                    else:
                        st.skip("参考包无可用内容")
                except ValueError:
                    # 项目未挂载参考包等情况，优雅降级
                    logger.info("[R6-剧情线] 项目未挂载参考包或无可用维度，跳过注入")
                    st.skip("项目未挂载参考包或无可用维度")
                except Exception as _e:  # pragma: no cover - 防御性兜底
                    logger.warning("[R6-剧情线] 拆书参考注入失败（已跳过）：%s", _e)
                    st.skip("注入失败，已跳过")

            # ========== 阶段 1：生成剧情线基本信息（title + description） ==========
            logger.info(f"🔹 [阶段 1] 开始生成剧情线基本信息")

            generated_lines_data = []  # 存储阶段 1 的结果
            current_previous_line = previous_line_summary  # 当前参考的上一条剧情线

            for i in range(count):
                async with stage_scope(f"line-{i+1}", f"第 {i+1}/{count} 条剧情线结构") as st:
                    logger.info(f"📝 [阶段 1] 生成第 {i+1}/{count} 条结构")

                    # 生成当前条的 Prompt（只要求结构）；支线锚定路径用主线时间轴代替"承接上一条"
                    if main_ctx is not None:
                        current_prompt = self.prompt_service.generate_sub_line_prompt(
                            project_data=project_data,
                            outline_content=outline_content,
                            main_ctx=main_ctx,
                            existing_subs=existing_subs,
                            line_type=line_type,
                            custom_prompt=custom_prompt,
                            sequence_index=i + 1,
                            total=count,
                            budget_cap=sub_budget_cap,
                        )
                    else:
                        current_prompt = self.prompt_service.generate_plot_line_prompt(
                            project_data=project_data,
                            outline_content=outline_content,
                            plot_cards=plot_cards,
                            line_type=line_type,
                            custom_prompt=custom_prompt,
                            count=1,  # 每次只生成一条
                            historical_context=historical_context,
                            previous_line_summary=current_previous_line,
                            sequence_index=i + 1
                        )

                    # MCP 增强处理
                    final_prompt = current_prompt
                    if enable_mcp and user_id:
                        logger.info(f"🚀 [阶段 1] 第 {i+1} 条使用 MCP 增强")

                        planning_result = await self._plan_with_mcp(
                            context_type="plot_line",
                            project_data=project_data,
                            outline_content=outline_content,
                            user_id=user_id,
                            db_session=db,
                            selected_plugins=selected_plugins,
                            provider=provider,
                            model=model
                        )

                        reference_materials = planning_result['reference_materials']
                        final_prompt = f"""{current_prompt}

    【参考资料】
    以下是通过 MCP 工具收集的真实背景资料，请参考这些信息生成更合理的剧情线：

    {reference_materials}

    请结合上述资料，生成符合要求的剧情线。"""

                    # R6：拼拆书参考包 user_segment（每条剧情线复用同一份 block，避免重复 IO）
                    if dissect_ref_block:
                        final_prompt = f"{final_prompt}\n\n{dissect_ref_block}"

                    final_prompt = project_prompt_service.apply_project_generation_prompt(
                        final_prompt,
                        project.generation_prompt or ''
                    )

                    # 调用 AI 生成单条剧情线结构（流式累积）
                    generation_start_time = time.time()

                    response = await self.ai_service.generate_text_stream_collect(
                        prompt=final_prompt,
                        provider=provider,
                        model=model,
                        temperature=0.7,
                        context=f"PlotLineStruct-{model or 'default'}"
                    )

                    generation_time = time.time() - generation_start_time
                    logger.info(f"  - 第 {i+1} 条结构生成耗时: {generation_time:.2f}s")

                    # 解析 AI 响应
                    ai_content = response if isinstance(response, str) else response.get("content", "")
                    lines_data = self._parse_ai_response(ai_content, "plot_lines")

                    if not lines_data:
                        logger.warning(f"⚠️ [阶段 1] 第 {i+1} 条剧情线结构生成失败，跳过")
                        st.skip("结构解析为空")
                        continue

                    # 取第一条结果
                    line_data = lines_data[0]

                    # 提取并规范化预计章节数（严格模式：必须是 >=1 的整数）
                    raw_estimated = line_data.get("estimated_chapters")
                    normalized_estimated: Optional[int] = None
                    if isinstance(raw_estimated, int):
                        normalized_estimated = raw_estimated
                    elif isinstance(raw_estimated, str):
                        import re
                        match = re.search(r"\d+", raw_estimated)
                        if match:
                            normalized_estimated = int(match.group(0))

                    if normalized_estimated is None or normalized_estimated < 1:
                        logger.error(
                            "❌ [阶段 1] 第 %s 条剧情线的 estimated_chapters 非法或缺失: %r",
                            i + 1,
                            raw_estimated,
                        )
                        raise ValueError(
                            "AI 返回格式不完整: 缺少合法的 estimated_chapters 字段(必须是>=1的整数), "
                            "请重试或调整提示词，让 AI 明确给出本剧情线的预计章节数。"
                        )

                    # 支线篇幅预算夹紧（只在锚定路径下生效；主线不受影响）
                    if main_ctx is not None and sub_budget_cap:
                        normalized_estimated = min(normalized_estimated, sub_budget_cap)

                    # 保存到阶段 1 结果列表
                    generated_lines_data.append({
                        "index": i + 1,
                        "title": line_data.get("title", f"剧情线 {i+1}"),
                        "description": line_data.get("description", ""),
                        "line_type": normalize_plot_line_type(
                            line_data.get("line_type", line_type),
                            default=line_type
                        ),
                        "plot_cards": line_data.get("plot_cards", []),
                        "estimated_chapters": normalized_estimated,
                        "mode": line_data.get("mode") if main_ctx is not None else None,
                        "anchor_start_beat": line_data.get("anchor_start_beat") if main_ctx is not None else None,
                        "anchor_end_beat": line_data.get("anchor_end_beat") if main_ctx is not None else None,
                    })

                    logger.info(f"  - 第 {i+1} 条结构已生成: {line_data.get('title')}")

                    # 锚定路径：本条进入"已有支线"，后续支线避免重复
                    if main_ctx is not None:
                        existing_subs.append({
                            "title": line_data.get("title", ""), "description": line_data.get("description", ""),
                            "mode": line_data.get("mode"), "anchor_start_beat": line_data.get("anchor_start_beat"),
                            "anchor_end_beat": line_data.get("anchor_end_beat"),
                        })

                    # 更新下一条的参考剧情线（用于承接）
                    current_previous_line = {
                        "title": line_data.get("title", ""),
                        "description": line_data.get("description", "")
                    }
                    st.note(title=line_data.get("title", ""), estimated_chapters=normalized_estimated)

            stage1_time = time.time() - total_start_time
            logger.info(f"✅ [阶段 1] 完成，共生成 {len(generated_lines_data)} 条剧情线结构")
            logger.info(f"  - 阶段 1 耗时: {stage1_time:.2f}s")

            # 如果阶段 1 没有生成任何剧情线，直接返回
            if not generated_lines_data:
                logger.warning(f"⚠️ [剧情线生成] 阶段 1 未生成任何剧情线，终止流程")
                return []

            # ========== 阶段 2：批量生成节点（beats） ==========
            logger.info(f"🔹 [阶段 2] 开始批量节点规划")
            stage2_start_time = time.time()

            # 调用批量 beats 生成（R6：透传同一份拆书参考块，避免阶段 2 重复查库）
            async with stage_scope("beats", "批量规划节点") as st:
                index_to_beats = await self._generate_beats_for_lines_with_ai(
                    project_data=project_data,
                    lines=generated_lines_data,
                    provider=provider,
                    model=model,
                    dissect_ref_block=dissect_ref_block,
                    main_ctx=main_ctx,
                )
                st.note(ai_lines=len(index_to_beats), fallback=len(generated_lines_data) - len(index_to_beats))

            stage2_time = time.time() - stage2_start_time
            logger.info(f"✅ [阶段 2] 节点规划完成")
            logger.info(f"  - 阶段 2 耗时: {stage2_time:.2f}s")
            logger.info(f"  - AI 生成节点: {len(index_to_beats)}/{len(generated_lines_data)} 条")
            logger.info(f"  - 规则回退节点: {len(generated_lines_data) - len(index_to_beats)} 条")

            # ========== 最终写库：创建 PlotLine 对象 ==========
            logger.info(f"🔹 [写库] 开始创建剧情线对象")

            async with stage_scope("persist", "写入剧情线") as st:
                # 获取当前最大排序序号
                max_order_result = await db.execute(
                    select(PlotLine.order_index).where(PlotLine.project_id == project_id)
                    .order_by(PlotLine.order_index.desc()).limit(1)
                )
                base_order_index = max_order_result.scalar() or 0

                created_lines = []

                for line_data in generated_lines_data:
                    line_index = line_data["index"]

                    # 尝试从 AI 结果获取 beats
                    if line_index in index_to_beats:
                        beats = index_to_beats[line_index]
                        logger.info(f"  - 剧情线 {line_index} 使用 AI 生成的节点（{len(beats)} 个）")
                    else:
                        logger.warning(f"  - 剧情线 {line_index} 未生成节点，跳过")
                        continue

                    # 权重归一化（确保总和接近 1.0）
                    total_weight = sum(beat.get("weight", 0) for beat in beats)
                    if total_weight > 0 and (total_weight < 0.95 or total_weight > 1.05):
                        logger.info(f"  - 剧情线 {line_index} 权重归一化: {total_weight:.2f} -> 1.0")
                        for beat in beats:
                            beat["weight"] = beat["weight"] / total_weight

                    # 构建 timeline_data：beats + （锚定成功时）mode / anchor 区间
                    timeline_data: Dict[str, Any] = {"beats": beats}
                    if (
                        line_data.get("mode")
                        and line_data.get("anchor_start_beat") is not None
                        and all(b.get("anchor_beat") is not None for b in beats)
                    ):
                        timeline_data.update(
                            mode=line_data["mode"],
                            anchor_start_beat=line_data["anchor_start_beat"],
                            anchor_end_beat=line_data["anchor_end_beat"],
                        )
                    timeline_data_json = json.dumps(timeline_data, ensure_ascii=False)

                    # 提取预计章节数（严格模式：必须由 AI 提供合法的正整数）
                    estimated_chapters = line_data.get("estimated_chapters")
                    if not isinstance(estimated_chapters, int) or estimated_chapters < 1:
                        logger.error(
                            "❌ 剧情线 %s 的 estimated_chapters 非法或缺失: %r",
                            line_index,
                            line_data.get("estimated_chapters"),
                        )
                        raise ValueError(
                            "AI 返回格式不完整: 缺少合法的 estimated_chapters 字段(必须是>=1的整数), "
                            "请重试或调整提示词，让 AI 明确给出本剧情线的预计章节数。"
                        )

                    logger.info(f"  - 剧情线 {line_index} 预计章节数: {estimated_chapters} 章")

                    # 创建 PlotLine 对象
                    line = PlotLine(
                        project_id=project_id,
                        story_outline_id=outline_id,
                        title=line_data["title"],
                        description=line_data["description"],
                        line_type=normalize_plot_line_type(line_data["line_type"], default=line_type),
                        order_index=base_order_index + line_index,
                        timeline_data=timeline_data_json,
                        estimated_chapters=estimated_chapters
                    )

                    db.add(line)
                    await db.commit()  # 立即提交以获取 ID
                    await db.refresh(line)  # 刷新以获取生成的 ID

                    created_lines.append(line)
                    logger.info(f"  - 剧情线 {line_index} 已创建: {line.title}")
                st.note(lines=len(created_lines))

            total_time = time.time() - total_start_time
            logger.info(f"✅ [剧情线生成] 完成，共生成 {len(created_lines)} 条剧情线")
            logger.info(f"  - 总耗时: {total_time:.2f}s")
            logger.info(f"  - 阶段 1（结构）: {stage1_time:.2f}s")
            logger.info(f"  - 阶段 2（节点）: {stage2_time:.2f}s")
            logger.info(f"  - 写库: {total_time - stage1_time - stage2_time:.2f}s")

            return created_lines

        except Exception as e:
            logger.error(f"生成剧情线失败: {str(e)}")
            await db.rollback()
            raise
    
    def _parse_ai_response(self, response: str, content_type: str) -> List[Dict[str, Any]]:
        """解析 AI 响应内容"""
        try:
            import re

            # 第一步：清理响应文本
            cleaned_response = response.strip()

            # 移除 markdown 代码块标记
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response[7:].lstrip('\n\r')
            elif cleaned_response.startswith('```'):
                cleaned_response = cleaned_response[3:].lstrip('\n\r')
            if cleaned_response.endswith('```'):
                cleaned_response = cleaned_response[:-3].rstrip('\n\r')
            cleaned_response = cleaned_response.strip()

            # 第二步：提取 JSON 部分（支持数组和对象）
            json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', cleaned_response)
            if json_match:
                json_text = json_match.group(1)
            else:
                json_text = cleaned_response

            # 第三步：修复常见的 JSON 格式错误
            # 1. 移除对象/数组最后一个元素后的多余逗号
            json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
            # 2. 移除注释（单行和多行）
            json_text = re.sub(r'//.*?$', '', json_text, flags=re.MULTILINE)
            json_text = re.sub(r'/\*.*?\*/', '', json_text, flags=re.DOTALL)

            logger.debug(f"清理后的 JSON 长度: {len(json_text)}")

            # 第四步：尝试解析 JSON
            data = json.loads(json_text)

            # 确保返回列表格式
            if not isinstance(data, list):
                if isinstance(data, dict):
                    # 如果是对象，尝试提取可能的数组字段
                    if content_type == "chapter_outlines" and "chapters" in data:
                        data = data["chapters"]
                    else:
                        data = [data]
                else:
                    data = [data]

            return self._normalize_field_names(data, content_type)

        except json.JSONDecodeError as e:
            logger.error(f"解析 AI 响应失败: {str(e)}")
            logger.error(f"原始响应内容: {self._safe_preview(response, 1000)}")

            # JSON 解析失败时，返回空列表（让上层逻辑处理）
            return []

        except Exception as e:
            logger.error(f"解析 AI 响应时发生异常: {str(e)}")
            logger.error(f"原始响应内容: {self._safe_preview(response, 1000)}")
            return []

    def _normalize_field_names(self, data: List[Dict[str, Any]], content_type: str) -> List[Dict[str, Any]]:
        """标准化字段名，处理可能的中文字段名"""
        if content_type == "plot_lines":
            # 中文到英文字段名映射
            field_mapping = {
                "起始点描述": "start",
                "发展点": "developments", 
                "发展点1": "developments",
                "发展点2": "developments",
                "发展点3": "developments",
                "高潮点描述": "climax",
                "结束点描述": "resolution"
            }
            
            normalized_data = []
            for item in data:
                normalized_item = {}
                for key, value in item.items():
                    if key == "timeline_data" and isinstance(value, dict):
                        # 标准化 timeline_data 内部字段
                        normalized_timeline = {}
                        for tk, tv in value.items():
                            if tk in field_mapping:
                                normalized_timeline[field_mapping[tk]] = tv
                            else:
                                normalized_timeline[tk] = tv
                        normalized_item[key] = normalized_timeline
                    else:
                        normalized_item[key] = value
                normalized_data.append(normalized_item)
            return normalized_data
        
        return data


# 注意：不再提供全局实例，需要通过依赖注入传入 AIService
