"""AI 生成单个组织（2026-09-11 从 api/organizations.py 的 generate 端点抽出，供后台任务 runner 调用）。

过程追踪：各步骤用 stage_scope 标注；世界规则语义检索（WorldRuleService）/ MCP 工具调用 / LLM 进度由
共享入口自动上报 reference / tool_call / llm 事件，这里不重复发。
服务层只抛 ValueError（面向用户的可读提示）或底层异常，由调用方转 HTTP 或任务 error 事件。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.models.project import Project
from app.models.relationship import Organization
from app.schemas.character import CharacterResponse
from app.schemas.relationship import OrganizationGenerateRequest
from app.services.ai_jobs import AIJob, Runner
from app.services.ai_service import AIService
from app.services.generation_trace import stage_scope
from app.services.prompt_service import prompt_service
from app.utils.json_cleaner import clean_and_parse_json

logger = get_logger(__name__)

MCP_REFERENCE_MAX_CHARS = 2000


async def _collect_mcp_reference(
    db: AsyncSession, *, user_id: str, project: Project, request: OrganizationGenerateRequest
) -> str:
    """强控工具流：优先用搜索类工具查资料；没有可用工具返回空串（调用方标为跳过）。"""
    from app.services.mcp_tool_service import mcp_tool_service

    tool_query = f"{project.theme or ''} {project.genre or ''} {request.organization_type or '组织'} 组织设定 世界观 背景资料"
    available_tools = await mcp_tool_service.get_user_enabled_tools(
        user_id=user_id, db_session=db, plugin_names=request.selected_plugins
    )
    search_tool = next((t for t in available_tools if "search" in t["function"]["name"].lower()), None)
    if search_tool is None:
        logger.warning("⚠️ [组织生成] 未找到可用的搜索工具（插件：%s）", request.selected_plugins)
        return ""
    tool_name = search_tool["function"]["name"]
    if "_" in tool_name:
        plugin_name, actual_tool_name = tool_name.split("_", 1)
    else:
        plugin_name, actual_tool_name = "unknown", tool_name
    logger.info("📞 [组织生成] 调用工具：%s，查询：%s", tool_name, tool_query)
    result = await mcp_tool_service._call_tool_with_retry(
        user_id=user_id, plugin_name=plugin_name, tool_name=actual_tool_name,
        arguments={"query": tool_query, "numResults": 5}, timeout=60.0,
    )
    return str(result) if result else ""


async def generate_organization_for_project(
    db: AsyncSession,
    *,
    ai_service: AIService,
    user_id: str,
    project: Project,
    request: OrganizationGenerateRequest,
) -> Character:
    """生成并落库一个组织（Character(is_organization) + Organization 详情 + 生成历史），返回已 refresh 的 Character。"""
    async with stage_scope("context", "整理项目上下文 / 已有角色 / 世界规则") as st:
        existing_characters = (await db.execute(
            select(Character).where(Character.project_id == request.project_id).order_by(Character.created_at.desc())
        )).scalars().all()
        character_list: list[str] = []
        organization_list: list[str] = []
        for c in existing_characters[:10]:  # 最多显示10个
            if c.is_organization:
                organization_list.append(f"- {c.name} [{c.organization_type or '组织'}]")
            else:
                character_list.append(f"- {c.name}（{c.role_type or '未知'}）")
        existing_info = ""
        if character_list:
            existing_info += "\n已有角色：\n" + "\n".join(character_list)
        if organization_list:
            existing_info += "\n\n已有组织：\n" + "\n".join(organization_list)

        # 详细世界规则（语义检索；WorldRuleService 会自动上报 reference 事件）；失败不中断
        from app.services.world_rule_service import world_rule_service

        world_rules_summary = ""
        try:
            query_text = f"{project.theme or ''} {project.genre or ''} {request.organization_type or ''}"
            world_rules_summary = await world_rule_service.generate_rules_summary_with_search(
                db, request.project_id, query_text, limit=10
            )
        except Exception as rule_error:  # noqa: BLE001 - 世界规则缺失不影响生成
            logger.warning("⚠️ [组织生成] 加载世界规则失败: %s", rule_error)
            world_rules_summary = ""

        project_context_parts = [f"""
项目信息：
- 书名：{project.title}
- 主题：{project.theme or '未设定'}
- 类型：{project.genre or '未设定'}
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}
- 世界规则：{project.world_rules or '未设定'}
{existing_info}
"""]
        if world_rules_summary:
            project_context_parts.append(f"""
【详细世界规则】
以下是本作品的详细世界规则设定，请确保组织设定符合这些规则：

{world_rules_summary}
""")
        user_input = f"""
