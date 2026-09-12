"""数据库连接和会话管理 - SQLite 嵌入式数据库"""
import asyncio
from typing import Dict, Any
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import Request, HTTPException
from app.config import settings
from app.db_base import Base
from app.logger import get_logger

logger = get_logger(__name__)

# 导入所有模型，确保 Base.metadata 能够发现它们
# 这必须在 Base 创建之后、init_db 之前导入
# 注意：这里不能再走 app.models 聚合入口，否则会触发
# database -> app.models -> model -> database 的循环导入。
from app.models.analysis_task import AnalysisTask  # noqa: F401
from app.models.book_dissect_task import BookDissectTask  # noqa: F401
from app.models.book_dissect_chapter_fact import BookDissectChapterFact  # noqa: F401
from app.models.book_dissect_dictionary import BookDissectDictionary  # noqa: F401
from app.models.book_dissect_entity import BookDissectEntity  # noqa: F401
from app.models.book_dissect_relation import BookDissectRelation  # noqa: F401
from app.models.book_dissect_event import BookDissectEvent  # noqa: F401
from app.models.chapter import Chapter  # noqa: F401
from app.models.chapter_causal_link import ChapterCausalLink  # noqa: F401
from app.models.chapter_consistency_issue import ChapterConsistencyIssue  # noqa: F401
from app.models.chapter_continuity_signal import ChapterContinuitySignal  # noqa: F401
from app.models.chapter_outline import ChapterOutline  # noqa: F401
from app.models.character import Character  # noqa: F401
from app.models.deai_prompt import DeaiPrompt  # noqa: F401
from app.models.character_known_info import CharacterKnownInfo  # noqa: F401
from app.models.generation_history import GenerationHistory  # noqa: F401
from app.models.memory import PlotAnalysis, StoryMemory  # noqa: F401
from app.models.narrative_promise import NarrativePromise  # noqa: F401
from app.models.plot_bridge import PlotBridge  # noqa: F401
from app.models.plot_card import PlotCard  # noqa: F401
from app.models.plot_line import PlotLine  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_default_style import ProjectDefaultStyle  # noqa: F401
from app.models.project_ai_preference import ProjectAIPreference  # noqa: F401
from app.models.project_reference_pack import ProjectReferencePack  # noqa: F401
from app.models.reference_pack import ReferencePack  # noqa: F401
from app.models.regeneration_task import RegenerationTask  # noqa: F401
from app.models.relationship import (  # noqa: F401
    CharacterRelationship,
    Organization,
    OrganizationMember,
    RelationshipType,
)
from app.models.relationship_event import RelationshipEvent  # noqa: F401
from app.models.settings import Settings  # noqa: F401
from app.models.story_outline import StoryOutline  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
from app.models.timeline_event import TimelineEvent  # noqa: F401
from app.models.world_rule import WorldRule  # noqa: F401
from app.models.writing_style import WritingStyle  # noqa: F401

# 引擎缓存：每个用户一个引擎
_engine_cache: Dict[str, Any] = {}

# 锁管理：用于保护引擎创建过程
_engine_locks: Dict[str, asyncio.Lock] = {}
_cache_lock = asyncio.Lock()

# 会话统计（用于监控连接泄漏）
_session_stats = {
    "created": 0,
    "closed": 0,
    "active": 0,
    "errors": 0,
    "generator_exits": 0,
    "last_check": None
}


async def get_engine(user_id: str):
    """获取或创建数据库引擎（线程安全）

    SQLite: 所有用户共享一个数据库文件，数据通过user_id字段隔离

    Args:
        user_id: 用户ID

    Returns:
        异步引擎
    """
    cache_key = "shared_sqlite"
    if cache_key in _engine_cache:
        return _engine_cache[cache_key]

    async with _cache_lock:
        if cache_key not in _engine_cache:
            # SQLite 连接配置（桌面应用使用 StaticPool 避免并发写入冲突）
            connect_args = {
                "check_same_thread": False,
            }

            engine = create_async_engine(
                settings.database_url,
                echo=False,
                future=True,
                poolclass=StaticPool,
                connect_args=connect_args
            )
            _engine_cache[cache_key] = engine
            logger.info(
                f"SQLite引擎已创建\n"
                f"   ├─ 数据库文件: {settings.database_path}\n"
                f"   └─ 嵌入式数据库，无需独立服务器"
            )

        return _engine_cache[cache_key]


