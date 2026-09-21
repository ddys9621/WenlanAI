"""AI 生成单个角色（2026-09-11 从 api/characters.py 的 generate 端点抽出，供后台任务 runner 调用）。

过程追踪：各步骤用 stage_scope 标注；MCP 工具调用 / 拆书参考 / LLM 进度由共享入口
（MCPToolService / ReferencePackInjector / AIService）自动上报，这里不重复发事件。
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
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.character import CharacterGenerateRequest, CharacterResponse
from app.services.ai_jobs import AIJob, Runner
from app.services.ai_service import AIService
from app.services.generation_trace import stage_scope
from app.services.prompt_service import prompt_service
from app.services.relationship_matcher import match_relationship_type
from app.utils.json_cleaner import clean_and_parse_json
from app.utils.role_type import normalize_role_type

logger = get_logger(__name__)

MCP_REFERENCE_MAX_CHARS = 2000


async def _collect_mcp_reference(
    db: AsyncSession, *, user_id: str, project: Project, request: CharacterGenerateRequest
) -> str:
    """强控工具流：优先用搜索类工具查资料；没有可用工具返回空串（调用方标为跳过）。"""
    from app.services.mcp_tool_service import mcp_tool_service

    tool_query = f"{project.theme or ''} {project.genre or ''} {request.role_type or '角色'} 角色设定 人物背景 性格特点"
    available_tools = await mcp_tool_service.get_user_enabled_tools(
        user_id=user_id, db_session=db, plugin_names=request.selected_plugins
    )
    search_tool = next((t for t in available_tools if "search" in t["function"]["name"].lower()), None)
    if search_tool is None:
        logger.warning("⚠️ [角色生成] 未找到可用的搜索工具（插件：%s）", request.selected_plugins)
        return ""
    tool_name = search_tool["function"]["name"]
    if "_" in tool_name:
        plugin_name, actual_tool_name = tool_name.split("_", 1)
    else:
        plugin_name, actual_tool_name = "unknown", tool_name
    logger.info("🔍 [角色生成] 调用工具: %s", tool_name)
    result = await mcp_tool_service._call_tool_with_retry(
        user_id=user_id, plugin_name=plugin_name, tool_name=actual_tool_name,
        arguments={"query": tool_query, "numResults": 5}, timeout=60.0,
    )
    return str(result) if result else ""


async def generate_character_for_project(
    db: AsyncSession,
    *,
    ai_service: AIService,
    user_id: str,
    project: Project,
    request: CharacterGenerateRequest,
) -> Character:
    """生成并落库一个角色（含关系 / 组织成员 / 生成历史），返回已 refresh 的 Character。"""
    async with stage_scope("context", "整理项目上下文与已有角色") as st:
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
        existing_chars_info = ""
        if character_list:
            existing_chars_info += "\n已有角色：\n" + "\n".join(character_list)
        if organization_list:
            existing_chars_info += "\n\n已有组织：\n" + "\n".join(organization_list)

        project_context_parts = [f"""
项目信息：
- 书名：{project.title}
- 主题：{project.theme or '未设定'}
- 类型：{project.genre or '未设定'}
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}
- 世界规则：{project.world_rules or '未设定'}
{existing_chars_info}
"""]
        user_input = f"""
用户要求：
- 角色名称：{request.name or '请AI生成'}
- 角色定位：{request.role_type or 'supporting'}（protagonist=主角, supporting=配角, antagonist=反派）
- 背景设定：{request.background or '无特殊要求'}
- 其他要求：{request.requirements or '无'}
"""
        st.note(existing_characters=len(existing_characters))

    # 【强控工具流】启用 MCP 时先调用工具收集资料；失败不中断
    reference_materials = ""
    if request.enable_mcp and request.selected_plugins:
        async with stage_scope("mcp", "MCP 工具检索参考资料") as st:
            try:
                reference_materials = await _collect_mcp_reference(db, user_id=user_id, project=project, request=request)
            except Exception as tool_error:  # noqa: BLE001 - 工具失败不中断生成
                logger.error("❌ [角色生成] MCP工具调用失败：%s", tool_error)
                st.skip(f"工具调用失败：{str(tool_error)[:80]}")
            else:
                if reference_materials:
                    st.note(raw_chars=len(reference_materials))
                else:
                    st.skip("未找到可用的搜索工具或工具返回为空")

    if reference_materials:
        raw_chars = len(reference_materials)
        if raw_chars > MCP_REFERENCE_MAX_CHARS:
            logger.warning("⚠️ [character_generation] 参考资料过长（%d字符），截断至%d字符", raw_chars, MCP_REFERENCE_MAX_CHARS)
            used_reference = reference_materials[:MCP_REFERENCE_MAX_CHARS] + "\n...(内容过长已截断)"
        else:
            used_reference = reference_materials
        logger.info(
            "[MCP] context=character_generation user_id=%s plugins=%s tools_used=['search'] raw_chars=%d used_chars=%d tool_calls=1",
            user_id, request.selected_plugins, raw_chars, len(used_reference),
        )
        project_context_parts.append(f"""
