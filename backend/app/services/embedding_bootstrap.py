"""Embedding 模型首启引导（桌面版启动器调用）

背景：打包 exe 不内置 embedding 模型。首次启动时由 start_app.py 调用本模块：
1. 检查本地 embedding 目录是否已有模型
2. 缺失则经 hf-mirror（可用 HF_ENDPOINT 覆盖）自动下载中文模型 bge-small-zh-v1.5（约 95MB）
3. 下载失败 → 返回 False，应用以「无向量检索」降级模式继续运行（召回只用人物 / 关键词匹配）

升级：旧版下载的是多语 MiniLM（约 470MB，只吃 128 token）。只有旧模型时应用照常能用（model_present 为真），
启动器会顺带尝试下载中文模型；下载失败继续用旧模型，一天内不再重试（has_recent_failure）。
作者在「设置 → 记忆检索」里明确选过的模型优先（preferred_model）：选了旧模型就不再自动升级。

注意：必须在 import sentence_transformers / memory_service 之前调用，
否则 HF_HUB_OFFLINE 常量固化后无法联网下载。
"""
from __future__ import annotations

import os
import time
from typing import Callable

from app.services import embedding_models

MODEL_REPO = "BAAI/bge-small-zh-v1.5"
LEGACY_MODEL_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_SIZE_LABEL = "约 95MB"
FAILURE_MARKER = ".bge_download_failed"
RETRY_AFTER_SECONDS = 24 * 3600

# 与 memory_service 保持一致：源码/容器 = backend/embedding；exe = {app}\embedding（不放 _internal，升级会被整目录替换）
from app.utils.runtime_paths import embedding_dir, runtime_base_dir

BASE_DIR = runtime_base_dir()
EMBEDDING_PATH = embedding_dir()


def _repo_present(repo: str) -> bool:
    return embedding_models.repo_present(repo)


def preferred_model() -> str:
    """应用会先用的模型：环境变量 / .env 指定的 → 设置页选的 → 默认中文模型。"""
    return embedding_models.env_override() or embedding_models.load_selection() or MODEL_REPO


def primary_model_present() -> bool:
    """首选模型已就绪（默认是中文 bge；作者在设置页选过别的就看那个）。"""
    return _repo_present(preferred_model())


def model_present() -> bool:
    """embedding 目录里有任何一个能用的模型：应用可以直接启动。"""
    return bool(embedding_models.installed_models())


def _marker_path() -> str:
    return os.path.join(EMBEDDING_PATH, FAILURE_MARKER)


def has_recent_failure(now: float | None = None) -> bool:
    """上次自动升级下载失败还不到一天：别每次启动都卡在下载上。"""
    try:
        return (now or time.time()) - os.path.getmtime(_marker_path()) < RETRY_AFTER_SECONDS
    except OSError:
        return False


def _mark_failure(failed: bool) -> None:
    try:
        if failed:
            os.makedirs(EMBEDDING_PATH, exist_ok=True)
            with open(_marker_path(), "w", encoding="utf-8") as fh:
                fh.write(str(int(time.time())))
        elif os.path.exists(_marker_path()):
            os.remove(_marker_path())
    except OSError:
        pass


def _download_target() -> str:
    """要下载的模型：首选模型是预设就下它；环境变量指定的自定义模型不在线下载（来源不明），退回默认中文模型。"""
    wanted = preferred_model()
    return wanted if embedding_models.preset(wanted) else MODEL_REPO


def download_repo(repo: str, log: Callable[[str, str], None]) -> bool:
    """逐文件下载一个模型（只拉推理需要的文件、一份权重）；每个文件依次换源。成功 = 权重已就绪。"""
    try:
        endpoint, files = embedding_models.remote_files(repo)
    except Exception as e:  # noqa: BLE001 - 所有源都拿不到清单
        log("WARNING", f"⚠️ {str(e)[:200]}")
        return False
    total = sum(size for _, size in files)
    log("INFO", f"⏬ 从 {endpoint} 下载 {len(files)} 个文件（共 {embedding_models.human_size(total)}，视网络约 1-3 分钟）…")
    for name, size in files:
        try:
            embedding_models.download_file(repo, name, endpoint)
        except Exception as e:  # noqa: BLE001
            log("WARNING", f"⚠️ {str(e)[:200]}")
            return False
        if size >= 5 * 1024 * 1024:
            log("INFO", f"  ✓ {name}（{embedding_models.human_size(size)}）")
    return _repo_present(repo)


