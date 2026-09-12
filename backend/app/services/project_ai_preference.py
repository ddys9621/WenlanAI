"""项目级 AI 偏好的合并与读取（纯逻辑 + 一次带归属校验的查询）。

合并规则：以用户全局 Settings 为底，偏好里 **非 None** 的字段覆盖同名全局值；接口三要素
（api_provider / api_key / api_base_url）永远取全局——项目只换模型和参数，不换接口。
判空一律 `is not None`：reasoning_enabled=False 是"本项目关闭思考"的有效覆盖。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.project_ai_preference import ProjectAIPreference
from app.models.settings import Settings

# 前端在项目壳内的每个请求都带此头；只有 get_user_ai_service 消费它
PROJECT_HEADER = "X-Project-Id"

# 允许按项目覆盖的字段（与 Settings 同名）；顺序即接口 / 前端展示顺序
OVERRIDE_FIELDS: tuple[str, ...] = (
    "llm_model", "temperature", "max_tokens", "top_p", "frequency_penalty",
    "presence_penalty", "reasoning_enabled", "reasoning_effort", "thinking_budget_tokens",
)


def resolve_override_values(settings: Settings, pref: Optional[ProjectAIPreference]) -> dict[str, Any]:
    """OVERRIDE_FIELDS 逐项取值：偏好非 None 用偏好，否则用全局。"""
    values = {f: getattr(settings, f, None) for f in OVERRIDE_FIELDS}
    if pref is not None:
        for f in OVERRIDE_FIELDS:
            v = getattr(pref, f, None)
            if v is not None:
                values[f] = v
    return values


def merge_ai_overrides(settings: Settings, pref: Optional[ProjectAIPreference]) -> dict[str, Any]:
    """产出 `create_user_ai_service(**kwargs)` 的完整参数（键名与该工厂形参一致）。"""
    v = resolve_override_values(settings, pref)
    return {
        "api_provider": settings.api_provider,
        "api_key": settings.api_key,
        "api_base_url": settings.api_base_url or "",
        "model_name": v["llm_model"],
        "temperature": v["temperature"],
        "max_tokens": v["max_tokens"],
        "top_p": v["top_p"],
        "frequency_penalty": v["frequency_penalty"],
        "presence_penalty": v["presence_penalty"],
        "reasoning_enabled": v["reasoning_enabled"],
        "reasoning_effort": v["reasoning_effort"],
        "thinking_budget_tokens": v["thinking_budget_tokens"],
    }


def effective_config(settings: Settings, pref: Optional[ProjectAIPreference]) -> dict[str, Any]:
    """给前端看的"实际生效配置"：带接口信息但不含密钥。"""
    return {
        "api_provider": settings.api_provider,
        "api_base_url": settings.api_base_url,
        **resolve_override_values(settings, pref),
    }


async def load_project_ai_preference(
    db: AsyncSession, project_id: Optional[str], user_id: Optional[str]
) -> Optional[ProjectAIPreference]:
    """取**本人**项目的偏好；头缺失 / 形状不对 / 项目不存在 / 不属于本人 → None（调用方回落全局）。"""
    if not project_id or not user_id or len(project_id) > 64:
        return None
    result = await db.execute(
        select(ProjectAIPreference)
        .join(Project, Project.id == ProjectAIPreference.project_id)
        .where(ProjectAIPreference.project_id == project_id, Project.user_id == user_id)
    )
    return result.scalar_one_or_none()
