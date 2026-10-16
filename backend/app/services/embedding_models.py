"""向量（记忆检索）模型的目录、本地安装情况、所选模型的持久化与下载。不 import sentence_transformers。

- 预设：bge-small-zh（默认）/ bge-base-zh / 多语 MiniLM（旧版）；embedding 目录里作者自己放进来的其它模型也列出来
  （只能选用，不提供在线下载：任意仓库的 pytorch 权重是 pickle，不放开）
- 所选模型存在 data/embedding_settings.json（与 data/chroma_db 一样相对运行目录）；环境变量 / .env 的 EMBEDDING_MODEL 优先
- 下载逐文件拉（HF_ENDPOINT → hf-mirror → huggingface.co），只拉一份权重（优先 safetensors）。运行中的服务已把
  huggingface_hub 固化成离线（HF_HUB_OFFLINE），下载期间用 online_mode() 临时放开、结束恢复

⚠️ huggingface_hub 一律在函数里懒导入：本模块会被 embedding_bootstrap 在设置离线变量之前 import。
"""
from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from glob import glob
from typing import Iterable, Iterator, Optional

from app.utils.runtime_paths import embedding_dir

EMBEDDING_PATH = embedding_dir()
SETTINGS_FILE = os.path.join("data", "embedding_settings.json")
DEFAULT_MIRROR = "https://hf-mirror.com"
OFFICIAL_ENDPOINT = "https://huggingface.co"
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
_SKIP_PREFIXES = ("onnx/", "openvino/", "coreml/")
_SKIP_SUFFIXES = (".h5", ".msgpack", ".ot", ".md", ".onnx", ".tflite", ".gitattributes", ".gitkeep")
_KEEP_SUFFIXES = (".json", ".txt", ".model")
_online_lock = threading.Lock()


@dataclass(frozen=True)
class EmbeddingPreset:
    id: str
    label: str
    size_label: str
    description: str
    language: str
    recommended: bool = False


PRESETS: tuple[EmbeddingPreset, ...] = (
    EmbeddingPreset(
        "BAAI/bge-small-zh-v1.5", "中文 · 轻量（bge-small-zh）", "约 95MB",
        "默认推荐：一次读 512 个 token，CPU 上编码快，长篇中文召回够用", "中文", recommended=True,
    ),
    EmbeddingPreset(
        "BAAI/bge-base-zh-v1.5", "中文 · 标准（bge-base-zh）", "约 400MB",
        "召回更准一些；编码耗时约为轻量版的 3 倍，适合章节多、电脑配置较好", "中文",
    ),
    EmbeddingPreset(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "多语 · 旧版（MiniLM）", "约 470MB",
        "旧版默认模型：一次只读 128 个 token（中文一百来字就截断），只为兼容保留", "多语",
    ),
)


def preset(model_id: str) -> Optional[EmbeddingPreset]:
    return next((p for p in PRESETS if p.id == model_id), None)


# ---------------- 本地安装情况 ----------------

def repo_dir(repo: str) -> str:
    return os.path.join(EMBEDDING_PATH, "models--" + repo.replace("/", "--"))


def repo_present(repo: str) -> bool:
    """HF 缓存结构里有权重文件 = 已安装（本地目录路径也认）。"""
    if os.path.isdir(repo):
        return any(os.path.isfile(os.path.join(repo, w)) for w in WEIGHT_FILES)
    snapshots = os.path.join(repo_dir(repo), "snapshots")
    return any(glob(os.path.join(snapshots, "*", w)) for w in WEIGHT_FILES)


def installed_models() -> list[str]:
    """embedding 目录里已有权重的模型（仓库 id，按名排序）。"""
    found = []
    for path in glob(os.path.join(EMBEDDING_PATH, "models--*")):
        parts = os.path.basename(path).split("--", 2)
        if len(parts) == 3:
            repo = f"{parts[1]}/{parts[2]}"
            if repo_present(repo):
                found.append(repo)
    return sorted(found)


def incomplete_bytes(repo: str) -> int:
    """正在下载的文件已写入的字节数（HF 先写 blobs/*.incomplete，下完再改名）。"""
    total = 0
    for path in glob(os.path.join(repo_dir(repo), "blobs", "*.incomplete")):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


# ---------------- 所选模型 ----------------

def _config_override() -> str:
    from app.config import settings as app_settings  # .env 里的 EMBEDDING_MODEL（pydantic 读取，不进 os.environ）

    return (getattr(app_settings, "embedding_model", "") or "").strip()


