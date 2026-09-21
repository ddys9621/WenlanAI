"""项目创建向导流式API - 使用SSE避免超时"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, or_, select
from typing import Dict, Any, AsyncGenerator
import asyncio
import json
import re

from app.database import get_db
from app.models.project import Project
from app.models.character import Character
from app.models.story_outline import StoryOutline
from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.plot_card import PlotCard
from app.models.plot_line import PlotLine
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.services.relationship_matcher import match_relationship_type
from app.models.world_rule import WorldRule
from app.models.writing_style import WritingStyle
from app.models.project_default_style import ProjectDefaultStyle
from app.models.reference_pack import ReferencePack
from app.models.project_reference_pack import ProjectReferencePack
from app.services.ai_service import AIService
from app.services.prompt_service import prompt_service
from app.logger import get_logger
from app.utils.role_type import normalize_role_type, is_protagonist_role
from app.utils.sse_response import SSEResponse, create_sse_response
from app.api.ai_jobs import job_sse_response
from app.api.settings import get_user_ai_service
from app.services.ai_jobs import AIJobConflictError, ai_jobs, job_session_factory
from app.services.sse_job_adapter import make_sse_generator_runner
router = APIRouter(prefix="/wizard-stream", tags=["项目创建向导(流式)"])
logger = get_logger(__name__)

WIZARD_CANCEL_MESSAGE = "已停止；本步已写入的数据保留，可重新生成"


async def _start_wizard_job(request: Request, data: Dict[str, Any], *, kind: str, title: str, factory):
    """向导一步 = 一个通用后台任务：生成器零改动，由 sse_job_adapter 转发事件（协议向后兼容：start / progress / result / done）。

    同一项目四步共用互斥键 wizard:{project_id}（本来就是顺序执行）；重连 / 停止走 /api/ai-jobs/*。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        data["user_id"] = user_id
    project_id = data.get("project_id")
    try:
        job = await ai_jobs.start(
            kind=kind,
            title=title,
            user_id=user_id or "system",
            project_id=project_id,
            scope=f"wizard:{project_id or user_id}",
            runner=make_sse_generator_runner(factory, session_factory=job_session_factory(user_id or "system")),
            cancel_message=WIZARD_CANCEL_MESSAGE,
            meta={"step": kind, "mode": data.get("mode")},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


# ============================================================
# V3.2-B：项目创建后自动挂载用户在灵感模式入口选好的拆书参考包
# 设计：在 world-building create 模式 project 提交成功后立即调用
# 失败容错：任一 pack 挂载失败仅记 warn，不阻断主流程
# ============================================================

def _wizard_infer_default_dimensions(strength: str) -> list:
    """与 reference_pack._infer_default_dimensions 保持一致的默认维度推断。

    V4.1：
    - light: 仅文风
    - medium: + synopsis（Story Bible 全局引导）
    - deep: + 模式三维度（entities/relations/events）+ 5 手法全开
            + V4.1 桥段范本(bridges) + V4.1 角色档案(character_archive)
    """
    if strength == "light":
        return ["style"]
    if strength == "deep":
        return [
            "synopsis",
            "entities",
            "relations",
            "events",
            "methodology",
            "style",
            "structure",
            "archetypes",
            "worldbuilding",
            "bridges",            # V4.1
            "character_archive",  # V4.1
            "corpus",
        ]
    # medium
    return ["synopsis", "methodology", "style", "corpus"]


async def _auto_attach_packs_to_project(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    pack_ids: list,
    dimensions: list,
    strength: str,
) -> int:
    """灵感模式入口选好的 pack 在项目创建后自动挂载。

    Args:
        pack_ids: 用户在 selector 选好的 pack 列表（必须非空）
        dimensions: 用户选的维度（空数组则按 strength 推断）
        strength: 用户选的强度（默认 medium）

    Returns:
        实际成功挂载的 pack 数量
    """
    if not pack_ids:
        return 0
    strength = strength if strength in ("light", "medium", "deep") else "medium"
    explicit_dims = list(dimensions) if dimensions else None

    # 一次查全部目标 pack（必须属于当前用户）
    result = await db.execute(
        select(ReferencePack).where(
            ReferencePack.id.in_(pack_ids),
            ReferencePack.user_id == user_id,
        )
    )
    packs = list(result.scalars().all())
    if not packs:
        logger.warning(
            "[V3.2-B] 灵感入口 pack_ids 全部不存在或无权访问 user=%s project=%s pack_ids=%s",
            user_id, project_id, pack_ids,
        )
        return 0

    attached = 0
    for pack in packs:
        # 仅 ready/partial 可挂载；其它状态跳过（用户体验降级）
        if pack.status not in ("ready", "partial"):
            logger.info("[V3.2-B] 跳过未就绪 pack id=%s status=%s", pack.id, pack.status)
            continue

        # 计算最终默认维度：显式 > strength 推断
        dims = explicit_dims if explicit_dims is not None else _wizard_infer_default_dimensions(strength)
        # 与 ReferencePack.generated_dimensions 求交集，避免引用空 tab
        try:
            gen_raw = pack.generated_dimensions or "[]"
            generated = set(json.loads(gen_raw) if isinstance(gen_raw, str) else (gen_raw or []))
        except Exception:
            generated = set()
        valid = generated | {"corpus"}
        dims_filtered = [d for d in dims if d in valid] or ["corpus"]

        link = ProjectReferencePack(
            project_id=project_id,
            pack_id=pack.id,
            default_dimensions=json.dumps(dims_filtered, ensure_ascii=False),
            default_strength=strength,
        )
        db.add(link)
        attached += 1

    if attached:
        try:
            await db.commit()
        except Exception as e:  # 一般是 UNIQUE 冲突（不应发生因为 project 是刚创建的）
            await db.rollback()
            logger.warning("[V3.2-B] 自动挂载提交失败 project=%s err=%s", project_id, e)
            return 0

        logger.info(
            "[V3.2-B] 灵感入口自动挂载完成 user=%s project=%s attached=%d strength=%s",
            user_id, project_id, attached, strength,
        )
    return attached


async def world_building_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """世界构建流式生成器 - 支持MCP工具增强"""
    # 标记数据库会话是否已提交
    try:
        mode = data.get("mode", "create")
        project_id = data.get("project_id")
        project = None

        if mode == "update":
            user_id = data.get("user_id")
            if not user_id:
                yield await SSEResponse.send_error("用户未登录", 401)
                return

            if not project_id:
                yield await SSEResponse.send_error("project_id 是必需的参数", 400)
                return

            result = await db.execute(
                select(Project).where(
                    Project.id == project_id,
                    Project.user_id == user_id
                )
            )
            project = result.scalar_one_or_none()
            if not project:
                yield await SSEResponse.send_error("项目不存在或无权访问", 404)
                return

            yield await SSEResponse.send_progress("更新世界设定...", 20)

            field_mapping = {
                "time_period": "world_time_period",
                "location": "world_location",
                "atmosphere": "world_atmosphere",
                "rules": "world_rules",
            }
            for payload_key, project_field in field_mapping.items():
                if payload_key in data:
                    setattr(project, project_field, data.get(payload_key))

            await db.commit()
            await db.refresh(project)

            yield await SSEResponse.send_result({
                "project_id": project.id,
                "time_period": project.world_time_period or "",
                "location": project.world_location or "",
                "atmosphere": project.world_atmosphere or "",
                "rules": project.world_rules or "",
            })
            yield await SSEResponse.send_progress("完成!", 100, "success")
            yield await SSEResponse.send_done()
            return

        if mode == "regenerate":
            user_id = data.get("user_id")
            if not user_id:
                yield await SSEResponse.send_error("用户未登录", 401)
                return

            if not project_id:
                yield await SSEResponse.send_error("project_id 是必需的参数", 400)
                return

            yield await SSEResponse.send_progress("加载项目资料...", 5)
            result = await db.execute(
                select(Project).where(
                    Project.id == project_id,
                    Project.user_id == user_id
                )
            )
            project = result.scalar_one_or_none()
            if not project:
                yield await SSEResponse.send_error("项目不存在或无权访问", 404)
                return

        # 发送开始消息
        start_message = "开始重新生成世界观..." if mode == "regenerate" else "开始生成世界观..."
        yield await SSEResponse.send_progress(start_message, 10)
        
        # 提取参数
        if mode == "regenerate" and project is not None:
            title = data.get("title") or project.title or "未命名项目"
            description = data.get("description") if data.get("description") is not None else (project.description or "")
            theme = data.get("theme") if data.get("theme") is not None else (project.theme or title)
            genre = data.get("genre") if data.get("genre") is not None else (project.genre or "通用")
            generation_prompt = data.get("generation_prompt") if "generation_prompt" in data else project.generation_prompt
            narrative_perspective = project.narrative_perspective
            target_words = project.target_words
            chapter_count = project.chapter_count
            character_count = project.character_count

            project.title = str(title).strip() or project.title
            project.description = description
            project.theme = theme
            project.genre = genre
            project.generation_prompt = generation_prompt
        else:
            title = data.get("title")
            description = data.get("description")
            theme = data.get("theme")
            genre = data.get("genre")
            generation_prompt = data.get("generation_prompt")
            narrative_perspective = data.get("narrative_perspective")
            target_words = data.get("target_words")
            chapter_count = data.get("chapter_count")
            character_count = data.get("character_count")
        provider = data.get("provider")
        model = data.get("model")
        enable_mcp = data.get("enable_mcp", False)  # 默认禁用MCP，需要用户明确选择
        selected_plugins = data.get("selected_plugins", [])  # 选择的插件列表
        user_id = data.get("user_id")  # 从中间件注入
        
        if mode == "create" and (not title or not description or not theme or not genre):
            yield await SSEResponse.send_error("title、description、theme 和 genre 是必需的参数", 400)
            return
        
        # 获取基础提示词
        yield await SSEResponse.send_progress("准备AI提示词...", 15)
        base_prompt = prompt_service.get_world_building_prompt(
            title=title,
            theme=theme,
            genre=genre
        )
        
        # MCP工具增强：收集参考资料
        reference_materials = ""
        if enable_mcp and user_id:
            try:
                yield await SSEResponse.send_progress("🔍 尝试使用MCP工具收集参考资料...", 18)
                
                # 直接调用MCP增强的AI，内部会自动检查和加载工具
                # 构建资料收集提示词（强制工具调用）
                planning_prompt = f"""请使用搜索工具查询以下内容：

题材：{genre}
主题：{theme}
查询目标：该题材相关的核心背景资料（历史、地理、文化、专业知识等）

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{genre}题材小说背景设定" 或 "{theme}相关历史文化资料"

请立即调用工具。"""
                    
                # 调用MCP增强的AI（非流式，最多2轮工具调用）
                # 强制使用工具（tool_choice="required"）确保启用MCP时必定触发工具调用
                planning_result = await user_ai_service.generate_text_with_mcp(
                    prompt=planning_prompt,
                    user_id=user_id,
                    db_session=db,
                    enable_mcp=True,
                    selected_plugins=selected_plugins,
                    max_tool_rounds=2,
                    tool_choice="required",  # 强制工具调用
                    provider=None,
                    model=None
                )

                # 提取参考资料
                reference_materials = planning_result.get("content", "")
                tool_calls_made = planning_result.get("tool_calls_made", 0)
                tools_used = planning_result.get("tools_used", [])

                # 记录原始长度
                raw_chars = len(reference_materials)

                # 截断参考资料（避免 Prompt 过长，影响 LLM 响应速度）
                max_length = 2000
                if len(reference_materials) > max_length:
                    logger.warning(f"⚠️ [wizard_worldview] 参考资料过长（{raw_chars}字符），截断至{max_length}字符")
                    reference_materials = reference_materials[:max_length] + "\n...(内容过长已截断)"

                used_chars = len(reference_materials)

                # 统一日志：记录参考资料使用情况
                logger.info(
                    f"[MCP] context=wizard_worldview_planning user_id={user_id} "
                    f"plugins={selected_plugins} tools_used={tools_used} "
                    f"raw_chars={raw_chars} used_chars={used_chars} "
                    f"tool_calls={tool_calls_made}"
                )

                if tool_calls_made > 0:
                    yield await SSEResponse.send_progress(
                        f"✅ MCP工具调用成功（{tool_calls_made}次，收集{raw_chars}字符）",
                        25
                    )
                else:
                    # 强制模式下仍未触发工具，记录警告
                    logger.warning(
                        f"⚠️ [wizard_worldview] MCP强制模式下工具未触发 "
                        f"user_id={user_id} plugins={selected_plugins}"
                    )
                    yield await SSEResponse.send_progress("⚠️ MCP工具未触发（可能模型不支持）", 25)
                    
            except Exception as e:
                logger.warning(f"MCP工具调用失败（降级处理）: {e}")
                yield await SSEResponse.send_progress("⚠️ MCP工具暂时不可用，使用基础模式", 25)
        
        # 构建增强提示词
        if reference_materials:
            enhanced_prompt = f"""{base_prompt}

【参考资料】
以下是通过MCP工具收集的真实背景资料，请参考这些信息构建更真实的世界观：

{reference_materials}

请结合上述资料，生成符合历史/现实的世界观设定。"""
            final_prompt = enhanced_prompt
            yield await SSEResponse.send_progress("💡 已整合参考资料，开始生成世界观...", 30)
        else:
            final_prompt = base_prompt
            yield await SSEResponse.send_progress("正在调用AI生成...", 30)

        # 拆书参考注入（R7-世界观）：仅 update 模式（项目已存在）才尝试，create 模式下项目还未创建无挂载关系
        # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
        if project_id:
            try:
                from app.services.reference_pack_injector import ReferencePackInjector
                _injector = ReferencePackInjector()
                _ref_block = await _injector.build_reference_block(
                    db, project_id,
                    scene="worldview_generation",
                    fallback_dimensions=("worldbuilding",),
                    pack_ids=data.get("pack_ids"),
                    dimensions=data.get("dimensions"),
                    strength=data.get("strength"),
                    anchor_query=f"{theme or ''} {genre or ''}".strip() or "世界观",
                )
                if _ref_block.user_segment:
                    final_prompt = (
                        f"{final_prompt}\n\n{_ref_block.user_segment}\n\n"
                        "请参考上述拆书中的世界观建模手法（仅作方法参考，"
                        "不要复刻原书的具体地名/规则名），生成本项目的世界观。"
                    )
                    yield await SSEResponse.send_progress(
                        f"📚 已注入拆书参考包（{','.join(_ref_block.used_dimensions)}）",
                        32,
                    )
            except ValueError:
                pass
            except Exception as _e:  # pragma: no cover
                logger.warning(f"[R7-世界观] 拆书参考注入失败（已跳过）: {_e}")

        final_prompt = prompt_service.apply_project_generation_prompt(
            final_prompt,
            generation_prompt or ""
        )

        # 流式生成世界观
        accumulated_text = ""
        chunk_count = 0
        
        async for chunk in user_ai_service.generate_text_stream(
            prompt=final_prompt,
            provider=provider,
            model=model
        ):
            chunk_count += 1
            accumulated_text += chunk
            
            # 发送内容块
            yield await SSEResponse.send_chunk(chunk)
            
            # 定期更新进度
            if chunk_count % 5 == 0:
                progress = min(30 + (chunk_count // 5), 70)
                yield await SSEResponse.send_progress(f"生成中... ({len(accumulated_text)}字符)", progress)
            
            # 每20个块发送心跳
            if chunk_count % 20 == 0:
                yield await SSEResponse.send_heartbeat()
        
        # 解析结果
        yield await SSEResponse.send_progress("解析AI返回结果...", 80)

        from app.utils.json_cleaner import clean_and_parse_json, repair_json_with_llm

        world_data = {}
        try:
            world_data = clean_and_parse_json(
                accumulated_text,
                expected_type='object',
                log_prefix="[世界观生成]"
            )

        except json.JSONDecodeError as e:
            # 一次兜底失败：调用 LLM 做"只改格式、不动内容"的二次修复
            logger.warning(f"[世界观生成] 首次解析失败，触发 LLM 二次格式修复: {e}")
            yield await SSEResponse.send_progress("⚠️ 格式异常，AI 正在二次修复...", 82)
            try:
                world_data = await repair_json_with_llm(
                    accumulated_text,
                    user_ai_service=user_ai_service,
                    expected_type='object',
                    provider=provider,
                    model=model,
                    schema_hint="time_period, location, atmosphere, rules",
                    log_prefix="[世界观生成]",
                )
                logger.info("[世界观生成] LLM 二次格式修复成功")
                yield await SSEResponse.send_progress("✅ 二次修复成功", 84)
            except Exception as repair_err:
                logger.error(f"[世界观生成] LLM 二次格式修复仍失败: {repair_err}")
                # 最终兜底：保留原始内容预览，避免用户重试时完全丢失生成结果
                preview = (accumulated_text or "").strip()
                if len(preview) > 1500:
                    preview = preview[:1500] + "...(已截断)"
                fallback_rules = (
                    f"AI返回格式错误，请重试。\n\n原始内容预览：\n{preview}"
                    if preview else "AI返回格式错误，请重试"
                )
                world_data = {
                    "time_period": "AI返回格式错误，请重试",
                    "location": "AI返回格式错误，请重试",
                    "atmosphere": "AI返回格式错误，请重试",
                    "rules": fallback_rules,
                }
        # 保存到数据库
        yield await SSEResponse.send_progress("保存到数据库...", 90)
        
        # 确保user_id存在
        if not user_id:
            yield await SSEResponse.send_error("用户ID缺失，无法创建项目", 401)
            return
        
        generated_rules = []
        if mode == "create":
            project = Project(
                user_id=user_id,  # 添加user_id字段
                title=title,
                description=description,
                theme=theme,
                genre=genre,
                world_time_period=world_data.get("time_period"),
                world_location=world_data.get("location"),
                world_atmosphere=world_data.get("atmosphere"),
                world_rules=world_data.get("rules"),
                generation_prompt=generation_prompt,
                narrative_perspective=narrative_perspective,
                target_words=target_words,
                chapter_count=chapter_count,
                character_count=character_count,
                wizard_status="incomplete",
                wizard_step=1,
                status="planning"
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)
            
            # 自动设置默认写作风格为第一个全局预设风格
            try:
                result = await db.execute(
                    select(WritingStyle).where(
                        WritingStyle.project_id.is_(None),
                        WritingStyle.order_index == 1
                    ).limit(1)
                )
                first_style = result.scalar_one_or_none()
                
                if first_style:
                    default_style = ProjectDefaultStyle(
                        project_id=project.id,
                        style_id=first_style.id
                    )
                    db.add(default_style)
                    await db.commit()
                    logger.info(f"为项目 {project.id} 自动设置默认风格: {first_style.name}")
                else:
                    logger.warning(f"未找到order_index=1的全局预设风格，项目 {project.id} 未设置默认风格")
            except Exception as e:
                logger.warning(f"设置默认写作风格失败: {e}，不影响项目创建")

            # V3.2-B：项目创建成功后，立即把灵感模式入口选好的拆书 pack 挂上来
            # 让后续 characters/outline 步骤的 ReferencePackInjector 能从挂载关系读到
            try:
                _wizard_pack_ids = data.get("pack_ids") or []
                if _wizard_pack_ids:
                    yield await SSEResponse.send_progress("📚 关联拆书参考包...", 83)
                    _attached = await _auto_attach_packs_to_project(
                        db,
                        user_id=user_id,
                        project_id=project.id,
                        pack_ids=_wizard_pack_ids,
                        dimensions=data.get("dimensions") or [],
                        strength=data.get("strength") or "medium",
                    )
                    if _attached:
                        yield await SSEResponse.send_progress(
                            f"✅ 已挂载 {_attached} 个拆书参考包", 84
                        )
            except Exception as _attach_err:  # pragma: no cover
                logger.warning(f"[V3.2-B] 自动挂载参考包失败（不影响项目创建）: {_attach_err}")


            # 【新增】世界观生成后,立即生成详细世界规则
            from app.services.world_rule_service import world_rule_service
            try:
                yield await SSEResponse.send_progress("🎨 正在生成详细世界规则系统...", 85)
                generated_rules = await world_rule_service.generate_initial_rules_for_project(
                    db, project, user_ai_service
                )

                if generated_rules:
                    # 先提交世界规则到数据库，确保规则持久化
                    yield await SSEResponse.send_progress("💾 正在保存世界规则...", 88)
                    await db.commit()
                    logger.info(f"✅ 成功保存 {len(generated_rules)} 条世界规则到数据库")

                    # 向量化生成的规则
                    yield await SSEResponse.send_progress("🔄 正在向量化世界规则...", 90)
                    vectorized_count = 0
                    for rule in generated_rules:
                        try:
                            await db.refresh(rule)
                            await world_rule_service.upsert_rule_to_vector_db(rule)
                            vectorized_count += 1
                        except Exception as vec_error:
                            logger.warning(f"⚠️ 规则向量化失败: {rule.name} - {str(vec_error)}")

                    logger.info(f"✅ 世界观生成完成,成功创建并向量化 {vectorized_count}/{len(generated_rules)} 条世界规则")
                    yield await SSEResponse.send_progress(f"✅ 已生成 {len(generated_rules)} 条世界规则", 95)
                else:
                    logger.info("📋 世界观生成完成,使用基础规则设定")
                    yield await SSEResponse.send_progress("📋 使用基础世界规则", 95)
            except Exception as rule_error:
                logger.warning(f"⚠️ 世界规则生成失败（不影响世界观创建）: {str(rule_error)}")
                yield await SSEResponse.send_progress("⚠️ 世界规则生成失败,已保存基础设定", 95)
        else:
            if project is None:
                yield await SSEResponse.send_error("项目不存在", 404)
                return

            project.world_time_period = world_data.get("time_period")
            project.world_location = world_data.get("location")
            project.world_atmosphere = world_data.get("atmosphere")
            project.world_rules = world_data.get("rules")
            await db.flush()

            from app.services.world_rule_service import world_rule_service
            try:
                yield await SSEResponse.send_progress("♻️ 正在刷新世界规则系统...", 85)

                existing_rules_result = await db.execute(
                    select(WorldRule).where(WorldRule.project_id == project.id)
                )
                existing_rules = existing_rules_result.scalars().all()

                for rule in existing_rules:
                    try:
                        await world_rule_service.delete_rule_from_vector_db(project.id, rule.id)
                    except Exception as vec_error:
                        logger.warning(f"⚠️ 删除旧规则向量失败: {rule.id} - {str(vec_error)}")
                    await db.delete(rule)

                generated_rules = await world_rule_service.generate_initial_rules_for_project(
                    db, project, user_ai_service
                )

                await db.commit()
                await db.refresh(project)

                if generated_rules:
                    yield await SSEResponse.send_progress("🔄 正在向量化世界规则...", 90)
                    vectorized_count = 0
                    for rule in generated_rules:
                        try:
                            await db.refresh(rule)
                            await world_rule_service.upsert_rule_to_vector_db(rule)
                            vectorized_count += 1
                        except Exception as vec_error:
                            logger.warning(f"⚠️ 规则向量化失败: {rule.name} - {str(vec_error)}")

                    logger.info(f"✅ 世界观重生成完成,成功重建并向量化 {vectorized_count}/{len(generated_rules)} 条世界规则")
                    yield await SSEResponse.send_progress(f"✅ 已重建 {len(generated_rules)} 条世界规则", 95)
                else:
                    yield await SSEResponse.send_progress("📋 已更新基础世界规则", 95)
            except Exception as rule_error:
                logger.warning(f"⚠️ 世界规则刷新失败（保留基础设定）: {str(rule_error)}")
                await db.commit()
                await db.refresh(project)
                yield await SSEResponse.send_progress("⚠️ 世界规则刷新失败,已保存基础设定", 95)

        # 发送最终结果
        yield await SSEResponse.send_result({
            "project_id": project.id,
            "time_period": world_data.get("time_period"),
            "location": world_data.get("location"),
            "atmosphere": world_data.get("atmosphere"),
            "rules": world_data.get("rules"),
            "generated_rules_count": len(generated_rules)  # 新增:返回生成的规则数量
        })

        yield await SSEResponse.send_progress("完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("世界构建生成器被提前关闭")
    except Exception as e:
        logger.error(f"世界构建流式生成失败: {str(e)}")
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")


@router.post("/world-building", summary="流式生成世界构建（后台任务 + SSE）")
async def generate_world_building_stream(
    request: Request,
    data: Dict[str, Any],
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """向导步骤 1：世界构建（create / regenerate）。跑在通用后台任务上：切页 / 刷新不中断，托盘可见。"""
    title = "向导：重新生成世界构建" if data.get("mode") == "regenerate" else "向导：生成世界构建"
    return await _start_wizard_job(
        request, data, kind="wizard_world_building", title=title,
        factory=lambda db: world_building_generator(data, db, user_ai_service),
    )


async def characters_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """角色批量生成流式生成器 - 优化版:分批+重试+MCP工具增强"""
    try:
        yield await SSEResponse.send_progress("开始生成角色...", 5)
        
        project_id = data.get("project_id")
        count = data.get("count", 5)
        world_context = data.get("world_context")
        theme = data.get("theme", "")
        genre = data.get("genre", "")
        requirements = data.get("requirements", "")
        provider = data.get("provider")
        model = data.get("model")
        enable_mcp = data.get("enable_mcp", False)  # 默认禁用MCP，需要用户明确选择
        selected_plugins = data.get("selected_plugins", [])  # 选择的插件列表
        user_id = data.get("user_id")  # 从中间件注入
        
        # 验证项目
        yield await SSEResponse.send_progress("验证项目...", 10)
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        project.wizard_step = 2

        world_context = world_context or {
            "time_period": project.world_time_period or "未设定",
            "location": project.world_location or "未设定",
            "atmosphere": project.world_atmosphere or "未设定",
            "rules": project.world_rules or "未设定"
        }

        # 【新增】查询世界规则,让角色生成参考详细规则
        from app.services.world_rule_service import world_rule_service
        world_rules_summary = ""
        try:
            yield await SSEResponse.send_progress("📋 加载世界规则...", 12)
            # 构建查询文本
            query_text = f"{theme or project.theme or ''} {genre or project.genre or ''}"
            # 使用语义检索获取相关规则
            world_rules_summary = await world_rule_service.generate_rules_summary_with_search(
                db, project.id, query_text, limit=10
            )
            if world_rules_summary:
                logger.info(f"✅ 为角色生成加载了世界规则摘要 ({len(world_rules_summary)} 字符)")
            else:
                logger.info("📋 项目暂无详细世界规则,使用基础设定")
        except Exception as rule_error:
            logger.warning(f"⚠️ 加载世界规则失败: {str(rule_error)}")
            world_rules_summary = ""
        
        # MCP工具增强：收集角色参考资料
        character_reference_materials = ""
        if enable_mcp and user_id:
            try:
                yield await SSEResponse.send_progress("🔍 尝试使用MCP工具收集角色参考资料...", 8)
                
                # 构建角色资料收集提示词（强制工具调用）
                planning_prompt = f"""请使用搜索工具查询以下内容：

题材：{genre or project.genre}
时代背景：{world_context.get('time_period', '未设定')}
地理位置：{world_context.get('location', '未设定')}
查询目标：该时代/地域的真实人物特征、文化背景、职业特点

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{world_context.get('time_period', genre)}时代人物特征" 或 "{world_context.get('location', '历史')}文化背景"

请立即调用工具。"""
                
                # 调用MCP增强的AI（非流式，最多2轮工具调用）
                # 强制使用工具（tool_choice="required"）确保启用MCP时必定触发工具调用
                planning_result = await user_ai_service.generate_text_with_mcp(
                    prompt=planning_prompt,
                    user_id=user_id,
                    db_session=db,
                    enable_mcp=True,
                    selected_plugins=selected_plugins,
                    max_tool_rounds=2,
                    tool_choice="required",  # 强制工具调用
                    provider=None,
                    model=None
                )

                # 提取参考资料
                character_reference_materials = planning_result.get("content", "")
                tool_calls_made = planning_result.get("tool_calls_made", 0)
                tools_used = planning_result.get("tools_used", [])

                # 记录原始长度
                raw_chars = len(character_reference_materials)

                # 截断参考资料（避免 Prompt 过长，影响 LLM 响应速度）
                max_length = 2000
                if len(character_reference_materials) > max_length:
                    logger.warning(f"⚠️ [wizard_characters] 参考资料过长（{raw_chars}字符），截断至{max_length}字符")
                    character_reference_materials = character_reference_materials[:max_length] + "\n...(内容过长已截断)"

                used_chars = len(character_reference_materials)

                # 统一日志：记录参考资料使用情况
                logger.info(
                    f"[MCP] context=wizard_characters_planning user_id={user_id} "
                    f"plugins={selected_plugins} tools_used={tools_used} "
                    f"raw_chars={raw_chars} used_chars={used_chars} "
                    f"tool_calls={tool_calls_made}"
                )

                if tool_calls_made > 0:
                    yield await SSEResponse.send_progress(
                        f"✅ MCP工具调用成功（{tool_calls_made}次，收集{raw_chars}字符）",
                        12
                    )
                else:
                    # 强制模式下仍未触发工具，记录警告
                    logger.warning(
                        f"⚠️ [wizard_characters] MCP强制模式下工具未触发 "
                        f"user_id={user_id} plugins={selected_plugins}"
                    )
                    yield await SSEResponse.send_progress("⚠️ MCP工具未触发（可能模型不支持）", 12)
                    
            except Exception as e:
                logger.warning(f"MCP工具调用失败（降级处理）: {e}")
                yield await SSEResponse.send_progress("⚠️ MCP工具暂时不可用，使用基础模式", 12)
        
        # 优化的分批策略:每批生成3个,平衡效率和成功率
        BATCH_SIZE = 3  # 每批生成3个角色
        MAX_RETRIES = 3  # 每批最多重试3次
        all_characters = []
        total_batches = (count + BATCH_SIZE - 1) // BATCH_SIZE
        
        for batch_idx in range(total_batches):
            # 精确计算当前批次应该生成的数量
            remaining = count - len(all_characters)
            current_batch_size = min(BATCH_SIZE, remaining)
            
            # 如果已经达到目标数量,直接退出
            if current_batch_size <= 0:
                logger.info(f"已生成{len(all_characters)}个角色,达到目标数量{count}")
                break
            
            batch_progress = 15 + (batch_idx * 60 // total_batches)
            
            # 重试逻辑
            retry_count = 0
            batch_success = False
            batch_error_message = ""
            
            while retry_count < MAX_RETRIES and not batch_success:
                try:
                    retry_suffix = f" (重试{retry_count}/{MAX_RETRIES})" if retry_count > 0 else ""
                    yield await SSEResponse.send_progress(
                        f"生成第{batch_idx+1}/{total_batches}批角色 ({current_batch_size}个){retry_suffix}...",
                        batch_progress
                    )
                    
                    # 构建批次要求 - 包含已生成角色信息保持连贯
                    existing_chars_context = ""
                    if all_characters:
                        existing_chars_context = "\n\n【已生成的角色】:\n"
                        for char in all_characters:
                            existing_chars_context += f"- {char.get('name')}: {char.get('role_type', '未知')}, {char.get('personality', '暂无')[:50]}...\n"
                        existing_chars_context += "\n请确保新角色与已有角色形成合理的关系网络和互动。\n"
                    
                    # 构建精确的批次要求,明确告诉AI要生成的数量
                    if batch_idx == 0:
                        if current_batch_size == 1:
                            batch_requirements = f"{requirements}\n请生成1个主角(protagonist)"
                        else:
                            batch_requirements = f"{requirements}\n请精确生成{current_batch_size}个角色:1个主角(protagonist)和{current_batch_size-1}个核心配角(supporting)"
                    else:
                        batch_requirements = f"{requirements}\n请精确生成{current_batch_size}个角色{existing_chars_context}"
                        if batch_idx == total_batches - 1:
                            batch_requirements += "\n可以包含组织或反派(antagonist)"
                        else:
                            batch_requirements += "\n主要是配角(supporting)和反派(antagonist)"
                    
                    # 构建基础提示词
                    base_prompt = prompt_service.get_characters_batch_prompt(
                        count=current_batch_size,  # 传递精确数量
                        time_period=world_context.get("time_period", ""),
                        location=world_context.get("location", ""),
                        atmosphere=world_context.get("atmosphere", ""),
                        rules=world_context.get("rules", ""),
                        theme=theme or project.theme or "",
                        genre=genre or project.genre or "",
                        requirements=batch_requirements
                    )

                    # 增强提示词: 添加详细世界规则和MCP参考资料
                    prompt_parts = [base_prompt]

                    # 添加详细世界规则
                    if world_rules_summary:
                        prompt_parts.append(f"""
【详细世界规则】
以下是本作品的详细世界规则设定（境界体系、装备系统等），请确保角色设定符合这些规则：

{world_rules_summary}

请根据上述规则设定角色的境界、装备、能力等属性。""")

                    # 添加MCP参考资料
                    if character_reference_materials:
                        prompt_parts.append(f"""
【参考资料】
以下是通过MCP工具收集的真实背景资料，请参考这些信息设计更真实的角色：

{character_reference_materials}

请结合上述资料，设计符合历史/文化背景的角色。""")

                    # 拆书参考注入（R6-向导批量角色）：注入 archetypes / corpus 维度
                    # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
                    try:
                        from app.services.reference_pack_injector import ReferencePackInjector
                        _injector = ReferencePackInjector()
                        _ref_block = await _injector.build_reference_block(
                            db, project_id,
                            scene="character_batch_generation",
                            fallback_dimensions=("archetypes", "corpus"),
                            anchor_query=f"{theme or ''} {genre or ''} 角色塑造".strip(),
                        )
                        if _ref_block.user_segment:
                            prompt_parts.append(
                                f"{_ref_block.user_segment}\n\n"
                                "请参考上述拆书中的角色塑造手法（仅作方法参考，"
                                "不要复刻原书的具体人名与设定），生成本项目的角色。"
                            )
                            logger.info(
                                f"📚 [R6-向导角色] 注入拆书参考包 {len(_ref_block.used_packs)} 个，"
                                f"维度={_ref_block.used_dimensions}"
                            )
                    except ValueError:
                        pass
                    except Exception as _e:  # pragma: no cover
                        logger.warning(f"[R6-向导角色] 拆书参考注入失败（已跳过）: {_e}")

                    prompt = "\n\n".join(prompt_parts)
                    
                    # 流式生成
                    accumulated_text = ""
                    async for chunk in user_ai_service.generate_text_stream(
                        prompt=prompt,
                        provider=provider,
                        model=model
                    ):
                        accumulated_text += chunk
                        yield await SSEResponse.send_chunk(chunk)
                    
                    # 解析批次结果
                    cleaned_text = accumulated_text.strip()
                    # 移除markdown代码块标记
                    if cleaned_text.startswith('```json'):
                        cleaned_text = cleaned_text[7:].lstrip('\n\r')
                    elif cleaned_text.startswith('```'):
                        cleaned_text = cleaned_text[3:].lstrip('\n\r')
                    if cleaned_text.endswith('```'):
                        cleaned_text = cleaned_text[:-3].rstrip('\n\r')
                    cleaned_text = cleaned_text.strip()

                    # 增强的JSON清理：修复常见的格式错误
                    # 1. 移除对象/数组最后一个元素后的多余逗号
                    cleaned_text = re.sub(r',(\s*[}\]])', r'\1', cleaned_text)
                    # 2. 移除注释（单行和多行）
                    cleaned_text = re.sub(r'//.*?$', '', cleaned_text, flags=re.MULTILINE)
                    cleaned_text = re.sub(r'/\*.*?\*/', '', cleaned_text, flags=re.DOTALL)
                    # 3. 尝试提取JSON部分（如果AI在JSON前后添加了说明文字）
                    json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', cleaned_text)
                    if json_match:
                        cleaned_text = json_match.group(1)

                    # 记录清理后的JSON（用于调试）
                    logger.debug(f"批次{batch_idx+1} JSON清理后长度: {len(cleaned_text)}")

                    characters_data = json.loads(cleaned_text)
                    if not isinstance(characters_data, list):
                        characters_data = [characters_data]
                    
                    # 严格验证生成数量是否精确匹配
                    if len(characters_data) != current_batch_size:
                        error_msg = f"批次{batch_idx+1}生成数量不正确: 期望{current_batch_size}个, 实际{len(characters_data)}个"
                        logger.error(error_msg)
                        
                        # 如果还有重试机会，继续重试
                        if retry_count < MAX_RETRIES - 1:
                            retry_count += 1
                            yield await SSEResponse.send_progress(
                                f"⚠️ {error_msg}，准备重试...",
                                batch_progress,
                                "warning"
                            )
                            continue
                        else:
                            # 最后一次重试仍失败，直接返回错误
                            yield await SSEResponse.send_error(error_msg)
                            return
                    
                    all_characters.extend(characters_data)
                    batch_success = True
                    logger.info(f"批次{batch_idx+1}成功添加{len(characters_data)}个角色,当前总数{len(all_characters)}/{count}")
                    
                except json.JSONDecodeError as e:
                    logger.error(f"批次{batch_idx+1}解析失败(尝试{retry_count+1}/{MAX_RETRIES}): {e}")
                    batch_error_message = f"JSON解析失败: {str(e)}"
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        yield await SSEResponse.send_progress(
                            f"解析失败，准备重试...",
                            batch_progress,
                            "warning"
                        )
                except Exception as e:
                    logger.error(f"批次{batch_idx+1}生成异常(尝试{retry_count+1}/{MAX_RETRIES}): {e}")
                    batch_error_message = f"生成异常: {str(e)}"
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        yield await SSEResponse.send_progress(
                            f"生成异常，准备重试...",
                            batch_progress,
                            "warning"
                        )
            
            # 检查批次是否成功
            if not batch_success:
                error_msg = f"批次{batch_idx+1}在{MAX_RETRIES}次重试后仍然失败"
                if batch_error_message:
                    error_msg += f": {batch_error_message}"
                logger.error(error_msg)
                yield await SSEResponse.send_error(error_msg)
                return
        
        # 保存到数据库 - 分阶段处理以保证一致性
        yield await SSEResponse.send_progress("验证角色数据...", 82)
        
        # 预处理：构建本批次所有实体的名称集合
        valid_entity_names = set()
        valid_organization_names = set()
        
        for char_data in all_characters:
            entity_name = char_data.get("name", "")
            if entity_name:
                valid_entity_names.add(entity_name)
                if char_data.get("is_organization", False):
                    valid_organization_names.add(entity_name)
        
        # 清理幻觉引用
        cleaned_count = 0
        for char_data in all_characters:
            # 清理关系数组中的无效引用
            if "relationships_array" in char_data and isinstance(char_data["relationships_array"], list):
                original_rels = char_data["relationships_array"]
                valid_rels = []
                for rel in original_rels:
                    target_name = rel.get("target_character_name", "")
                    if target_name in valid_entity_names:
                        valid_rels.append(rel)
                    else:
                        cleaned_count += 1
                        logger.debug(f"  🧹 清理无效关系引用：{char_data.get('name')} -> {target_name}")
                char_data["relationships_array"] = valid_rels
            
            # 清理组织成员关系中的无效引用
            if "organization_memberships" in char_data and isinstance(char_data["organization_memberships"], list):
                original_orgs = char_data["organization_memberships"]
                valid_orgs = []
                for org_mem in original_orgs:
                    org_name = org_mem.get("organization_name", "")
                    if org_name in valid_organization_names:
                        valid_orgs.append(org_mem)
                    else:
                        cleaned_count += 1
                        logger.debug(f"  🧹 清理无效组织引用：{char_data.get('name')} -> {org_name}")
                char_data["organization_memberships"] = valid_orgs
        
        if cleaned_count > 0:
            logger.info(f"✨ 清理了{cleaned_count}个AI幻觉引用")
            yield await SSEResponse.send_progress(f"已清理{cleaned_count}个无效引用", 84)
        
        yield await SSEResponse.send_progress("保存角色到数据库...", 85)
        
        # 第一阶段：创建所有Character记录
        created_characters = []
        character_name_to_obj = {}  # 名称到对象的映射，用于后续关系创建
        
        for char_data in all_characters:
            # 从relationships_array提取文本描述以保持向后兼容
            relationships_text = ""
            relationships_array = char_data.get("relationships_array", [])
            if relationships_array and isinstance(relationships_array, list):
                # 将关系数组转换为可读文本
                rel_descriptions = []
                for rel in relationships_array:
                    target = rel.get("target_character_name", "未知")
                    rel_type = rel.get("relationship_type", "关系")
                    desc = rel.get("description", "")
                    rel_descriptions.append(f"{target}({rel_type}): {desc}")
                relationships_text = "; ".join(rel_descriptions)
            # 兼容旧格式
            elif isinstance(char_data.get("relationships"), dict):
                relationships_text = json.dumps(char_data.get("relationships"), ensure_ascii=False)
            elif isinstance(char_data.get("relationships"), str):
                relationships_text = char_data.get("relationships")
            
            # 判断是否为组织
            is_organization = char_data.get("is_organization", False)
            
            character = Character(
                project_id=project_id,
                name=char_data.get("name", "未命名角色"),
                age=str(char_data.get("age", "")) if not is_organization else None,
                gender=char_data.get("gender") if not is_organization else None,
                is_organization=is_organization,
                role_type=normalize_role_type(char_data.get("role_type"), "supporting"),
                personality=char_data.get("personality", ""),
                background=char_data.get("background", ""),
                appearance=char_data.get("appearance", ""),
                relationships=relationships_text,
                organization_type=char_data.get("organization_type") if is_organization else None,
                organization_purpose=char_data.get("organization_purpose") if is_organization else None,
                organization_members=json.dumps(char_data.get("organization_members", []), ensure_ascii=False) if is_organization else None,
                traits=json.dumps(char_data.get("traits", []), ensure_ascii=False) if char_data.get("traits") else None
            )
            db.add(character)
            created_characters.append((character, char_data))
        
        await db.flush()  # 获取所有角色的ID
        
        # 刷新并建立名称映射
        for character, _ in created_characters:
            await db.refresh(character)
            character_name_to_obj[character.name] = character
            logger.info(f"向导创建角色：{character.name} (ID: {character.id}, 是否组织: {character.is_organization})")
        
        # 为is_organization=True的角色创建Organization记录
        yield await SSEResponse.send_progress("创建组织记录...", 87)
        organization_name_to_obj = {}  # 组织名称到Organization对象的映射
        
        for character, char_data in created_characters:
            if character.is_organization:
                # 检查是否已存在Organization记录
                org_check = await db.execute(
                    select(Organization).where(Organization.character_id == character.id)
                )
                existing_org = org_check.scalar_one_or_none()
                
                if not existing_org:
                    # 创建Organization记录
                    org = Organization(
                        character_id=character.id,
                        project_id=project_id,
                        member_count=0,  # 初始为0，后续添加成员时会更新
                        power_level=char_data.get("power_level", 50),
                        location=char_data.get("location"),
                        motto=char_data.get("motto"),
                        color=char_data.get("color")
                    )
                    db.add(org)
                    logger.info(f"向导创建组织记录：{character.name}")
                else:
                    org = existing_org
                
                # 建立组织名称映射（无论是新建还是已存在）
                organization_name_to_obj[character.name] = org
        
        await db.flush()  # 确保Organization记录有ID
        
        # 刷新角色以获取ID
        for character, _ in created_characters:
            await db.refresh(character)
        
        # 第三阶段：创建角色间的关系
        yield await SSEResponse.send_progress("创建角色关系...", 90)
        relationships_created = 0
        
        for character, char_data in created_characters:
            # 跳过组织实体的角色关系处理（组织通过成员关系关联）
            if character.is_organization:
                continue
            
            # 处理relationships数组
            relationships_data = char_data.get("relationships_array", [])
            if not relationships_data and isinstance(char_data.get("relationships"), list):
                relationships_data = char_data.get("relationships")
            
            if relationships_data and isinstance(relationships_data, list):
                for rel in relationships_data:
                    try:
                        target_name = rel.get("target_character_name")
                        if not target_name:
                            logger.debug(f"  ⚠️  {character.name}的关系缺少target_character_name，跳过")
                            continue
                        
                        # 使用名称映射快速查找
                        target_char = character_name_to_obj.get(target_name)
                        
                        if target_char:
                            # 避免创建重复关系
                            existing_rel = await db.execute(
                                select(CharacterRelationship).where(
                                    CharacterRelationship.project_id == project_id,
                                    CharacterRelationship.character_from_id == character.id,
                                    CharacterRelationship.character_to_id == target_char.id
                                )
                            )
                            if existing_rel.scalars().first():
                                logger.debug(f"  ℹ️  关系已存在：{character.name} -> {target_name}")
                                continue
                            
                            relationship = CharacterRelationship(
                                project_id=project_id,
                                character_from_id=character.id,
                                character_to_id=target_char.id,
                                relationship_name=rel.get("relationship_type", "未知关系"),
                                intimacy_level=rel.get("intimacy_level", 50),
                                description=rel.get("description", ""),
                                started_at=rel.get("started_at"),
                                source="ai"
                            )
                            
                            # 模糊匹配预定义关系类型（三级回退）
                            matched_type_id = await match_relationship_type(db, rel.get("relationship_type"))
                            if matched_type_id:
                                relationship.relationship_type_id = matched_type_id
                            
                            db.add(relationship)
                            relationships_created += 1
                            logger.info(f"  ✅ 向导创建关系：{character.name} -> {target_name} ({rel.get('relationship_type')})")
                        else:
                            logger.warning(f"  ⚠️  目标角色不存在：{character.name} -> {target_name}（可能是AI幻觉）")
                    except Exception as e:
                        logger.warning(f"  ❌ 向导创建关系失败：{character.name} - {str(e)}")
                        continue
            
        # 第四阶段：创建组织成员关系
        yield await SSEResponse.send_progress("创建组织成员关系...", 93)
        members_created = 0
        
        for character, char_data in created_characters:
            # 跳过组织实体本身
            if character.is_organization:
                continue
            
            # 处理组织成员关系
            org_memberships = char_data.get("organization_memberships", [])
            if org_memberships and isinstance(org_memberships, list):
                for membership in org_memberships:
                    try:
                        org_name = membership.get("organization_name")
                        if not org_name:
                            logger.debug(f"  ⚠️  {character.name}的组织成员关系缺少organization_name，跳过")
                            continue
                        
                        # 使用映射快速查找组织
                        org = organization_name_to_obj.get(org_name)
                        
                        if org:
                            # 检查是否已存在成员关系
                            existing_member = await db.execute(
                                select(OrganizationMember).where(
                                    OrganizationMember.organization_id == org.id,
                                    OrganizationMember.character_id == character.id
                                )
                            )
                            if existing_member.scalars().first():
                                logger.debug(f"  ℹ️  成员关系已存在：{character.name} -> {org_name}")
                                continue
                            
                            # 创建成员关系
                            member = OrganizationMember(
                                organization_id=org.id,
                                character_id=character.id,
                                position=membership.get("position", "成员"),
                                rank=membership.get("rank", 0),
                                loyalty=membership.get("loyalty", 50),
                                joined_at=membership.get("joined_at"),
                                status=membership.get("status", "active"),
                                source="ai"
                            )
                            db.add(member)
                            
                            # 更新组织成员计数
                            org.member_count += 1
                            
                            members_created += 1
                            logger.info(f"  ✅ 向导添加成员：{character.name} -> {org_name} ({membership.get('position')})")
                        else:
                            # 这种情况理论上已经被预处理清理了，但保留日志以防万一
                            logger.debug(f"  ℹ️  组织引用已被清理：{character.name} -> {org_name}")
                    except Exception as e:
                        logger.warning(f"  ❌ 向导添加组织成员失败：{character.name} - {str(e)}")
                        continue
        
        logger.info(f"📊 向导数据统计：")
        logger.info(f"  - 创建角色/组织：{len(created_characters)} 个")
        logger.info(f"  - 创建组织详情：{len(organization_name_to_obj)} 个")
        logger.info(f"  - 创建角色关系：{relationships_created} 条")
        logger.info(f"  - 创建组织成员：{members_created} 条")
        
        # 更新项目的角色数量
        project.character_count = len(created_characters)
        logger.info(f"✅ 更新项目角色数量: {project.character_count}")
        
        await db.commit()
        
        # 重新提取character对象
        created_characters = [char for char, _ in created_characters]
        
        # 发送结果
        yield await SSEResponse.send_result({
            "message": f"成功生成{len(created_characters)}个角色/组织（分{total_batches}批完成）",
            "count": len(created_characters),
            "batches": total_batches,
            "characters": [
                {
                    "id": char.id,
                    "project_id": char.project_id,
                    "name": char.name,
                    "age": char.age,
                    "gender": char.gender,
                    "is_organization": char.is_organization,
                    "role_type": char.role_type,
                    "personality": char.personality,
                    "background": char.background,
                    "appearance": char.appearance,
                    "relationships": char.relationships,
                    "organization_type": char.organization_type,
                    "organization_purpose": char.organization_purpose,
                    "organization_members": char.organization_members,
                    "traits": char.traits,
                    "created_at": char.created_at.isoformat() if char.created_at else None,
                    "updated_at": char.updated_at.isoformat() if char.updated_at else None
                } for char in created_characters
            ]
        })
        
        yield await SSEResponse.send_progress("完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("角色生成器被提前关闭")
    except Exception as e:
        logger.error(f"角色生成失败: {str(e)}")
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")


@router.post("/characters", summary="流式批量生成角色（后台任务 + SSE）")
async def generate_characters_stream(
    request: Request,
    data: Dict[str, Any],
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """向导步骤 2：批量生成角色（支持 MCP 工具增强）。跑在通用后台任务上。"""
    return await _start_wizard_job(
        request, data, kind="wizard_characters", title="向导：生成角色",
        factory=lambda db: characters_generator(data, db, user_ai_service),
    )


def _parse_high_level_outline(ai_response: str) -> dict:
    """解析AI响应为故事前提大纲对象"""
    try:
        # 清理响应文本
        cleaned_text = ai_response.strip()

        # 移除可能的markdown标记
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith('```'):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]

        # 查找JSON对象的开始和结束
        start_idx = cleaned_text.find('{')
        end_idx = cleaned_text.rfind('}')

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            # 提取JSON部分
            json_part = cleaned_text[start_idx:end_idx + 1]
        else:
            json_part = cleaned_text

        json_part = json_part.strip()

        # 尝试修复常见的JSON语法错误
        # 移除最后一个字段后的多余逗号
        import re
        json_part = re.sub(r',(\s*[}\]])', r'\1', json_part)

        logger.info(f"尝试解析JSON，长度: {len(json_part)}")
        logger.debug(f"JSON内容预览: {json_part[:500]}...")

        outline_data = json.loads(json_part)

        # 确保是字典格式
        if isinstance(outline_data, list):
            if outline_data:
                outline_data = outline_data[0]
            else:
                outline_data = {}
        elif not isinstance(outline_data, dict):
            outline_data = {"title": str(outline_data)}

        # 确保有必需字段
        if "title" not in outline_data:
            outline_data["title"] = "故事大纲"
        if "premise" not in outline_data:
            outline_data["premise"] = "待完善"

        return outline_data

    except json.JSONDecodeError as e:
        logger.error(f"故事大纲AI响应解析失败: {e}")
        return {
            "title": "AI生成的故事大纲",
            "premise": ai_response[:1000] if ai_response else "解析失败，请重新生成"
        }


async def _save_high_level_outline(
    project_id: str,
    data: dict,
    db: AsyncSession
) -> StoryOutline:
    """保存故事前提大纲到数据库（每个项目只有一条记录）"""

    # 删除该项目的旧大纲
    await db.execute(
        delete(StoryOutline).where(StoryOutline.project_id == project_id)
    )

    # 将完整数据序列化为JSON保存到content字段
    # 包含：premise, golden_finger, selling_points, power_system, main_tropes, ultimate_goal, opening_hook
    # 注意：title/theme/tone/protagonists 不再存储（避免与 Project 和 Character 表重复）
    content = json.dumps(data, ensure_ascii=False)

    # 创建新的大纲记录（title 从关联的 Project 获取）
    outline = StoryOutline(
        project_id=project_id,
        title="故事大纲",
        content=content,
        order_index=1
    )

    db.add(outline)

    return outline


async def outline_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """大纲生成流式生成器 - 生成高层故事大纲（不再生成章节）"""
    try:
        yield await SSEResponse.send_progress("开始生成高层故事大纲...", 5)
        
        project_id = data.get("project_id")
        narrative_perspective = data.get("narrative_perspective")
        target_words = data.get("target_words", 100000)
        chapter_count = data.get("chapter_count", 10)  # 作为预估章节数提示
        requirements = data.get("requirements", "")
        provider = data.get("provider")
        model = data.get("model")
        enable_mcp = data.get("enable_mcp", False)  # 默认禁用MCP，需要用户明确选择
        selected_plugins = data.get("selected_plugins", [])  # 选择的插件列表
        user_id = data.get("user_id")  # 从中间件注入
        # R8 拆书参考包显式参数（任一缺省则该字段走 injector 默认）
        explicit_pack_ids = data.get("pack_ids")
        explicit_dimensions = data.get("dimensions")
        explicit_strength = data.get("strength")

        # 获取项目信息
        yield await SSEResponse.send_progress("加载项目信息...", 10)
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        # 获取角色信息
        yield await SSEResponse.send_progress("加载角色信息...", 15)
        result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = result.scalars().all()

        # 筛选主角（role_type 包含"主角"）
        protagonists = [char for char in characters if is_protagonist_role(char.role_type)]

        # 构建主角详细信息（完整信息，用于强制约束）
        protagonists_info_parts = []
        for idx, char in enumerate(protagonists, 1):
            parts = [f"【主角{idx}】{char.name}"]
            if char.personality:
                parts.append(f"  - 性格：{char.personality[:200]}")
            if char.background:
                parts.append(f"  - 背景：{char.background[:300]}")
            motivation = getattr(char, "motivation", None)
            initial_status = getattr(char, "initial_status", None)
            if motivation:
                parts.append(f"  - 动机：{str(motivation)[:200]}")
            if initial_status:
                parts.append(f"  - 开局处境：{str(initial_status)[:200]}")
            protagonists_info_parts.append("\n".join(parts))

        protagonists_info = "\n\n".join(protagonists_info_parts) if protagonists_info_parts else ""

        # 其他角色信息（非主角）
        other_characters = [char for char in characters if not is_protagonist_role(char.role_type)]
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): {char.personality[:100] if char.personality else '暂无描述'}"
            for char in other_characters
        ])
        
        # MCP工具增强：收集大纲设计参考资料
        mcp_reference_materials = ""
        if enable_mcp and user_id:
            try:
                yield await SSEResponse.send_progress("🔍 尝试使用MCP工具收集参考资料...", 18)
                
                # 构建资料收集查询（强制工具调用）
                planning_query = f"""请使用搜索工具查询以下内容：

类型：{project.genre}
主题：{project.theme}
查询目标：该类型小说的经典情节结构、冲突设计、场景元素

要求：
1. 必须调用搜索工具（不要凭空编造）
2. 搜索关键词要具体明确
3. 返回搜索结果的原始内容（不要总结）

示例查询："{project.genre}小说经典情节结构" 或 "{project.theme}主题冲突设计"

请立即调用工具。"""
                
                # 调用MCP增强的AI（非流式，最多2轮工具调用）
                # 强制使用工具（tool_choice="required"）确保启用MCP时必定触发工具调用
                planning_result = await user_ai_service.generate_text_with_mcp(
                    prompt=planning_query,
                    user_id=user_id,
                    db_session=db,
                    enable_mcp=True,
                    selected_plugins=selected_plugins,
                    max_tool_rounds=2,
                    tool_choice="required",  # 强制工具调用
                    provider=None,
                    model=None
                )

                # 提取参考资料
                mcp_reference_materials = planning_result.get("content", "")
                tool_calls_made = planning_result.get("tool_calls_made", 0)
                tools_used = planning_result.get("tools_used", [])

                # 记录原始长度
                raw_chars = len(mcp_reference_materials)

                # 截断参考资料（避免 Prompt 过长，影响 LLM 响应速度）
                max_length = 2000
                if len(mcp_reference_materials) > max_length:
                    logger.warning(f"⚠️ [wizard_outline] 参考资料过长（{raw_chars}字符），截断至{max_length}字符")
                    mcp_reference_materials = mcp_reference_materials[:max_length] + "\n...(内容过长已截断)"

                used_chars = len(mcp_reference_materials)

                # 统一日志：记录参考资料使用情况
                logger.info(
                    f"[MCP] context=wizard_outline_planning user_id={user_id} "
                    f"plugins={selected_plugins} tools_used={tools_used} "
                    f"raw_chars={raw_chars} used_chars={used_chars} "
                    f"tool_calls={tool_calls_made}"
                )

                if tool_calls_made > 0:
                    yield await SSEResponse.send_progress(
                        f"✅ MCP工具调用成功（{tool_calls_made}次，收集{raw_chars}字符）",
                        25
                    )
                else:
                    # 强制模式下仍未触发工具，记录警告
                    logger.warning(
                        f"⚠️ [wizard_outline] MCP强制模式下工具未触发 "
                        f"user_id={user_id} plugins={selected_plugins}"
                    )
                    yield await SSEResponse.send_progress("⚠️ MCP工具未触发（可能模型不支持）", 25)
                    
            except Exception as e:
                logger.warning(f"MCP工具调用失败（降级处理）: {e}")
                yield await SSEResponse.send_progress("⚠️ MCP工具暂时不可用，使用基础模式", 25)
        
        # 准备生成高层大纲
        yield await SSEResponse.send_progress("准备生成高层故事大纲...", 30)

        # 【修改】只查询现有世界规则,不再生成(规则已在世界观阶段生成)
        from app.services.world_rule_service import world_rule_service
        yield await SSEResponse.send_progress("📋 加载世界规则...", 32)

        # 构建查询文本（用于智能检索世界规则）
        query_text = f"{project.theme or ''} {project.genre or ''}"

        # 增强世界规则（使用语义检索）
        enhanced_world_rules = await world_rule_service.generate_rules_summary_with_search(
            db, project.id, query_text, limit=5
        )
        final_world_rules = project.world_rules or "未设定"
        if enhanced_world_rules:
            final_world_rules = f"{final_world_rules}\n\n{enhanced_world_rules}"

        # 拆书参考注入（R3）：把已挂载参考包的方法论/结构/世界观/角色塑造拼到 references
        # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
        ref_pack_block = ""
        try:
            from app.services.reference_pack_injector import ReferencePackInjector
            injector = ReferencePackInjector()
            block = await injector.build_reference_block(
                db,
                project_id,
                scene="story_outline",
                # R8：用户在前端 ReferencePackSelector 显式指定时优先使用
                pack_ids=explicit_pack_ids,
                dimensions=explicit_dimensions,
                strength=explicit_strength,
                anchor_query=(
                    f"{project.theme or ''} {project.genre or ''} "
                    f"{project.description or ''}"
                ).strip() or "故事大纲",
            )
            if not block.is_empty:
                ref_pack_block = block.user_segment
                yield await SSEResponse.send_progress(
                    f"📚 已注入拆书参考包 {len(block.used_packs)} 个"
                    f"（{','.join(block.used_dimensions)}）",
                    33,
                )
        except ValueError:
            # 项目未挂载参考包 / 全部未就绪 → 优雅跳过，不影响主流程
            pass
        except Exception as e:  # pragma: no cover - 防御性兜底
            logger.warning(f"[R3-故事大纲] 拆书参考注入失败（已跳过）: {e}")

        # 合并 MCP 与拆书参考（保持 MCP 在前，拆书参考紧随其后）
        combined_references = mcp_reference_materials or ""
        if ref_pack_block:
            combined_references = (
                f"{combined_references}\n\n{ref_pack_block}".strip()
                if combined_references
                else ref_pack_block
            )

        # 构建高层大纲提示词（包含 MCP 参考资料、拆书参考包注入和主角信息）
        prompt = prompt_service.get_complete_outline_prompt(
            title=project.title,
            theme=project.theme or "未设定",
            genre=project.genre or "通用",
            chapter_count=chapter_count,
            narrative_perspective=narrative_perspective,
            target_words=target_words,
            description=project.description or "",
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=final_world_rules,
            characters_info=characters_info or "暂无其他角色",
            protagonists_info=protagonists_info,
            requirements=requirements or "",
            mcp_references=combined_references
        )
        prompt = prompt_service.apply_project_generation_prompt(
            prompt,
            project.generation_prompt or ""
        )
        
        yield await SSEResponse.send_progress("正在调用AI生成高层大纲...", 35)
        
        # 流式生成高层大纲
        accumulated_text = ""
        chunk_count = 0
        
        try:
            async for chunk in user_ai_service.generate_text_stream(
                prompt=prompt,
                provider=provider,
                model=model
            ):
                chunk_count += 1
                accumulated_text += chunk
                
                # 发送内容块
                yield await SSEResponse.send_chunk(chunk)
                
                # 定期更新进度
                if chunk_count % 5 == 0:
                    progress = min(35 + (chunk_count // 5), 70)
                    yield await SSEResponse.send_progress(f"生成中... ({len(accumulated_text)}字符)", progress)
                
                # 每20个块发送心跳
                if chunk_count % 20 == 0:
                    yield await SSEResponse.send_heartbeat()
        except Exception as stream_error:
            logger.error(f"流式生成过程中发生错误: {str(stream_error)}")
            logger.error(f"  - 错误类型: {type(stream_error).__name__}")
            logger.error(f"  - 已接收chunk数量: {chunk_count}")
            logger.error(f"  - 已累积文本长度: {len(accumulated_text)}")
            
            # 如果是HTTP错误，提供更具体的错误信息
            if hasattr(stream_error, 'response'):
                status_code = getattr(stream_error.response, 'status_code', 'unknown')
                logger.error(f"  - HTTP状态码: {status_code}")
            
            # 重新抛出异常，让外层异常处理器处理
            raise stream_error
        
        # 解析AI响应为高层大纲对象
        yield await SSEResponse.send_progress("解析AI返回结果...", 75)
        
        # 使用 _parse_high_level_outline 解析
        outline_data = _parse_high_level_outline(accumulated_text)
        
        # 保存高层大纲到数据库
        yield await SSEResponse.send_progress("保存到数据库...", 85)
        
        # 使用 _save_high_level_outline 保存
        outline = await _save_high_level_outline(project_id, outline_data, db)
        
        # 更新项目向导状态
        project.wizard_step = 3
        project.wizard_status = "incomplete"

        await db.commit()
        await db.refresh(outline)
        await db.refresh(project)

        logger.info(f"故事前提大纲生成完成 - 项目: {project_id}")

        # 发送最终结果（下一步固定为向导步骤 4：剧情线生成，见 plot_lines_generator）
        yield await SSEResponse.send_result({
            "message": "故事前提大纲生成完成",
            "outline": {
                "id": outline.id,
                "project_id": outline.project_id,
                "title": outline.title,
                "content": outline.content,
                "order_index": outline.order_index,
                "created_at": outline.created_at.isoformat() if outline.created_at else None,
                "updated_at": outline.updated_at.isoformat() if outline.updated_at else None
            },
            "total_chapters": 1,
        })
        
        yield await SSEResponse.send_progress("完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("大纲生成器被提前关闭")
    except Exception as e:
        logger.error(f"大纲生成失败: {str(e)}")
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")


@router.post("/outline", summary="流式生成完整大纲（后台任务 + SSE）")
async def generate_outline_stream(
    request: Request,
    data: Dict[str, Any],
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """向导步骤 3：高层故事大纲（支持 MCP 工具增强）。跑在通用后台任务上。"""
    # 记录用户AI服务配置信息（用于排查）
    logger.info(f"故事大纲生成开始 - 用户: {getattr(request.state, 'user_id', 'unknown')}")
    logger.info(f"  - AI提供商: {user_ai_service.api_provider}")
    logger.info(f"  - 默认模型: {user_ai_service.default_model}")
    logger.info(f"  - 请求参数: provider={data.get('provider')}, model={data.get('model')}")
    return await _start_wizard_job(
        request, data, kind="wizard_outline", title="向导：生成故事大纲",
        factory=lambda db: outline_generator(data, db, user_ai_service),
    )


class _PlotPipelineError(Exception):
    """剧情线流水线里可预期的业务失败，带 SSE 错误码"""

    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code


# 客户端断开后仍在跑的流水线任务：保持强引用，避免被 GC 中途回收
_DETACHED_PIPELINE_TASKS: set = set()


async def _pipeline_session_factory(user_id: str):
    """后台流水线专用的 session 工厂：请求级 session 会在连接断开时被关闭，不能复用"""
    from app.database import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = await get_engine(user_id)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _plot_lines_pipeline(
    data: Dict[str, Any],
    outline_id: str,
    user_ai_service: AIService,
    emit,
) -> Dict[str, Any]:
    """剧情线完整流水线：主线 → 对齐章节数 → 支线 → wizard_step → 骨架预览。

    用独立 session 跑在后台任务里，不依赖请求连接：浏览器中途断开也会完整写库，
    不会留下"主线已建、章节数没对齐、没有支线、wizard_step 停在 3"的半成品。
    emit(message, progress) 只往队列塞进度，没人消费也不影响执行。
    """
    from app.services.bridge_slot_planner import (
        BridgePlanningPreconditionError,
        compute_bridge_slots,
        parse_plot_line,
        sub_budget_cap,
    )
    from app.services.plot_generation_service import PlotGenerationService

    project_id = data.get("project_id")
    chapter_count = int(data.get("chapter_count") or 0)
    sub_line_count = int(data.get("sub_line_count", 2) or 0)
    requirements = (data.get("requirements") or "").strip()
    user_id = data.get("user_id")

    session_factory = await _pipeline_session_factory(user_id)
    async with session_factory() as db:
        service = PlotGenerationService(user_ai_service)
        common = dict(
            db=db, project_id=project_id, outline_id=outline_id,
            custom_prompt=requirements or None,
            enable_mcp=bool(data.get("enable_mcp", False)),
            selected_plugins=data.get("selected_plugins") or [],
            user_id=user_id,
            pack_ids=data.get("pack_ids"), dimensions=data.get("dimensions"), strength=data.get("strength"),
            provider=data.get("provider"), model=data.get("model"),
        )

        emit(f"生成主线（全书 {chapter_count} 章）...", 10)
        main_lines = await service.generate_plot_lines(line_type="main", count=1, chapter_count=chapter_count, **common)
        if not main_lines:
            raise _PlotPipelineError("主线生成失败：AI 未返回剧情线", 500)
        main = main_lines[0]
        main.estimated_chapters = chapter_count
        await db.commit()
        await db.refresh(main)
        emit(f"主线《{main.title}》完成，预计 {chapter_count} 章", 55)

        sub_lines = []
        cap = sub_budget_cap(chapter_count, sub_line_count)
        if sub_line_count > 0:
            emit(f"生成 {sub_line_count} 条支线（每条篇幅预算 ≤ {cap} 章，锚定主线节点）...", 60)
            sub_lines = await service.generate_plot_lines(
                line_type="sub", count=sub_line_count, based_on_lines=[main.id], sub_budget_cap=cap, **common
            )

        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()
        project.wizard_step = 4
        project.wizard_status = "incomplete"
        await db.commit()

        emit("计算桥段骨架预览...", 92)
        all_lines = [parse_plot_line(l) for l in (await db.execute(
            select(PlotLine).where(PlotLine.project_id == project_id).order_by(PlotLine.order_index)
        )).scalars().all()]
        try:
            plan = compute_bridge_slots(all_lines)
        except BridgePlanningPreconditionError as exc:
            raise _PlotPipelineError(f"剧情线已生成但不满足桥段规划前置条件：{exc}", 400) from exc

        main_data = parse_plot_line(main)
        message = "剧情线生成完成"
        if plan.total_chapters != chapter_count:
            # 桥段按 4 章取整（每节点至少 1 个桥段），实际章数可能与用户填的不同——必须明示，别让用户以为还是原数
            message += f"（桥段按每桥段 4 章取整：实际规划 {plan.total_chapters} 章，共 {plan.total_bridges} 个桥段）"
            emit(f"每桥段 4 章取整：实际规划 {plan.total_chapters} 章（你填的是 {chapter_count} 章）", 96)
        return {
            "message": message,
            "main_line": {
                "id": main.id, "title": main.title,
                "estimated_chapters": main.estimated_chapters, "beat_count": len(main_data.beats),
            },
            "sub_lines": [{"id": s.id, "title": s.title} for s in sub_lines],
            "plan_preview": {"total_bridges": plan.total_bridges, "total_chapters": plan.total_chapters},
            "chapter_count_requested": chapter_count,
            "sub_budget_cap": cap,
            "line_budgets": plan.to_dict()["line_budgets"],
        }


async def plot_lines_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """向导步骤 4：生成 1 条主线 + N 条支线（含节点）。主线预计章节数固定为项目章节数。

    前置（不满足直接 error，不做退化）：项目存在、有 active 故事大纲、项目内尚无主线。
    前置校验用请求 session 快速失败；通过后流水线转入后台任务，本生成器只负责转发进度与心跳。
    """
    project_id = data.get("project_id")
    chapter_count = int(data.get("chapter_count") or 0)

    try:
        yield await SSEResponse.send_progress("校验前置条件...", 3)
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        if chapter_count < 1:
            yield await SSEResponse.send_error("chapter_count 必须 ≥ 1", 400)
            return
        outline = (await db.execute(
            select(StoryOutline)
            .where(StoryOutline.project_id == project_id, StoryOutline.is_active == True)  # noqa: E712
            .order_by(StoryOutline.version.desc()).limit(1)
        )).scalar_one_or_none()
        if not outline:
            yield await SSEResponse.send_error("请先完成故事大纲，再生成剧情线", 400)
            return
        existing_main = (await db.execute(
            select(PlotLine.id).where(PlotLine.project_id == project_id, PlotLine.line_type == "main").limit(1)
        )).scalar_one_or_none()
        if existing_main:
            yield await SSEResponse.send_error("项目已存在主线剧情线，工程化流水线要求且仅要求一条主线", 400)
            return
    except Exception as e:
        logger.error(f"剧情线前置校验失败: {str(e)}", exc_info=True)
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")
        return

    queue: "asyncio.Queue" = asyncio.Queue()

    def emit(message: str, progress: int) -> None:
        queue.put_nowait((message, progress))

    async def run_pipeline():
        try:
            return await _plot_lines_pipeline(data, outline.id, user_ai_service, emit)
        finally:
            queue.put_nowait(None)  # 结束哨兵，让转发循环及时退出

    task = asyncio.create_task(run_pipeline())
    _DETACHED_PIPELINE_TASKS.add(task)
    task.add_done_callback(_DETACHED_PIPELINE_TASKS.discard)

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield await SSEResponse.send_heartbeat()
                continue
            if item is None:
                break
            yield await SSEResponse.send_progress(*item)

        result = await task
        yield await SSEResponse.send_result(result)
        yield await SSEResponse.send_progress("完成!", 100, "success")
        yield await SSEResponse.send_done()
    except (GeneratorExit, asyncio.CancelledError):
        # 连接断开：不取消 task，让流水线在后台跑完并写库；前端已看不到结果，改由日志记录
        logger.warning(
            f"剧情线生成器被提前关闭（客户端断开），后台流水线继续执行 - 项目: {project_id}, 任务已完成: {task.done()}"
        )
        task.add_done_callback(_log_detached_pipeline_result)
        raise
    except _PlotPipelineError as e:
        logger.error(f"剧情线生成失败: {e.message}")
        yield await SSEResponse.send_error(e.message, e.code)
    except Exception as e:
        logger.error(f"剧情线生成失败: {str(e)}", exc_info=True)
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")


def _log_detached_pipeline_result(task: "asyncio.Task") -> None:
    """后台流水线结束时记一条日志：连接断开后前端看不到结果，只能靠日志确认"""
    if task.cancelled():
        logger.warning("剧情线后台流水线被取消")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"剧情线后台流水线失败: {exc}")
    else:
        result = task.result() or {}
        main = result.get("main_line") or {}
        logger.info(f"剧情线后台流水线完成 - 主线《{main.get('title')}》，支线 {len(result.get('sub_lines') or [])} 条")


@router.post("/plot-lines", summary="流式生成剧情线（向导步骤 4，后台任务 + SSE）")
async def generate_plot_lines_stream(
    request: Request,
    data: Dict[str, Any],
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """向导步骤 4：主线 ×1（预计章节数 = chapter_count）+ 支线 ×sub_line_count，含节点。跑在通用后台任务上。"""
    logger.info(f"剧情线生成开始 - 用户: {getattr(request.state, 'user_id', 'unknown')}, 项目: {data.get('project_id')}")
    return await _start_wizard_job(
        request, data, kind="wizard_plot_lines", title="向导：生成剧情线",
        factory=lambda db: plot_lines_generator(data, db, user_ai_service),
    )


async def cleanup_wizard_generator(
    project_id: str,
    user_id: str,
    db: AsyncSession
) -> AsyncGenerator[str, None]:
    """清理向导数据生成器 - 删除项目的角色、大纲、章节和记忆"""
    from app.services.memory_service import memory_service
    from app.models.memory import StoryMemory
    
    try:
        yield await SSEResponse.send_progress("开始清理向导数据...", 10)
        
        # 验证项目存在
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        # 统计要删除的数据
        yield await SSEResponse.send_progress("统计数据...", 20)
        
        # 统计角色
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = characters_result.scalars().all()
        characters_count = len(characters)
        
        # 统计大纲
        outlines_result = await db.execute(
            select(StoryOutline).where(StoryOutline.project_id == project_id)
        )
        outlines = outlines_result.scalars().all()
        outlines_count = len(outlines)

        # 统计剧情线
        plot_lines_result = await db.execute(
            select(PlotLine).where(PlotLine.project_id == project_id)
        )
        plot_lines = plot_lines_result.scalars().all()
        plot_lines_count = len(plot_lines)

        # 统计剧情卡片
        plot_cards_result = await db.execute(
            select(PlotCard).where(PlotCard.project_id == project_id)
        )
        plot_cards = plot_cards_result.scalars().all()
        plot_cards_count = len(plot_cards)

        # 统计章纲
        chapter_outlines_result = await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id)
        )
        chapter_outlines = chapter_outlines_result.scalars().all()
        chapter_outlines_count = len(chapter_outlines)

        # 统计桥段（剧情线的下游产物，重跑上游节点时必须一并删除）
        from app.models.plot_bridge import PlotBridge
        plot_bridges_result = await db.execute(
            select(PlotBridge).where(PlotBridge.project_id == project_id)
        )
        plot_bridges = plot_bridges_result.scalars().all()
        plot_bridges_count = len(plot_bridges)
        
        # 统计章节
        chapters_result = await db.execute(
            select(Chapter).where(Chapter.project_id == project_id)
        )
        chapters = chapters_result.scalars().all()
        chapters_count = len(chapters)
        
        # 统计记忆
        memories_result = await db.execute(
            select(StoryMemory).where(StoryMemory.project_id == project_id)
        )
        memories = memories_result.scalars().all()
        memories_count = len(memories)
        
        yield await SSEResponse.send_progress(
            f"找到 {characters_count} 个角色，{outlines_count} 个大纲，{plot_lines_count} 条剧情线，{plot_bridges_count} 个桥段，{plot_cards_count} 张剧情卡片，{chapter_outlines_count} 个章纲，{chapters_count} 个章节，{memories_count} 条记忆",
            30
        )
        
        # 1. 清理记忆数据（关系数据库）
        if memories_count > 0:
            yield await SSEResponse.send_progress("清理记忆数据...", 40)
            for memory in memories:
                await db.delete(memory)
            
            # 清理向量数据库
            try:
                await memory_service.delete_project_memories(
                    user_id=user_id,
                    project_id=project_id
                )
                logger.info(f"✅ 已清理项目{project_id[:8]}的{memories_count}条记忆向量")
            except Exception as e:
                logger.warning(f"⚠️ 向量记忆清理失败: {str(e)}")
        
        # 2. 删除章节
        if chapters_count > 0:
            yield await SSEResponse.send_progress("删除章节...", 60)
            for chapter in chapters:
                await db.delete(chapter)

        # 3. 删除章纲
        if chapter_outlines_count > 0:
            yield await SSEResponse.send_progress("删除章纲...", 66)
            for chapter_outline in chapter_outlines:
                await db.delete(chapter_outline)

        # 4. 删除剧情卡片
        if plot_cards_count > 0:
            yield await SSEResponse.send_progress("删除剧情卡片...", 70)
            for plot_card in plot_cards:
                await db.delete(plot_card)

        # 4.5 删除桥段（先于剧情线，避免 FK SET NULL 留下孤儿骨架）
        if plot_bridges_count > 0:
            yield await SSEResponse.send_progress("删除桥段骨架...", 72)
            for plot_bridge in plot_bridges:
                await db.delete(plot_bridge)

        # 5. 删除剧情线
        if plot_lines_count > 0:
            yield await SSEResponse.send_progress("删除剧情线...", 74)
            for plot_line in plot_lines:
                await db.delete(plot_line)

        # 6. 删除大纲
        if outlines_count > 0:
            yield await SSEResponse.send_progress("删除大纲...", 78)
            for outline in outlines:
                await db.delete(outline)

        # 7. 删除角色和关系
        if characters_count > 0:
            yield await SSEResponse.send_progress("删除角色和关系...", 82)
            
            # 删除角色关系
            await db.execute(
                delete(CharacterRelationship).where(
                    or_(
                        CharacterRelationship.character_from_id.in_([c.id for c in characters]),
                        CharacterRelationship.character_to_id.in_([c.id for c in characters]),
                    )
                )
            )
            
            # 删除组织成员关系
            await db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.character_id.in_([c.id for c in characters])
                )
            )
            
            # 删除组织
            await db.execute(
                delete(Organization).where(
                    Organization.character_id.in_([c.id for c in characters if c.is_organization])
                )
            )
            
            # 删除角色
            for character in characters:
                await db.delete(character)
        
        # 8. 重置项目统计
        yield await SSEResponse.send_progress("重置项目统计...", 90)
        project.character_count = 0
        project.current_words = 0
        
        await db.commit()
        
        yield await SSEResponse.send_progress("清理完成!", 100)
        
        # 发送结果
        yield await SSEResponse.send_result({
            "message": "向导数据清理完成",
            "deleted": {
                "characters": characters_count,
                "outlines": outlines_count,
                "plot_lines": plot_lines_count,
                "plot_bridges": plot_bridges_count,
                "plot_cards": plot_cards_count,
                "chapter_outlines": chapter_outlines_count,
                "chapters": chapters_count,
                "memories": memories_count
            }
        })
        
        yield await SSEResponse.send_done()
        
    except Exception as e:
        logger.error(f"清理向导数据失败: {str(e)}")
        yield await SSEResponse.send_error(f"清理失败: {str(e)}")


@router.post("/cleanup/{project_id}", summary="清理向导数据")
async def cleanup_wizard_data_stream(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    清理项目的向导数据（角色、大纲、章节、记忆）
    """
    # 获取用户ID
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    logger.info(f"开始清理项目{project_id}的向导数据 - 用户: {user_id}")
    
    return create_sse_response(cleanup_wizard_generator(project_id, user_id, db))
