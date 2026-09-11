"""
设置管理 API
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any, Optional
from pydantic import BaseModel
import httpx

from app.database import get_db
from app.models.settings import Settings
from app.schemas.settings import SettingsCreate, SettingsUpdate, SettingsResponse
from app.user_manager import User
from app.logger import get_logger
from app.config import settings as app_settings
from app.services.ai_service import AIService, create_user_ai_service
from app.api.deps import require_login

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["设置管理"])


def read_env_defaults() -> Dict[str, Any]:
    """从.env文件读取默认配置（仅读取，不修改）"""
    return {
        "api_provider": app_settings.default_ai_provider,
        "api_key": app_settings.openai_api_key or app_settings.anthropic_api_key or "",
        "api_base_url": app_settings.openai_base_url or app_settings.anthropic_base_url or "",
        "llm_model": app_settings.default_model,
        "temperature": app_settings.default_temperature,
        "max_tokens": app_settings.default_max_tokens,
        "reasoning_enabled": app_settings.default_reasoning_enabled,
        "reasoning_effort": app_settings.default_reasoning_effort,
        "thinking_budget_tokens": app_settings.default_thinking_budget_tokens,
    }


async def get_user_ai_service(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
) -> AIService:
    """
    依赖：获取当前用户的AI服务实例
    从数据库读取用户设置并创建对应的AI服务
    """
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        # 如果用户没有设置，从.env读取并保存
        env_defaults = read_env_defaults()
        settings = Settings(
            user_id=user.user_id,
            **env_defaults
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 首次使用AI服务，已从.env同步设置到数据库")
    
    # 使用用户设置创建AI服务实例（思考强度随之全局生效）
    return create_user_ai_service(
        api_provider=settings.api_provider,
        api_key=settings.api_key,
        api_base_url=settings.api_base_url or "",
        model_name=settings.llm_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        reasoning_enabled=settings.reasoning_enabled,
        reasoning_effort=settings.reasoning_effort,
        thinking_budget_tokens=settings.thinking_budget_tokens,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的设置
    如果用户没有保存过设置，自动从.env创建并保存到数据库
    """
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        # 如果用户没有保存过设置，从.env读取默认配置并保存到数据库
        env_defaults = read_env_defaults()
        logger.info(f"用户 {user.user_id} 首次获取设置，自动从.env同步到数据库")
        
        # 创建新设置并保存到数据库（处理并发竞争）
        try:
            settings = Settings(
                user_id=user.user_id,
                **env_defaults
            )
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
            logger.info(f"用户 {user.user_id} 的设置已从.env同步到数据库")
        except Exception:
            # 并发情况下可能已被另一个请求插入，回滚后重新查询
            await db.rollback()
            result = await db.execute(
                select(Settings).where(Settings.user_id == user.user_id)
            )
            settings = result.scalar_one_or_none()
            if not settings:
                raise
            logger.info(f"用户 {user.user_id} 的设置已由并发请求创建，直接使用")
    
    logger.info(f"用户 {user.user_id} 获取已保存的设置")
    return settings


@router.post("", response_model=SettingsResponse)
async def save_settings(
    data: SettingsCreate,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    创建或更新当前用户的设置（Upsert）
    如果设置已存在则更新，否则创建新设置
    仅保存到数据库
    """
    # 查找现有设置
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    # 准备数据
    settings_dict = data.model_dump(exclude_unset=True)
    
    if settings:
        # 更新现有设置
        for key, value in settings_dict.items():
            setattr(settings, key, value)
        
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 更新设置")
    else:
        # 创建新设置
        settings = Settings(
            user_id=user.user_id,
            **settings_dict
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 创建设置")
    
    return settings


@router.put("", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    更新当前用户的设置
    仅保存到数据库
    """
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        raise HTTPException(status_code=404, detail="设置不存在，请先创建设置")
    
    # 更新设置
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)
    
    await db.commit()
    await db.refresh(settings)
    logger.info(f"用户 {user.user_id} 更新设置")
    
    return settings


