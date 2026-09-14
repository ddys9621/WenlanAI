"""V3 仿写重构：参考包 API

涵盖两类资源：
1. 参考包自身：CRUD + 5 tab 子资源
2. 项目-参考包关联：挂载 / 卸载 / 列表 / 配置更新

所有端点强制鉴权（require_login）+ 跨用户隔离。

参见：@/agent-docs/features/book_dissect_v3_imitation_design.md §6 R3
"""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.models.project import Project
from app.models.project_reference_pack import ProjectReferencePack
from app.models.reference_pack import ReferencePack
from app.schemas.reference_pack import (
    AttachReferencePackRequest,
    AttachReferencePackResponse,
    ProjectReferencePackResponse,
    ReferencePackDetail,
    ReferencePackSummary,
    UpdateAttachmentRequest,
)
from app.user_manager import User
from app.api.deps import require_login

logger = get_logger(__name__)


# ============================================================
# 共用依赖与工具
# ============================================================


def _safe_load_json(raw: Optional[str], default):
    """容错解析 JSON 字符串。"""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("[V3-API] JSON 解析失败，已退回默认值：%r", raw[:80] if raw else None)
        return default


async def _attached_count(db: AsyncSession, pack_id: str) -> int:
    """查询某个参考包当前被挂载到几个项目。"""
    result = await db.execute(
        select(func.count(ProjectReferencePack.id))
        .where(ProjectReferencePack.pack_id == pack_id)
    )
    return int(result.scalar_one() or 0)


async def _ensure_pack_owned(
    db: AsyncSession, pack_id: str, user_id: str
) -> ReferencePack:
    """获取参考包，校验所有权；不存在或无权访问 → 404。"""
    result = await db.execute(
        select(ReferencePack).where(
            ReferencePack.id == pack_id,
            ReferencePack.user_id == user_id,
        )
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="参考包不存在或无权访问")
    return pack


async def _ensure_project_owned(
    db: AsyncSession, project_id: str, user_id: str
) -> Project:
    """获取项目，校验所有权；不存在或无权访问 → 404。"""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    return project


