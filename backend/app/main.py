"""FastAPI应用主入口"""
import sys
from pathlib import Path

# 在导入其他模块之前，先加载外部配置文件
# 这样可以确保配置在所有模块加载前生效
if getattr(sys, 'frozen', False):
    # 打包后的 exe 环境
    sys.path.insert(0, str(Path(sys.executable).parent / 'backend'))
    from config_loader import init_config
    init_config()

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from contextlib import asynccontextmanager

from app.config import settings as config_settings
from app.database import close_db, _session_stats, check_database_health
from app.logger import setup_logging, get_logger
from app.middleware import RequestIDMiddleware
from app.middleware.auth_middleware import AuthMiddleware
from app.mcp.registry import mcp_registry
from app.migrations.auto_migrator import run_auto_migrations

setup_logging(
    level=config_settings.log_level,
    log_to_file=config_settings.log_to_file,
    log_file_path=config_settings.log_file_path,
    max_bytes=config_settings.log_max_bytes,
    backup_count=config_settings.log_backup_count
)
logger = get_logger(__name__)

_startup_state = {
    "database_ready": False,
    "database_error": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动，初始化数据库表结构...")

    # 在应用启动时初始化数据库表结构
    try:
        from app.database import get_engine, Base

        # 使用全局引擎创建所有表
        engine = await get_engine("_global_init_")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 自动执行需要的迁移（幂等）
        await run_auto_migrations(engine)

        _startup_state["database_ready"] = True
        _startup_state["database_error"] = None
        logger.info("✅ 数据库表结构初始化成功")
    except Exception as e:
        _startup_state["database_ready"] = False
        _startup_state["database_error"] = str(e)
        logger.error(f"❌ 数据库表结构初始化失败: {str(e)}", exc_info=True)
        # 不阻止应用启动，允许在后续操作中重试

    # 启动 MCP 后台任务（现在有事件循环了）
    try:
        mcp_registry._start_background_tasks()
        logger.info("✅ MCP 后台任务已启动")
    except Exception as e:
        logger.warning(f"⚠️ MCP 后台任务启动失败: {str(e)}")

    logger.info("应用启动完成，等待用户登录...")

    yield

    # 停掉仍在跑的 AI 后台任务（桥段填充 / 角色生成 …；各业务表状态由 runner 保证可续跑）
    try:
        from app.services.ai_jobs import ai_jobs
        await ai_jobs.shutdown()
    except Exception as e:
        logger.warning(f"⚠️ AI 后台任务清理失败: {str(e)}")

    # 清理AI服务HTTP客户端资源
    try:
        from app.services.ai_service import ai_service
        await ai_service.close()
        logger.info("✅ AI服务资源已清理")
    except Exception as e:
        logger.warning(f"⚠️ AI服务资源清理失败: {str(e)}")

    # 清理MCP插件
    await mcp_registry.cleanup_all()
    await close_db()
    logger.info("应用已关闭")


app = FastAPI(
    title=config_settings.app_name,
    version=config_settings.app_version,
    description="AI写小说工具 - 智能小说创作助手",
    lifespan=lifespan
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证错误"""
    logger.error(f"请求验证失败: {exc.errors()}")
    # pydantic v2 的 field_validator 抛 ValueError 时 errors()[i]["ctx"]["error"] 是异常对象，直接塞进 JSONResponse 会
    # TypeError 变成 500；用 jsonable_encoder 与 FastAPI 默认处理器保持一致
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "请求参数验证失败",
            "errors": jsonable_encoder(exc.errors())
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的异常"""
    logger.error(f"未处理的异常: {type(exc).__name__}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "服务器内部错误",
            "message": str(exc) if config_settings.debug else "请稍后重试"
        }
    )

app.add_middleware(RequestIDMiddleware)
app.add_middleware(AuthMiddleware)

if config_settings.debug:
    # ⚠️ 安全警告：调试模式下 CORS 允许所有来源
    # 生产环境请确保 debug=False，否则存在安全风险
    logger.warning("⚠️ [安全警告] 调试模式已启用，CORS 允许所有来源 (allow_origins=['*'])")
    logger.warning("⚠️ [安全警告] 生产环境请设置 DEBUG=false 以启用严格的 CORS 策略")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    logger.info(f"✅ CORS 已配置为仅允许以下来源: {config_settings.cors_origins}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health_check():
    """进程存活检查：只表示 HTTP 服务还在响应。"""
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness_check():
    """服务就绪检查：部署和容器健康检查必须走这里。"""
    if not _startup_state["database_ready"]:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "checks": {
                    "startup_database": {
                        "healthy": False,
                        "error": _startup_state["database_error"] or "database initialization not completed",
                    }
                },
            },
        )

    db_health = await check_database_health()
    if not db_health.get("healthy"):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "checks": {
                    "startup_database": {"healthy": True},
                    "database": db_health,
                },
            },
        )

    return {
        "status": "ok",
        "checks": {
            "startup_database": {"healthy": True},
            "database": db_health,
        },
    }


