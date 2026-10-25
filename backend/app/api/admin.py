"""
管理员API - 用户管理功能 + 登录方式设置 + 公告弹窗设置
"""
from fastapi import APIRouter, HTTPException, Request, Depends, File, UploadFile
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import asyncio
import hashlib
import os
import uuid
import weakref
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import mark_config_password_superseded
from app.database import get_db, init_db
from app.models.user import User
from app.user_manager import user_manager
from app.user_password import password_manager
from app.services import announcement_service
from app.services import admin_audit_service, user_status_service
from app.services.announcement_service import AnnouncementUpdate, announcement_store
from app.services.auth_settings_service import AuthSettingsUpdate, auth_settings_store
from app.services.email_service import BRAND_NAME, SmtpConfig, send_email
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["管理员"])


# ==================== 请求/响应模型 ====================

class CreateUserRequest(BaseModel):
    """创建用户请求"""
    username: str = Field(..., min_length=3, max_length=20, description="用户名")
    display_name: str = Field(..., min_length=2, max_length=50, description="显示名称")
    password: Optional[str] = Field(None, min_length=6, description="初始密码，留空则自动生成")
    avatar_url: Optional[str] = Field(None, description="头像URL")
    trust_level: int = Field(0, ge=0, le=9, description="信任等级")
    is_admin: bool = Field(False, description="是否为管理员")


class UpdateUserRequest(BaseModel):
    """更新用户请求"""
    display_name: Optional[str] = Field(None, min_length=2, max_length=50)
    avatar_url: Optional[str] = None
    trust_level: Optional[int] = Field(None, ge=-1, le=9)
    is_admin: Optional[bool] = Field(None, description="是否为管理员")


class ToggleStatusRequest(BaseModel):
    """切换用户状态请求"""
    is_active: bool = Field(..., description="true=启用, false=禁用")


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    new_password: Optional[str] = Field(None, min_length=6, description="新密码，留空则重置为默认密码")


class CreateUserResponse(BaseModel):
    """创建用户响应"""
    success: bool
    message: str
    user: dict
    default_password: Optional[str] = None


class TestEmailRequest(BaseModel):
    """发送测试邮件请求"""
    to: str = Field(..., min_length=3, max_length=200, description="收件邮箱")


# ==================== 并发串行锁 ====================

# 用户增 / 改 / 禁 / 删按事件循环共用一把锁，串行化「读—判定—写」临界区：
# 避免同名并发建两个、并发禁用 / 降权把最后一个活跃管理员清零（所有会话共用一个 SQLite 连接）。
_admin_lock_by_loop: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _admin_mutation_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _admin_lock_by_loop.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _admin_lock_by_loop[loop] = lock
    return lock


# ==================== 权限检查依赖 ====================

async def check_admin(request: Request) -> User:
    """检查管理员权限"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    return user


# ==================== API 端点 ====================

@router.get("/users")
async def get_users(
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取用户列表（仅管理员）"""
    try:
        all_users = await user_manager.get_all_users()

        disabled_ids = await user_status_service.disabled_user_ids([u.user_id for u in all_users])
        users_data = []
        for user in all_users:
            # user_manager 返回的是 Pydantic User 对象，直接转为 dict
            user_dict = user.model_dump()
            user_dict["is_active"] = user.user_id not in disabled_ids
            users_data.append(user_dict)
        
        logger.info(f"管理员 {admin.user_id} 获取用户列表，共 {len(users_data)} 个用户")
        
        return {
            "total": len(users_data),
            "users": users_data
        }
    except Exception as e:
        logger.error(f"获取用户列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取用户列表失败: {str(e)}")


