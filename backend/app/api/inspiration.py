"""灵感模式API - 通过对话引导创建项目

两个 AI 端点（候选生成 / 智能补全）都跑在通用后台任务上（2026-09-11 D）：
POST /generate-options-stream、/quick-generate-stream 返回 SSE（start → llm 思考计数 → result{原 JSON} → done），
按用户互斥；重连 / 停止走 /api/ai-jobs/*。实现函数 _generate_options_impl / _quick_generate_impl 保持原逻辑。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any, List
import json
import re

from app.api.ai_jobs import job_sse_response
from app.services.ai_jobs import AIJobConflictError, ai_jobs
from app.services.ai_service import AIService
from app.api.settings import get_user_ai_service
from app.logger import get_logger
from app.utils.json_cleaner import clean_and_parse_json

router = APIRouter(prefix="/inspiration", tags=["灵感模式"])
logger = get_logger(__name__)

STEP_LABELS = {"title": "书名", "description": "简介", "theme": "主题", "genre": "类型"}


def _options_title(step: Any) -> str:
    label = STEP_LABELS.get(str(step), "")
    return f"灵感：生成{label}候选"


# 灵感模式提示词模板
INSPIRATION_PROMPTS = {
    "title": {
        "system": """你是一位专业的小说创作顾问。
用户原始灵感：{original_idea}

请根据用户的想法，生成6个吸引人的书名建议，要求：
1. 符合用户的故事构思
2. 富有创意和吸引力
3. 涵盖不同的风格倾向

返回JSON格式：
{{
    "prompt": "根据你的想法，我为你准备了几个书名建议：",
    "options": ["书名1", "书名2", "书名3", "书名4", "书名5", "书名6"]
}}

只返回纯JSON，不要有其他文字。""",
        "user": "用户的原始灵感：{original_idea}\n请生成6个书名建议"
    },
    
    "description": {
        "system": """你是一位专业的小说创作顾问。
用户原始灵感：{original_idea}
用户已经确定了书名：{title}

请生成6个精彩的小说简介，要求：
1. 符合书名风格
2. 简洁有力，每个50-100字
3. 包含核心冲突
4. 涵盖不同的故事走向

返回JSON格式：
{{"prompt":"选择一个简介：","options":["简介1","简介2","简介3","简介4","简介5","简介6"]}}

只返回纯JSON，不要有其他文字，不要换行。""",
        "user": "原始灵感：{original_idea}\n书名是：{title}，请生成6个简介选项"
    },
    
    "theme": {
        "system": """你是一位专业的小说创作顾问。
用户的小说信息：
- 原始灵感：{original_idea}
- 书名：{title}
- 简介：{description}

请生成6个深刻的主题选项，要求：
1. 符合书名和简介的风格
2. 有深度和思想性
3. 每个50-150字
4. 涵盖不同角度（如：成长、复仇、救赎、探索等）

返回JSON格式：
{{"prompt":"这本书的核心主题是什么？","options":["主题1","主题2","主题3","主题4","主题5","主题6"]}}

只返回纯JSON，不要有其他文字，不要换行。""",
        "user": "原始灵感：{original_idea}\n书名：{title}\n简介：{description}\n请生成6个主题选项"
    },
    
    "genre": {
        "system": """你是一位专业的小说创作顾问。
用户的小说信息：
- 原始灵感：{original_idea}
- 书名：{title}
- 简介：{description}
- 主题：{theme}

请生成6个合适的类型标签（每个2-4字），要求：
1. 符合小说整体风格
2. 可以多选组合

常见类型：玄幻、都市、科幻、武侠、仙侠、历史、言情、悬疑、奇幻、修仙等

返回JSON格式：
{{"prompt":"选择类型标签（可多选）：","options":["类型1","类型2","类型3","类型4","类型5","类型6"]}}

