"""章节分析抽到的人物 / 组织入库（新建或补空字段）与组织归属变动。

按章幂等：角色背景里「第N章：…」、组织成员备注里「第N章 …」每章各只留一行——重新分析同一章是替换那一行，
不再越积越多；整章替换 / 删除章节时 strip_chapter_entity_notes 把这一章的行去掉（建档记录「首次出场」保留）。
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.character import Character
from app.models.relationship import Organization, OrganizationMember
from app.utils.character_names import build_name_index
from app.utils.data_consistency import sync_organization_member_count

logger = get_logger(__name__)

# 以这些字结尾的"人物"几乎一定是机构：自动挪到组织
ORG_SUFFIXES = ("宗", "派", "门", "堂", "殿", "阁", "院", "府", "家", "帮", "盟", "会", "楼", "馆", "谷", "洞", "族",
                "庄", "寺", "观", "教", "营", "军", "城", "国")
ROLE_RANK = {"minor": 0, "supporting": 1, "major": 2, "protagonist": 3}


def _val(raw: object) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text and text.lower() not in ("null", "none", "未知") else None


def _chapter_prefix(chapter_number: int) -> str:
    return f"第{chapter_number}章："


def _note_prefix(chapter_number: int) -> str:
    return f"第{chapter_number}章 "


def _with_chapter_line(text: Optional[str], chapter_number: int, new_line: Optional[str]) -> str:
    """背景按行存：去掉本章旧行，再追加本章新行（本章建档的首行「第N章首次出场。」直接改写）。"""
    lines = [line for line in (text or "").split("\n") if line.strip()]
    created = f"第{chapter_number}章首次出场。"
    prefix = _chapter_prefix(chapter_number)
    lines = [line for line in lines if not line.startswith(prefix)]
    if new_line:
        if lines and lines[0].startswith(created):
            lines[0] = f"{created}{new_line}"
        elif not any(new_line in line for line in lines):
            lines.append(f"{prefix}{new_line}")
    return "\n".join(lines)


def _split_corrected(entity_result: dict) -> tuple[list[dict], list[dict]]:
    characters, organizations = [], list(entity_result.get("organizations") or [])
    corrected = []
    for char in entity_result.get("characters") or []:
        name = (char.get("name") or "").strip()
        if name and name[-1] in ORG_SUFFIXES:
            organizations.append({
                "name": name, "organization_type": None, "organization_purpose": None,
                "personality": char.get("personality"), "appearance": char.get("appearance"), "location": None,
                "known_members": [], "traits": char.get("traits"), "background": char.get("background"),
            })
            corrected.append(name)
        else:
            characters.append(char)
    if corrected:
        logger.info(f"🔄 自动纠正分类: {corrected} 从人物移至组织")
    return characters, organizations


def _enrich(existing: Character, data: dict, chapter_number: int, is_org: bool = False) -> bool:
    """空字段才补（不覆盖作者写的）；背景按章替换；角色定位只升不降。"""
    changed = False
    fields = ["gender", "age", "personality", "appearance", "traits"]
    fields += ["organization_type", "organization_purpose"] if is_org else ["speech_style"]
    for field in fields:
        if field == "traits":
            raw = data.get("traits")
            if isinstance(raw, list) and raw and not (existing.traits or "").strip():
                existing.traits = json.dumps(raw, ensure_ascii=False)
                changed = True
            continue
        new_val = _val(data.get(field))
        if new_val and not str(getattr(existing, field, None) or "").strip():
            setattr(existing, field, new_val)
            changed = True

    background = _with_chapter_line(existing.background, chapter_number, _val(data.get("background")))
    if background != (existing.background or ""):
        existing.background = background
        changed = True

    if is_org:
        new_members = data.get("known_members") or []
        if isinstance(new_members, list) and new_members:
            try:
                cur_list = json.loads(existing.organization_members or "[]")
            except (ValueError, TypeError):
                cur_list = []
            cur_set = {str(m).strip().lower() for m in cur_list if m}
            added = [m for m in new_members if str(m).strip() and str(m).strip().lower() not in cur_set]
            if added:
                existing.organization_members = json.dumps(list(cur_list) + added, ensure_ascii=False)
                changed = True

    new_role = _val(data.get("role_type"))
    if new_role and new_role in ROLE_RANK:
        if ROLE_RANK[new_role] > ROLE_RANK.get((existing.role_type or "minor").lower(), 0):
            existing.role_type = new_role
            changed = True
    return changed


def _set_note(member: OrganizationMember, chapter_number: int, action: str, reason: Optional[str]) -> None:
    """成员备注按章一行：同一章重新分析时替换，不重复追加。"""
    prefix = _note_prefix(chapter_number)
    lines = [line for line in (member.notes or "").split("\n") if line.strip() and not line.startswith(prefix)]
    note = f"{prefix}{action}" + (f"（{reason}）" if reason else "")
    member.notes = "\n".join(lines + [note])


async def auto_create_entities(db: AsyncSession, project_id: str, chapter_number: int, entity_result: dict) -> int:
    """新建或补全人物 / 组织，并结算组织归属变动（不提交）。返回新建 + 补全 + 归属变动的条数。"""
    characters_list, organizations_list = _split_corrected(entity_result or {})
    existing_rows = (await db.execute(select(Character).where(Character.project_id == project_id))).scalars().all()
    # 正式名 + 曾用名都指向同一角色：改名后旧章节里的旧名不会被当成新角色重复建档
    existing_map: dict[str, Character] = build_name_index(existing_rows)
    created = enriched = 0

    for char in characters_list:
        name = _val(char.get("name"))
        if not name:
            continue
        existing = existing_map.get(name.lower())
        if existing:
            enriched += int(_enrich(existing, char, chapter_number))
            continue
        role_type = (_val(char.get("role_type")) or "minor").lower()
        if role_type == "minor":
            # 龙套（店小二 / 路人甲）不建档：长篇里每章都冒几个；之后升格为配角再出场时自然会建档
            continue
        traits = char.get("traits")
        new_char = Character(
            project_id=project_id, name=name, gender=_val(char.get("gender")), age=_val(char.get("age")),
            role_type=role_type, personality=_val(char.get("personality")), appearance=_val(char.get("appearance")),
            speech_style=_val(char.get("speech_style")),
            background=f"第{chapter_number}章首次出场。{_val(char.get('background')) or ''}",
            traits=json.dumps(traits, ensure_ascii=False) if isinstance(traits, list) and traits else None,
        )
        db.add(new_char)
        existing_map[name.lower()] = new_char
        created += 1

    for org in organizations_list:
        name = _val(org.get("name"))
        if not name:
            continue
        existing = existing_map.get(name.lower())
        if existing:
            enriched += int(_enrich(existing, org, chapter_number, is_org=True))
            continue
        traits, members = org.get("traits"), org.get("known_members")
        location = _val(org.get("location"))
        background = f"第{chapter_number}章首次出场。" + (f"位于{location}。" if location else "") + (_val(org.get("background")) or "")
        new_org = Character(
            project_id=project_id, name=name, is_organization=True, role_type="supporting",
            organization_type=_val(org.get("organization_type")), organization_purpose=_val(org.get("organization_purpose")),
            personality=_val(org.get("personality")), appearance=_val(org.get("appearance")), background=background,
            traits=json.dumps(traits, ensure_ascii=False) if isinstance(traits, list) and traits else None,
            organization_members=json.dumps(members, ensure_ascii=False) if isinstance(members, list) and members else None,
        )
        db.add(new_org)
        existing_map[name.lower()] = new_org
        created += 1

    await db.flush()
    affiliation_count = 0
    dirty: dict[str, Organization] = {}
    for char in characters_list:
        char_obj = existing_map.get((_val(char.get("name")) or "").lower())
        if not char_obj or not getattr(char_obj, "id", None):
            continue
        for aff in char.get("affiliations") or []:
            org_char = existing_map.get((_val(aff.get("org_name")) or "").lower())
            if not org_char or not getattr(org_char, "is_organization", False) or not org_char.id:
                continue
            org = (await db.execute(select(Organization).where(Organization.character_id == org_char.id))).scalar_one_or_none()
            if not org:
                org = Organization(character_id=org_char.id, project_id=project_id, member_count=0)
                db.add(org)
                await db.flush()
            member = (await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org.id, OrganizationMember.character_id == char_obj.id,
                ).limit(1)
            )).scalar_one_or_none()
            change = (aff.get("change") or "active").strip().lower()
            position, reason = _val(aff.get("position")), _val(aff.get("reason"))
            if member:
                if change in ("left", "expelled", "promoted", "joined", "active"):
                    dirty[org.id] = org
                if change in ("left", "expelled"):
                    if member.status != change:
                        member.status = change
                        member.left_at = f"第{chapter_number}章"
                        _set_note(member, chapter_number, "离开" if change == "left" else "被逐出", reason)
                        affiliation_count += 1
                elif change == "promoted" and position:
                    if member.position != position or member.status != "active":
                        member.position, member.status, member.left_at = position, "active", None
                        _set_note(member, chapter_number, f"晋升为{position}", reason)
                        affiliation_count += 1
                elif change in ("joined", "active") and member.status != "active":
                    member.status = "active"
                    if change == "joined":
                        member.joined_at = f"第{chapter_number}章"
                    member.left_at = None
                    if position:
                        member.position = position
                    _set_note(member, chapter_number, "重新加入" if change == "joined" else "恢复活跃状态", reason)
                    affiliation_count += 1
            elif change not in ("left", "expelled"):
                new_member = OrganizationMember(
                    organization_id=org.id, character_id=char_obj.id, position=position or "成员", rank=0,
                    loyalty=50, status="active", joined_at=f"第{chapter_number}章", source="ai", notes=None,
                )
                _set_note(new_member, chapter_number, "加入", reason)
                db.add(new_member)
                dirty[org.id] = org
                affiliation_count += 1

    if dirty:
        await db.flush()
        for touched in dirty.values():
            await sync_organization_member_count(touched, db)
    if created or enriched or affiliation_count:
        logger.info(f"👥 第{chapter_number}章实体入库: 新建{created}个, 丰富{enriched}个, 归属变动{affiliation_count}条")
    return created + enriched + affiliation_count


async def strip_chapter_entity_notes(db: AsyncSession, project_id: str, chapter_number: int) -> int:
    """去掉这一章分析写进角色背景 / 成员备注的行（不提交）；返回改动条数。"""
    changed = 0
    prefix = _chapter_prefix(chapter_number)
    for character in (await db.execute(select(Character).where(Character.project_id == project_id))).scalars():
        if character.background and prefix in character.background:
            stripped = _with_chapter_line(character.background, chapter_number, None)
            if stripped != character.background:
                character.background = stripped
                changed += 1
    note_prefix = _note_prefix(chapter_number)
    members = (await db.execute(
        select(OrganizationMember).join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(Organization.project_id == project_id)
    )).scalars().all()
    for member in members:
        if member.notes and note_prefix in member.notes:
            kept = [line for line in member.notes.split("\n") if line.strip() and not line.startswith(note_prefix)]
            member.notes = "\n".join(kept) or None
            changed += 1
    return changed
