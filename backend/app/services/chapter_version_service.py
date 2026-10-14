"""章节正文的唯一替换入口：先把旧稿存成历史版本，再写新稿并同步字数。

手动修改、采用候选稿、恢复旧版、智能助笔回填都走 replace_chapter_content，不再有"直接覆盖、不留版本"的写法。
版本按正文指纹去重（与上一版相同不再存），每章最多保留 MAX_VERSIONS_PER_CHAPTER 个。
content_hash 也是分析结果 / 候选稿绑定正文的指纹：正文一变，绑定在旧指纹上的派生数据就算过期。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_version import ChapterVersion
from app.models.project import Project
from app.utils.text_utils import count_words

MAX_VERSIONS_PER_CHAPTER = 50
PREVIEW_CHARS = 120


def normalize_content(text: Optional[str]) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def content_hash(text: Optional[str]) -> str:
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


@dataclass
class ReplaceResult:
    changed: bool
    version: Optional[ChapterVersion]
    old_hash: str
    new_hash: str


async def latest_version(db: AsyncSession, chapter_id: str) -> Optional[ChapterVersion]:
    return (await db.execute(
        select(ChapterVersion)
        .where(ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_number.desc())
        .limit(1)
    )).scalar_one_or_none()


async def _prune(db: AsyncSession, chapter_id: str) -> None:
    stale_ids = (await db.execute(
        select(ChapterVersion.id)
        .where(ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_number.desc())
        .offset(MAX_VERSIONS_PER_CHAPTER)
    )).scalars().all()
    if stale_ids:
        await db.execute(delete(ChapterVersion).where(ChapterVersion.id.in_(stale_ids)))


async def snapshot_chapter(
    db: AsyncSession, chapter: Chapter, *, reason: str, note: Optional[str] = None,
) -> Optional[ChapterVersion]:
    """把章节当前正文存成一个历史版本；空稿或与上一版相同则不存，返回 None。"""
    text = chapter.content or ""
    if not normalize_content(text):
        return None
    digest = content_hash(text)
    latest = await latest_version(db, chapter.id)
    if latest is not None and latest.content_hash == digest:
        return None
    version = ChapterVersion(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        version_number=(latest.version_number + 1) if latest else 1,
        content=text,
        content_hash=digest,
        word_count=count_words(text),
        reason=reason,
        note=note[:200] if note else None,
    )
    db.add(version)
    await db.flush()
    await _prune(db, chapter.id)
    return version


async def replace_chapter_content(
    db: AsyncSession,
    chapter: Chapter,
    new_content: Optional[str],
    *,
    reason: str,
    note: Optional[str] = None,
    project: Optional[Project] = None,
) -> ReplaceResult:
    """替换正文：内容有实质变化时先快照旧稿；同步本章与项目字数。不提交事务。"""
    new_text = new_content or ""
    old_hash, new_hash = content_hash(chapter.content), content_hash(new_text)
    changed = old_hash != new_hash
    version = await snapshot_chapter(db, chapter, reason=reason, note=note) if changed else None
    old_wc = chapter.word_count or 0
    new_wc = count_words(new_text)
    chapter.content = new_text
    chapter.word_count = new_wc
    if old_wc != new_wc:
        project = project or await db.get(Project, chapter.project_id)
        if project is not None:
            project.current_words = max(0, (project.current_words or 0) - old_wc + new_wc)
    return ReplaceResult(changed=changed, version=version, old_hash=old_hash, new_hash=new_hash)


def version_summary(version: ChapterVersion) -> dict:
    text = normalize_content(version.content)
    return {
        "id": version.id,
        "chapter_id": version.chapter_id,
        "version_number": version.version_number,
        "word_count": version.word_count or 0,
        "reason": version.reason,
        "note": version.note,
        "preview": text[:PREVIEW_CHARS],
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


async def list_versions(db: AsyncSession, chapter_id: str) -> list[ChapterVersion]:
    return list((await db.execute(
        select(ChapterVersion)
        .where(ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_number.desc())
    )).scalars().all())