def _summary_from(pack: ReferencePack, attached_count: int) -> ReferencePackSummary:
    """ORM → ReferencePackSummary。"""
    dims = _safe_load_json(pack.generated_dimensions, [])
    return ReferencePackSummary(
        id=pack.id,
        user_id=pack.user_id,
        task_id=pack.task_id,
        source_book_title=pack.source_book_title,
        status=pack.status,
        generated_dimensions=dims if isinstance(dims, list) else [],
        pipeline_version=pack.pipeline_version or 2,
        error_message=pack.error_message,
        attached_project_count=attached_count,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


def _detail_from(pack: ReferencePack, attached_count: int) -> ReferencePackDetail:
    """ORM → ReferencePackDetail（V5 六维度；老包同名字段原样下发，前端按 pipeline_version 分流）。"""
    dims = _safe_load_json(pack.generated_dimensions, [])
    return ReferencePackDetail(
        id=pack.id,
        user_id=pack.user_id,
        task_id=pack.task_id,
        source_book_title=pack.source_book_title,
        status=pack.status,
        generated_dimensions=dims if isinstance(dims, list) else [],
        pipeline_version=pack.pipeline_version or 2,
        error_message=pack.error_message,
        synopsis=_safe_load_json(pack.synopsis_json, None),
        bridges=_safe_load_json(pack.bridges_json, None),
        style=_safe_load_json(pack.style_json, None),
        character_archive=_safe_load_json(pack.character_archive_json, None),
        methodology=_safe_load_json(pack.methodology_json, None),
        structure=_safe_load_json(pack.structure_json, None),
        attached_project_count=attached_count,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


# ============================================================
# 参考包：CRUD
# ============================================================


router = APIRouter(prefix="/reference-packs", tags=["拆书参考包"])


@router.get("", response_model=List[ReferencePackSummary], summary="列出当前用户的参考包")
async def list_packs(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """按 created_at 倒序返回当前用户的所有参考包（不含 5 tab 详细内容）。"""
    result = await db.execute(
        select(ReferencePack)
        .where(ReferencePack.user_id == user.user_id)
        .order_by(ReferencePack.created_at.desc())
    )
    packs = result.scalars().all()

    if not packs:
        return []

    # 一次查所有 pack 的 attached_count，避免 N+1
    pack_ids = [p.id for p in packs]
    counts_result = await db.execute(
        select(
            ProjectReferencePack.pack_id,
            func.count(ProjectReferencePack.id),
        )
        .where(ProjectReferencePack.pack_id.in_(pack_ids))
        .group_by(ProjectReferencePack.pack_id)
    )
    counts_map = {pack_id: int(cnt) for pack_id, cnt in counts_result.all()}

    return [_summary_from(p, counts_map.get(p.id, 0)) for p in packs]


@router.get("/{pack_id}", response_model=ReferencePackDetail, summary="参考包详情（含 5 tab）")
async def get_pack(
    pack_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    pack = await _ensure_pack_owned(db, pack_id, user.user_id)
    attached = await _attached_count(db, pack_id)
    return _detail_from(pack, attached)


@router.delete("/{pack_id}", summary="删除参考包")
async def delete_pack(
    pack_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """删除参考包；显式清理所有 ProjectReferencePack 关联（不删项目本身）。

    注意：项目用 SQLite 但未启用 PRAGMA foreign_keys=ON，
    因此外键 ondelete=CASCADE 不会自动生效，必须显式删除。
    """
    pack = await _ensure_pack_owned(db, pack_id, user.user_id)
    # 1. 显式删除关联表中所有指向该 pack 的记录
    await db.execute(
        delete(ProjectReferencePack).where(ProjectReferencePack.pack_id == pack_id)
    )
    # 2. 删除 pack 本体
    await db.delete(pack)
    await db.commit()
    logger.info("[V3-API] 删除参考包 user=%s pack=%s", user.user_id, pack_id)
    return {"deleted": pack_id}


# ============================================================
# 项目-参考包关联
#
# 路由前缀仍在 /reference-packs 之外，挂在 /projects/{project_id}/reference-packs。
# 用第二个 router 实例承载，注册时单独 include。
# ============================================================


project_router = APIRouter(prefix="/projects/{project_id}/reference-packs", tags=["项目参考包"])


@project_router.get(
    "",
    response_model=List[ProjectReferencePackResponse],
    summary="项目已挂载的参考包列表",
)
async def list_attachments(
    project_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """返回该项目已挂载的所有参考包（含来源 pack 元信息）。"""
    await _ensure_project_owned(db, project_id, user.user_id)

    result = await db.execute(
        select(ProjectReferencePack, ReferencePack)
        .join(ReferencePack, ProjectReferencePack.pack_id == ReferencePack.id)
        .where(ProjectReferencePack.project_id == project_id)
        .order_by(ProjectReferencePack.attached_at.desc())
    )
    rows = result.all()

    if not rows:
        return []

    # 计算每个 pack 的 attached_count 一次查全
    pack_ids = list({pack.id for _, pack in rows})
    counts_result = await db.execute(
        select(
            ProjectReferencePack.pack_id,
            func.count(ProjectReferencePack.id),
        )
        .where(ProjectReferencePack.pack_id.in_(pack_ids))
        .group_by(ProjectReferencePack.pack_id)
    )
    counts_map = {pid: int(cnt) for pid, cnt in counts_result.all()}

    out: list[ProjectReferencePackResponse] = []
    for link, pack in rows:
        out.append(
            ProjectReferencePackResponse(
                id=link.id,
                project_id=link.project_id,
                pack_id=link.pack_id,
                pack_summary=_summary_from(pack, counts_map.get(pack.id, 0)),
                default_dimensions=_safe_load_json(link.default_dimensions, []) or [],
                default_strength=link.default_strength or "medium",
                attached_at=link.attached_at,
            )
        )
    return out


@project_router.post(
    "",
    response_model=AttachReferencePackResponse,
    summary="挂载参考包到项目",
)
async def attach_pack(
    project_id: str,
    payload: AttachReferencePackRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """将参考包挂载到项目；同一参考包不能在同一项目重复挂载（409）。"""
    await _ensure_project_owned(db, project_id, user.user_id)
    pack = await _ensure_pack_owned(db, payload.pack_id, user.user_id)
    if pack.status not in ("ready", "partial"):
        raise HTTPException(
            status_code=409,
            detail=f"参考包未就绪（status={pack.status}），无法挂载",
        )

    # 重复挂载检查
    exists_result = await db.execute(
        select(ProjectReferencePack).where(
            ProjectReferencePack.project_id == project_id,
            ProjectReferencePack.pack_id == pack.id,
        )
    )
    if exists_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="该参考包已挂载到本项目")

    # 默认维度推断（若未显式传）：按 strength 自动配置
    dims = payload.default_dimensions
    if dims is None:
        dims = _infer_default_dimensions(payload.default_strength)
    # 仅保留参考包真实生成的维度（避免引用空 tab）
    generated = set(_safe_load_json(pack.generated_dimensions, []) or [])
    # corpus 永远可用（来自 V2 表）
    valid = generated | {"corpus"}
    dims = [d for d in dims if d in valid]
    if not dims:
        # 兜底：至少保留 corpus，确保一键仿写有数据可用
        dims = ["corpus"]

    link = ProjectReferencePack(
        project_id=project_id,
        pack_id=pack.id,
        default_dimensions=json.dumps(dims, ensure_ascii=False),
        default_strength=payload.default_strength,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    logger.info(
        "[V3-API] 挂载参考包 user=%s project=%s pack=%s dims=%s strength=%s",
        user.user_id, project_id, pack.id, dims, payload.default_strength,
    )

    return AttachReferencePackResponse(
        attachment_id=link.id,
        project_id=project_id,
        pack_id=pack.id,
        default_dimensions=dims,
        default_strength=payload.default_strength,
    )


@project_router.patch(
    "/{pack_id}",
    response_model=ProjectReferencePackResponse,
    summary="更新挂载配置（默认维度/强度）",
)
async def update_attachment(
    project_id: str,
    pack_id: str,
    payload: UpdateAttachmentRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owned(db, project_id, user.user_id)

    result = await db.execute(
        select(ProjectReferencePack, ReferencePack)
        .join(ReferencePack, ProjectReferencePack.pack_id == ReferencePack.id)
        .where(
            ProjectReferencePack.project_id == project_id,
            ProjectReferencePack.pack_id == pack_id,
            ReferencePack.user_id == user.user_id,  # 校验 pack 也属于本人
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="挂载关系不存在")

    link, pack = row
    if payload.default_dimensions is not None:
        link.default_dimensions = json.dumps(
            payload.default_dimensions, ensure_ascii=False
        )
    if payload.default_strength is not None:
        link.default_strength = payload.default_strength
    await db.commit()
    await db.refresh(link)

    attached_count = await _attached_count(db, pack_id)
    return ProjectReferencePackResponse(
        id=link.id,
        project_id=link.project_id,
        pack_id=link.pack_id,
        pack_summary=_summary_from(pack, attached_count),
        default_dimensions=_safe_load_json(link.default_dimensions, []) or [],
        default_strength=link.default_strength or "medium",
        attached_at=link.attached_at,
    )


@project_router.delete("/{pack_id}", summary="卸载参考包")
async def detach_pack(
    project_id: str,
    pack_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owned(db, project_id, user.user_id)

    # 校验 pack 也属于本人，防越权操作他人 pack
    pack_check = await db.execute(
        select(ReferencePack.id).where(
            ReferencePack.id == pack_id,
            ReferencePack.user_id == user.user_id,
        )
    )
    if pack_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="挂载关系不存在")

    deleted = await db.execute(
        delete(ProjectReferencePack).where(
            ProjectReferencePack.project_id == project_id,
            ProjectReferencePack.pack_id == pack_id,
        )
    )
    await db.commit()
    if deleted.rowcount == 0:
        raise HTTPException(status_code=404, detail="挂载关系不存在")

    logger.info(
        "[V3-API] 卸载参考包 user=%s project=%s pack=%s",
        user.user_id, project_id, pack_id,
    )
    return {"detached": pack_id}


# ============================================================
# 辅助函数
# ============================================================


def _infer_default_dimensions(strength: str) -> List[str]:
    """根据参考强度推断默认维度（V5 七维）。

    - light: 仅文风（保持极简）
    - medium: + 全书骨架 + 写法手册 + 拆书卡检索
    - deep: 七维全开（+ 桥段库 / 人物功能谱 / 结构统计）
    """
    if strength == "light":
        return ["style"]
    if strength == "deep":
        return ["synopsis", "bridges", "methodology", "style", "structure", "character_archive", "corpus"]
    # medium
    return ["synopsis", "methodology", "style", "corpus"]
