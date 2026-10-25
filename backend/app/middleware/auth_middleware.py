"""
认证中间件 - 从 Cookie 中提取用户信息并注入到 request.state
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.user_manager import user_manager
from app.services.session_token import get_session_secret, parse_session
from app.services.user_status_service import get_status
from app.logger import get_logger

logger = get_logger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""
    
    async def dispatch(self, request: Request, call_next):
        """
        处理请求，校验会话令牌并把用户信息注入到 request.state
        """
        # Cookie 里是 HMAC 签名令牌；旧的明文 user_id、被篡改或过期的令牌一律验签失败，视为未登录
        token = request.cookies.get("user_id")
        user_id, iat = None, 0
        if token:
            secret = await get_session_secret()
            parsed = parse_session(token, secret)
            if parsed:
                user_id, iat = parsed

        # 注入到 request.state
        if user_id:
            user = await user_manager.get_user(user_id)
            if user:
                # 禁用标志与会话吊销时刻都在 user_account_status 表（一次查询）
                status = await get_status(user_id)
                if status.disabled:
                    logger.warning(f"禁用用户尝试访问: {user_id} ({user.username})")
                    # 清除用户状态，视为未登录
                    request.state.user_id = None
                    request.state.user = None
                    request.state.is_admin = False
                elif status.token_revoked(iat):
                    # 强制下线 / 重置密码 / 改密码之前签发的令牌：视为未登录
                    request.state.user_id = None
                    request.state.user = None
                    request.state.is_admin = False
                else:
                    # 用户正常，注入状态
                    request.state.user_id = user_id
                    request.state.user = user
                    request.state.is_admin = user.is_admin
            else:
                # 用户不存在，清除状态
                request.state.user_id = None
                request.state.user = None
                request.state.is_admin = False
        else:
            # 未登录
            request.state.user_id = None
            request.state.user = None
            request.state.is_admin = False
        
        # 继续处理请求
        response = await call_next(request)
        return response