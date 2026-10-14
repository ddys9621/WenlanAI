"""候选稿：AI 输出先成候选，作者采用才写入正式正文。

- 整章候选（replace_all）：生成后正文若被改过，要作者确认覆盖；采用后清掉本章旧分析（回到「未分析」），
  同章其余待定候选作废（它们基于旧稿）。
- 局部候选（append / replace_range，智能助笔用）：不比对整章指纹，按原文定位；不清分析（指纹判过期）。
- 一律经 replace_chapter_content 写入：旧稿先进历史版本。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_candidate import ChapterCandidate, utcnow
from app.models.chapter_version import ChapterVersion
from app.services.chapter_purge_service import purge_chapter_analysis
from app.services.chapter_version_service import content_hash, normalize_content, replace_chapter_content
from app.services.outline_contract import outline_fingerprint
from app.utils.text_utils import count_words

__all__ = [
    "AdoptResult", "CandidateClosedError", "CandidateError", "CandidateNotFoundError", "CandidateRangeError",
    "CandidateStaleError", "adopt_candidate", "adopt_candidate_by_id", "candidate_detail", "candidate_summary",
    "create_candidate", "discard_candidate", "list_candidates", "outline_fingerprint",
]

MAX_DECIDED_PER_CHAPTER = 20
PREVIEW_CHARS = 160
SOURCE_LABELS = {"ai_generate": "AI 生成", "deai_rewrite": "去 AI 味重写", "assistant": "智能助笔"}


class CandidateError(Exception):
    """候选稿操作失败（接口层转 409）。"""


class CandidateNotFoundError(CandidateError):
    pass


class CandidateClosedError(CandidateError):
    pass


class CandidateStaleError(CandidateError):
    pass


class CandidateRangeError(CandidateError):
    pass


def _dump(value: Any) -> Optional[str]:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _load(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def _prune_decided(db: AsyncSession, chapter_id: str) -> None:
    stale_ids = (await db.execute(
        select(ChapterCandidate.id)
        .where(ChapterCandidate.chapter_id == chapter_id, ChapterCandidate.status != "pending")
        .order_by(ChapterCandidate.created_at.desc())
        .offset(MAX_DECIDED_PER_CHAPTER)
    )).scalars().all()
    if stale_ids:
        await db.execute(delete(ChapterCandidate).where(ChapterCandidate.id.in_(stale_ids)))


async def create_candidate(
    db: AsyncSession,
    chapter: Chapter,
    *,
    content: str,
    source: str,
    base_hash: Optional[str] = None,
    outline_hash: Optional[str] = None,
    outline_changed: bool = False,
    quality: Any = None,
    adherence: Any = None,
    meta: Any = None,
    mode: str = "replace_all",
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    original_text: Optional[str] = None,
) -> ChapterCandidate:
    """存一份待定候选稿（不提交事务）。"""
    candidate = ChapterCandidate(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        source=source,
        mode=mode,
        content=content or "",
        word_count=count_words(content or ""),
        base_content_hash=base_hash,
        outline_hash=outline_hash,
        outline_changed=bool(outline_changed),
        range_start=range_start,
        range_end=range_end,
        original_text=original_text,
        quality_json=_dump(quality),
        adherence_json=_dump(adherence),
        meta_json=_dump(meta),
        status="pending",
    )
    db.add(candidate)
    await db.flush()
    await _prune_decided(db, chapter.id)
    return candidate


async def list_candidates(
    db: AsyncSession, chapter_id: str, status: Optional[str] = "pending", limit: int = 20,
) -> list[ChapterCandidate]:
    query = select(ChapterCandidate).where(ChapterCandidate.chapter_id == chapter_id)
    if status:
        query = query.where(ChapterCandidate.status == status)
    return list((await db.execute(query.order_by(ChapterCandidate.created_at.desc()).limit(limit))).scalars().all())


def candidate_summary(candidate: ChapterCandidate, current_hash: str) -> dict:
    base_stale = bool(
        candidate.status == "pending"
        and candidate.mode == "replace_all"
        and candidate.base_content_hash
        and candidate.base_content_hash != current_hash
    )
    return {
        "id": candidate.id,
        "chapter_id": candidate.chapter_id,
        "source": candidate.source,
        "source_label": SOURCE_LABELS.get(candidate.source, candidate.source),
        "mode": candidate.mode,
        "status": candidate.status,
        "word_count": candidate.word_count or 0,
        "preview": normalize_content(candidate.content)[:PREVIEW_CHARS],
        "outline_changed": bool(candidate.outline_changed),
        "base_stale": base_stale,
        "range_start": candidate.range_start,
        "range_end": candidate.range_end,
        "original_text": candidate.original_text,
        "quality": _load(candidate.quality_json),
        "adherence": _load(candidate.adherence_json),
        "meta": _load(candidate.meta_json),
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }


def candidate_detail(candidate: ChapterCandidate, current_hash: str) -> dict:
    return {**candidate_summary(candidate, current_hash), "content": candidate.content}


def _apply(candidate: ChapterCandidate, current: str, text: str) -> str:
    if candidate.mode == "append":
        base = current.rstrip()
        addition = text.strip()
        return f"{base}\n\n{addition}" if base else addition
    if candidate.mode == "replace_range":
        start, end, original = candidate.range_start, candidate.range_end, candidate.original_text or ""
        if start is not None and end is not None and current[start:end] == original:
            return current[:start] + text + current[end:]
        idx = current.find(original) if original else -1
        if idx < 0 or current.find(original, idx + 1) >= 0:
            raise CandidateRangeError("正文里找不到（或不止一处）这段选中的原文，可能已被修改；请重新选中后再试")
        return current[:idx] + text + current[idx + len(original):]
    return text


@dataclass
class AdoptResult:
    chapter: Chapter
    version: Optional[ChapterVersion]
    purged_memories: int
    changed: bool


async def adopt_candidate(
    db: AsyncSession,
    candidate: ChapterCandidate,
    chapter: Chapter,
    *,
    content_override: Optional[str] = None,
    force: bool = False,
) -> AdoptResult:
    """采用候选稿写入正文（不提交事务）。content_override = 作者在候选面板里改过的文本。"""
    if candidate.status != "pending":
        raise CandidateClosedError("这份候选稿已经处理过（已采用 / 已丢弃 / 已被新稿取代）")
    whole = candidate.mode == "replace_all"
    if whole and candidate.base_content_hash and not force and candidate.base_content_hash != content_hash(chapter.content):
        raise CandidateStaleError(
            "正文在生成这份候选稿之后被修改过，直接采用会覆盖这些修改；确认覆盖后再采用（当前正文会先存入历史版本）"
        )
    text = content_override if content_override is not None else candidate.content
    new_content = _apply(candidate, chapter.content or "", text)
    note = f"采用{SOURCE_LABELS.get(candidate.source, '')}候选稿前自动保存"
    result = await replace_chapter_content(db, chapter, new_content, reason="adopt_candidate", note=note)
    purged = await purge_chapter_analysis(db, chapter.id) if (whole and result.changed) else 0
    if (chapter.content or "").strip():
        chapter.status = "completed"
    if whole and candidate.outline_hash:
        chapter.outline_hash = candidate.outline_hash
    now = utcnow()
    candidate.status = "adopted"
    candidate.decided_at = now
    if whole:
        # 同章其余待定候选都基于旧稿：作废
        await db.execute(
            update(ChapterCandidate)
            .where(
                ChapterCandidate.chapter_id == chapter.id,
                ChapterCandidate.status == "pending",
                ChapterCandidate.id != candidate.id,
            )
            .values(status="superseded", decided_at=now)
        )
    return AdoptResult(chapter=chapter, version=result.version, purged_memories=purged, changed=result.changed)


async def discard_candidate(db: AsyncSession, candidate: ChapterCandidate) -> None:
    if candidate.status != "pending":
        raise CandidateClosedError("这份候选稿已经处理过（已采用 / 已丢弃 / 已被新稿取代）")
    candidate.status = "discarded"
    candidate.decided_at = utcnow()


async def adopt_candidate_by_id(db: AsyncSession, candidate_id: str, *, force: bool = False) -> AdoptResult:
    """批量生成用：按 id 采用并提交。"""
    candidate = await db.get(ChapterCandidate, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError("候选稿不存在")
    chapter = await db.get(Chapter, candidate.chapter_id)
    if chapter is None:
        raise CandidateNotFoundError("章节不存在")
    result = await adopt_candidate(db, candidate, chapter, force=force)
    await db.commit()
    return result