async def get_db(request: Request):
    """获取数据库会话的依赖函数
    
    从 request.state.user_id 获取用户ID，然后返回该用户的数据库会话
    """
    user_id = getattr(request.state, "user_id", None)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或用户ID缺失")
    
    engine = await get_engine(user_id)
    
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    session = AsyncSessionLocal()
    session_id = id(session)
    
    global _session_stats
    _session_stats["created"] += 1
    _session_stats["active"] += 1
    
    rollback_handled = False

    async def rollback_if_needed(log_message: str = None, log_level: str = "info"):
        nonlocal rollback_handled
        if rollback_handled or not session.in_transaction():
            return False

        # 进入 rollback 前先标记，避免异常链路里重复触发 rollback()
        rollback_handled = True
        await session.rollback()

        if log_message:
            getattr(logger, log_level)(log_message)

        return True

    logger.debug(f"📊 会话创建 [User:{user_id}][ID:{session_id}] - 活跃:{_session_stats['active']}, 总创建:{_session_stats['created']}, 总关闭:{_session_stats['closed']}")
    
    try:
        yield session
        await rollback_if_needed()
    except GeneratorExit:
        _session_stats["generator_exits"] += 1
        logger.warning(f"⚠️ GeneratorExit [User:{user_id}][ID:{session_id}] - SSE连接断开（总计:{_session_stats['generator_exits']}次）")
        try:
            await rollback_if_needed(
                f"✅ 事务已回滚 [User:{user_id}][ID:{session_id}]（GeneratorExit）"
            )
        except Exception as rollback_error:
            _session_stats["errors"] += 1
            logger.error(f"❌ GeneratorExit回滚失败 [User:{user_id}][ID:{session_id}]: {str(rollback_error)}")
    except Exception as e:
        _session_stats["errors"] += 1

        # 检测是否为 MCP 相关异常，使用简化日志
        from app.exceptions import MCPToolNotTriggeredError, MCPPlanningFailedError
        if isinstance(e, (MCPToolNotTriggeredError, MCPPlanningFailedError)):
            # MCP 异常已在底层记录详细信息，这里只记录简化版本
            logger.debug(f"📝 会话异常 [User:{user_id}][ID:{session_id}]: MCP 异常（已在底层记录）")
        else:
            # 其他异常记录完整信息
            logger.error(f"❌ 会话异常 [User:{user_id}][ID:{session_id}]: {str(e)}")

        try:
            await rollback_if_needed(
                f"✅ 事务已回滚 [User:{user_id}][ID:{session_id}]（异常）"
            )
        except Exception as rollback_error:
            logger.error(f"❌ 异常回滚失败 [User:{user_id}][ID:{session_id}]: {str(rollback_error)}")
        raise
    finally:
        try:
            await rollback_if_needed(
                f"⚠️ finally中发现未提交事务 [User:{user_id}][ID:{session_id}]，已回滚",
                "warning"
            )
            
            await session.close()

            _session_stats["closed"] += 1
            # 使用 max(0, ...) 防止活跃会话数出现负数
            _session_stats["active"] = max(0, _session_stats["active"] - 1)
            _session_stats["last_check"] = datetime.now().isoformat()

            logger.debug(f"📊 会话关闭 [User:{user_id}][ID:{session_id}] - 活跃:{_session_stats['active']}, 总创建:{_session_stats['created']}, 总关闭:{_session_stats['closed']}, 错误:{_session_stats['errors']}")

            # 使用优化后的会话监控阈值
            if _session_stats["active"] > settings.database_session_leak_threshold:
                logger.error(f"🚨 严重告警：活跃会话数 {_session_stats['active']} 超过泄漏阈值 {settings.database_session_leak_threshold}！")
            elif _session_stats["active"] > settings.database_session_max_active:
                logger.warning(f"⚠️ 警告：活跃会话数 {_session_stats['active']} 超过警告阈值 {settings.database_session_max_active}，可能存在连接泄漏！")

        except Exception as e:
            _session_stats["errors"] += 1
            logger.error(f"❌ 关闭会话时出错 [User:{user_id}][ID:{session_id}]: {str(e)}", exc_info=True)
            try:
                await session.close()
            except:
                pass

