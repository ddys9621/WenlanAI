"""章节历史版本：列表 / 查看全文 / 恢复（恢复前当前稿也进历史；整章替换清掉旧分析，回到「未分析」）。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_project_access
from app.database import get_db
from app.models.chapter import Chapter
from app.models.chapter_version import ChapterVersion
from app.services.chapter_purge_service import purge_chapter_analysis, purge_chapter_vector_memory
from app.services.chapter_version_service import list_versions, replace_chapter_content, version_summary

router = APIRouter(prefix="/chapters", tags=["章节历史版本"])


async def load_owned_chapter(db: AsyncSession, chapter_id: str, request: Request) -> Chapter:
    chapter = (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, getattr(request.state, "user_id", None), db)
    return chapter


async def _load_version(db: AsyncSession, chapter: Chapter, version_id: str) -> ChapterVersion:
    version = (await db.execute(
        select(ChapterVersion).where(ChapterVersion.id == version_id, ChapterVersion.chapter_id == chapter.id)
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    return version


@router.get("/{chapter_id}/versions", summary="章节历史版本列表（不含全文）")
async def list_chapter_versions(chapter_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await load_owned_chapter(db, chapter_id, request)
    items = [version_summary(v) for v in await list_versions(db, chapter.id)]
    return {"total": len(items), "items": items}


@router.get("/{chapter_id}/versions/{version_id}", summary="查看某个历史版本全文")
async def get_chapter_version(chapter_id: str, version_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await load_owned_chapter(db, chapter_id, request)
    version = await _load_version(db, chapter, version_id)
    return {**version_summary(version), "content": version.content}


@router.post("/{chapter_id}/versions/{version_id}/restore", summary="恢复到某个历史版本")
async def restore_chapter_version(chapter_id: str, version_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    chapter = await load_owned_chapter(db, chapter_id, request)
    version = await _load_version(db, chapter, version_id)
    result = await replace_chapter_content(
        db, chapter, version.content, reason="restore", note=f"恢复第 {version.version_number} 版时自动保存",
    )
    purged = 0
    if result.changed:
        purged = await purge_chapter_analysis(db, chapter.id)
        if (chapter.content or "").strip():
            chapter.status = "completed"
    await db.commit()
    await db.refresh(chapter)
    if result.changed:
        await purge_chapter_vector_memory(getattr(request.state, "user_id", None), chapter.project_id, chapter.id, purged)
    return {
        "id": chapter.id,
        "content": chapter.content,
        "word_count": chapter.word_count or 0,
        "status": chapter.status,
        "purged_memories": purged,
        "snapshot_version_id": result.version.id if result.version else None,
    }