def ensure_embedding_model(log: Callable[[str, str], None]) -> bool:
    """确保首选的 embedding 模型就绪；缺失则逐文件下载。

    下载源顺序：HF_ENDPOINT 环境变量（若设）→ hf-mirror → 官方 huggingface.co；单个文件失败自动换源。

    Returns:
        True = 首选模型可用；False = 下载失败（有别的模型就继续用，否则降级运行）
    """
    if primary_model_present():
        log("INFO", "✅ Embedding 模型已就绪")
        return True

    repo = _download_target()
    item = embedding_models.preset(repo)
    label = item.label if item else repo
    size = item.size_label if item else MODEL_SIZE_LABEL
    log("WARNING", f"📥 下载 AI 记忆模型 {label}（{size}）")
    os.makedirs(EMBEDDING_PATH, exist_ok=True)
    if download_repo(repo, log):
        _mark_failure(False)
        log("INFO", "✅ Embedding 模型下载完成")
        return True

    _mark_failure(True)
    log("ERROR", "❌ 所有下载源均失败")
    if model_present():
        log("WARNING", "⚠️ 本次继续使用已有的记忆模型，明天启动时会再试")
    else:
        log("WARNING", "⚠️ 可改选「导入本地模型包」或「跳过」（跳过后语义检索不可用，其余功能正常）")
    log("INFO", f"💡 也可以进入应用后在「设置 → 记忆检索」里重新下载；或把模型文件夹放入 {EMBEDDING_PATH} 后重启"
                f"（目录结构为 models--BAAI--bge-small-zh-v1.5/snapshots/<hash>/）")
    return False


def import_model_zip(zip_path: str, log: Callable[[str, str], None]) -> bool:
    """从本地 zip 导入模型（离线分发场景：模型包随群文件/网盘单独提供）。

    支持两种压缩包结构（中文 bge 或旧版 MiniLM 都认）：
    1. 顶层为 embedding/models--…（官方离线包结构）→ 解压到 backend 根
    2. 顶层直接是 models--…                         → 解压到 embedding/

    Returns:
        True = 导入成功且校验通过
    """
    import zipfile

    if not zip_path or not os.path.isfile(zip_path):
        log("ERROR", f"❌ 文件不存在：{zip_path}")
        return False

    log("INFO", f"📦 正在导入模型包：{os.path.basename(zip_path)} …")
    prefixes = tuple("models--" + repo.replace("/", "--") for repo in (MODEL_REPO, LEGACY_MODEL_REPO))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # zip-slip 防护：拒绝绝对路径与路径穿越
            for n in names:
                if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/"):
                    log("ERROR", f"❌ 压缩包含非法路径，已拒绝导入：{n}")
                    return False

            if any(n.replace("\\", "/").startswith("embedding/") for n in names):
                dest = BASE_DIR          # 结构1：包内自带 embedding/ 层
            elif any(n.replace("\\", "/").startswith(prefixes) for n in names):
                dest = EMBEDDING_PATH    # 结构2：包内直接是 models--… 层
            else:
                log("ERROR", "❌ 压缩包结构不符：应包含 embedding/ 或 "
                             f"{prefixes[0]}/ 目录")
                return False

            os.makedirs(dest, exist_ok=True)
            zf.extractall(dest)
    except Exception as e:
        log("ERROR", f"❌ 解压失败：{e}")
        return False

    if model_present():
        log("INFO", "✅ 模型导入完成")
        return True
    log("ERROR", "❌ 解压完成但未通过校验（缺少模型权重文件）")
    return False