def env_override() -> str:
    """环境变量 / .env 指定的模型（指定了就以它为准，设置页不能改）。"""
    return (os.environ.get("EMBEDDING_MODEL") or "").strip() or _config_override()


def load_selection() -> Optional[str]:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            value = json.load(fh).get("model")
    except (OSError, ValueError, AttributeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_selection(model_id: str) -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"model": model_id}, fh, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)


# ---------------- 下载 ----------------

def endpoints() -> list[str]:
    out: list[str] = []
    for ep in (os.environ.get("HF_ENDPOINT"), DEFAULT_MIRROR, OFFICIAL_ENDPOINT):
        if ep and ep.rstrip("/") not in out:
            out.append(ep.rstrip("/"))
    return out


def select_repo_files(files: Iterable[str]) -> list[str]:
    """只要推理需要的文件：配置 / 分词器 / 池化层 + 一份权重（有 safetensors 就不要 pytorch_model.bin）。"""
    files = list(files)
    weight = next((w for w in WEIGHT_FILES if w in files), None)
    picked = []
    for name in files:
        if name in WEIGHT_FILES:
            if name == weight:
                picked.append(name)
            continue
        if name.startswith(_SKIP_PREFIXES) or name.endswith(_SKIP_SUFFIXES) or os.path.basename(name).startswith("."):
            continue
        if name.endswith(_KEEP_SUFFIXES):
            picked.append(name)
    return picked


@contextmanager
def online_mode() -> Iterator[None]:
    """临时放开 huggingface_hub 的离线模式（运行中的服务启动时已强制离线），结束后恢复并丢掉缓存的会话。"""
    from huggingface_hub import constants
    from huggingface_hub.utils import reset_sessions

    with _online_lock:
        prev_const = constants.HF_HUB_OFFLINE
        prev_env = {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
        constants.HF_HUB_OFFLINE = False
        for key in prev_env:
            os.environ.pop(key, None)
        reset_sessions()
        try:
            yield
        finally:
            constants.HF_HUB_OFFLINE = prev_const
            for key, value in prev_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_sessions()


def short_error(exc: BaseException) -> str:
    """下载失败原因的一句话说明（不把整段 urllib3 堆栈甩给作者）。"""
    text = f"{type(exc).__name__}: {exc}"
    if "Timeout" in text or "timed out" in text:
        return "连接超时"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 404:
        return "找不到这个模型"
    if status:
        return f"HTTP {status}"
    if "ConnectionError" in text or "Max retries" in text or "NewConnectionError" in text:
        return "连不上"
    return text[:120]


def _host(endpoint: str) -> str:
    return endpoint.split("://", 1)[-1]


def remote_files(repo: str) -> tuple[str, list[tuple[str, int]]]:
    """(可用的下载源, [(文件名, 字节数)])：逐个源试，返回第一个拿到文件清单的。"""
    from huggingface_hub import HfApi

    failures: list[str] = []
    for ep in endpoints():
        try:
            with online_mode():
                info = HfApi(endpoint=ep).model_info(repo, files_metadata=True, timeout=30)
            sizes = {s.rfilename: int(getattr(s, "size", None) or 0) for s in (info.siblings or [])}
            picked = select_repo_files(sizes)
            if picked:
                return ep, [(name, sizes.get(name, 0)) for name in picked]
            failures.append(f"{_host(ep)}：清单里没有模型权重")
        except Exception as exc:  # noqa: BLE001 - 换下一个源
            failures.append(f"{_host(ep)}：{short_error(exc)}")
    raise RuntimeError(f"拿不到 {repo} 的文件清单（{'；'.join(failures)}），请检查网络后重试")


def download_file(repo: str, filename: str, preferred: Optional[str] = None) -> str:
    """下载单个文件到 embedding 目录（HF 缓存结构）；先用 preferred 源，失败依次换源。同步函数，放线程里跑。"""
    from huggingface_hub import hf_hub_download

    order = [preferred] if preferred else []
    order += [ep for ep in endpoints() if ep != preferred]
    failures: list[str] = []
    for ep in order:
        try:
            with online_mode():
                return hf_hub_download(repo, filename, cache_dir=EMBEDDING_PATH, endpoint=ep, etag_timeout=30)
        except Exception as exc:  # noqa: BLE001 - 换下一个源
            failures.append(f"{_host(ep)}：{short_error(exc)}")
    raise RuntimeError(f"下载 {filename} 失败（{'；'.join(failures)}），已下好的部分会保留，重试会接着下")


def human_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


_REPO_ID = re.compile(r"^[\w.-]+/[\w.-]+$")


def valid_repo_id(value: str) -> bool:
    return bool(_REPO_ID.match(value or ""))
