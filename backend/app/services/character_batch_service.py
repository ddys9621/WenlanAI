"""AI 批量生成角色与组织（「角色与组织」页手动触发；向导第 2 步仍走 api/wizard_stream.characters_generator）。

和向导批量的区别：
- 已有角色 / 组织进提示词：新实体不重名，关系可以连到已有人物，成员可以加入已有组织
- 先组织后人物，每批最多 BATCH_SIZE 个：后面批次的人物能加入前面批次的新组织
- 每批生成完立刻落库：停止 / 中途失败时已完成的批次保留
过程追踪：上下文 / MCP / 仿写参考 / 每批一个 stage；世界规则检索、MCP 工具、仿写参考、LLM 进度由共享入口自动上报。
服务层只抛 ValueError（面向用户的可读提示）或底层异常，由调用方转 HTTP 或任务 error 事件。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.models.project import Project
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.character import CharacterBatchGenerateRequest
from app.services.ai_jobs import AIJob, Runner
from app.services.ai_service import AIService
from app.services.character_generation_service import MCP_REFERENCE_MAX_CHARS, collect_search_reference
from app.services.generation_trace import stage_scope
from app.services.knowledge.kb_context import traced_kb_context
from app.services.prompt_service import prompt_service
from app.services.relationship_matcher import match_relationship_type
from app.services.world_setting_context import build_world_context, world_query
from app.utils.character_names import build_name_index, normalize_name
from app.utils.json_cleaner import clean_and_parse_json
from app.utils.prompt_safety import quote_untrusted
from app.utils.role_type import normalize_role_type

logger = get_logger(__name__)

BATCH_SIZE = 3          # 每批最多几个实体：和向导一致，单次输出不至于被 Max Tokens 截断
MAX_ATTEMPTS = 2        # 每批最多请求几次（解析不出 / 没有可用实体时重试）
CAST_DETAIL_LIMIT = 30  # 已有角色里带简介的条数，其余只列名字（防重名）

ProgressFn = Callable[[str, int], None]


def plan_batches(character_count: int, organization_count: int, size: int = BATCH_SIZE) -> list[tuple[int, int]]:
    """[(人物数, 组织数), ...]：组织排在前面，每批最多 size 个。"""
    batches: list[tuple[int, int]] = []
    chars, orgs = max(character_count, 0), max(organization_count, 0)
    while chars or orgs:
        take_orgs = min(orgs, size)
        take_chars = min(chars, size - take_orgs)
        batches.append((take_chars, take_orgs))
        chars, orgs = chars - take_chars, orgs - take_orgs
    return batches


def _count_text(characters: int, organizations: int, sep: str = " · ") -> str:
    parts = (f"{characters} 个人物" if characters else "", f"{organizations} 个组织" if organizations else "")
    return sep.join(p for p in parts if p)


def batch_title(character_count: int, organization_count: int) -> str:
    return f"AI 批量生成：{_count_text(character_count, organization_count)}"


def _text(value: Any) -> str:
    return "" if value is None or isinstance(value, (dict, list)) else str(value).strip()


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _is_org(data: dict) -> bool:
    return str(data.get("is_organization")).strip().lower() in ("true", "1", "yes")


def _clip(text: Optional[str], limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _cast_block(cast: list[Character]) -> str:
    """已有角色 / 组织清单：前 CAST_DETAIL_LIMIT 个带一句简介，其余只列名字。"""
    lines = []
    for c in cast[:CAST_DETAIL_LIMIT]:
        if c.is_organization:
            head, brief = f"- {c.name}［组织·{c.organization_type or '势力'}］", c.organization_purpose or c.background
        else:
            head, brief = f"- {c.name}（{c.role_type or '未知'}）", c.personality or c.background
        lines.append(f"{head}：{_clip(brief, 60)}" if brief else head)
    rest = [c.name for c in cast[CAST_DETAIL_LIMIT:]]
    if rest:
        lines.append(f"- 另有：{'、'.join(rest)}")
    return "\n".join(lines)


async def _load_cast(db: AsyncSession, project_id: str) -> list[Character]:
    return list((await db.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at, Character.name)
    )).scalars().all())


async def _world_rules_summary(db: AsyncSession, project: Project) -> str:
    """详细世界规则 + 世界设定条目（语义检索；各服务自动上报 reference 事件）；失败不中断。"""
    world = await build_world_context(db, project, world_query(project, "人物 势力"), rule_limit=10, scene="批量角色")
    return world.detail


def _extra_blocks(world_rules: str, reference: str, kb_text: str) -> str:
    blocks = []
    if world_rules:
        blocks.append(f"【详细世界规则】\n以下是本作品的详细世界规则设定，新角色与组织要符合这些规则：\n\n{world_rules}")
    if reference:
        used = reference if len(reference) <= MCP_REFERENCE_MAX_CHARS else reference[:MCP_REFERENCE_MAX_CHARS] + "\n...(内容过长已截断)"
        blocks.append(f"【参考资料】\n以下是通过MCP工具收集的相关参考资料，可以作为灵感来源：\n\n{quote_untrusted(used, 'MCP 检索结果')}")
    if kb_text:
        blocks.append(kb_text)
    return "\n\n".join(blocks)


def _batch_prompt(project: Project, cast: list[Character], request: CharacterBatchGenerateRequest,
                  characters: int, organizations: int, extras: str) -> str:
    prompt = prompt_service.get_characters_supplement_prompt(
        title=project.title, theme=project.theme, genre=project.genre, time_period=project.world_time_period,
        location=project.world_location, atmosphere=project.world_atmosphere, rules=project.world_rules,
        existing_cast=_cast_block(cast), requirements=(request.requirements or "").strip(),
        character_count=characters, organization_count=organizations,
    )
    return f"{prompt}\n\n{extras}" if extras else prompt


def _pick_entities(data: Any, characters: int, organizations: int) -> list[dict]:
    """模型输出 → 本批要的实体：只留有名字的对象，人物 / 组织各按要的个数截取（多给的丢掉），组织在前。"""
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [data])
    if not isinstance(data, list):
        return []
    people, orgs = [], []
    for item in data:
        if isinstance(item, dict) and _text(item.get("name")):
            (orgs if _is_org(item) else people).append(item)
    return orgs[:organizations] + people[:characters]


async def _generate_batch(ai_service: AIService, prompt: str, characters: int, organizations: int,
                          label: str) -> tuple[list[dict], str]:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = await ai_service.generate_text_stream_collect(prompt=prompt, context=f"批量生成角色 {label}") or {}
        content = resp.get("content") or ""
        if resp.get("finish_reason") == "length":
            raise ValueError(f"{label}：输出被 Max Tokens 截断（已输出 {len(content)} 字），请在「设置」中调大 Max Tokens 后重试")
        if not content.strip():
            last_error = "模型没有返回内容"
        else:
            try:
                parsed = clean_and_parse_json(content, expected_type="array", log_prefix="[批量角色]")
            except json.JSONDecodeError as e:
                last_error = f"返回内容不是合法 JSON（{e.msg}）"
            else:
                entities = _pick_entities(parsed, characters, organizations)
                if entities:
                    return entities, content
                last_error = "返回内容里没有可用的角色 / 组织"
        logger.warning("[批量角色] %s 第 %d 次生成不可用：%s", label, attempt, last_error)
    raise ValueError(f"{label} 生成失败（试了 {MAX_ATTEMPTS} 次）：{last_error}")


def _new_character(project_id: str, name: str, data: dict) -> Character:
    is_org = _is_org(data)
    traits, members = data.get("traits"), data.get("organization_members")
    return Character(
        project_id=project_id,
        name=name,
        age=None if is_org else (_text(data.get("age")) or None),
        gender=None if is_org else (_text(data.get("gender")) or None),
        is_organization=is_org,
        role_type="supporting" if is_org else normalize_role_type(_text(data.get("role_type")), "supporting"),
        personality=_text(data.get("personality")),
        background=_text(data.get("background")),
        appearance=_text(data.get("appearance")),
        speech_style=None if is_org else (_text(data.get("speech_style")) or None),
        organization_type=(_text(data.get("organization_type"))[:100] or None) if is_org else None,
        organization_purpose=(_text(data.get("organization_purpose"))[:500] or None) if is_org else None,
        organization_members=json.dumps(members if isinstance(members, list) else [], ensure_ascii=False) if is_org else None,
        traits=json.dumps(traits, ensure_ascii=False) if isinstance(traits, list) and traits else None,
    )


async def _link_relationships(db: AsyncSession, project_id: str, character: Character, data: dict,
                              index: dict[str, Character]) -> int:
    """按名字连关系（目标只能是人物）；关系文字只写真正连上的，和关系表一致。"""
    rels = data.get("relationships_array")
    if not isinstance(rels, list):
        rels = data.get("relationships") if isinstance(data.get("relationships"), list) else []
    linked: set[str] = set()
    texts: list[str] = []
    for rel in rels:
        if not isinstance(rel, dict):
            continue
        target = index.get(normalize_name(_text(rel.get("target_character_name"))))
        if target is None or target is character or target.is_organization or target.id in linked:
            continue
        linked.add(target.id)
        rel_type, description = _text(rel.get("relationship_type")), _text(rel.get("description"))
        relationship = CharacterRelationship(
            project_id=project_id, character_from_id=character.id, character_to_id=target.id,
            relationship_name=rel_type or "未知关系", intimacy_level=_int(rel.get("intimacy_level"), 50, -100, 100),
            description=description, started_at=_text(rel.get("started_at")) or None, source="ai",
        )
        relationship.relationship_type_id = await match_relationship_type(db, rel_type)
        db.add(relationship)
        texts.append(f"{target.name}：{rel_type or '关系'}" + (f"（{description}）" if description else ""))
    character.relationships = "；".join(texts) or None
    return len(linked)


async def _join_organizations(db: AsyncSession, project_id: str, character: Character, data: dict,
                              index: dict[str, Character], orgs: dict[str, Organization]) -> int:
    memberships = data.get("organization_memberships")
    if not isinstance(memberships, list):
        return 0
    joined: set[str] = set()
    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        org_char = index.get(normalize_name(_text(membership.get("organization_name"))))
        if org_char is None or not org_char.is_organization or org_char.id in joined:
            continue
        joined.add(org_char.id)
        org = orgs.get(org_char.id)
        if org is None:      # 已有组织缺详情记录（手动建组织时没填势力等级等）：入会时补建
            org = orgs[org_char.id] = Organization(character_id=org_char.id, project_id=project_id, member_count=0)
            db.add(org)
            await db.flush()
        db.add(OrganizationMember(
            organization_id=org.id, character_id=character.id, position=_text(membership.get("position")) or "成员",
            rank=_int(membership.get("rank"), 0, 0, 100), loyalty=_int(membership.get("loyalty"), 50, 0, 100),
            joined_at=_text(membership.get("joined_at")) or None, status="active", source="ai",
        ))
        org.member_count = (org.member_count or 0) + 1
    return len(joined)


@dataclass
class _BatchOutcome:
    created: list[Character] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    relationships: int = 0
    memberships: int = 0


async def _persist_batch(db: AsyncSession, project_id: str, entities: list[dict], cast: list[Character]) -> _BatchOutcome:
    """落库一批实体（不提交）：和已有实体重名的跳过；关系 / 成员按名字连到已有的或本批新建的实体，引用不存在的丢掉。"""
    index = build_name_index(cast)
    outcome = _BatchOutcome()
    pending: list[tuple[Character, dict]] = []
    for data in entities:
        name = _text(data.get("name"))[:100]
        if normalize_name(name) in index:
            outcome.skipped.append(name)
            continue
        character = _new_character(project_id, name, data)
        db.add(character)
        index[normalize_name(name)] = character
        pending.append((character, data))
    await db.flush()

    orgs = {o.character_id: o for o in (await db.execute(
        select(Organization).where(Organization.project_id == project_id)
    )).scalars().all()}
    for character, data in pending:
        if character.is_organization:
            orgs[character.id] = Organization(
                character_id=character.id, project_id=project_id, member_count=0,
                power_level=_int(data.get("power_level"), 50, 0, 100), location=_text(data.get("location")) or None,
                motto=_text(data.get("motto"))[:200] or None, color=_text(data.get("color"))[:100] or None,
            )
            db.add(orgs[character.id])
    await db.flush()

    for character, data in pending:
        if not character.is_organization:
            outcome.relationships += await _link_relationships(db, project_id, character, data, index)
            outcome.memberships += await _join_organizations(db, project_id, character, data, index, orgs)
    outcome.created = [c for c, _ in pending]
    return outcome


def _summary(created: list[Character], skipped: list[str], relationships: int, memberships: int,
             request: CharacterBatchGenerateRequest) -> dict[str, Any]:
    people = sum(1 for c in created if not c.is_organization)
    made = _count_text(people, len(created) - people, "、")
    message = f"新建 {made}，关系 {relationships} 条，组织成员 {memberships} 条" if made else "没有新建角色或组织"
    if skipped:
        message += f"；跳过重名：{'、'.join(skipped)}"
    return {
        "message": message,
        "characters": people,
        "organizations": len(created) - people,
        "relationships": relationships,
        "memberships": memberships,
        "created": [
            {"id": c.id, "name": c.name, "is_organization": bool(c.is_organization), "role_type": c.role_type}
            for c in created
        ],
        "skipped": skipped,
        "requested": {"characters": request.character_count, "organizations": request.organization_count},
    }


async def generate_cast_for_project(
    db: AsyncSession,
    *,
    ai_service: AIService,
    user_id: str,
    project: Project,
    request: CharacterBatchGenerateRequest,
    on_progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    """按批生成并逐批提交，返回结果摘要（result 事件的 data）。某批失败抛 ValueError，已提交的批次保留。"""
    report = on_progress or (lambda message, pct: None)
    report("整理已有角色与世界规则…", 2)
    async with stage_scope("context", "整理世界观 / 世界规则 / 已有角色与组织") as st:
        cast = await _load_cast(db, project.id)
        world_rules = await _world_rules_summary(db, project)
        organizations = sum(1 for c in cast if c.is_organization)
        st.note(existing_characters=len(cast) - organizations, existing_organizations=organizations,
                world_rules_chars=len(world_rules))

    reference = ""
    if request.enable_mcp and request.selected_plugins:
        async with stage_scope("mcp", "MCP 工具检索参考资料") as st:
            try:
                reference = await collect_search_reference(
                    db, user_id=user_id, plugins=request.selected_plugins, log_tag="批量角色",
                    query=f"{project.theme or ''} {project.genre or ''} 人物群像 势力设定 角色原型",
                )
            except Exception as tool_error:  # noqa: BLE001 - 工具失败不中断生成
                logger.error("❌ [批量角色] MCP工具调用失败：%s", tool_error)
                st.skip(f"工具调用失败：{str(tool_error)[:80]}")
            else:
                if reference:
                    st.note(raw_chars=len(reference))
                else:
                    st.skip("未找到可用的搜索工具或工具返回为空")

    async with stage_scope("knowledge", "组装仿写参考") as st:
        kb = await traced_kb_context(db, project.id, "characters")
        if kb.text:
            st.note(source=kb.source_title, entries=len(kb.refs))
        else:
            st.skip("项目没有对标书")

    extras = _extra_blocks(world_rules, reference, kb.text)
    plan = plan_batches(request.character_count, request.organization_count)
    created: list[Character] = []
    skipped: list[str] = []
    relationships = memberships = 0
    for number, (characters, orgs) in enumerate(plan, 1):
        label = f"第 {number}/{len(plan)} 批：{_count_text(characters, orgs)}"
        report(label, 5 + 90 * (number - 1) // len(plan))
        async with stage_scope(f"batch_{number}", label) as st:
            cast = await _load_cast(db, project.id)
            prompt = _batch_prompt(project, cast, request, characters, orgs, extras)
            try:
                entities, content = await _generate_batch(ai_service, prompt, characters, orgs, label)
            except ValueError as e:
                if created:
                    raise ValueError(f"{e}；已保存前面批次的 {len(created)} 个角色 / 组织") from e
                raise
            outcome = await _persist_batch(db, project.id, entities, cast)
            db.add(GenerationHistory(
                project_id=project.id, prompt=prompt, generated_content=content,
                model=getattr(ai_service, "default_model", None),
            ))
            await db.commit()
            created += outcome.created
            skipped += outcome.skipped
            relationships += outcome.relationships
            memberships += outcome.memberships
            st.note(created="、".join(c.name for c in outcome.created) or "无",
                    relationships=outcome.relationships, memberships=outcome.memberships)
            if outcome.skipped:
                st.note(skipped="、".join(outcome.skipped))
    logger.info("🎉 项目 %s 批量生成角色完成：新建 %d 个，跳过 %d 个", project.id, len(created), len(skipped))
    return _summary(created, skipped, relationships, memberships, request)


def make_character_batch_runner(
    *,
    user_id: str,
    project_id: str,
    request: CharacterBatchGenerateRequest,
    ai_service: AIService,
    session_factory: Callable[[], Any],
) -> Runner:
    """后台任务 runner：独立会话里重新加载项目 → 分批生成落库 → 返回结果摘要（result 事件的 data）。"""

    async def runner(job: AIJob) -> dict[str, Any]:
        async with session_factory() as db:
            project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if project is None:
                raise ValueError("项目不存在或已被删除")
            return await generate_cast_for_project(
                db, ai_service=ai_service, user_id=user_id, project=project, request=request, on_progress=job.progress,
            )

    return runner
