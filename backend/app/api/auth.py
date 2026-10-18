"""
认证 API - 本地账号密码 + Linux.do OAuth2 + 邮箱验证码注册/密码登录

Linux.do / 邮箱两种方式是否开放由管理员后台（system_settings.auth）决定，本地账号由 .env 决定。
"""
from fastapi import APIRouter, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Dict, Optional
import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from app.user_manager import user_manager, is_email_user, normalize_email
from app.user_password import password_manager
from app.database import init_db
from app.logger import get_logger
from app.config import settings
from app.services.auth_settings_service import AuthSettings, auth_settings_store
from app.services.email_service import BRAND_NAME, CooldownError, SmtpConfig, email_code_store, send_email
from app.services.oauth_service import LinuxDOOAuthService
from app.services.system_settings_store import JsonSettingsStore


CHINA_TZ = timezone(timedelta(hours=8))


def get_china_now():
    """获取中国当前时间"""
    return datetime.now(CHINA_TZ)


logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class LocalLoginRequest(BaseModel):
    """本地登录请求"""
    username: str
    password: str


class LocalLoginResponse(BaseModel):
    """本地登录响应"""
    success: bool
    message: str
    user: Optional[dict] = None


class SetPasswordRequest(BaseModel):
    """设置密码请求"""
    password: str


class SetPasswordResponse(BaseModel):
    """设置密码响应"""
    success: bool
    message: str


class PasswordStatusResponse(BaseModel):
    """密码状态响应"""
    has_password: bool
    has_custom_password: bool
    username: Optional[str] = None
    default_password: Optional[str] = None


@router.get("/config")
async def get_auth_config():
    """获取认证配置信息：本地账号来自 .env，Linux.do / 邮箱来自管理员后台（返回的是有效开关）"""
    auth_settings = await auth_settings_store.get()
    return {
        "local_auth_enabled": settings.LOCAL_AUTH_ENABLED,
        **auth_settings.effective_flags(),
    }


def _local_user_id(username: str) -> str:
    return f"local_{hashlib.md5(username.encode()).hexdigest()[:16]}"


async def _create_or_update_local_user(username: str):
    return await user_manager.create_or_update_local_user(
        user_id=_local_user_id(username),
        username=username,
        display_name=settings.LOCAL_AUTH_DISPLAY_NAME,
        avatar_url=None,
        trust_level=9,
        is_admin=True,
    )


class _UsedConfigPassword(BaseModel):
    """配置文件里已经用过的密码（指纹）：生效过、或已被网页改密码顶掉；换成别的值才会再生效一次"""
    user_id: str = ""
    password_hash: str = ""


_used_config_password_store = JsonSettingsStore("local_auth", _UsedConfigPassword, "本地账号")


def _config_password_hash() -> str:
    return hashlib.sha256(settings.LOCAL_AUTH_PASSWORD.encode()).hexdigest()


async def _mark_config_password_used(user_id: str) -> None:
    await _used_config_password_store.save(_UsedConfigPassword(user_id=user_id, password_hash=_config_password_hash()))


async def mark_config_password_superseded(user_id: str) -> None:
    """配置账号的密码在网页 / 管理后台改过：配置文件里现在这个密码随之作废"""
    if settings.LOCAL_AUTH_USERNAME and settings.LOCAL_AUTH_PASSWORD and user_id == _local_user_id(settings.LOCAL_AUTH_USERNAME):
        await _mark_config_password_used(user_id)


