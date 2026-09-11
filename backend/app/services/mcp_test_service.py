"""MCP插件测试服务 - 专门处理插件测试逻辑"""

import time
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.mcp_plugin import MCPPlugin
from app.models.settings import Settings as UserSettings
from app.mcp.registry import mcp_registry
from app.services.ai_service import create_user_ai_service
from app.schemas.mcp_plugin import MCPTestResult
from app.logger import get_logger
from app.user_manager import User

logger = get_logger(__name__)


class MCPTestService:
    """MCP插件测试服务（分离的测试逻辑）"""
    
    async def test_plugin_connection(
        self,
        plugin: MCPPlugin,
        user_id: str
    ) -> MCPTestResult:
        """
        简单连接测试
        
        Args:
            plugin: 插件配置
            user_id: 用户ID
            
        Returns:
            测试结果
        """
        start_time = time.time()
        
        try:
            # 确保插件已加载
            if not mcp_registry.get_client(user_id, plugin.plugin_name):
                success = await mcp_registry.load_plugin(plugin)
                if not success:
                    return MCPTestResult(
                        success=False,
                        message="插件加载失败",
                        error="无法创建MCP客户端",
                        suggestions=["请检查插件配置", "请确认服务器URL正确"]
                    )
            
            # 测试连接并获取工具列表
            test_result = await mcp_registry.test_plugin(user_id, plugin.plugin_name)
            
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            if test_result["success"]:
                return MCPTestResult(
                    success=True,
                    message=f"✅ 连接测试成功",
                    response_time_ms=response_time,
                    tools_count=test_result.get("tools_count", 0),
                    suggestions=[
                        f"响应时间: {response_time}ms",
                        f"可用工具数: {test_result.get('tools_count', 0)}"
                    ]
                )
            else:
                return MCPTestResult(**test_result)
                
        except Exception as e:
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            logger.error(f"测试插件失败: {plugin.plugin_name}, 错误: {e}")
            
            return MCPTestResult(
                success=False,
                message="❌ 测试失败",
                response_time_ms=response_time,
                error=str(e),
                error_type=type(e).__name__,
                suggestions=[
                    "请检查服务器是否在线",
                    "请确认配置正确",
                    "请检查API Key是否有效"
                ]
            )
    
    async def test_plugin_with_ai(
        self,
        plugin: MCPPlugin,
        user: User,
        db_session: AsyncSession
    ) -> MCPTestResult:
        """
        使用AI进行智能工具调用测试
        
        Args:
            plugin: 插件配置
            user: 用户对象
            db_session: 数据库会话
            
        Returns:
            测试结果
        """
        start_time = time.time()
        
        try:
            # 1. 先进行连接测试
            connection_result = await self.test_plugin_connection(plugin, user.user_id)
            
            if not connection_result.success:
                return connection_result
            
            # 2. 获取工具列表
            tools = await mcp_registry.get_plugin_tools(user.user_id, plugin.plugin_name)
            
            if not tools:
                return MCPTestResult(
                    success=False,
                    message="插件没有提供任何工具",
                    error="工具列表为空",
                    response_time_ms=connection_result.response_time_ms,
                    suggestions=["请检查插件配置", "请确认MCP服务器正常运行"]
                )
            
            # 3. 获取用户的AI设置
            settings_result = await db_session.execute(
                select(UserSettings).where(UserSettings.user_id == user.user_id)
            )
            user_settings = settings_result.scalar_one_or_none()
            
            if not user_settings or not user_settings.api_key:
                # 没有AI配置，返回简单测试结果
                logger.warning("用户未配置AI服务，跳过智能测试")
                return MCPTestResult(
                    success=True,
                    message=f"✅ 连接测试成功（未配置AI，跳过工具调用测试）",
                    response_time_ms=connection_result.response_time_ms,
                    tools_count=len(tools),
                    suggestions=[
                        f"连接测试: 成功",
                        f"可用工具数: {len(tools)}",
                        "提示: 配置AI服务后可进行智能工具调用测试"
                    ]
                )
            
            # 4. 使用AI选择工具并生成测试参数
            logger.info(f"使用AI分析工具并生成测试计划...")
            
            ai_service = create_user_ai_service(
                api_provider=user_settings.api_provider,
                api_key=user_settings.api_key,
                api_base_url=user_settings.api_base_url,
                model_name=user_settings.llm_model,
                temperature=0.3,
                max_tokens=user_settings.max_tokens,
                reasoning_enabled=user_settings.reasoning_enabled,
                reasoning_effort=user_settings.reasoning_effort,
                thinking_budget_tokens=user_settings.thinking_budget_tokens,
            )
            
            # 转换为OpenAI Function Calling格式
            openai_tools = self._convert_tools_to_openai_format(tools)
            
            logger.info(f"📋 转换后的OpenAI工具数量: {len(openai_tools)}")
            logger.debug(f"📋 OpenAI工具列表: {[t['function']['name'] for t in openai_tools]}")
            
            # 调用AI选择工具
            prompt = f"""你是MCP插件测试助手，需要测试插件 '{plugin.plugin_name}' 的功能。

⚠️ 重要规则：生成参数时，必须严格使用工具 schema 中定义的原始参数名称，不要转换为 snake_case 或其他格式。
例如：如果 schema 中是 'nextThoughtNeeded'，就必须使用 'nextThoughtNeeded'，不能改成 'next_thought_needed'。

请选择一个合适的工具进行测试，优先选择搜索、查询类工具。
生成真实有效的测试参数（例如搜索"人工智能最新进展"而不是"test"）。

现在开始测试这个插件。"""

            system_prompt = """你是专业的API测试工具。当给定工具列表时，选择一个工具并使用合适的参数调用它。

⚠️ 关键规则：调用工具时，必须严格使用 schema 中定义的原始参数名，不要自行转换命名风格。
- 如果参数名是 camelCase（如 nextThoughtNeeded），就使用 camelCase
- 如果参数名是 snake_case（如 next_thought），就使用 snake_case
- 保持与 schema 中定义的完全一致，包括大小写和命名风格"""
            
            ai_response = await ai_service.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                tools=openai_tools,
                tool_choice="required"
            )
            
            # 5. 检查AI是否返回工具调用
            if not ai_response.get("tool_calls"):
                logger.error(f"❌ AI未返回工具调用")
                return MCPTestResult(
                    success=False,
                    message="❌ AI Function Calling失败",
                    error=f"AI未返回工具调用请求。响应: {ai_response.get('content', 'N/A')[:200]}",
                    tools_count=len(tools),
                    suggestions=[
                        "请确认使用的AI模型支持Function Calling",
                        f"当前Provider: {user_settings.api_provider}",
                        f"当前模型: {user_settings.llm_model}"
                    ]
                )
            
            # 6. 解析工具调用
            tool_call = ai_response["tool_calls"][0]
            function = tool_call["function"]
            tool_name = function["name"]
            test_arguments = function["arguments"]
            
            if isinstance(test_arguments, str):
                try:
                    test_arguments = json.loads(test_arguments)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ 解析AI参数失败: {e}")
                    return MCPTestResult(
                        success=False,
                        message="❌ AI返回的参数格式错误",
                        error=f"无法解析参数JSON: {str(e)}",
                        tools_count=len(tools)
                    )
            
            logger.info(f"🤖 AI选择的工具: {tool_name}")
            logger.info(f"📝 AI生成的参数: {test_arguments}")
            
            # 7. 调用MCP工具
            call_start = time.time()
            try:
                tool_result = await mcp_registry.call_tool(
                    user.user_id,
                    plugin.plugin_name,
                    tool_name,
                    test_arguments
                )
                
                call_end = time.time()
                call_time = round((call_end - call_start) * 1000, 2)
                total_time = round((call_end - start_time) * 1000, 2)
                
                # 格式化结果
                result_str = str(tool_result)
                if len(result_str) > 800:
                    result_preview = result_str[:800] + "\n...(结果已截断)"
                else:
                    result_preview = result_str
                
                return MCPTestResult(
                    success=True,
                    message=f"✅ Function Calling测试成功！工具 '{tool_name}' 调用正常",
                    response_time_ms=total_time,
                    tools_count=len(tools),
                    suggestions=[
                        f"🤖 AI选择: {tool_name}",
                        f"📝 参数: {json.dumps(test_arguments, ensure_ascii=False)}",
                        f"⏱️ 耗时: {call_time}ms",
                        f"📊 结果:\n{result_preview}"
                    ]
                )
                
            except Exception as call_error:
                call_end = time.time()
                total_time = round((call_end - start_time) * 1000, 2)
                
                logger.warning(f"工具调用失败: {tool_name}, 错误: {call_error}")
                
                return MCPTestResult(
                    success=True,  # 连接成功就算测试通过
                    message=f"⚠️ 连接成功，但工具调用失败",
                    response_time_ms=total_time,
                    tools_count=len(tools),
                    error=f"工具 '{tool_name}' 调用失败: {str(call_error)}",
                    suggestions=[
                        f"✅ 连接测试: 成功",
                        f"❌ 工具调用测试: 失败",
                        f"🤖 AI选择: {tool_name}",
                        f"❌ 错误: {str(call_error)}",
                        "💡 可能原因: API Key无效、参数错误或服务限制"
                    ]
                )
                
        except Exception as e:
            end_time = time.time()
            total_time = round((end_time - start_time) * 1000, 2)
            
            logger.error(f"测试插件失败: {plugin.plugin_name}, 错误: {e}")
            
            return MCPTestResult(
                success=False,
                message="❌ 测试失败",
                response_time_ms=total_time,
                error=str(e),
                error_type=type(e).__name__,
                suggestions=[
                    "请检查服务器是否在线",
                    "请确认配置正确",
                    "请检查API Key是否有效"
                ]
            )
    
    def _convert_tools_to_openai_format(self, tools: list) -> list:
        """将MCP工具格式转换为OpenAI Function Calling格式"""
        openai_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                }
            }
            if "inputSchema" in tool:
                openai_tool["function"]["parameters"] = tool["inputSchema"]
            openai_tools.append(openai_tool)
        return openai_tools


# 全局单例
mcp_test_service = MCPTestService()