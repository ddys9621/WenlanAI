"""剧情卡片生成服务（规划链 总纲 → 卷纲 → 章纲 见 volume_service）"""
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.models import Project, StoryOutline, PlotCard
from app.services.plot_prompts import PlotPromptService
from app.services.ai_service import AIService
from app.services.generation_trace import stage_scope
from app.services.world_rule_service import WorldRuleService
from app.services.prompt_service import prompt_service as project_prompt_service
from app.logger import get_logger
from app.utils.prompt_safety import quote_untrusted

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
            context_type: 上下文类型 ("plot_card" | "chapter_outline")
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
            context_type: 上下文类型（plot_card/chapter_outline/chapter_content）
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

{quote_untrusted(reference_materials, "MCP 检索结果")}

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
        return data


# 注意：不再提供全局实例，需要通过依赖注入传入 AIService