async def _authenticate_config_local_account(username: str, password: str):
    """Authenticate the configured local admin account."""
    if not settings.LOCAL_AUTH_USERNAME or not settings.LOCAL_AUTH_PASSWORD:
        return None
    if username != settings.LOCAL_AUTH_USERNAME:
        return None

    user_id = _local_user_id(username)
    user = await user_manager.get_user(user_id)
    has_password = user is not None and await password_manager.has_password(user_id)
    used = await _used_config_password_store.get()
    used_hash = used.password_hash if used.user_id == user_id else ""

    if not has_password or (used_hash and used_hash != _config_password_hash()):
        if password != settings.LOCAL_AUTH_PASSWORD:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user:
            user = await _create_or_update_local_user(username)
        await password_manager.set_password(user_id, username, settings.LOCAL_AUTH_PASSWORD)
        await _mark_config_password_used(user_id)
        logger.info(f"[本地登录] 配置账号 {user_id} 已按配置文件设置密码并登录")
        return user

    if not used_hash:
        await _mark_config_password_used(user_id)
    if not await password_manager.verify_password(user_id, password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    logger.info(f"[本地登录] 配置账号 {user_id} 登录成功")
    return user


async def _authenticate_database_local_account(username: str, password: str):
    """Authenticate local database accounts by stored username/password."""
    all_users = await user_manager.get_all_users()

    for user in all_users:
        if is_email_user(user.user_id):
            # 邮箱注册用户只走 /auth/email/login，受「邮箱登录」开关约束
            continue
        password_username = await password_manager.get_username(user.user_id)
        if user.username != username and password_username != username:
            continue

        if not await password_manager.has_password(user.user_id):
            logger.warning(f"[本地登录] 用户 {user.user_id} 没有设置密码")
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not await password_manager.verify_password(user.user_id, password):
            logger.warning(f"[本地登录] 用户 {user.user_id} 密码验证失败")
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        logger.info(f"[本地登录] 本地账号 {user.user_id} 登录成功")
        return user

    logger.info(f"[本地登录] 未找到匹配的本地账号: {username}")
    return None


async def _init_user_db(user_id: str, label: str):
    """登录/注册后确保用户数据表就位；失败只记日志，不阻断登录"""
    try:
        await init_db(user_id)
        logger.info(f"{label} {user_id} 数据库初始化成功")
    except Exception as e:
        logger.error(f"{label} {user_id} 数据库初始化失败: {e}")


async def _set_session_cookies(response: Response, user_id: str):
    max_age = settings.SESSION_EXPIRE_MINUTES * 60
    response.set_cookie(
        key="user_id",
        value=user_id,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )

    expire_time = get_china_now() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
    expire_at = int(expire_time.timestamp())
    response.set_cookie(
        key="session_expire_at",
        value=str(expire_at),
        max_age=max_age,
        httponly=False,
        samesite="lax",
    )


@router.post("/local/login", response_model=LocalLoginResponse)
async def local_login(request: LocalLoginRequest, response: Response):
    """本地账户登录"""
    if not settings.LOCAL_AUTH_ENABLED:
        raise HTTPException(status_code=403, detail="本地账户登录未启用")

    logger.info(f"[本地登录] 尝试登录用户名: {request.username}")

    user = await _authenticate_config_local_account(request.username, request.password)
    if not user:
        user = await _authenticate_database_local_account(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    await _init_user_db(user.user_id, "本地用户")

    await _set_session_cookies(response, user.user_id)
    logger.info(f"✅ [登录] 用户 {user.user_id} 登录成功，会话有效期 {settings.SESSION_EXPIRE_MINUTES} 分钟")

    return LocalLoginResponse(
        success=True,
        message="登录成功",
        user=user.dict(),
    )


# ==================== Linux.do OAuth2 ====================

class AuthUrlResponse(BaseModel):
    auth_url: str
    state: str


# OAuth state 临时存储 {state: 过期时间戳}，防 CSRF；5 分钟内未回调即失效
_oauth_states: Dict[str, float] = {}
_OAUTH_STATE_TTL_SECONDS = 300


def _cleanup_expired_oauth_states():
    now = time.time()
    for state in [s for s, expires in _oauth_states.items() if now > expires]:
        del _oauth_states[state]


def _oauth_service_factory(auth_settings: AuthSettings) -> LinuxDOOAuthService:
    """按当前后台配置构造 OAuth 客户端（测试用替身替换）"""
    return LinuxDOOAuthService(
        client_id=auth_settings.linuxdo_client_id,
        client_secret=auth_settings.linuxdo_client_secret,
        redirect_uri=auth_settings.linuxdo_redirect_uri,
    )


def _login_error_redirect(code: str) -> RedirectResponse:
    """回调链路里的失败统一带错误码跳回登录页，由前端翻译成提示"""
    return RedirectResponse(url=f"/login?error={code}", status_code=302)


@router.get("/linuxdo/url", response_model=AuthUrlResponse)
async def get_linuxdo_auth_url():
    """获取 Linux.do 授权地址"""
    auth_settings = await auth_settings_store.get()
    if not auth_settings.effective_flags()["linuxdo_login_enabled"]:
        raise HTTPException(status_code=403, detail="Linux.do 登录未开启")

    _cleanup_expired_oauth_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time() + _OAUTH_STATE_TTL_SECONDS
    auth_url = _oauth_service_factory(auth_settings).authorization_url(state)
    return AuthUrlResponse(auth_url=auth_url, state=state)


@router.get("/linuxdo/callback")
async def linuxdo_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Linux.do OAuth2 回调：换 token → 拉用户 → 建/更新用户 → 设 Cookie 跳首页"""
    auth_settings = await auth_settings_store.get()
    flags = auth_settings.effective_flags()
    if not flags["linuxdo_login_enabled"]:
        return _login_error_redirect("linuxdo_disabled")

    if error:
        logger.warning(f"[Linux.do] 授权被拒绝或出错: {error}")
        return _login_error_redirect("oauth_denied")

    _cleanup_expired_oauth_states()
    if not code or not state or _oauth_states.pop(state, None) is None:
        logger.warning("[Linux.do] 回调 state 无效或已使用")
        return _login_error_redirect("invalid_state")

    oauth_service = _oauth_service_factory(auth_settings)
    access_token = await oauth_service.fetch_access_token(code)
    if not access_token:
        return _login_error_redirect("token_failed")

    user_info = await oauth_service.fetch_user_info(access_token)
    if not user_info or user_info.get("id") is None:
        return _login_error_redirect("userinfo_failed")

    linuxdo_id = str(user_info["id"])
    username = str(user_info.get("username") or f"linuxdo_{linuxdo_id}")
    existing = await user_manager.get_user_by_linuxdo_id(linuxdo_id)
    if existing is None and not flags["linuxdo_register_enabled"]:
        logger.info(f"[Linux.do] 注册已关闭，拒绝新用户 {username} (id={linuxdo_id})")
        return _login_error_redirect("register_disabled")

    user = await user_manager.upsert_linuxdo_user(
        linuxdo_id=linuxdo_id,
        username=username,
        display_name=str(user_info.get("name") or username),
        avatar_url=user_info.get("avatar_url"),
        trust_level=int(user_info.get("trust_level") or 0),
    )
    if user.trust_level == -1:
        logger.warning(f"[Linux.do] 禁用用户尝试登录: {user.user_id} ({user.username})")
        return _login_error_redirect("user_disabled")

    await _init_user_db(user.user_id, "Linux.do 用户")

    response = RedirectResponse(url="/", status_code=302)
    await _set_session_cookies(response, user.user_id)
    logger.info(f"✅ [Linux.do登录] 用户 {user.user_id} ({user.username}) 登录成功{'' if existing else '（新注册）'}")
    return response


# ==================== 邮箱验证码注册 / 邮箱密码登录 ====================

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailSendCodeRequest(BaseModel):
    email: str


class EmailRegisterRequest(BaseModel):
    email: str
    code: str
    password: str
    display_name: Optional[str] = Field(None, max_length=50)


class EmailLoginRequest(BaseModel):
    email: str
    password: str


def _validate_email(raw: str) -> str:
    email = normalize_email(raw)
    if len(email) > 200 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    return email


async def _require_email_flag(flag: str, message: str) -> AuthSettings:
    auth_settings = await auth_settings_store.get()
    if not auth_settings.effective_flags()[flag]:
        raise HTTPException(status_code=403, detail=message)
    return auth_settings


@router.post("/email/send-code")
async def email_send_code(request: EmailSendCodeRequest):
    """向待注册邮箱发送 6 位验证码"""
    auth_settings = await _require_email_flag("email_register_enabled", "邮箱注册未开启")
    email = _validate_email(request.email)
    if await user_manager.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")

    try:
        code = email_code_store.issue(email)
    except CooldownError as e:
        raise HTTPException(status_code=429, detail=f"发送过于频繁，请 {e.remaining} 秒后再试")

    ttl_minutes = email_code_store.ttl_seconds // 60
    try:
        await send_email(
            SmtpConfig.from_auth_settings(auth_settings),
            email,
            f"【{BRAND_NAME}】邮箱验证码",
            f"您正在注册 {BRAND_NAME} 账号，验证码：{code}（{ttl_minutes} 分钟内有效）。\n\n如非本人操作，请忽略本邮件。",
        )
    except Exception as e:
        email_code_store.discard(email)  # 没发出去就不占冷却，让用户能立刻重试
        logger.error(f"[邮箱注册] 验证码发送到 {email} 失败: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="验证码发送失败，请稍后重试或联系管理员")

    logger.info(f"[邮箱注册] 验证码已发送到 {email}")
    return {
        "success": True,
        "message": "验证码已发送，请查收邮件",
        "cooldown_seconds": email_code_store.cooldown_seconds,
    }


@router.post("/email/register", response_model=LocalLoginResponse)
async def email_register(request: EmailRegisterRequest, response: Response):
    """邮箱 + 验证码 + 密码 注册，成功即登录"""
    await _require_email_flag("email_register_enabled", "邮箱注册未开启")
    email = _validate_email(request.email)
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6个字符")
    if await user_manager.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")
    if not email_code_store.verify(email, request.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    display_name = (request.display_name or "").strip() or email.split("@", 1)[0]
    user = await user_manager.create_email_user(email=email, display_name=display_name)
    await password_manager.set_password(user.user_id, user.username, request.password)
    await _init_user_db(user.user_id, "邮箱用户")

    await _set_session_cookies(response, user.user_id)
    logger.info(f"✅ [邮箱注册] 用户 {user.user_id} ({email}) 注册并登录成功")
    return LocalLoginResponse(success=True, message="注册成功", user=user.model_dump())


@router.post("/email/login", response_model=LocalLoginResponse)
async def email_login(request: EmailLoginRequest, response: Response):
    """邮箱 + 密码 登录"""
    await _require_email_flag("email_login_enabled", "邮箱登录未开启")
    email = _validate_email(request.email)

    user = await user_manager.get_user_by_email(email)
    if not user or not await password_manager.verify_password(user.user_id, request.password):
        logger.info(f"[邮箱登录] 邮箱或密码错误: {email}")
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if user.trust_level == -1:
        logger.warning(f"[邮箱登录] 禁用用户尝试登录: {user.user_id} ({email})")
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    await _init_user_db(user.user_id, "邮箱用户")
    await _set_session_cookies(response, user.user_id)
    logger.info(f"✅ [邮箱登录] 用户 {user.user_id} ({email}) 登录成功")
    return LocalLoginResponse(success=True, message="登录成功", user=user.model_dump())


@router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    """刷新会话 - 延长登录状态"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录，无法刷新会话")

    user = request.state.user

    session_expire_at = request.cookies.get("session_expire_at")
    if session_expire_at:
        try:
            expire_timestamp = int(session_expire_at)
            current_timestamp = int(get_china_now().timestamp())
            remaining_minutes = (expire_timestamp - current_timestamp) / 60

            if remaining_minutes > settings.SESSION_REFRESH_THRESHOLD_MINUTES:
                logger.info(f"⏱️ [刷新会话] 用户 {user.user_id} 会话仍有效，剩余 {int(remaining_minutes)} 分钟")
                return {
                    "message": "会话仍然有效，无需刷新",
                    "remaining_minutes": int(remaining_minutes),
                    "expire_at": expire_timestamp,
                }
        except (ValueError, TypeError):
            pass

    await _set_session_cookies(response, user.user_id)
    expire_at = int((get_china_now() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)).timestamp())

    logger.info(f"用户 {user.user_id} 刷新会话成功")
    return {
        "message": "会话刷新成功",
        "expire_at": expire_at,
        "remaining_minutes": settings.SESSION_EXPIRE_MINUTES,
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    """退出登录"""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        logger.info(f"🚪 [退出] 用户 {user_id} 退出登录")

    response.delete_cookie("user_id")
    response.delete_cookie("session_expire_at")
    return {"message": "退出登录成功"}


@router.get("/user")
async def get_current_user(request: Request):
    """获取当前登录用户信息"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    return request.state.user.dict()


@router.get("/password/status", response_model=PasswordStatusResponse)
async def get_password_status(request: Request):
    """获取当前用户的密码状态"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    user = request.state.user
    has_password = await password_manager.has_password(user.user_id)
    has_custom = await password_manager.has_custom_password(user.user_id)
    username = await password_manager.get_username(user.user_id)

    default_password = None
    if has_password and not has_custom:
        default_password = f"{user.username}@666"

    return PasswordStatusResponse(
        has_password=has_password,
        has_custom_password=has_custom,
        username=username or user.username,
        default_password=default_password,
    )


@router.post("/password/set", response_model=SetPasswordResponse)
async def set_user_password(request: Request, password_req: SetPasswordRequest):
    """设置当前用户的密码"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    user = request.state.user

    if len(password_req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6个字符")

    await password_manager.set_password(user.user_id, user.username, password_req.password)
    await mark_config_password_superseded(user.user_id)
    logger.info(f"用户 {user.user_id} ({user.username}) 设置了自定义密码")

    return SetPasswordResponse(
        success=True,
        message="密码设置成功",
    )
