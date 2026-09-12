"""应用配置管理"""
from pathlib import Path
from typing import Optional
import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 获取项目根目录(从backend/app/config.py向上两级)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# 配置模块使用标准logging（在logger.py初始化之前）
config_logger = logging.getLogger(__name__)

# 数据库配置在 Settings 中通过 pydantic-settings 从 .env 加载
# 不再在模块顶层用 os.getenv 提前检查，避免 .env 未加载时误报

class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        case_sensitive=False,
        extra="ignore",
    )
    
    # 应用配置
    app_name: str = "WenlanAI"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    
    # 日志配置
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_to_file: bool = True  # 是否输出到文件
    log_file_path: str = str(PROJECT_ROOT / "logs" / "app.log")
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 30  # 保留30个备份文件
    
    # CORS配置
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    
    # 数据库配置 - SQLite（嵌入式数据库，无需独立服务器）
    database_url: str = "sqlite+aiosqlite:///./data/mumuai.db"
    database_path: str = "./data/mumuai.db"

    # SQLite 连接池配置（SQLite 为单写者模式，仅需少量连接）
    database_pool_size: int = 5  # 核心连接池大小
    database_max_overflow: int = 5  # 最大溢出连接数
    database_pool_timeout: int = 30  # 连接池超时秒数
    database_pool_recycle: int = 3600  # 连接回收时间秒数
    database_pool_pre_ping: bool = True  # 连接前ping检测
    database_pool_use_lifo: bool = True  # 使用LIFO策略
    
    # 会话监控配置
    database_session_max_active: int = 50  # 活跃会话警告阈值（从100降低到50）
    database_session_leak_threshold: int = 100  # 会话泄漏严重告警阈值
    
    # 数据库监控配置
    database_enable_slow_query_log: bool = True  # 启用慢查询日志
    database_slow_query_threshold: float = 1.0  # 慢查询阈值（秒）
    database_enable_metrics: bool = True  # 启用性能指标收集
    
    # AI服务配置
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    default_ai_provider: str = "openai"
    default_model: str = "gpt-4"
    default_temperature: float = 0.7
    default_max_tokens: int = 2000
    # 采样多样性参数（降低"AI 味"/困惑度检测）：新用户首次同步到 Settings。
    # top_p<1 做核采样收敛；frequency/presence_penalty 提高用词多样性、抑制重复套路句。
    # 默认给一组温和的抗重复值；对 JSON 结构化生成（世界观/角色）几乎无影响，用户可在设置页调整。
    default_top_p: float = 0.95
    default_frequency_penalty: float = 0.3
    default_presence_penalty: float = 0.3
    # 思考/推理强度默认值（新用户首次同步到 Settings；默认关闭以兼容非推理模型）
    default_reasoning_enabled: bool = False
    default_reasoning_effort: str = "medium"  # none|minimal|low|medium|high|xhigh|max
    default_thinking_budget_tokens: Optional[int] = None  # Anthropic：空=按档位自动换算

    # 章节分析任务超时配置
    analysis_task_running_timeout_seconds: int = 300  # running 超过 5 分钟才视为卡死
    analysis_task_pending_timeout_seconds: int = 120  # pending 超过 2 分钟仍未启动则视为异常

    # 章节字数控制配置
    # 软目标区间：生成的章节字数应尽量落在 [target * (1 - soft_range), target * (1 + soft_range)] 内
    # 此参数仅用于生成 Prompt 中的字数范围提示，不会截断输出
    chapter_word_soft_range: float = 0.10  # ±10%

    # 以下参数暂不使用（保留以备将来需要）
    # API max_tokens 乘数：根据目标字数计算 max_tokens 上限（中文约 1字≈1token）
    chapter_max_tokens_factor: float = 1.3  # 目标字数 * 1.3（暂不使用，避免截断）
    # 极端兜底乘数：服务端流式生成时的硬截断阈值（防止失控）
    chapter_hard_cap_factor: float = 1.5  # 目标字数 * 1.5（暂不使用，避免截断）
    
    # 本地账户登录配置
    LOCAL_AUTH_ENABLED: bool = True  # 是否启用本地账户登录
    LOCAL_AUTH_USERNAME: Optional[str] = None  # 本地登录用户名
    LOCAL_AUTH_PASSWORD: Optional[str] = None  # 本地登录密码
    LOCAL_AUTH_DISPLAY_NAME: str = "本地用户"  # 本地用户显示名称
    
    # 会话配置
    SESSION_EXPIRE_MINUTES: int = 120  # 会话过期时间（分钟），默认2小时
    SESSION_REFRESH_THRESHOLD_MINUTES: int = 30  # 会话刷新阈值（分钟），剩余时间少于此值时可刷新

    # 检查更新（更新源 = GitHub Releases，tag v*，安装包资产 WenlanAI-Setup-v{ver}.exe；更新器按 .exe 后缀挑资产，名称仅示意）
    update_check_enabled: bool = True  # 内网/离线部署可关：关掉后不再联网检查
    update_repo: str = "ddys9621/WenlanAI"  # owner/repo（旧名 MuMuAINovel 已由 GitHub 永久重定向，老客户端仍可查更新）
    update_github_proxy: str = ""  # 安装包下载加速前缀（如 https://gh-proxy.com/），为空直连 github.com
    
    @property
    def app_version(self) -> str:
        """版本号唯一来源是 app/__init__.py 的 __version__，刻意不做成可被 .env / APP_VERSION 覆盖的字段：
        旧版 .env.example 写死过 APP_VERSION=1.0.0，若仍从环境读取，升级后检查更新会永远认为自己是 1.0.0。"""
        from app import __version__
        return __version__

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_value(cls, value):
        """兼容 DEBUG=release / production 等部署写法，避免导入期直接炸掉。"""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value


# 创建全局配置实例
settings = Settings()
config_logger.info(f"配置加载完成: {settings.app_name} v{settings.app_version}")
config_logger.debug(f"调试模式: {settings.debug}")
config_logger.debug(f"AI提供商: {settings.default_ai_provider}")