只返回紧凑的纯JSON，不要换行，不要有其他文字。""",
        "user": "原始灵感：{original_idea}\n书名：{title}\n简介：{description}\n主题：{theme}\n请生成6个类型标签"
    }
}


def validate_options_response(result: Dict[str, Any], step: str, max_retries: int = 3) -> tuple[bool, str]:
    """
    校验AI返回的选项格式是否正确
    
    Returns:
        (is_valid, error_message)
    """
    # 检查必需字段
    if "options" not in result:
        return False, "缺少options字段"
    
    options = result.get("options", [])
    
    # 检查options是否为数组
    if not isinstance(options, list):
        return False, "options必须是数组"
    
    # 检查数组长度
    if len(options) < 3:
        return False, f"选项数量不足，至少需要3个，当前只有{len(options)}个"
    
    if len(options) > 10:
        return False, f"选项数量过多，最多10个，当前有{len(options)}个"
    
    # 检查每个选项是否为字符串且不为空
    for i, option in enumerate(options):
        if not isinstance(option, str):
            return False, f"第{i+1}个选项不是字符串类型"
        if not option.strip():
            return False, f"第{i+1}个选项为空"
        if len(option) > 500:
            return False, f"第{i+1}个选项过长（超过500字符）"
    
    # 根据不同步骤进行特定校验
    if step == "genre":
        # 类型标签应该比较短
        for option in options:
            if len(option) > 10:
                return False, f"类型标签【{option}】过长，应该在2-10字之间"
    
    return True, ""


def _strip_code_fence(content: str) -> str:
    cleaned = (content or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].lstrip("\n\r")
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].lstrip("\n\r")
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].rstrip("\n\r")
    return cleaned.strip()


def _extract_bracket_block(text: str, open_char: str, close_char: str, start_index: int) -> str:
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    block_start = -1

    for index in range(start_index, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == quote_char:
                in_string = False
            continue

        if ch in ['"', "'"]:
            in_string = True
            quote_char = ch
            continue

        if ch == open_char:
            if depth == 0:
                block_start = index
            depth += 1
        elif ch == close_char and depth > 0:
            depth -= 1
            if depth == 0 and block_start != -1:
                return text[block_start:index + 1]

    return text[block_start:] if block_start != -1 else ""


def _split_relaxed_string_array(array_text: str) -> List[str]:
    text = array_text.strip()
    if text.startswith("["):
        text = text[1:]
    if text.endswith("]"):
        text = text[:-1]

    items: List[str] = []
    current: List[str] = []
    in_string = False
    quote_char = ""
    escape = False

    def flush():
        item = "".join(current).strip().strip(",").strip()
        item = item.strip('"').strip("'").strip()
        item = re.sub(r"^[\-\*\d\.\)\s]+", "", item)
        if item:
            items.append(item)
        current.clear()

    i = 0
    while i < len(text):
        ch = text[i]

        if in_string:
            if escape:
                current.append(ch)
                escape = False
                i += 1
                continue

            if ch == "\\":
                escape = True
                i += 1
                continue

            if ch == quote_char:
                j = i + 1
                while j < len(text) and text[j].isspace():
                    j += 1
                if j >= len(text) or text[j] in [",", "]"]:
                    in_string = False
                    i += 1
                    continue

            current.append(ch)
            i += 1
            continue

        if ch in ['"', "'"]:
            in_string = True
            quote_char = ch
            i += 1
            continue

        if ch == ",":
            flush()
            i += 1
            continue

        current.append(ch)
        i += 1

    flush()
    return items


def _normalize_options(options: List[Any], step: str) -> List[str]:
    normalized: List[str] = []
    seen = set()

    for option in options:
        value = str(option).strip()
        value = re.sub(r"^[\-\*\d\.\)\s]+", "", value)
        value = value.strip("，,;； ")
        if not value:
            continue
        if step == "genre":
            value = value.replace("类型：", "").replace("标签：", "").strip()
        if value not in seen:
            normalized.append(value)
            seen.add(value)

    return normalized[:10]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_text_list(value: Any) -> List[str]:
    if not value:
        return []

    raw_items = value if isinstance(value, list) else [value]
    items: List[str] = []
    seen = set()

    for item in raw_items:
        text = _coerce_text(item)
        if not text:
            continue
        if text not in seen:
            items.append(text)
            seen.add(text)

    return items


def _extract_refinement_context(data: Dict[str, Any], hint: str) -> tuple[List[str], List[str]]:
    raw_context = data.get("refinement_context") or data.get("refinementContext") or {}
    if not isinstance(raw_context, dict):
        raw_context = {}

    requirements = _normalize_text_list(raw_context.get("requirements"))
    previous_options = _normalize_text_list(
        raw_context.get("previous_options") or raw_context.get("previousOptions")
    )

    if hint and (not requirements or requirements[-1] != hint):
        requirements.append(hint)

    return requirements, previous_options


def _build_refinement_instruction(requirements: List[str], previous_options: List[str]) -> str:
    sections: List[str] = []

    if requirements:
        requirement_lines = "\n".join(
            f"{index}. {requirement}" for index, requirement in enumerate(requirements, start=1)
        )
        sections.append(
            "用户连续改稿要求（按时间顺序，必须全部满足；后续要求是在前序基础上追加/收紧，不是替换）：\n"
            f"{requirement_lines}"
        )

    if previous_options:
        option_lines = "\n".join(f"- {option}" for option in previous_options[:10])
        sections.append(
            "上一轮候选结果（本轮不要简单重复，除非用户明确要求保留）：\n"
            f"{option_lines}"
        )

    if not sections:
        return ""

    return (
        "\n\n【连续对话上下文】\n"
        + "\n\n".join(sections)
        + "\n请基于原始灵感、已确定信息和以上连续要求重新生成。"
    )


def _salvage_options_response(content: str, step: str) -> Dict[str, Any]:
    cleaned = _strip_code_fence(content)

    # 先走统一 JSON 清理器
    try:
        result = clean_and_parse_json(
            cleaned,
            expected_type='object',
            log_prefix=f"[灵感模式-{step}]"
        )
        if isinstance(result, dict):
            result["options"] = _normalize_options(result.get("options", []), step)
            return result
    except Exception as exc:
        logger.warning(f"[灵感模式-{step}] 严格 JSON 解析失败，尝试宽松修复: {exc}")
        pass

    prompt = ""
    prompt_match = re.search(
        r'["\']prompt["\']\s*:\s*(.+?)(?=,\s*["\']options["\']\s*:|\}\s*$)',
        cleaned,
        flags=re.DOTALL
    )
    if prompt_match:
        prompt = prompt_match.group(1).strip().strip(",").strip()
        prompt = prompt.strip('"').strip("'").strip()

    options: List[str] = []
    options_match = re.search(r'["\']options["\']\s*:\s*\[', cleaned)
    if options_match:
        array_start = cleaned.find("[", options_match.end() - 1)
        if array_start != -1:
            array_text = _extract_bracket_block(cleaned, "[", "]", array_start)
            options = _split_relaxed_string_array(array_text)

    if len(options) < 3:
        lines = [
            re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
            for line in cleaned.splitlines()
        ]
        fallback_lines = [
            line for line in lines
            if line
            and "prompt" not in line.lower()
            and "options" not in line.lower()
            and line not in ["{", "}", "[", "]"]
        ]
        options = options or fallback_lines

    normalized_options = _normalize_options(options, step)
    if normalized_options:
        logger.info(f"[灵感模式-{step}] 宽松修复成功，恢复 {len(normalized_options)} 个选项")
    return {
        "prompt": prompt or "请选择一个选项：",
        "options": normalized_options
    }


async def _generate_options_impl(
    data: Dict[str, Any],
    ai_service: AIService,
) -> Dict[str, Any]:
    """
    根据当前收集的信息生成下一步的选项建议（带自动重试）——后台任务 runner 调用
    
    Request:
        {
            "step": "title",  // title/description/theme/genre
            "context": {
                "original_idea": "...",
                "title": "...",
                "description": "...",
                "theme": "..."
            },
            "hint": "本轮额外要求（可选）",
            "refinement_context": {
                "requirements": ["连续改稿要求1", "连续改稿要求2"],
                "previous_options": ["上一轮候选1", "上一轮候选2"]
            }
        }
    
    Response:
        {
            "prompt": "引导语",
            "options": ["选项1", "选项2", ...]
        }
    """
    max_retries = 3
    
    hint = _coerce_text(data.get("hint"))
    requirements, previous_options = _extract_refinement_context(data, hint)
    refinement_instruction = _build_refinement_instruction(requirements, previous_options)

    for attempt in range(max_retries):
        try:
            step = data.get("step", "title")
            context = data.get("context", {})
            if not isinstance(context, dict):
                context = {}

            logger.info(f"灵感模式：生成{step}阶段的选项（第{attempt + 1}次尝试）")

            # 获取对应的提示词模板
            if step not in INSPIRATION_PROMPTS:
                return {
                    "error": f"不支持的步骤: {step}",
                    "prompt": "",
                    "options": []
                }

            prompt_template = INSPIRATION_PROMPTS[step]

            # 准备格式化参数（提供默认值避免KeyError）
            original_idea = _coerce_text(
                context.get("original_idea")
                or context.get("originalIdea")
                or context.get("description")
            )
            format_params = {
                "original_idea": original_idea or "未提供",
                "title": _coerce_text(context.get("title")),
                "description": _coerce_text(context.get("description")),
                "theme": _coerce_text(context.get("theme"))
            }

            # 格式化系统提示词
            system_prompt = prompt_template["system"].format(**format_params)
            user_prompt = prompt_template["user"].format(**format_params)

            if refinement_instruction:
                system_prompt += refinement_instruction
                user_prompt += "\n\n请把连续改稿要求视为同一段对话历史，不要只参考最后一句。"
            
            # 如果是重试，在提示词中强调格式要求
            if attempt > 0:
                system_prompt += f"\n\n⚠️ 这是第{attempt + 1}次生成，请务必严格按照JSON格式返回，确保options数组包含6个有效选项！"
            
            # 调用AI生成选项
            logger.info(f"调用AI生成{step}选项...")
            response = await ai_service.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.8  # 提高创造性
            )
            
            content = response.get("content", "")
            logger.info(f"AI返回内容长度: {len(content)}")
            
            # 解析JSON（优先严格解析，失败时尝试宽松修复）
            try:
                result = _salvage_options_response(content, step)
                
                # 校验返回格式
                is_valid, error_msg = validate_options_response(result, step)
                
                if not is_valid:
                    logger.warning(f"⚠️ 第{attempt + 1}次生成格式校验失败: {error_msg}")
                    if attempt < max_retries - 1:
                        logger.info("准备重试...")
                        continue  # 重试
                    else:
                        # 最后一次尝试也失败了
                        return {
                            "prompt": f"请为【{step}】提供内容：",
                            "options": ["让AI重新生成", "我自己输入"],
                            "error": f"AI生成格式错误（{error_msg}），已自动重试{max_retries}次，请手动重试或自己输入"
                        }
                
                logger.info(f"✅ 第{attempt + 1}次成功生成{len(result.get('options', []))}个有效选项")
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"第{attempt + 1}次JSON解析失败: {e}")
                
                if attempt < max_retries - 1:
                    logger.info("JSON解析失败，准备重试...")
                    continue  # 重试
                else:
                    # 最后一次尝试也失败了
                    return {
                        "prompt": f"请为【{step}】提供内容：",
                        "options": ["让AI重新生成", "我自己输入"],
                        "error": f"AI返回格式错误，已自动重试{max_retries}次，请手动重试或自己输入"
                    }
        
        except Exception as e:
            logger.error(f"第{attempt + 1}次生成失败: {e}", exc_info=True)
            if attempt < max_retries - 1:
                logger.info("发生异常，准备重试...")
                continue
            else:
                return {
                    "error": str(e),
                    "prompt": "生成失败，请重试",
                    "options": ["重新生成", "我自己输入"]
                }
    
    # 理论上不会到这里
    return {
        "error": "生成失败",
        "prompt": "请重试",
        "options": []
    }


@router.post("/generate-options-stream", summary="灵感模式：生成候选（后台任务 + SSE）")
async def generate_options_stream(
    data: Dict[str, Any],
    request: Request,
    ai_service: AIService = Depends(get_user_ai_service)
):
    """请求体与原 /generate-options 相同；result 事件的 data 即原 JSON（含软错误 error 字段）。同用户互斥。"""
    user_id = getattr(request.state, "user_id", None) or "system"

    async def runner(job):
        return await _generate_options_impl(data, ai_service)

    try:
        job = await ai_jobs.start(
            kind="inspiration_options", title=_options_title(data.get("step", "title")), user_id=user_id,
            project_id=None, scope=f"inspiration_options:{user_id}", runner=runner,
            cancel_message="已停止生成候选", meta={"step": data.get("step")},
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)


async def _quick_generate_impl(
    data: Dict[str, Any],
    ai_service: AIService,
) -> Dict[str, Any]:
    """
    智能补全：根据用户已提供的部分信息，AI自动补全缺失字段——后台任务 runner 调用
    
    Request:
        {
            "title": "书名（可选）",
            "description": "简介（可选）",
            "theme": "主题（可选）",
            "genre": ["类型1", "类型2"]（可选）,
            "narrative_perspective": "叙事视角（可选）"
        }
    
    Response:
        {
            "title": "补全的书名",
            "description": "补全的简介",
            "theme": "补全的主题",
            "genre": ["补全的类型"],
            "narrative_perspective": "第一人称 / 第三人称 / 全知视角"
        }
    """
    try:
        logger.info("灵感模式：智能补全")
        
        # 构建补全提示词
        existing_info = []
        if data.get("title"):
            existing_info.append(f"- 书名：{data['title']}")
        if data.get("description"):
            existing_info.append(f"- 简介：{data['description']}")
        if data.get("theme"):
            existing_info.append(f"- 主题：{data['theme']}")
        if data.get("genre"):
            existing_info.append(f"- 类型：{', '.join(data['genre'])}")
        if data.get("narrative_perspective"):
            existing_info.append(f"- 叙事视角：{data['narrative_perspective']}")
        
        existing_text = "\n".join(existing_info) if existing_info else "暂无信息"
        
        system_prompt = """你是一位专业的小说创作顾问。用户提供了部分小说信息，请补全缺失的字段。