@router.delete("")
async def delete_settings(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    删除当前用户的设置
    """
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        raise HTTPException(status_code=404, detail="设置不存在")
    
    await db.delete(settings)
    await db.commit()
    logger.info(f"用户 {user.user_id} 删除设置")
    
    return {"message": "设置已删除", "user_id": user.user_id}


@router.get("/models")
async def get_available_models(
    api_key: str,
    api_base_url: str,
    provider: str = "openai"
):
    """
    从配置的 API 获取可用的模型列表
    
    Args:
        api_key: API 密钥
        api_base_url: API 基础 URL
        provider: API 提供商 (openai, anthropic, azure, custom)
    
    Returns:
        模型列表
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "openai" or provider == "azure" or provider == "custom":
                # OpenAI 兼容接口获取模型列表
                url = f"{api_base_url.rstrip('/')}/models"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                logger.info(f"正在从 {url} 获取模型列表")
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                models = []
                
                if "data" in data and isinstance(data["data"], list):
                    for model in data["data"]:
                        model_id = model.get("id", "")
                        # 返回所有模型，不进行过滤
                        if model_id:
                            models.append({
                                "value": model_id,
                                "label": model_id,
                                "description": model.get("description", "") or f"Created: {model.get('created', 'N/A')}"
                            })
                
                if not models:
                    raise HTTPException(
                        status_code=404,
                        detail="未能从 API 获取到可用的模型列表"
                    )
                
                logger.info(f"成功获取 {len(models)} 个模型")
                return {
                    "provider": provider,
                    "models": models,
                    "count": len(models)
                }
                
            elif provider == "anthropic":
                # Anthropic 官方模型列表 API：GET {base}/v1/models
                # 鉴权用 x-api-key + anthropic-version（非 Bearer），响应 {"data":[{"id","display_name",...}]}
                base = (api_base_url or "https://api.anthropic.com").rstrip("/")
                url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                }

                logger.info(f"正在从 {url} 获取 Anthropic 模型列表")
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                data = response.json()
                models = []
                for model in data.get("data", []) or []:
                    model_id = model.get("id", "")
                    if model_id:
                        models.append({
                            "value": model_id,
                            "label": model.get("display_name") or model_id,
                            "description": f"Created: {model.get('created_at', 'N/A')}"
                        })

                if not models:
                    raise HTTPException(
                        status_code=404,
                        detail="未能从 Anthropic API 获取到可用的模型列表"
                    )

                logger.info(f"成功获取 {len(models)} 个 Anthropic 模型")
                return {
                    "provider": provider,
                    "models": models,
                    "count": len(models)
                }
            
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的提供商: {provider}"
                )
            
    except httpx.HTTPStatusError as e:
        logger.error(f"获取模型列表失败 (HTTP {e.response.status_code}): {e.response.text}")
        raise HTTPException(
            status_code=400,
            detail=f"无法从 API 获取模型列表 (HTTP {e.response.status_code})"
        )
    except httpx.RequestError as e:
        logger.error(f"请求模型列表失败: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"无法连接到 API: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型列表时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取模型列表失败: {str(e)}"
        )


class ApiTestRequest(BaseModel):
    """API 测试请求模型"""
    api_key: str
    api_base_url: str
    provider: str
    llm_model: str
    max_tokens: Optional[int] = None  # 未传时回落全局默认，与正式生成保持同一来源