【参考资料】
以下是通过MCP工具收集的相关参考资料，可以作为灵感来源：

{used_reference}
""")

    prompt = prompt_service.get_single_character_prompt(
        project_context="\n".join(project_context_parts), user_input=user_input
    )

    # 拆书参考注入（R6）：archetypes / corpus 维度提供角色塑造手法参考（injector 自动上报 reference 事件）
    async with stage_scope("reference_pack", "组装拆书参考包") as st:
        try:
            from app.services.reference_pack_injector import ReferencePackInjector

            _ref_block = await ReferencePackInjector().build_reference_block(
                db, request.project_id,
                scene="character_generation",
                fallback_dimensions=("archetypes", "corpus"),
                pack_ids=request.pack_ids,
                dimensions=request.dimensions,
                strength=request.strength,
                anchor_query=f"{request.role_type or ''} {user_input}".strip() or "角色生成",
            )
        except ValueError as exc:
            st.skip(str(exc)[:80])          # 项目未挂载参考包 / 所选包未就绪
        except Exception as exc:  # noqa: BLE001 - 防御性兜底
            logger.warning("[R6-角色] 拆书参考注入失败（已跳过）: %s", exc)
            st.skip("注入失败，已跳过")
        else:
            if _ref_block.user_segment:
                prompt = (
                    f"{prompt}\n\n{_ref_block.user_segment}\n\n"
                    "请参考上述拆书中的角色塑造手法（仅作方法参考，"
                    "不要复刻原书人名与具体设定），生成本项目的角色。"
                )
                st.note(packs=len(_ref_block.used_packs), dimensions="、".join(_ref_block.used_dimensions))
            else:
                st.skip("参考包无可用内容")

    async with stage_scope("llm", "模型生成角色卡") as st:
        logger.info(
            "🎯 开始为项目 %s 生成角色：名=%s 定位=%s 提供商=%s 模型=%s prompt=%d 字符",
            request.project_id, request.name or "AI生成", request.role_type,
            getattr(ai_service, "api_provider", "?"), getattr(ai_service, "default_model", "?"), len(prompt),
        )
        ai_response = await ai_service.generate_text(prompt=prompt, provider=None, model=None)
        if not isinstance(ai_response, dict):
            ai_response = {"content": str(ai_response or "")}
        ai_content = ai_response.get("content") or ""
        if not ai_content.strip():
            raise ValueError("AI服务返回空响应。可能原因：1) API配置错误 2) 模型不支持 3) 网络问题。请检查后端日志。")
        st.note(content_chars=len(ai_content))

    async with stage_scope("persist", "解析并写入角色 / 关系 / 组织成员") as st:
        try:
            character_data = clean_and_parse_json(ai_content, expected_type="object", log_prefix="[角色生成]")
        except json.JSONDecodeError as e:
            raise ValueError(f"AI返回的内容无法解析为JSON。错误：{e}。响应内容已记录到日志，请查看后端日志排查。") from e

        traits_json = json.dumps(character_data.get("traits", []), ensure_ascii=False) if character_data.get("traits") else None
        is_organization = bool(character_data.get("is_organization", False))
        # 展示用的关系文字：模型偶尔漏掉 relationships_text 只给结构化列表，此时拼一段文字而不是把 list 写进 Text 列
        relationships_text = character_data.get("relationships_text")
        if not isinstance(relationships_text, str):
            raw_relationships = character_data.get("relationships", "")
            relationships_text = raw_relationships if isinstance(raw_relationships, str) else "；".join(
                f"{r.get('target_character_name', '?')}：{r.get('relationship_type', '')}"
                + (f"（{r['description']}）" if r.get("description") else "")
                for r in raw_relationships if isinstance(r, dict)
            )

        character = Character(
            project_id=request.project_id,
            name=character_data.get("name", request.name or "未命名角色"),
            age=str(character_data.get("age", "")),
            gender=character_data.get("gender"),
            is_organization=is_organization,
            role_type=normalize_role_type(request.role_type, "supporting"),
            personality=character_data.get("personality", ""),
            background=character_data.get("background", ""),
            appearance=character_data.get("appearance", ""),
            relationships=relationships_text,
            organization_type=character_data.get("organization_type") if is_organization else None,
            organization_purpose=character_data.get("organization_purpose") if is_organization else None,
            organization_members=json.dumps(character_data.get("organization_members", []), ensure_ascii=False) if is_organization else None,
            traits=traits_json,
        )
        db.add(character)
        await db.flush()
        logger.info("✅ 角色创建成功：%s (ID: %s, 是否组织: %s)", character.name, character.id, is_organization)

        if is_organization:
            existing_org = (await db.execute(
                select(Organization).where(Organization.character_id == character.id)
            )).scalar_one_or_none()
            if not existing_org:
                db.add(Organization(
                    character_id=character.id,
                    project_id=request.project_id,
                    member_count=0,
                    power_level=character_data.get("power_level", 50),
                    location=character_data.get("location"),
                    motto=character_data.get("motto"),
                    color=character_data.get("color"),
                ))
                await db.flush()

        created_rels = 0
        created_members = 0
        if not is_organization:
            relationships_data = character_data.get("relationships", [])
            if relationships_data and isinstance(relationships_data, list):
                for rel in relationships_data:
                    try:
                        target_name = rel.get("target_character_name")
                        if not target_name:
                            continue
                        target_char = (await db.execute(
                            select(Character).where(Character.project_id == request.project_id, Character.name == target_name)
                        )).scalars().first()
                        if not target_char:
                            logger.warning("  ⚠️  目标角色不存在：%s", target_name)
                            continue
                        existing_rel = await db.execute(
                            select(CharacterRelationship).where(
                                CharacterRelationship.project_id == request.project_id,
                                CharacterRelationship.character_from_id == character.id,
                                CharacterRelationship.character_to_id == target_char.id,
                            )
                        )
                        if existing_rel.scalars().first():
                            continue
                        relationship = CharacterRelationship(
                            project_id=request.project_id,
                            character_from_id=character.id,
                            character_to_id=target_char.id,
                            relationship_name=rel.get("relationship_type", "未知关系"),
                            intimacy_level=rel.get("intimacy_level", 50),
                            description=rel.get("description", ""),
                            started_at=rel.get("started_at"),
                            source="ai",
                        )
                        matched_type_id = await match_relationship_type(db, rel.get("relationship_type"))
                        if matched_type_id:
                            relationship.relationship_type_id = matched_type_id
                        db.add(relationship)
                        created_rels += 1
                    except Exception as rel_error:  # noqa: BLE001 - 单条关系失败不影响角色本身
                        logger.warning("  ❌ 创建关系失败：%s", rel_error)

            org_memberships = character_data.get("organization_memberships", [])
            if org_memberships and isinstance(org_memberships, list):
                for membership in org_memberships:
                    try:
                        org_name = membership.get("organization_name")
                        if not org_name:
                            continue
                        org_char = (await db.execute(
                            select(Character).where(
                                Character.project_id == request.project_id,
                                Character.name == org_name,
                                Character.is_organization == True,  # noqa: E712 - SQLAlchemy 表达式
                            )
                        )).scalars().first()
                        if not org_char:
                            logger.warning("  ⚠️  组织不存在：%s", org_name)
                            continue
                        org = (await db.execute(
                            select(Organization).where(Organization.character_id == org_char.id)
                        )).scalar_one_or_none()
                        if not org:
                            org = Organization(character_id=org_char.id, project_id=request.project_id, member_count=0)
                            db.add(org)
                            await db.flush()
                        existing_member = await db.execute(
                            select(OrganizationMember).where(
                                OrganizationMember.organization_id == org.id,
                                OrganizationMember.character_id == character.id,
                            )
                        )
                        if existing_member.scalars().first():
                            continue
                        db.add(OrganizationMember(
                            organization_id=org.id,
                            character_id=character.id,
                            position=membership.get("position", "成员"),
                            rank=membership.get("rank", 0),
                            loyalty=membership.get("loyalty", 50),
                            joined_at=membership.get("joined_at"),
                            status=membership.get("status", "active"),
                            source="ai",
                        ))
                        org.member_count += 1
                        created_members += 1
                    except Exception as org_error:  # noqa: BLE001
                        logger.warning("  ❌ 添加组织成员失败：%s", org_error)

        db.add(GenerationHistory(
            project_id=request.project_id,
            prompt=prompt,
            generated_content=json.dumps(ai_response, ensure_ascii=False),
            model=getattr(ai_service, "default_model", None),
        ))
        await db.commit()
        await db.refresh(character)
        st.note(name=character.name, relationships=created_rels, memberships=created_members)

    logger.info("🎉 成功为项目 %s 生成角色: %s", request.project_id, character.name)
    return character


def make_character_runner(
    *,
    user_id: str,
    project_id: str,
    request: CharacterGenerateRequest,
    ai_service: AIService,
    session_factory: Callable[[], Any],
) -> Runner:
    """后台任务 runner：独立会话里重新加载项目 → 生成 → 返回 CharacterResponse 字典（result 事件的 data）。"""

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if project is None:
                raise ValueError("项目不存在或已被删除")
            character = await generate_character_for_project(
                db, ai_service=ai_service, user_id=user_id, project=project, request=request
            )
            return CharacterResponse.model_validate(character).model_dump(mode="json")

    return runner
