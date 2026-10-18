"""HTTP MCP客户端 - 使用官方 MCP Python SDK 实现（Streamable HTTP / SSE 两种远程传输）"""
import asyncio
from datetime import timedelta
from typing import Dict, Any, List, Optional

from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import AnyUrl

from app.logger import get_logger
from app.mcp.server_config import TRANSPORT_SSE, TRANSPORT_STREAMABLE_HTTP
from app.utils.outbound_guard import OutboundBlockedError, OutboundGuard, mcp_http_client_factory

logger = get_logger(__name__)

# SSE 长连接读超时（秒）：工具调用期间服务端可能长时间不发消息
_SSE_READ_TIMEOUT_SECONDS = 300


class MCPError(Exception):
    """MCP错误"""
    pass


class HTTPMCPClient:
    """HTTP模式MCP客户端（基于官方 MCP Python SDK）"""
    
    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
        transport: str = TRANSPORT_STREAMABLE_HTTP,
        guard: Optional[OutboundGuard] = None,
    ):
        """
        初始化HTTP MCP客户端
        
        Args:
            url: MCP服务器URL
            headers: HTTP请求头
            env: 环境变量（用于API Key等）
            timeout: 超时时间（秒）
            transport: 远程传输方式，TRANSPORT_STREAMABLE_HTTP（默认）或 TRANSPORT_SSE
            guard: 出站守卫（插件主人是普通用户时）；None = 不限制
        """
        if transport not in (TRANSPORT_STREAMABLE_HTTP, TRANSPORT_SSE):
            raise ValueError(f"不支持的 transport: {transport}")

        # URL 原样保留：尾部斜杠、查询串里的 key（如 ?key=xxx）都不能改写
        self.url = url
        self.headers = dict(headers or {})
        self.env = env or {}
        self.timeout = timeout
        self.transport = transport
        self.guard = guard
        
        # 如果env中有API Key，添加到headers
        if 'API_KEY' in self.env:
            self.headers['Authorization'] = f'Bearer {self.env["API_KEY"]}'
        
        self._session: Optional[ClientSession] = None
        self._initialized = False
        self._lock = asyncio.Lock()

        # 连接守护任务：SDK 的 transport / ClientSession 上下文都在它里面进入与退出。
        # anyio 的 cancel scope 要求同一任务进出；若留在某个请求任务里，请求结束时
        # starlette 的 TaskGroup 退出会抛 "Attempted to exit a cancel scope ..." 并重置连接。
        self._runner: Optional[asyncio.Task] = None
        self._ready: Optional[asyncio.Event] = None
        self._closing: Optional[asyncio.Event] = None
        self._connect_error: Optional[BaseException] = None

    def _open_transport(self):
        """按 transport 创建 SDK 传输上下文（headers 在此真正下发）；有守卫时 SDK 的 httpx 客户端每个连接都过守卫"""
        extra = {"httpx_client_factory": mcp_http_client_factory(self.guard)} if self.guard is not None else {}
        if self.transport == TRANSPORT_SSE:
            return sse_client(
                self.url,
                headers=self.headers,
                timeout=self.timeout,
                sse_read_timeout=_SSE_READ_TIMEOUT_SECONDS,
                **extra,
            )
        return streamablehttp_client(
            self.url,
            headers=self.headers,
            timeout=timedelta(seconds=self.timeout),
            sse_read_timeout=timedelta(seconds=_SSE_READ_TIMEOUT_SECONDS),
            **extra,
        )
    
    async def _run_connection(self, ready: asyncio.Event, closing: asyncio.Event):
        """连接守护任务：建立连接 → 标记就绪 → 挂起直到 close() → 在本任务内按序退出上下文"""
        session: Optional[ClientSession] = None
        try:
            # streamable_http 产出 (read, write, get_session_id)，sse 产出 (read, write)
            async with self._open_transport() as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    self._session = session
                    self._initialized = True
                    ready.set()
                    await closing.wait()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._connect_error = e
            if session is not None:
                logger.warning(f"⚠️ MCP连接中断或关闭时出错: {self.url}: {e}")
        finally:
            # 只清理本任务建立的会话：被超时取消的旧守护任务不能误清掉新连接
            if self._session is session:
                self._session = None
                self._initialized = False
            ready.set()

    async def _ensure_connected(self):
        """确保连接已建立（连接失败抛 MCPError，可重试）"""
        async with self._lock:
            if self._session is not None:
                return
            if self._runner is not None and not self._runner.done():
                # 上一次连接已断开但守护任务仍在收尾，先等它退出
                await self._shutdown_runner()

            if self.guard is not None:
                # 先查一遍给出清楚的原因（SDK 里的拦截会被它的 TaskGroup 包成看不懂的 ExceptionGroup）
                try:
                    await self.guard.precheck(self.url)
                except OutboundBlockedError as e:
                    raise MCPError(f"连接MCP服务器失败: {e}") from e

            logger.info(f"🔗 连接到MCP服务器: {self.url} ({self.transport})")
            self._ready = asyncio.Event()
            self._closing = asyncio.Event()
            self._connect_error = None
            self._runner = asyncio.create_task(
                self._run_connection(self._ready, self._closing), name=f"mcp-conn:{self.url}"
            )
            await self._ready.wait()

            if self._session is None:
                error = self._connect_error
                self._runner = None
                logger.error(f"❌ MCP连接失败: {error}")
                raise MCPError(f"连接MCP服务器失败: {error}")
            logger.info(f"✅ MCP会话初始化成功")

    async def _shutdown_runner(self):
        """通知守护任务退出并等待其收尾（超时则取消）"""
        runner, self._runner = self._runner, None
        if self._closing is not None:
            self._closing.set()
        if runner is None or runner.done():
            return
        try:
            await asyncio.wait_for(runner, timeout=15)
        except asyncio.TimeoutError:
            logger.warning(f"关闭MCP连接超时，强制取消: {self.url}")
            runner.cancel()
        except Exception as e:
            logger.error(f"关闭MCP连接失败: {self.url}: {e}")

    async def _cleanup(self):
        """清理连接资源"""
        await self._shutdown_runner()
        self._session = None
        self._initialized = False
    
    async def initialize(self) -> Dict[str, Any]:
        """
        初始化MCP会话
        
        Returns:
            初始化响应
        """
        await self._ensure_connected()
        return {"status": "initialized"}
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        列举可用工具
        
        Returns:
            工具列表
        """
        try:
            await self._ensure_connected()
            
            result = await self._session.list_tools()
            
            # 转换为字典格式
            tools = []
            for tool in result.tools:
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                }
                tools.append(tool_dict)
            
            logger.info(f"获取到 {len(tools)} 个工具")
            return tools
            
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")
            raise MCPError(f"获取工具列表失败: {str(e)}")
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            工具执行结果
        """
        try:
            await self._ensure_connected()
            
            logger.info(f"调用工具: {tool_name}")
            logger.debug(f"参数: {arguments}")
            
            result = await self._session.call_tool(tool_name, arguments)
            
            # 处理返回结果
            # MCP SDK 返回 CallToolResult 对象
            if result.content:
                # 提取第一个content的文本
                for content in result.content:
                    if isinstance(content, types.TextContent):
                        return content.text
                    elif isinstance(content, types.ImageContent):
                        return {
                            "type": "image",
                            "data": content.data,
                            "mimeType": content.mimeType
                        }
                # 如果没有文本内容，返回原始内容
                return result.content[0] if result.content else None
            
            # 如果有结构化内容（2025-06-18规范）
            if hasattr(result, 'structuredContent') and result.structuredContent:
                return result.structuredContent
            
            return None
            
        except Exception as e:
            logger.error(f"调用工具失败: {tool_name}, 错误: {e}")
            raise MCPError(f"调用工具失败: {str(e)}")
    
    async def list_resources(self) -> List[Dict[str, Any]]:
        """
        列举可用资源
        
        Returns:
            资源列表
        """
        try:
            await self._ensure_connected()
            
            result = await self._session.list_resources()
            
            # 转换为字典格式
            resources = []
            for resource in result.resources:
                resource_dict = {
                    "uri": str(resource.uri),
                    "name": resource.name,
                    "description": resource.description or "",
                    "mimeType": resource.mimeType or ""
                }
                resources.append(resource_dict)
            
            logger.info(f"获取到 {len(resources)} 个资源")
            return resources
            
        except Exception as e:
            logger.error(f"获取资源列表失败: {e}")
            raise MCPError(f"获取资源列表失败: {str(e)}")
    
    async def read_resource(self, uri: str) -> Any:
        """
        读取资源
        
        Args:
            uri: 资源URI
            
        Returns:
            资源内容
        """
        try:
            await self._ensure_connected()
            
            result = await self._session.read_resource(AnyUrl(uri))
            
            # 提取资源内容
            if result.contents:
                content = result.contents[0]
                if isinstance(content, types.TextContent):
                    return content.text
                elif isinstance(content, types.ImageContent):
                    return {
                        "type": "image",
                        "data": content.data,
                        "mimeType": content.mimeType
                    }
                elif isinstance(content, types.BlobResourceContents):
                    return {
                        "type": "blob",
                        "blob": content.blob,
                        "mimeType": content.mimeType
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"读取资源失败: {uri}, 错误: {e}")
            raise MCPError(f"读取资源失败: {str(e)}")
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        测试连接
        
        Returns:
            测试结果
        """
        import time
        start_time = time.time()
        
        try:
            # 尝试连接并列举工具（直接调用SDK，避免重复日志）
            await self._ensure_connected()
            
            result = await self._session.list_tools()
            
            # 转换为字典格式
            tools = []
            for tool in result.tools:
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                }
                tools.append(tool_dict)
            
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            logger.info(f"✅ 连接测试成功，获取到 {len(tools)} 个工具")
            
            return {
                "success": True,
                "message": "连接测试成功",
                "response_time_ms": response_time,
                "tools_count": len(tools),
                "tools": tools
            }
            
        except Exception as e:
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            return {
                "success": False,
                "message": "连接测试失败",
                "response_time_ms": response_time,
                "error": str(e),
                "error_type": type(e).__name__,
                "suggestions": [
                    "请检查服务器URL是否正确",
                    "请确认API Key是否有效",
                    "请检查网络连接",
                    "请确认MCP服务器是否在线"
                ]
            }
    
    async def close(self):
        """关闭客户端连接（可从任意任务调用，上下文退出由守护任务完成）"""
        logger.info(f"关闭MCP客户端: {self.url}")
        async with self._lock:
            await self._cleanup()