用户要求：
- 组织名称：{request.name or '请AI生成'}
- 组织类型：{request.organization_type or '请AI根据世界观决定'}
- 背景设定：{request.background or '无特殊要求'}
- 其他要求：{request.requirements or '无'}
"""
        st.note(existing_characters=len(existing_characters), world_rules_chars=len(world_rules_summary))

    # 【强控工具流】启用 MCP 时先调用工具收集资料；失败不中断
    reference_materials = ""
    if request.enable_mcp and request.selected_plugins:
        async with stage_scope("mcp", "MCP 工具检索参考资料") as st:
            try:
                reference_materials = await _collect_mcp_reference(db, user_id=user_id, project=project, request=request)
            except Exception as tool_error:  # noqa: BLE001 - 工具失败不中断生成
                logger.error("❌ [组织生成] MCP工具调用失败：%s", tool_error)
                st.skip(f"工具调用失败：{str(tool_error)[:80]}")
            else:
                if reference_materials:
                    st.note(raw_chars=len(reference_materials))
                else:
                    st.skip("未找到可用的搜索工具或工具返回为空")

    if reference_materials:
        raw_chars = len(reference_materials)
        if raw_chars > MCP_REFERENCE_MAX_CHARS:
            logger.warning("⚠️ [organization_generation] 参考资料过长（%d字符），截断至%d字符", raw_chars, MCP_REFERENCE_MAX_CHARS)
            used_reference = reference_materials[:MCP_REFERENCE_MAX_CHARS] + "\n...(内容过长已截断)"
        else:
            used_reference = reference_materials
        logger.info(
            "[MCP] context=organization_generation user_id=%s plugins=%s tools_used=['search'] raw_chars=%d used_chars=%d tool_calls=1",
            user_id, request.selected_plugins, raw_chars, len(used_reference),
        )
        project_context_parts.append(f"""
【参考资料】
以下是通过MCP工具收集的相关参考资料，可以作为灵感来源：

{used_reference}
""")

    prompt = prompt_service.get_single_organization_prompt(
        project_context="\n".join(project_context_parts), user_input=user_input
    )

    async with stage_scope("llm", "模型生成组织设定") as st:
        logger.info(
            "🎯 开始为项目 %s 生成组织：名=%s 类型=%s 提供商=%s 模型=%s prompt=%d 字符",
            request.project_id, request.name or "AI生成", request.organization_type or "AI决定",
            getattr(ai_service, "api_provider", "?"), getattr(ai_service, "default_model", "?"), len(prompt),
        )
        ai_response = await ai_service.generate_text(prompt=prompt, provider=None, model=None)
        if not isinstance(ai_response, dict):
            ai_response = {"content": str(ai_response or "")}
        ai_content = ai_response.get("content") or ""
        if not ai_content.strip():
            raise ValueError("AI服务返回空响应。请检查AI配置和网络连接。")
        st.note(content_chars=len(ai_content))

    async with stage_scope("persist", "解析并写入组织 / 详情") as st:
        try:
            organization_data = clean_and_parse_json(ai_content, expected_type="object", log_prefix="[组织生成]")
        except json.JSONDecodeError as e:
            raise ValueError(f"AI返回的内容无法解析为JSON。错误：{e}") from e

        # 组织也是角色的一种
        character = Character(
            project_id=request.project_id,
            name=organization_data.get("name", request.name or "未命名组织"),
            is_organization=True,
            role_type="supporting",  # 组织通常作为配角
            personality=organization_data.get("personality", ""),
            background=organization_data.get("background", ""),
            appearance=organization_data.get("appearance", ""),
            organization_type=organization_data.get("organization_type"),
            organization_purpose=organization_data.get("organization_purpose"),
            organization_members=json.dumps(organization_data.get("organization_members", []), ensure_ascii=False),
            traits=json.dumps(organization_data.get("traits", []), ensure_ascii=False),
        )
        db.add(character)
        await db.flush()
        logger.info("✅ 组织角色创建成功：%s (ID: %s)", character.name, character.id)

        organization = Organization(
            character_id=character.id,
            project_id=request.project_id,
            member_count=0,
            power_level=organization_data.get("power_level", 50),
            location=organization_data.get("location"),
            motto=organization_data.get("motto"),
            color=organization_data.get("color"),
        )
        db.add(organization)
        await db.flush()

        db.add(GenerationHistory(
            project_id=request.project_id,
            prompt=prompt,
            generated_content=ai_content,
            model=getattr(ai_service, "default_model", None),
        ))
        await db.commit()
        await db.refresh(character)
        st.note(name=character.name, organization_type=character.organization_type or "")

    logger.info("🎉 成功为项目 %s 生成组织: %s", request.project_id, character.name)
    return character


def make_organization_runner(
    *,
    user_id: str,
    project_id: str,
    request: OrganizationGenerateRequest,
    ai_service: AIService,
    session_factory: Callable[[], Any],
) -> Runner:
    """后台任务 runner：独立会话里重新加载项目 → 生成 → 返回 CharacterResponse 字典（result 事件的 data）。"""

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if project is None:
                raise ValueError("项目不存在或已被删除")
            character = await generate_organization_for_project(
                db, ai_service=ai_service, user_id=user_id, project=project, request=request
            )
            return CharacterResponse.model_validate(character).model_dump(mode="json")

    return runner