async def _init_relationship_types(user_id: str):
    """为指定用户初始化预置的关系类型数据
    
    Args:
        user_id: 用户ID
    """
    
    relationship_types = [
        {"name": "父亲", "category": "family", "reverse_name": "子女", "intimacy_range": "high", "icon": "👨"},
        {"name": "母亲", "category": "family", "reverse_name": "子女", "intimacy_range": "high", "icon": "👩"},
        {"name": "兄弟", "category": "family", "reverse_name": "兄弟", "intimacy_range": "high", "icon": "👬"},
        {"name": "姐妹", "category": "family", "reverse_name": "姐妹", "intimacy_range": "high", "icon": "👭"},
        {"name": "子女", "category": "family", "reverse_name": "父母", "intimacy_range": "high", "icon": "👶"},
        {"name": "配偶", "category": "family", "reverse_name": "配偶", "intimacy_range": "high", "icon": "💑"},
        {"name": "恋人", "category": "family", "reverse_name": "恋人", "intimacy_range": "high", "icon": "💕"},
        
        {"name": "师父", "category": "social", "reverse_name": "徒弟", "intimacy_range": "high", "icon": "🎓"},
        {"name": "徒弟", "category": "social", "reverse_name": "师父", "intimacy_range": "high", "icon": "📚"},
        {"name": "朋友", "category": "social", "reverse_name": "朋友", "intimacy_range": "medium", "icon": "🤝"},
        {"name": "同学", "category": "social", "reverse_name": "同学", "intimacy_range": "medium", "icon": "🎒"},
        {"name": "邻居", "category": "social", "reverse_name": "邻居", "intimacy_range": "low", "icon": "🏘️"},
        {"name": "知己", "category": "social", "reverse_name": "知己", "intimacy_range": "high", "icon": "💙"},
        
        {"name": "上司", "category": "professional", "reverse_name": "下属", "intimacy_range": "low", "icon": "👔"},
        {"name": "下属", "category": "professional", "reverse_name": "上司", "intimacy_range": "low", "icon": "💼"},
        {"name": "同事", "category": "professional", "reverse_name": "同事", "intimacy_range": "medium", "icon": "🤵"},
        {"name": "合作伙伴", "category": "professional", "reverse_name": "合作伙伴", "intimacy_range": "medium", "icon": "🤜🤛"},
        
        {"name": "敌人", "category": "hostile", "reverse_name": "敌人", "intimacy_range": "low", "icon": "⚔️"},
        {"name": "仇人", "category": "hostile", "reverse_name": "仇人", "intimacy_range": "low", "icon": "💢"},
        {"name": "竞争对手", "category": "hostile", "reverse_name": "竞争对手", "intimacy_range": "low", "icon": "🎯"},
        {"name": "宿敌", "category": "hostile", "reverse_name": "宿敌", "intimacy_range": "low", "icon": "⚡"},
    ]
    
    try:
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(RelationshipType))
            existing = result.scalars().first()
            
            if existing:
                logger.info(f"用户 {user_id} 的关系类型数据已存在，跳过初始化")
                return
            
            logger.info(f"开始为用户 {user_id} 插入关系类型数据...")
            for rt_data in relationship_types:
                relationship_type = RelationshipType(**rt_data)
                session.add(relationship_type)
            
            await session.commit()
            logger.info(f"成功为用户 {user_id} 插入 {len(relationship_types)} 条关系类型数据")
            
    except Exception as e:
        logger.error(f"用户 {user_id} 初始化关系类型数据失败: {str(e)}", exc_info=True)
        raise



