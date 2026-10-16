"""共享的向量运行时：一个 chromadb 客户端 + 一份 SentenceTransformer。

MemoryService / WorldRuleService 此前各自 new 一份（实测第二份多占 ~300MB 内存、多花 ~1.6s 启动）。

⚠️ 环境变量必须在 import sentence_transformers / huggingface_hub 之前设置：
huggingface_hub 在 import 时就把 HF_HUB_OFFLINE 固化为常量，先 import 再设等于没设——
无本地模型时会发起无超时的 HF 网络请求，在 HF 不可达的环境（如国内直连）下进程永久挂死。
"""
import os
import threading

from app.services import embedding_models  # 不 import huggingface_hub，放在离线变量之前无妨
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
# 默认中文向量模型：512 token、约 95MB；旧版内置的多语 MiniLM（128 token，中文一百来字就截断）降为兜底
PRIMARY_MODEL = 'BAAI/bge-small-zh-v1.5'
FALLBACK_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
LEGACY_FALLBACK_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
BUILTIN_MODELS = (PRIMARY_MODEL, FALLBACK_MODEL, LEGACY_FALLBACK_MODEL)
# bge 中文模型做「短查询 → 段落」检索时，查询前加这句指令召回更准（入库的段落不加）
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
ENCODE_BATCH = 32

_client = None
_model = None
_model_name: str | None = None
_model_attempted = False
# 持有 embedding_model / client 引用的检索服务（MemoryService / WorldRuleService）：运行中换模型时一起换
_consumers: list = []
_swap_lock = threading.Lock()


def configured_model_names() -> tuple[str, ...]:
    """加载顺序：环境变量 / .env 的 EMBEDDING_MODEL → 设置页选的模型（data/embedding_settings.json）
    → bge-small-zh → 多语 MiniLM → 英文 MiniLM。前面的没下载 / 加载失败就往后退。"""
    picked = (embedding_models.env_override(), embedding_models.load_selection() or "")
    return tuple(dict.fromkeys(n for n in (*picked, *BUILTIN_MODELS) if n))


def get_embedding_model_name() -> str | None:
    """实际加载成功的模型名（未加载 / 加载失败为 None）。"""
    return _model_name


def register_consumer(service) -> None:
    """检索服务登记自己（要有 client / embedding_model 两个属性），换模型时由 switch_model 统一更新。"""
    if service not in _consumers:
        _consumers.append(service)


def loaded_model_info() -> dict | None:
    """当前模型的名字、向量维度、一次最多读的 token 数（没加载为 None）。"""
    if _model is None or not _model_name:
        return None
    try:
        dimension = int(_model.get_sentence_embedding_dimension() or 0) or None
    except Exception:  # noqa: BLE001 - 只用于展示
        dimension = None
    max_tokens = getattr(_model, "max_seq_length", None)
    return {"name": _model_name, "dimension": dimension, "max_tokens": int(max_tokens) if isinstance(max_tokens, int) else None}


def switch_model(name: str) -> str:
    """运行中换向量模型（设置页「使用」）：先在本地加载新模型，成功了才换掉旧的、记住选择、通知各检索服务。

    同步且较慢（加载权重几秒），调用方放线程里跑。集合名带模型指纹，换模型 = 换集合：各项目的检索索引
    在下次打开故事账本 / 写正文时按账本自动重建，世界规则在下次检索时补齐。
    """
    global _model, _model_name, _model_attempted
    name = (name or "").strip()
    locked = embedding_models.env_override()
    if locked and locked != name:
        raise ValueError(f"向量模型由环境变量 / 配置文件 EMBEDDING_MODEL 指定为 {locked}，设置页不能切换")
    if not embedding_models.repo_present(name):
        raise ValueError(f"还没下载 {name}，请先下载")
    try:
        model = SentenceTransformer(name, cache_folder=EMBEDDING_PATH, device='cpu', trust_remote_code=False, local_files_only=True)
    except Exception as exc:
        raise RuntimeError(f"加载 {name} 失败：{exc}") from exc
    with _swap_lock:
        _model, _model_name, _model_attempted = model, name, True
        client = get_chroma_client()
        for service in _consumers:
            service.embedding_model = model
            if getattr(service, "client", None) is None:
                service.client = client
    embedding_models.save_selection(name)
    logger.info(f"🔁 向量模型已切换为 {name}")
    return name


def collection_suffix() -> str:
    """不同模型的向量维度 / 语义空间不同，不能混存：集合名带上实际加载模型的指纹（换模型 = 换集合，按需重建）。"""
    import hashlib

    if not _model_name:
        return ""
    return "_e" + hashlib.sha256(_model_name.encode()).hexdigest()[:6]


def query_instruction() -> str:
    name = (_model_name or "").lower()
    return BGE_QUERY_INSTRUCTION if "bge" in name and "zh" in name else ""


def encode_texts(model, texts: list[str]) -> list[list[float]]:
    """批量编码（归一化后用余弦距离）；同步函数，调用方放进线程里跑，别卡事件循环。"""
    if not texts:
        return []
    vectors = model.encode(list(texts), batch_size=ENCODE_BATCH, normalize_embeddings=True, show_progress_bar=False)
    return [list(map(float, v)) for v in (vectors.tolist() if hasattr(vectors, "tolist") else vectors)]


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

    logger.error("❌ 所有模型加载失败：请把模型文件放到 embedding 目录（桌面版启动器会尝试自动下载）")
    logger.error(f"   期望的模型目录: {os.path.abspath(EMBEDDING_PATH)}/models--BAAI--bge-small-zh-v1.5/")
    return None