@router.post("/test")
async def test_api_connection(data: ApiTestRequest):
    """
    测试 API 连接和配置是否正确
    
    Args:
        data: 包含 API 配置的请求数据
    
    Returns:
        测试结果包含状态、响应时间和详细信息
    """
    api_key = data.api_key
    api_base_url = data.api_base_url
    provider = data.provider
    llm_model = data.llm_model
    import time
    
    try:
        start_time = time.time()
        
        # 创建临时 AI 服务实例
        test_service = AIService(
            api_provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            default_model=llm_model,
            default_temperature=0.7,
            default_max_tokens=data.max_tokens
        )
        
        # 发送简单的测试请求
        test_prompt = "请用一句话回复：测试成功"
        
        logger.info(f"🧪 开始测试 API 连接")
        logger.info(f"  - 提供商: {provider}")
        logger.info(f"  - 模型: {llm_model}")
        logger.info(f"  - Base URL: {api_base_url}")
        
        response = await test_service.generate_text(
            prompt=test_prompt,
            provider=provider,
            model=llm_model,
            temperature=0.7,
        )
        
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000, 2)  # 转换为毫秒
        
        logger.info(f"✅ API 测试成功")
        logger.info(f"  - 响应时间: {response_time}ms")
        
        # 安全地处理响应内容（确保是字符串）
        response_str = str(response) if response else 'N/A'
        logger.info(f"  - 响应内容: {response_str[:100]}")
        
        return {
            "success": True,
            "message": "API 连接测试成功",
            "response_time_ms": response_time,
            "provider": provider,
            "model": llm_model,
            "response_preview": response_str[:100] if len(response_str) > 100 else response_str,
            "details": {
                "api_available": True,
                "model_accessible": True,
                "response_valid": bool(response)
            }
        }
        
    except ValueError as e:
        # 配置错误
        error_msg = str(e)
        logger.error(f"❌ API 配置错误: {error_msg}")
        return {
            "success": False,
            "message": "API 配置错误",
            "error": error_msg,
            "error_type": "ConfigurationError",
            "suggestions": [
                "请检查 API Key 是否正确",
                "请确认 API Base URL 格式正确",
                "请验证所选提供商是否匹配"
            ]
        }
        
    except TimeoutError as e:
        # 超时错误
        error_msg = str(e)
        logger.error(f"❌ API 请求超时: {error_msg}")
        return {
            "success": False,
            "message": "API 请求超时",
            "error": error_msg,
            "error_type": "TimeoutError",
            "suggestions": [
                "请检查网络连接",
                "请确认 API Base URL 是否可访问",
                "如果使用代理，请检查代理设置"
            ]
        }
        
    except Exception as e:
        # 其他错误
        error_msg = str(e)
        error_type = type(e).__name__
        
        logger.error(f"❌ API 测试失败: {error_msg}")
        logger.error(f"  - 错误类型: {error_type}")
        
        # 分析错误原因并提供建议
        suggestions = []
        if "blocked" in error_msg.lower():
            suggestions = [
                "请求被 API 提供商阻止",
                "可能原因：API Key 被限制或地区限制",
                "建议：检查 API Key 状态和账户余额",
                "建议：尝试更换 API Base URL 或使用代理"
            ]
        elif "unauthorized" in error_msg.lower() or "401" in error_msg:
            suggestions = [
                "API Key 认证失败",
                "建议：检查 API Key 是否正确",
                "建议：确认 API Key 是否过期"
            ]
        elif "not found" in error_msg.lower() or "404" in error_msg:
            suggestions = [
                "API 端点不存在或模型不可用",
                "建议：检查 API Base URL 是否正确",
                "建议：确认模型名称是否正确"
            ]
        elif "rate limit" in error_msg.lower() or "429" in error_msg:
            suggestions = [
                "API 请求频率超限",
                "建议：稍后重试",
                "建议：升级 API 套餐"
            ]
        elif "insufficient" in error_msg.lower() or "quota" in error_msg.lower():
            suggestions = [
                "API 配额不足",
                "建议：检查账户余额",
                "建议：充值或升级套餐"
            ]
        else:
            suggestions = [
                "请检查所有配置参数是否正确",
                "请确认网络连接正常",
                "请查看详细错误信息"
            ]
        
        return {
            "success": False,
            "message": "API 测试失败",
            "error": error_msg,
            "error_type": error_type,
            "suggestions": suggestions
        }