"""设置页「记忆检索」：查看 / 下载 / 切换向量模型。

向量模型全站共用一份（两个检索服务单例 + 一个 Chroma 客户端），所以只有管理员能下载、切换；
环境变量 / .env 指定了 EMBEDDING_MODEL 时以它为准，设置页只读。
- 下载：后台任务（托盘可见、可取消），逐文件拉，按 blobs/*.incomplete 已写入的字节报进度；只下预设模型
- 切换：本地加载新模型成功后才换掉旧的（embedding_runtime.switch_model），随后起一个后台任务按账本重建
  当前用户各项目的检索索引（集合名带模型指纹，换模型 = 换集合；别的用户的项目在打开账本 / 写正文时自动重建）
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from sqlalchemy import select

from app.services import embedding_models as em
from app.services import embedding_runtime as runtime
from app.services.ai_jobs import AIJob, AIJobManager, ai_jobs, job_session_factory

DOWNLOAD_KIND = "embedding_model_download"
DOWNLOAD_SCOPE = "embedding_model"
REBUILD_ALL_KIND = "memory_index_rebuild_all"
_switch_lock = asyncio.Lock()


def rebuild_all_scope(user_id: str) -> str:
    return f"{REBUILD_ALL_KIND}:{user_id}"


def model_status(*, can_manage: bool, manager: Optional[AIJobManager] = None) -> dict[str, Any]:
    manager = manager or ai_jobs
    active = runtime.get_embedding_model_name()
    info = runtime.loaded_model_info() or {}
    locked = em.env_override()
    installed = set(em.installed_models())
    models: list[dict[str, Any]] = [
        {
            "id": p.id, "label": p.label, "size_label": p.size_label, "description": p.description, "language": p.language,
            "recommended": p.recommended, "preset": True, "installed": p.id in installed, "active": p.id == active,
        }
        for p in em.PRESETS
    ]
    preset_ids = {p.id for p in em.PRESETS}
    for repo in sorted(installed - preset_ids):
        models.append({
            "id": repo, "label": repo, "size_label": "本地", "description": "embedding 目录里已有的模型（手动放入）",
            "language": "", "recommended": False, "preset": False, "installed": True, "active": repo == active,
        })
    if active and all(m["id"] != active for m in models):  # 本地目录路径之类，列表里没有也要让人知道在用什么
        models.append({
            "id": active, "label": active, "size_label": "本地", "description": "当前加载的模型", "language": "",
            "recommended": False, "preset": False, "installed": True, "active": True,
        })
    download = manager.current(DOWNLOAD_SCOPE)
    return {
        "available": active is not None,
        "active_model": active,
        "dimension": info.get("dimension"),
        "max_tokens": info.get("max_tokens"),
        "selected_model": em.load_selection(),
        "env_model": locked or None,
        "env_locked": bool(locked),
        "can_manage": can_manage,
        "downloading": download is not None,
        "download_job_id": download.id if download else None,
        "embedding_dir": em.EMBEDDING_PATH,
        "models": models,
    }


async def start_rebuild_all(
    *, user_id: str, manager: Optional[AIJobManager] = None, session_factory: Optional[Callable[[], Any]] = None,
) -> Optional[AIJob]:
    """换模型后：按账本依次重建当前用户每个项目的检索索引（不调用大模型）。已在跑就不重复起。"""
    manager = manager or ai_jobs
    if manager.current(rebuild_all_scope(user_id)) is not None:
        return None
    sessions = session_factory or job_session_factory(user_id)

    async def runner(job: AIJob) -> dict[str, Any]:
        from app.models.project import Project
        from app.services import story_index_items
        from app.services.memory_service import memory_service

        if not memory_service.available:
            raise RuntimeError("向量模型没有加载，检索索引不可用")
        async with sessions() as db:
            projects = (await db.execute(
                select(Project.id, Project.title).where(Project.user_id == user_id).order_by(Project.created_at)
            )).all()
        total = 0
        for index, (project_id, title) in enumerate(projects, 1):
            job.progress(f"重建《{title}》的检索索引（{index}/{len(projects)}）", int(100 * (index - 1) / max(1, len(projects))))
            async with sessions() as db:
                items = await story_index_items.project_items(db, project_id)
            if items:
                total += await memory_service.rebuild(user_id, project_id, items)
        return {"projects": len(projects), "count": total}

    return await manager.start(
        kind=REBUILD_ALL_KIND,
        title="换模型后重建检索索引",
        user_id=user_id,
        scope=rebuild_all_scope(user_id),
        runner=runner,
        cancel_message="已停止重建；没重建的项目在打开故事账本 / 写正文时会自动补",
        meta={"model": runtime.get_embedding_model_name()},
    )


async def activate(model_id: str, *, user_id: str, manager: Optional[AIJobManager] = None) -> dict[str, Any]:
    """切换到已下载的模型（ValueError = 没下载 / 被环境变量锁定；RuntimeError = 加载失败），再起重建任务。"""
    manager = manager or ai_jobs
    if manager.current(DOWNLOAD_SCOPE) is not None:
        raise ValueError("正在下载模型，等下载完成后再切换")
    async with _switch_lock:
        await asyncio.to_thread(runtime.switch_model, model_id)
    job = await start_rebuild_all(user_id=user_id, manager=manager)
    return {"rebuild_job_id": job.id if job else None}


async def _download(job: AIJob, repo: str) -> None:
    if em.repo_present(repo):
        job.progress("本机已经下载过这个模型", 90)
        return
    job.progress("读取模型文件清单…", 2)
    endpoint, files = await asyncio.to_thread(em.remote_files, repo)
    total = sum(size for _, size in files) or 1
    done = 0
    for index, (name, size) in enumerate(files, 1):
        task = asyncio.ensure_future(asyncio.to_thread(em.download_file, repo, name, endpoint))
        while True:
            finished, _ = await asyncio.wait({task}, timeout=1.0)
            current = min(em.incomplete_bytes(repo), size) if size and not finished else (size if finished else 0)
            job.progress(
                f"下载 {name}（{index}/{len(files)}）· {em.human_size(done + current)} / {em.human_size(total)}",
                3 + int(90 * (done + current) / total),
            )
            if finished:
                break
        task.result()
        done += size
    if not em.repo_present(repo):
        raise RuntimeError(f"{repo} 下载完成但缺少模型权重文件，请重试")


async def start_download(
    model_id: str, *, user_id: str, activate: bool = True, manager: Optional[AIJobManager] = None,
) -> AIJob:
    """后台下载预设模型（全站同时只下一个）；activate=True 下完就切换并重建当前用户的检索索引。"""
    manager = manager or ai_jobs
    item = em.preset(model_id)
    if item is None:
        raise ValueError("只能下载列表里的预设模型；其它模型请手动放进 embedding 目录")

    async def runner(job: AIJob) -> dict[str, Any]:
        await _download(job, model_id)
        result: dict[str, Any] = {"model": model_id, "activated": False}
        if activate:
            job.progress("加载新模型…", 95)
            async with _switch_lock:
                await asyncio.to_thread(runtime.switch_model, model_id)
            rebuild = await start_rebuild_all(user_id=user_id, manager=manager)
            result.update(activated=True, rebuild_job_id=rebuild.id if rebuild else None)
        return result

    return await manager.start(
        kind=DOWNLOAD_KIND,
        title=f"下载向量模型：{item.label}",
        user_id=user_id,
        scope=DOWNLOAD_SCOPE,
        runner=runner,
        cancel_message="已停止下载；已下好的文件会保留，再次下载会接着下",
        meta={"model": model_id, "activate": activate},
    )