用户已提供的信息：
{existing}

请生成完整的小说方案，包含：
1. title: 书名（3-6字，如果用户已提供则保持原样）
2. description: 简介（50-100字）
3. theme: 核心主题（30-50字）
4. genre: 类型标签数组（2-3个）
5. narrative_perspective: 叙事视角，只能是"第一人称"、"第三人称"、"全知视角"之一

返回JSON格式：
{{
    "title": "书名",
    "description": "简介内容...",
    "theme": "主题内容...",
    "genre": ["类型1", "类型2"],
    "narrative_perspective": "第三人称"
}}

只返回纯JSON，不要有其他文字。"""
        
        user_prompt = "请补全小说信息"
        
        # 调用AI
        response = await ai_service.generate_text(
            prompt=user_prompt,
            system_prompt=system_prompt.format(existing=existing_text),
            temperature=0.7
        )
        
        content = response.get("content", "")
        
        # 使用统一的 JSON 清理工具解析 AI 响应
        from app.utils.json_cleaner import clean_and_parse_json

        try:
            result = clean_and_parse_json(
                content,
                expected_type='object',
                log_prefix="[灵感补全]"
            )
            
            # 合并用户已提供的信息（用户输入优先）
            final_result = {
                "title": data.get("title") or result.get("title", ""),
                "description": data.get("description") or result.get("description", ""),
                "theme": data.get("theme") or result.get("theme", ""),
                "genre": data.get("genre") or result.get("genre", []),
                # 前端 readyToGenerate 依赖视角字段，缺了会卡在创建 0%
                "narrative_perspective": data.get("narrative_perspective")
                or result.get("narrative_perspective")
                or "第三人称",
            }
            
            logger.info(f"✅ 智能补全成功")
            return final_result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            raise Exception("AI返回格式错误，请重试")
    
    except Exception as e:
        logger.error(f"智能补全失败: {e}", exc_info=True)
        return {
            "error": str(e)
        }


@router.post("/quick-generate-stream", summary="灵感模式：智能补全（后台任务 + SSE）")
async def quick_generate_stream(
    data: Dict[str, Any],
    request: Request,
    ai_service: AIService = Depends(get_user_ai_service)
):
    """请求体与原 /quick-generate 相同；result 事件的 data 即原 JSON（含软错误 error 字段）。同用户互斥。"""
    user_id = getattr(request.state, "user_id", None) or "system"

    async def runner(job):
        return await _quick_generate_impl(data, ai_service)

    try:
        job = await ai_jobs.start(
            kind="inspiration_quick", title="灵感：智能补全书籍信息", user_id=user_id,
            project_id=None, scope=f"inspiration_quick:{user_id}", runner=runner,
            cancel_message="已停止补全",
        )
    except AIJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job_sse_response(job)
