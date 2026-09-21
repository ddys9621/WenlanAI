"""V3 generator 通用基类（T2.2，2026-05-21）。

设计目的：
- 把 6 个 V3 generator 重复的 "调 LLM → 取 content → safe_parse_json → 失败返 None"
  模板收敛到唯一一处
- 首次本地解析失败时自动触发 LLM 二次修复（repair_json_with_llm），把之前
  "白白丢弃 LLM 已生成 token" 的损失补回来
- 日志格式统一：调用失败 / 空内容 / 首次解析失败 / 二次修复触发 / 二次修复
  失败 / 最终成功 都有一致前缀

涉及 generator：
- MethodologyGenerator     ([拆书V3-方法论])
- StructureGenerator       ([拆书V3-结构])
- ArchetypeGenerator       ([拆书V3-角色塑造])
- WorldbuildingGenerator   ([拆书V3-世界观])
- SynopsisGenerator        ([拆书V3.2-梗概])
- StyleGenerator           ([拆书V3-文风])
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.utils.json_cleaner import repair_json_with_llm, safe_parse_json

logger = logging.getLogger(__name__)


class BaseV3Generator:
    """所有 V3 generator 的通用基类，封装统一的 LLM 调用 + 解析 + 二次修复流程。

    子类约定：
    - 持有 `self.ai_service`
    - 自己负责构造 prompt / system_prompt / sanitize 等业务细节
    - LLM 调用统一走 `_call_and_parse_object`（dict 输出）
    """

    async def _call_and_parse_object(
        self,
        *,
        prompt: str,
        system_prompt: str,
        temperature: float,
        label: str,
        schema_hint: str = "",
    ) -> Optional[dict]:
        """调一次 LLM，解析为 dict；首次失败自动触发 LLM 二次修复。

        Args:
            prompt: 用户 prompt
            system_prompt: system prompt
            temperature: 温度
            label: 日志前缀（含方括号），如 ``"[拆书V3-方法论]"``
            schema_hint: 字段名提示，传给 ``repair_json_with_llm`` 用于约束
                字段名不被改名。例如 ``"name, description, prompt_content"``

        Returns:
            解析后的 dict；任一环节失败返回 None
        """
        ai_service = getattr(self, "ai_service", None)
        if ai_service is None:
            logger.error("%s ai_service 未初始化，跳过 LLM 调用", label)
            return None

        # ---------- 1. 调 LLM（流式累积：长 JSON 输出非流式会被中转网关 100s 超时掐断）----------
        try:
            resp = await ai_service.generate_text_stream_collect(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                context=label.strip("[]"),
            )
        except Exception as exc:
            logger.error("%s LLM 调用失败: %s", label, exc)
            return None

        content = (resp or {}).get("content") if isinstance(resp, dict) else None
        if not content:
            logger.warning("%s LLM 返回空内容", label)
            return None

        # ---------- 2. 首次本地解析 ----------
        first_pass = safe_parse_json(
            content,
            default=None,
            expected_type="object",
            log_prefix=label,
        )
        if isinstance(first_pass, dict):
            return first_pass

        # ---------- 3. LLM 二次修复 ----------
        logger.info("%s 首次解析失败，触发 LLM 二次修复", label)
        try:
            repaired: Any = await repair_json_with_llm(
                content,
                user_ai_service=ai_service,
                expected_type="object",
                schema_hint=schema_hint or None,
                log_prefix=label,
            )
        except Exception as exc:
            logger.warning("%s LLM 二次修复失败: %s", label, exc)
            return None

        if isinstance(repaired, dict):
            logger.info("%s 二次修复成功", label)
            return repaired

        logger.warning(
            "%s 二次修复返回非 dict (type=%s)，舍弃",
            label,
            type(repaired).__name__,
        )
        return None