async def _init_global_writing_styles(user_id: str):
    """为指定用户初始化全局预设写作风格
    
    全局预设风格的 project_id 为 NULL，所有用户共享
    第一次创建数据库时插入；之后每次初始化按 preset_id 把名称 / 描述 / 提示词同步成代码里的最新版
    （全局预设用户不能编辑，见 writing_styles.update_writing_style，所以覆盖不会丢用户改动）
    
    Args:
        user_id: 用户ID
    """
    from app.services.prompt_service import WritingStyleManager
    
    try:
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            # 获取所有预设风格配置
            presets = WritingStyleManager.get_all_presets()

            # 检查是否已存在全局预设风格
            result = await session.execute(
                select(WritingStyle).where(WritingStyle.project_id.is_(None))
            )
            existing_rows = list(result.scalars().all())
            
            if existing_rows:
                by_preset_id = {row.preset_id: row for row in existing_rows if row.preset_id}
                changed = 0
                for index, (preset_id, preset_data) in enumerate(presets.items(), start=1):
                    row = by_preset_id.get(preset_id)
                    if row is None:
                        session.add(WritingStyle(
                            project_id=None, name=preset_data["name"], style_type="preset", preset_id=preset_id,
                            description=preset_data["description"], prompt_content=preset_data["prompt_content"],
                            order_index=len(existing_rows) + index,
                        ))
                        changed += 1
                        continue
                    new_values = (preset_data["name"], preset_data["description"], preset_data["prompt_content"])
                    if (row.name, row.description, row.prompt_content) != new_values:
                        row.name, row.description, row.prompt_content = new_values
                        changed += 1
                if changed:
                    await session.commit()
                    logger.info(f"用户 {user_id} 的全局预设风格已同步 {changed} 项到最新版")
                else:
                    logger.info(f"用户 {user_id} 的全局预设风格已存在且为最新，跳过初始化")
                return
            
            logger.info(f"开始为用户 {user_id} 插入全局预设写作风格...")
            
            for index, (preset_id, preset_data) in enumerate(presets.items(), start=1):
                style = WritingStyle(
                    project_id=None,  # NULL 表示全局预设
                    name=preset_data["name"],
                    style_type="preset",
                    preset_id=preset_id,
                    description=preset_data["description"],
                    prompt_content=preset_data["prompt_content"],
                    order_index=index
                )
                session.add(style)
            
            await session.commit()
            logger.info(f"成功为用户 {user_id} 插入 {len(presets)} 个全局预设写作风格")
            
    except Exception as e:
        logger.error(f"用户 {user_id} 初始化全局预设写作风格失败: {str(e)}", exc_info=True)
        raise


async def init_db(user_id: str):
    """初始化指定用户的数据库,创建所有表并插入预置数据
    
    Args:
        user_id: 用户ID
    """
    try:
        logger.info(f"开始初始化用户 {user_id} 的数据库...")
        engine = await get_engine(user_id)
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        await _init_relationship_types(user_id)
        await _init_global_writing_styles(user_id)
        
        logger.info(f"用户 {user_id} 的数据库初始化成功")
    except Exception as e:
        logger.error(f"用户 {user_id} 的数据库初始化失败: {str(e)}", exc_info=True)
        raise


async def close_db():
    """关闭所有数据库连接"""
    try:
        logger.info("正在关闭所有数据库连接...")
        for user_id, engine in _engine_cache.items():
            await engine.dispose()
            logger.info(f"用户 {user_id} 的数据库连接已关闭")
        _engine_cache.clear()
        logger.info("所有数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {str(e)}", exc_info=True)
        raise


async def check_database_health(user_id: str = None) -> dict:
    """检查数据库连接健康状态
    
    Args:
        user_id: 可选的用户ID，如果提供则检查特定用户的数据库
        
    Returns:
        dict: 健康检查结果
    """
    result = {
        "healthy": True,
        "checks": {},
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # 检查引擎是否存在
        cache_key = "shared_sqlite"
        if user_id:
            engine = await get_engine(user_id)
        else:
            if cache_key not in _engine_cache:
                result["checks"]["engine"] = {"status": "not_initialized", "healthy": True}
                return result
            engine = _engine_cache[cache_key]
        
        # 测试数据库连接
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            # 执行简单查询测试连接
            await session.execute(text("SELECT 1"))
            result["checks"]["connection"] = {"status": "ok", "healthy": True}
            
        # 检查连接池状态
        if hasattr(engine.pool, 'size'):
            pool_status = {
                "size": engine.pool.size(),
                "checked_in": engine.pool.checkedin(),
                "checked_out": engine.pool.checkedout(),
                "overflow": engine.pool.overflow(),
                "healthy": True
            }
            
            # 连接池健康检查
            if engine.pool.overflow() >= settings.database_max_overflow:
                pool_status["healthy"] = False
                pool_status["warning"] = "连接池溢出已满"
                result["healthy"] = False
            
            result["checks"]["pool"] = pool_status
        
    except Exception as e:
        result["healthy"] = False
        result["checks"]["error"] = {
            "status": "error",
            "message": str(e),
            "healthy": False
        }
        logger.error(f"数据库健康检查失败: {str(e)}", exc_info=True)
    
    return result
