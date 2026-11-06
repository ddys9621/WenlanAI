"""共创室 · 撤销本轮：把一轮运行写进书里的东西一次撤回。

按创作顺序倒着撤：
- 自动执行采用的正文 → 恢复到采用前（采用后作者又改过的不动）
- 这一轮写出、还没采用的候选稿 → 丢弃
- 这一轮生成的章纲 → 删掉（已经写了正文的不动），连带当时同步出来、还空着的章节
- 这一轮分出来的卷 → 删掉（还挂着章纲的不动）
- 新建的关系 / 组织成员 / 人物 / 组织 / 设定条目 / 世界规则 → 删掉（被这一轮以外的关系、成员用到的不动）
- 应用了的修改 → 撤回（之后又被改过的不动）
- 团队记进作品备忘的 → 删掉
撤不了的如实列出：后台批量写的正文（到历史版本恢复）、重新分卷替换掉的旧卷纲、细化前的剧情单元（都没留旧版）。

和卡片上的按钮同一套服务函数、同一把项目锁（decision_lock）、提交后读回真东西核对（所有会话共用一个 SQLite 连接）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.assistant import AssistantEntityCandidate, AssistantFieldCandidate, AssistantMemo, AssistantMessage, AssistantRun
from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate, utcnow
from app.models.chapter_outline import ChapterOutline
from app.models.chapter_version import ChapterVersion
from app.models.character import Character
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.setting_entry import SettingEntry
from app.models.volume import Volume
from app.models.world_rule import WorldRule
from app.services import assistant_candidate_service as cands
from app.services import assistant_fields as fields
from app.services.assistant_persistence import WRITE_ATTEMPTS, decision_lock, write_verified

logger = get_logger(__name__)

DONE_STATUSES = ("completed", "failed", "cancelled", "interrupted")
LINK_TYPES = ("relationship", "membership")
ENTITY_ORDER = {"relationship": 0, "membership": 0, "character": 1, "organization": 1, "setting_entry": 2, "world_rule": 2}


class UndoError(Exception):
    """这一轮现在不能撤（还在跑 / 在等回答 / 撤过了 / 不存在）：消息直接给作者看。"""


@dataclass
class Item:
    kind: str  # chapter 正文 / draft 候选稿 / outline 章纲 / volume 卷纲 / entity 新建 / field 修改 / memo 备忘 / note 撤不了的
    label: str
    action: str
    target: dict = field(default_factory=dict)
    ok: bool = True  # 预览：能撤；执行后：撤成了
    reason: str = ""

    def view(self) -> dict:
        """chapter_id：正文 / 候选稿那几项带上，前端撤完按它刷新章节页。"""
        return {"kind": self.kind, "label": self.label, "action": self.action, "ok": self.ok, "reason": self.reason,
                "chapter_id": self.target.get("chapter_id")}


def _loads(raw: Optional[str]) -> dict:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _when(text: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


async def _run(db: AsyncSession, project_id: str, run_id: str, *, stale_running: bool = False) -> AssistantRun:
    """stale_running：库里还是 running、本项目却没有在跑的助笔任务（服务重启打断的），按已中断处理，可以撤。"""
    run = (await db.execute(select(AssistantRun).where(AssistantRun.id == run_id)
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if run is None or run.project_id != project_id:
        raise UndoError("这一轮不存在")
    if run.status == "undone":
        raise UndoError("这一轮已经撤销过了")
    if run.status not in DONE_STATUSES and not (stale_running and run.status == "running"):
        raise UndoError("这一轮还没结束（在处理中或在等你回答），结束后再撤销")
    return run


async def _run_metas(db: AsyncSession, run: AssistantRun) -> list[dict]:
    rows = (await db.execute(select(AssistantMessage.meta_json).where(
        AssistantMessage.session_id == run.session_id, AssistantMessage.role == "assistant"))).scalars()
    return [meta for meta in (_loads(raw) for raw in rows) if meta.get("run_id") == run.id]


# ---------------------------------------------------------------- 列出要撤的


async def _chapter_items(db: AsyncSession, writes: list[dict], drafts: list[dict]) -> list[Item]:
    from app.services.chapter_version_service import content_hash

    items: list[Item] = []
    for w in writes:
        label = f"第 {w.get('chapter_number')} 章正文"
        chapter = await db.get(Chapter, w.get("chapter_id") or "")
        if chapter is None:
            continue
        adopted = w.get("adopted")
        if adopted:
            item = Item("chapter", label, "恢复到采用前", {"chapter_id": chapter.id, **adopted})
            if content_hash(chapter.content) != adopted.get("after_hash"):
                item.ok, item.reason = False, "采用之后正文又改过，没动（要恢复去章节写作页的历史版本）"
            elif not adopted.get("before_empty") and await _version_by_hash(db, chapter.id, adopted.get("before_hash")) is None:
                item.ok, item.reason = False, "找不到采用前的那一版"
            items.append(item)
            continue
        started = _when(w.get("started_at"))
        pending = (await db.execute(select(ChapterCandidate).where(
            ChapterCandidate.chapter_id == chapter.id, ChapterCandidate.status == "pending",
            *([ChapterCandidate.created_at >= started] if started else []),
        ))).scalars().all()
        items += [Item("draft", f"第 {w.get('chapter_number')} 章的候选稿", "丢弃",
                       {"candidate_id": c.id, "chapter_id": chapter.id}) for c in pending]
    for ref in drafts:
        cand = await db.get(ChapterCandidate, ref.get("id") or "")
        if cand is not None and cand.status == "pending":
            items.append(Item("draft", f"第 {ref.get('chapter_number')} 章的候选稿", "丢弃",
                              {"candidate_id": cand.id, "chapter_id": cand.chapter_id}))
    return items


async def _version_by_hash(db: AsyncSession, chapter_id: str, digest: Optional[str]) -> Optional[ChapterVersion]:
    if not digest:
        return None
    return (await db.execute(select(ChapterVersion).where(
        ChapterVersion.chapter_id == chapter_id, ChapterVersion.content_hash == digest,
    ).order_by(ChapterVersion.version_number.desc()))).scalars().first()


async def _plan_items(db: AsyncSession, plans: list[dict]) -> list[Item]:
    items: list[Item] = []
    outline_ids = [c["id"] for p in plans if p.get("kind") == "outlines" for c in p.get("chapters") or []]
    volume_ids = [v["id"] for p in plans if p.get("kind") == "volumes" for v in p.get("volumes") or []]
    gone_outlines = set()
    for oid in dict.fromkeys(outline_ids):
        outline = await db.get(ChapterOutline, oid)
        if outline is None:
            continue
        item = Item("outline", f"第 {outline.chapter_number} 章章纲", "删除", {"outline_id": oid})
        written = await db.scalar(select(func.count()).select_from(Chapter).where(
            Chapter.chapter_outline_id == oid, Chapter.content.isnot(None), Chapter.content != ""))
        if written:
            item.ok, item.reason = False, "这一章已经写了正文，没删"
        else:
            gone_outlines.add(oid)
        items.append(item)
    for vid in dict.fromkeys(volume_ids):
        volume = await db.get(Volume, vid)
        if volume is None:
            continue
        item = Item("volume", f"第 {volume.volume_number} 卷卷纲", "删除", {"volume_id": vid})
        left = (await db.execute(select(ChapterOutline.id).where(ChapterOutline.volume_id == vid))).scalars().all()
        if [i for i in left if i not in gone_outlines]:
            item.ok, item.reason = False, "这一卷还挂着章纲，没删"
        items.append(item)
    if volume_ids:
        items.append(Item("note", "重新分卷时替换掉的旧卷纲", "恢复", ok=False, reason="没留旧版，撤不回"))
    for p in plans:
        if p.get("kind") == "units" and p.get("volume"):
            items.append(Item("note", f"第 {p['volume'].get('volume_number')} 卷细化出的剧情单元", "恢复到细化前", ok=False,
                              reason="没留旧版，撤不回：到谋篇页调整或重新细化"))
    return items


async def _entity_items(db: AsyncSession, run_id: str) -> list[Item]:
    rows = (await db.execute(select(AssistantEntityCandidate).where(
        AssistantEntityCandidate.run_id == run_id, AssistantEntityCandidate.status == "applied",
    ))).scalars().all()
    ours = {c.created_entity_id for c in rows if c.entity_type in LINK_TYPES and c.created_entity_id}
    items: list[Item] = []
    for cand in sorted(rows, key=lambda c: (ENTITY_ORDER.get(c.entity_type, 9), c.created_at or utcnow())):
        item = Item("entity", cand.label, "删除", {"candidate_id": cand.id})
        if cand.entity_type in ("character", "organization") and cand.created_entity_id:
            used = await _outside_links(db, cand.entity_type, cand.created_entity_id, ours)
            if used:
                item.ok, item.reason = False, f"还被这一轮以外的{used}用到，没删（到角色页处理）"
        items.append(item)
    return items


async def _outside_links(db: AsyncSession, entity_type: str, entity_id: str, ours: set[str]) -> str:
    """这一轮以外建的关系 / 组织成员还连着它：返回是什么（没有就是空）。"""
    rels = (await db.execute(select(CharacterRelationship.id).where(or_(
        CharacterRelationship.character_from_id == entity_id, CharacterRelationship.character_to_id == entity_id,
    )))).scalars().all()
    if [r for r in rels if r not in ours]:
        return "人物关系"
    member_where = [OrganizationMember.character_id == entity_id]
    if entity_type == "organization":
        org_id = await db.scalar(select(Organization.id).where(Organization.character_id == entity_id))
        if org_id:
            member_where.append(OrganizationMember.organization_id == org_id)
    members = (await db.execute(select(OrganizationMember.id).where(or_(*member_where)))).scalars().all()
    return "组织成员" if [m for m in members if m not in ours] else ""


async def _field_items(db: AsyncSession, project_id: str, run_id: str) -> list[Item]:
    rows = (await db.execute(select(AssistantFieldCandidate).where(
        AssistantFieldCandidate.run_id == run_id, AssistantFieldCandidate.status == "applied",
    ))).scalars().all()
    items: list[Item] = []
    for cand in sorted(rows, key=lambda c: c.decided_at or c.created_at or utcnow(), reverse=True):
        item = Item("field", f"修改{cand.target_label}", "撤回", {"candidate_id": cand.id})
        try:
            current = (await fields.read_field(db, project_id, cand.field_id, cand.target_id))["value"]
        except fields.FieldError:
            item.ok, item.reason = False, "这一项已经不在了"
        else:
            if json.dumps(current, ensure_ascii=False) != (cand.after_json or ""):
                item.ok, item.reason = False, "应用之后又被改过，没动"
        items.append(item)
    return items


def _steps(raw: Optional[str]) -> list:
    try:
        steps = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


async def collect(db: AsyncSession, project_id: str, run_id: str, *,
                  stale_running: bool = False) -> tuple[AssistantRun, list[Item]]:
    run = await _run(db, project_id, run_id, stale_running=stale_running)
    metas = await _run_metas(db, run)
    writes = [w for m in metas for w in m.get("chapter_writes") or []]
    drafts = [c for m in metas for c in m.get("chapter_candidates") or []]
    plans = [p for m in metas for p in m.get("plans") or []]
    items = [
        *await _chapter_items(db, writes, drafts),
        *await _plan_items(db, plans),
        *await _entity_items(db, run.id),
        *await _field_items(db, project_id, run.id),
    ]
    memos = (await db.execute(select(AssistantMemo).where(AssistantMemo.run_id == run.id))).scalars().all()
    items += [Item("memo", f"作品备忘「{m.content[:30]}」", "删除", {"memo_id": m.id}) for m in memos]
    if any(s.get("tool") == "write_chapters" and s.get("ok") for s in _steps(run.steps_json)):
        items.append(Item("note", "后台批量写的正文", "恢复", ok=False, reason="撤不回：到章节写作页的历史版本里恢复"))
    return run, items


def summary(items: list[Item]) -> dict:
    return {"items": [i.view() for i in items], "doable": sum(1 for i in items if i.ok),
            "blocked": sum(1 for i in items if not i.ok)}


async def preview(db: AsyncSession, project_id: str, run_id: str, *, stale_running: bool = False) -> dict:
    _run_row, items = await collect(db, project_id, run_id, stale_running=stale_running)
    return {"run_id": run_id, **summary(items)}


# ---------------------------------------------------------------- 撤


async def _fresh(db: AsyncSession, model: Any, row_id: str) -> Any:
    return (await db.execute(select(model).where(model.id == row_id).execution_options(populate_existing=True))
            ).scalar_one_or_none()


async def _restore_chapter(db: AsyncSession, user_id: Optional[str], target: dict) -> str:
    from app.services.chapter_purge_service import purge_chapter_analysis, purge_chapter_vector_memory
    from app.services.chapter_version_service import content_hash, replace_chapter_content

    chapter_id = target["chapter_id"]
    before = ""
    if not target.get("before_empty"):
        version = await _version_by_hash(db, chapter_id, target.get("before_hash"))
        if version is None:
            return "找不到采用前的那一版"
        before = version.content or ""
    want = content_hash(before)
    purged, project_id, number = 0, "", 0
    for _attempt in range(WRITE_ATTEMPTS):
        chapter = await _fresh(db, Chapter, chapter_id)
        if chapter is None:
            return "这一章已经不在了"
        project_id, number = chapter.project_id, chapter.chapter_number
        current = content_hash(chapter.content)
        if current == want:
            break
        if current != target.get("after_hash"):
            return "采用之后正文又改过，没动"
        result = await replace_chapter_content(db, chapter, before, reason="restore", note="撤销本轮：恢复到采用前")
        if result.changed:
            purged = await purge_chapter_analysis(db, chapter.id)
        chapter.status = "completed" if before.strip() else "draft"
        await db.commit()
        if content_hash(await db.scalar(select(Chapter.content).where(Chapter.id == chapter_id))) == want:
            break
        db.expire_all()
    else:
        return "没能写进数据库（被同时进行的其他操作打断）"
    if user_id and purged:
        try:
            await purge_chapter_vector_memory(user_id, project_id, chapter_id, purged)
        except Exception as exc:  # noqa: BLE001 - 向量只是检索增强，索引可重建
            logger.warning(f"[撤销本轮] 第 {number} 章的向量记忆没清掉：{exc}")
    return ""


async def _discard_draft(db: AsyncSession, target: dict) -> str:
    from app.services.chapter_candidate_service import CandidateError, discard_candidate

    async def write() -> None:
        cand = await _fresh(db, ChapterCandidate, target["candidate_id"])
        if cand is not None and cand.status == "pending":
            await discard_candidate(db, cand)

    async def verify() -> bool:
        status = await db.scalar(select(ChapterCandidate.status).where(ChapterCandidate.id == target["candidate_id"]))
        return status != "pending"

    try:
        await write_verified(db, write, verify, "丢弃候选稿")
    except CandidateError as exc:
        return str(exc)
    return ""


async def _delete_outline(db: AsyncSession, target: dict) -> str:
    """删章纲，连带当时同步出来、还空着的章节（写过正文的不动；留过版本 / 候选稿的章节行留着，只解开章纲）。"""
    oid = target["outline_id"]
    linked = (await db.execute(select(Chapter).where(Chapter.chapter_outline_id == oid))).scalars().all()
    if any((c.content or "").strip() for c in linked):
        return "这一章已经写了正文，没删"
    empty_ids = []
    for chapter in linked:
        history = await db.scalar(select(func.count()).select_from(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id))
        drafts = await db.scalar(select(func.count()).select_from(ChapterCandidate).where(
            ChapterCandidate.chapter_id == chapter.id, ChapterCandidate.status != "discarded"))
        if not history and not drafts:
            empty_ids.append(chapter.id)

    async def write() -> None:
        if empty_ids:
            await db.execute(delete(Chapter).where(Chapter.id.in_(empty_ids)))
        await db.execute(update(Chapter).where(Chapter.chapter_outline_id == oid).values(chapter_outline_id=None))
        await db.execute(delete(ChapterOutline).where(ChapterOutline.id == oid))

    async def verify() -> bool:
        return not await db.scalar(select(ChapterOutline.id).where(ChapterOutline.id == oid))

    await write_verified(db, write, verify, "删除章纲")
    return ""


async def _delete_volume(db: AsyncSession, target: dict) -> str:
    vid = target["volume_id"]
    if await db.scalar(select(func.count()).select_from(ChapterOutline).where(ChapterOutline.volume_id == vid)):
        return "这一卷还挂着章纲，没删"

    async def write() -> None:
        await db.execute(delete(Volume).where(Volume.id == vid))

    async def verify() -> bool:
        return not await db.scalar(select(Volume.id).where(Volume.id == vid))

    await write_verified(db, write, verify, "删除卷纲")
    return ""


async def _drop_entity_row(db: AsyncSession, cand: AssistantEntityCandidate) -> list:
    """删掉候选建出来的那一行（和页面上删除同一套连带）；返回提交后要做的向量清理。"""
    from app.services import world_map_service as wms

    eid, etype, project_id = cand.created_entity_id, cand.entity_type, cand.project_id
    after: list = []
    if not eid:
        return after
    if etype == "relationship":
        await db.execute(delete(CharacterRelationship).where(CharacterRelationship.id == eid))
    elif etype == "membership":
        member = await db.get(OrganizationMember, eid)
        if member is not None:
            org = await db.get(Organization, member.organization_id)
            if org is not None:
                org.member_count = max(0, (org.member_count or 0) - 1)
            await db.delete(member)
    elif etype in ("character", "organization"):
        await db.execute(delete(Organization).where(Organization.character_id == eid))
        await db.execute(delete(Character).where(Character.id == eid))
    elif etype == "setting_entry":
        await db.execute(delete(SettingEntry).where(SettingEntry.id == eid))
        after.append(("setting_entry", project_id, eid))
    elif etype == "world_rule":
        rule = await db.get(WorldRule, eid)
        if rule is not None and rule.category == wms.RULE_CATEGORY:
            await wms.delete_rule_locations(db, project_id, eid)
        await db.execute(delete(WorldRule).where(WorldRule.id == eid))
        after.append(("world_rule", project_id, eid))
    return after


async def _vector_cleanup(jobs: list) -> None:
    from app.services import setting_entry_service
    from app.services.world_rule_service import world_rule_service

    for kind, project_id, eid in jobs:
        try:
            if kind == "setting_entry":
                await setting_entry_service.setting_entry_index().remove(project_id, eid)
            else:
                await world_rule_service.delete_rule_from_vector_db(project_id, eid)
        except Exception as exc:  # noqa: BLE001 - 向量只是检索增强，索引可重建
            logger.warning(f"[撤销本轮] {kind} {eid} 的向量没删掉：{exc}")


async def _delete_entity(db: AsyncSession, target: dict) -> str:
    from app.services.assistant_entity_candidate_service import created_entity_exists

    cid = target["candidate_id"]
    cleanup: list = []
    for _attempt in range(WRITE_ATTEMPTS):
        cand = await _fresh(db, AssistantEntityCandidate, cid)
        if cand is None:
            return "卡片不见了"
        etype, eid = cand.entity_type, cand.created_entity_id  # 提交 / expire_all 之后只用这两个值
        if cand.status == "undone" and not await created_entity_exists(db, etype, eid):
            break
        if etype in ("character", "organization") and eid:
            used = await _outside_links(db, etype, eid, set())  # 这一轮的关系 / 成员已经先删了，还连着的都是别处的
            if used:
                return f"还有{used}连着它，没删（到角色页处理）"
        cleanup = await _drop_entity_row(db, cand)
        cand.status, cand.decided_at = "undone", utcnow()
        await db.commit()
        status = await db.scalar(select(AssistantEntityCandidate.status).where(AssistantEntityCandidate.id == cid))
        if status == "undone" and not await created_entity_exists(db, etype, eid):
            break
        db.expire_all()
    else:
        return "没能写进数据库（被同时进行的其他操作打断）"
    await _vector_cleanup(cleanup)
    return ""


async def _undo_field(db: AsyncSession, project_id: str, target: dict) -> str:
    """同 api/assistant._decide（撤销）：记成已撤销、内容却被冲掉了就退回一步重做。"""
    cid = target["candidate_id"]
    for attempt in range(WRITE_ATTEMPTS):
        cand = await _fresh(db, AssistantFieldCandidate, cid)
        if cand is None:
            return "卡片不见了"
        if attempt and cand.status == "undone":
            cand.status = "applied"
        field_id, target_id, expected = cand.field_id, cand.target_id, cand.before_json
        try:
            await cands.undo_candidate(db, cand)
        except fields.FieldError as exc:
            await db.rollback()
            return str(exc)
        await db.commit()
        status = await db.scalar(select(AssistantFieldCandidate.status).where(AssistantFieldCandidate.id == cid))
        if status == "undone" and await cands.value_is(db, project_id, field_id, target_id, expected or ""):
            return ""
        db.expire_all()
    return "没能写进数据库（被同时进行的其他操作打断）"


async def _delete_memo(db: AsyncSession, target: dict) -> str:
    mid = target["memo_id"]

    async def write() -> None:
        await db.execute(delete(AssistantMemo).where(AssistantMemo.id == mid))

    async def verify() -> bool:
        return not await db.scalar(select(AssistantMemo.id).where(AssistantMemo.id == mid))

    await write_verified(db, write, verify, "删除作品备忘")
    return ""


async def undo(db: AsyncSession, project_id: str, run_id: str, user_id: Optional[str], *,
               stale_running: bool = False) -> dict:
    """撤销一轮：能撤的按顺序撤，撤不了的照实列出；做完把这一轮记成 undone。"""
    async with decision_lock(project_id):
        # 之后只用 run_id 字符串：各项撤回里会 rollback / expire_all，ORM 对象过期后再读属性会触发懒加载
        _run_row, items = await collect(db, project_id, run_id, stale_running=stale_running)
        for item in items:
            if not item.ok:
                continue
            try:
                if item.kind == "chapter":
                    reason = await _restore_chapter(db, user_id, item.target)
                elif item.kind == "draft":
                    reason = await _discard_draft(db, item.target)
                elif item.kind == "outline":
                    reason = await _delete_outline(db, item.target)
                elif item.kind == "volume":
                    reason = await _delete_volume(db, item.target)
                elif item.kind == "entity":
                    reason = await _delete_entity(db, item.target)
                elif item.kind == "field":
                    reason = await _undo_field(db, project_id, item.target)
                elif item.kind == "memo":
                    reason = await _delete_memo(db, item.target)
                else:
                    reason = ""
            except Exception as exc:  # noqa: BLE001 - 一项没撤成不挡其余的，如实记下
                await db.rollback()
                logger.warning(f"[撤销本轮] {item.label} 没撤成：{exc}")
                reason = f"出错了：{str(exc)[:120]}"
            if reason:
                item.ok, item.reason = False, reason
        done = sum(1 for i in items if i.ok)
        message = f"已撤销本轮：撤回 {done} 项" + (f"，{len(items) - done} 项没动" if len(items) > done else "")

        async def mark() -> None:
            await db.execute(update(AssistantRun).where(AssistantRun.id == run_id).values(
                status="undone", message=message[:500], updated_at=utcnow()))

        async def marked() -> bool:
            return await db.scalar(select(AssistantRun.status).where(AssistantRun.id == run_id)) == "undone"

        await write_verified(db, mark, marked, "撤销本轮")
    return {"run_id": run_id, "message": message, **summary(items)}