@app.get("/health/db-sessions")
async def db_session_stats():
    """
    数据库会话统计（监控连接泄漏）
    
    返回：
    - created: 总创建会话数
    - closed: 总关闭会话数
    - active: 当前活跃会话数（应该接近0）
    - errors: 错误次数
    - generator_exits: SSE断开次数
    - last_check: 最后检查时间
    """
    return {
        "status": "ok",
        "session_stats": _session_stats,
        "warning": "活跃会话数过多" if _session_stats["active"] > 10 else None
    }


from app.api import (
    projects, characters, chapters,
    wizard_stream, relationships, organizations,
    auth, settings, writing_styles, memories,
    mcp_plugins, mcp_marketplace, admin, inspiration,
    plot_cards, plot_lines, chapter_outlines, story_outlines,
    world_rules, scene_generation, book_dissect,
    reference_pack, imitation, announcement
)

app.include_router(auth.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(announcement.router, prefix="/api")  # 登录后公告弹窗（管理员在用户管理页配置）

# 系统更新：检查 GitHub Release / 一键更新（exe 下载安装包、源码 git pull、容器给命令）
from app.api import system_update as _system_update
app.include_router(_system_update.router, prefix="/api")

app.include_router(projects.router, prefix="/api")
app.include_router(wizard_stream.router, prefix="/api")
app.include_router(inspiration.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(chapters.router, prefix="/api")
app.include_router(relationships.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(writing_styles.router, prefix="/api")
app.include_router(memories.router)  # 记忆管理API (已包含/api前缀)
app.include_router(mcp_plugins.router, prefix="/api")  # MCP插件管理API
app.include_router(mcp_marketplace.router, prefix="/api")  # MCP商城（内置精选目录 + 一键安装）

# 新增剧情相关API
app.include_router(story_outlines.router, prefix="/api")
app.include_router(plot_cards.router, prefix="/api")
app.include_router(plot_lines.router, prefix="/api")
app.include_router(chapter_outlines.router, prefix="/api")

# V4.1 K2 桥段四章结构 API
from app.api import plot_bridges as _plot_bridges
app.include_router(_plot_bridges.router, prefix="/api")

# 通用 AI 后台任务：列表 / 快照 / 回放续尾 / 取消（各业务的发起端点仍在各自模块）
from app.api import ai_jobs as _ai_jobs_api
app.include_router(_ai_jobs_api.router, prefix="/api")

# 世界规则系统API
app.include_router(world_rules.router, prefix="/api")

# 场景生成API（场景级创作循环）
app.include_router(scene_generation.router, prefix="/api")

# 拆书参考 API（上传参考书反向拆解为创作素材）
app.include_router(book_dissect.router, prefix="/api")

# V3 仿写：参考包（独立资料库）+ 项目挂载关联
app.include_router(reference_pack.router, prefix="/api")
app.include_router(reference_pack.project_router, prefix="/api")

# V3 仿写 R5：项目内章节编辑器的一键仿写（preview / SSE 流式）
app.include_router(imitation.router, prefix="/api")

# 项目级 AI 偏好：复用设置页接口，按项目覆盖模型 / 参数（生效点：get_user_ai_service 读 X-Project-Id）
from app.api import project_ai_preference as _project_ai_preference
app.include_router(_project_ai_preference.router, prefix="/api")

# 项目级去 AI 味提示词（只在重写正文时注入）
from app.api import deai_prompts as _deai_prompts
app.include_router(_deai_prompts.router, prefix="/api")

# 静态文件目录（兼容打包后的环境）
if getattr(sys, 'frozen', False):
    # 打包后的 exe：static 在 _internal 目录下
    static_dir = Path(sys.executable).parent / "_internal" / "static"
else:
    # 开发环境：static 在 backend 目录下
    static_dir = Path(__file__).parent.parent / "static"

if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """服务单页应用，所有非API路径返回index.html"""
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "API路径不存在"}
            )
        
        file_path = static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        
        return JSONResponse(
            status_code=404,
            content={"detail": "页面不存在"}
        )
else:
    logger.warning("静态文件目录不存在，请先构建前端: cd frontend && npm run build")
    
    @app.get("/")
    async def root():
        return {
            "message": "欢迎使用AI Story Creator",
            "version": config_settings.app_version,
            "docs": "/docs",
            "notice": "请先构建前端: cd frontend && npm run build"
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config_settings.app_host,
        port=config_settings.app_port,
        reload=config_settings.debug
    )
