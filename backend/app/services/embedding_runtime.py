"""共享的向量运行时：一个 chromadb 客户端 + 一份 SentenceTransformer。

MemoryService / WorldRuleService 此前各自 new 一份（实测第二份多占 ~300MB 内存、多花 ~1.6s 启动）。

⚠️ 环境变量必须在 import sentence_transformers / huggingface_hub 之前设置：
huggingface_hub 在 import 时就把 HF_HUB_OFFLINE 固化为常量，先 import 再设等于没设——
无本地模型时会发起无超时的 HF 网络请求，在 HF 不可达的环境（如国内直连）下进程永久挂死。
"""
import os

from app.utils.runtime_paths import embedding_dir  # 源码/容器 = backend/embedding；exe = {app}\embedding（不在 _internal 内）

EMBEDDING_PATH = embedding_dir()

if 'SENTENCE_TRANSFORMERS_HOME' not in os.environ:
    os.environ['SENTENCE_TRANSFORMERS_HOME'] = EMBEDDING_PATH

# 强制使用离线模式，避免重新下载
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_OFFLINE'] = '1'

import chromadb  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

from app.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

CHROMA_DIR = "data/chroma_db"
PRIMARY_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
FALLBACK_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
BUILTIN_MODELS = (PRIMARY_MODEL, FALLBACK_MODEL)

_client = None
_model = None
_model_name: str | None = None
_model_attempted = False


def configured_model_names() -> tuple[str, ...]:
    """加载顺序：环境变量 EMBEDDING_MODEL（如 BAAI/bge-small-zh-v1.5、BAAI/bge-m3，需事先放进 embedding 目录）→ 主模型 → 备用。

    MiniLM 只吃 128 个 token（中文一百多字就截断），长篇里检索章纲 / 摘要偏弱；换中文向量模型能明显提高召回。
    """
    custom = (os.environ.get("EMBEDDING_MODEL") or "").strip()
    if not custom:
        from app.config import settings as app_settings  # .env 里的 EMBEDDING_MODEL（pydantic 读取，不进 os.environ）

        custom = (getattr(app_settings, "embedding_model", "") or "").strip()
    return tuple(dict.fromkeys(n for n in (custom, PRIMARY_MODEL, FALLBACK_MODEL) if n))


def get_embedding_model_name() -> str | None:
    """实际加载成功的模型名（未加载 / 加载失败为 None）。"""
    return _model_name


def collection_suffix() -> str:
    """自定义向量模型的维度可能和内置 MiniLM（384 维）不同，向量不能混存：换模型后集合名带上模型指纹。
    内置主 / 备模型保持旧集合名（老数据不丢）。"""
    import hashlib

    if not _model_name or _model_name in BUILTIN_MODELS:
        return ""
    return "_e" + hashlib.sha256(_model_name.encode()).hexdigest()[:6]


def get_chroma_client():
    """返回进程内唯一的 ChromaDB PersistentClient（首次调用时创建）。"""
    global _client
    if _client is None:
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def get_embedding_model():
    """返回共享的 embedding 模型；主模型失败退备用模型，都失败返回 None。只尝试一次。

    仅从本地 embedding 目录加载（local_files_only + 上方 offline 环境变量）：
    缺模型时快速失败并给出下载指引，绝不在运行时静默联网。
    """
    global _model, _model_name, _model_attempted
    if _model_attempted:
        return _model
    _model_attempted = True

    os.makedirs(EMBEDDING_PATH, exist_ok=True)
    logger.info(f"🔄 正在加载Embedding模型... 模型目录: {os.path.abspath(EMBEDDING_PATH)}")
    for name in configured_model_names():
        try:
            _model = SentenceTransformer(
                name,
                cache_folder=EMBEDDING_PATH,
                device='cpu',  # 明确指定使用CPU
                trust_remote_code=False,  # 安全起见
                local_files_only=True,  # 强制使用本地文件
            )
            _model_name = name
            logger.info(f"✅ Embedding模型加载成功 ({name})")
            return _model
        except Exception as e:
            logger.warning(f"⚠️ 无法加载 Embedding 模型 {name}: {e!r}")

    logger.error("❌ 所有模型加载失败：请把模型文件放到 embedding 目录（群文件提供，约 420MB）")
    logger.error(f"   期望的模型目录: {os.path.abspath(EMBEDDING_PATH)}/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/")
    return None