@router.post("/users")
async def create_user(
    data: CreateUserRequest,
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """添加用户（仅管理员）"""
    lock = _admin_mutation_lock()
    await lock.acquire()
    try:
        # 检查用户名是否已存在
        all_users = await user_manager.get_all_users()
        for user in all_users:
            if user.username == data.username:
                raise HTTPException(status_code=409, detail="用户名已存在")
        
        # 生成用户ID
        user_id = f"admin_created_{hashlib.md5(data.username.encode()).hexdigest()[:16]}"
        
        # 创建本地用户
        new_user = await user_manager.create_or_update_local_user(
            user_id=user_id,
            username=data.username,
            display_name=data.display_name,
            avatar_url=data.avatar_url,
            trust_level=data.trust_level,
            is_admin=data.is_admin,
        )
        
        # 设置密码
        actual_password = await password_manager.set_password(
            user_id=new_user.user_id,
            username=data.username,
            password=data.password
        )
        
        # 初始化用户数据库
        try:
            await init_db(new_user.user_id)
            logger.info(f"用户 {new_user.user_id} 数据库初始化成功")
        except Exception as e:
            logger.error(f"用户 {new_user.user_id} 数据库初始化失败: {e}")
        
        logger.info(f"管理员 {admin.user_id} 创建了新用户 {new_user.user_id} ({data.username})")
        await admin_audit_service.record(
            admin, "user.create", new_user,
            detail={"username": data.username, "is_admin": data.is_admin, "generated_password": not data.password},
        )
        
        return CreateUserResponse(
            success=True,
            message="用户创建成功",
            user=new_user.model_dump(),
            default_password=actual_password if not data.password else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建用户失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建用户失败: {str(e)}")
    finally:
        lock.release()


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UpdateUserRequest,
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """编辑用户信息（仅管理员）"""
    lock = _admin_mutation_lock()
    await lock.acquire()
    try:
        # 获取目标用户
        target_user = await user_manager.get_user(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 更新用户信息
        async with await user_manager._get_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                raise HTTPException(status_code=404, detail="用户不存在")
            
            # 更新字段
            if data.display_name is not None:
                db_user.display_name = data.display_name
            if data.avatar_url is not None:
                db_user.avatar_url = data.avatar_url
            if data.trust_level is not None:
                db_user.trust_level = data.trust_level
            if data.is_admin is not None:
                # 检查是否是最后一个管理员
                if db_user.is_admin and not data.is_admin:
                    all_users = await user_manager.get_all_users()
                    admin_count = sum(1 for u in all_users if u.is_admin)
                    if admin_count <= 1:
                        raise HTTPException(status_code=400, detail="不能取消最后一个管理员的权限")
                db_user.is_admin = data.is_admin
            
            await session.commit()
            await session.refresh(db_user)
        
        logger.info(f"管理员 {admin.user_id} 更新了用户 {user_id} 的信息")
        
        updated_user = await user_manager.get_user(user_id)
        await admin_audit_service.record(
            admin, "user.update", updated_user,
            detail={"changed": sorted(data.model_dump(exclude_none=True).keys())},
        )
        user_dict = updated_user.model_dump()
        user_dict["is_active"] = not await user_status_service.is_disabled(user_id)
        
        return {
            "success": True,
            "message": "用户信息更新成功",
            "user": user_dict
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新用户失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新用户失败: {str(e)}")
    finally:
        lock.release()


@router.post("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: str,
    data: ToggleStatusRequest,
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """切换用户状态（启用/禁用）（仅管理员）"""
    lock = _admin_mutation_lock()
    await lock.acquire()
    try:
        # 不允许禁用自己
        if user_id == admin.user_id:
            raise HTTPException(status_code=400, detail="不能禁用自己的账号")

        # 获取目标用户
        target_user = await user_manager.get_user(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 禁用管理员前，确保禁用后仍有至少一个活跃管理员
        if not data.is_active and target_user.is_admin:
            all_users = await user_manager.get_all_users()
            disabled_ids = await user_status_service.disabled_user_ids([u.user_id for u in all_users])
            others_active_admin = [
                u for u in all_users
                if u.is_admin and u.user_id != user_id and u.user_id not in disabled_ids
            ]
            if not others_active_admin:
                raise HTTPException(status_code=400, detail="不能禁用最后一个活跃管理员")

        # 禁用状态独立于 trust_level（后者只作信任等级展示），启用不再冲掉真实等级
        await user_status_service.set_disabled(user_id, not data.is_active)
        if not data.is_active:
            await user_status_service.revoke_sessions(user_id)

        status_text = "启用" if data.is_active else "禁用"
        logger.info(f"管理员 {admin.user_id} {status_text}了用户 {user_id}")
        await admin_audit_service.record(admin, "user.enable" if data.is_active else "user.disable", target_user)

        return {
            "success": True,
            "message": f"用户已{status_text}",
            "is_active": data.is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"切换用户状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"切换用户状态失败: {str(e)}")
    finally:
        lock.release()


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    data: ResetPasswordRequest,
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """重置用户密码（仅管理员）"""
    try:
        # 获取目标用户
        target_user = await user_manager.get_user(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 重置密码
        actual_password = await password_manager.set_password(
            user_id=user_id,
            username=target_user.username,
            password=data.new_password
        )
        await mark_config_password_superseded(user_id)
        # 密码被重置，该用户已有的登录态全部作废
        await user_status_service.revoke_sessions(user_id)
        
        logger.info(f"管理员 {admin.user_id} 重置了用户 {user_id} 的密码")
        await admin_audit_service.record(
            admin, "user.reset_password", target_user, detail={"generated": data.new_password is None},
        )
        
        return {
            "success": True,
            "message": "密码重置成功",
            "new_password": actual_password
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置密码失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重置密码失败: {str(e)}")


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    user_id: str,
    admin: User = Depends(check_admin),
):
    """强制下线（仅管理员）：让该用户此刻之前签发的所有会话令牌失效，下次请求即需重新登录"""
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="不能强制下线自己，请直接退出登录")
    target_user = await user_manager.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await user_status_service.revoke_sessions(user_id)
    logger.info(f"管理员 {admin.user_id} 强制下线了用户 {user_id}")
    await admin_audit_service.record(admin, "user.revoke_sessions", target_user)
    return {"success": True, "message": "已强制下线，该用户需重新登录"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(check_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除用户（仅管理员，慎用）"""
    lock = _admin_mutation_lock()
    await lock.acquire()
    try:
        # 不允许删除自己
        if user_id == admin.user_id:
            raise HTTPException(status_code=400, detail="不能删除自己的账号")
        
        # 获取目标用户
        target_user = await user_manager.get_user(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 检查是否是最后一个管理员
        if target_user.is_admin:
            all_users = await user_manager.get_all_users()
            admin_count = sum(1 for u in all_users if u.is_admin)
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="不能删除最后一个管理员账号")
        
        # 删除用户（包括密码记录）
        async with await user_manager._get_session() as session:
            # 删除用户记录
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            if db_user:
                await session.delete(db_user)
            
            # 删除密码记录
            from app.models.user import UserPassword
            result = await session.execute(
                select(UserPassword).where(UserPassword.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            if pwd_record:
                await session.delete(pwd_record)
            
            await session.commit()
        
        logger.warning(f"管理员 {admin.user_id} 删除了用户 {user_id}")
        await admin_audit_service.record(
            admin, "user.delete", target_user, detail={"username": target_user.username, "was_admin": target_user.is_admin},
        )
        
        return {
            "success": True,
            "message": "用户已删除"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除用户失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除用户失败: {str(e)}")
    finally:
        lock.release()


# ==================== 操作审计 API ====================

@router.get("/audit-logs", summary="管理员操作记录（倒序分页）")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(check_admin),
):
    total, items = await admin_audit_service.list_logs(limit=limit, offset=offset)
    return {"total": total, "items": items, "limit": limit, "offset": offset}


# ==================== 登录方式设置 API ====================

@router.get("/auth-settings", summary="获取登录方式设置（脱敏）")
async def get_auth_settings(admin: User = Depends(check_admin)):
    """Linux.do / 邮箱 登录注册开关与凭据；秘密字段只返回 *_set 布尔"""
    settings = await auth_settings_store.get()
    return settings.to_admin_view()


@router.put("/auth-settings", summary="更新登录方式设置")
async def update_auth_settings(
    data: AuthSettingsUpdate,
    admin: User = Depends(check_admin),
):
    """部分更新：未传（None）的字段保持不变，秘密字段传空串才会清空"""
    settings = await auth_settings_store.apply_update(data)
    changed = sorted(data.model_dump(exclude_none=True).keys())
    logger.info(f"管理员 {admin.user_id} 更新登录方式设置: {changed}")
    return settings.to_admin_view()


@router.post("/auth-settings/test-email", summary="用当前 SMTP 配置发送测试邮件")
async def send_test_email(
    data: TestEmailRequest,
    admin: User = Depends(check_admin),
):
    """校验 SMTP 配置可用性；发送失败把 SMTP 报错原文返给管理员排查"""
    settings = await auth_settings_store.get()
    if not settings.smtp_configured():
        raise HTTPException(status_code=400, detail="请先填写并保存 SMTP 服务器与发件人邮箱")

    try:
        await send_email(
            SmtpConfig.from_auth_settings(settings),
            data.to,
            f"【{BRAND_NAME}】SMTP 测试邮件",
            "这是一封测试邮件，收到即表示 SMTP 配置可用。",
        )
    except Exception as e:
        logger.warning(f"管理员 {admin.user_id} 发送测试邮件到 {data.to} 失败: {e}")
        raise HTTPException(status_code=502, detail=f"发送失败: {e}")

    logger.info(f"管理员 {admin.user_id} 发送测试邮件到 {data.to} 成功")
    return {"success": True, "message": f"测试邮件已发送至 {data.to}"}


# ==================== 公告弹窗设置 API ====================

@router.get("/announcement", summary="获取公告弹窗设置")
async def get_announcement_settings(admin: User = Depends(check_admin)):
    settings = await announcement_store.get()
    return settings.to_admin_view(datetime.now(timezone.utc))


@router.put("/announcement", summary="更新公告弹窗设置")
async def update_announcement_settings(
    data: AnnouncementUpdate,
    admin: User = Depends(check_admin),
):
    """部分更新：未传（None）的字段保持不变；start_at / end_at 传空串清空。"""
    settings = await announcement_store.apply_update(data)
    changed = sorted(data.model_dump(exclude_none=True).keys())
    logger.info(f"管理员 {admin.user_id} 更新公告弹窗设置: {changed}")
    return settings.to_admin_view(datetime.now(timezone.utc))


@router.post("/announcement/image", summary="上传公告图片（≤2MB，jpg/png/gif/webp）")
async def upload_announcement_image(
    file: UploadFile = File(...),
    admin: User = Depends(check_admin),
):
    """按文件头识别格式（不信任 Content-Type），保存后直接写入配置并清理被替换的旧图。"""
    data = await file.read(announcement_service.MAX_IMAGE_BYTES + 1)
    if len(data) > announcement_service.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"图片过大，上限 {announcement_service.MAX_IMAGE_BYTES // 1024 // 1024}MB")
    ext = announcement_service.sniff_image_ext(data)
    if not ext:
        raise HTTPException(status_code=400, detail="只支持 jpg / png / gif / webp 图片")

    os.makedirs(announcement_service.IMAGE_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(announcement_service.IMAGE_DIR, name), "wb") as fh:
        fh.write(data)

    image_url = f"{announcement_service.IMAGE_URL_PREFIX}{name}"
    await announcement_store.apply_update(AnnouncementUpdate(image_url=image_url))
    logger.info(f"管理员 {admin.user_id} 上传公告图片 {name}（{len(data)} 字节）")
    return {"image_url": image_url}
