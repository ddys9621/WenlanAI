"""
用户管理模块 - 使用数据库存储
"""
import hashlib
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from pydantic import BaseModel


class User(BaseModel):
    """用户数据传输对象"""
    user_id: str
    username: str
    display_name: str
    avatar_url: Optional[str] = None
    trust_level: int = 0
    is_admin: bool = False
    linuxdo_id: str
    email: Optional[str] = None
    created_at: str
    last_login: str


def normalize_email(email: str) -> str:
    """邮箱统一小写去空白，作为唯一标识比较。"""
    return email.strip().lower()


def email_user_id(email: str) -> str:
    return f"email_{hashlib.md5(normalize_email(email).encode()).hexdigest()[:16]}"


def linuxdo_user_id(linuxdo_id: str) -> str:
    return f"linuxdo_{linuxdo_id}"


def is_email_user(user_id: str) -> bool:
    """用户来源以 user_id 前缀区分：email_ 是邮箱注册用户"""
    return user_id.startswith("email_")


class UserManager:
    """用户管理器 - 使用数据库存储（SQLite嵌入式数据库）"""

    def __init__(self):
        """初始化用户管理器"""
        pass

    async def _get_session(self) -> AsyncSession:
        """获取数据库会话"""
        from app.database import get_engine

        engine = await get_engine("_global_users_")
        
        session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        return session_maker()
    
    async def create_or_update_local_user(
        self,
        user_id: str,
        username: str,
        display_name: str,
        avatar_url: Optional[str] = None,
        trust_level: int = 0,
        is_admin: bool = False,
    ) -> User:
        """创建或更新本地用户。"""
        from app.models.user import User as UserModel

        async with await self._get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if user:
                user.username = username
                user.display_name = display_name
                user.avatar_url = avatar_url
                user.trust_level = trust_level
                user.last_login = datetime.now()
                if is_admin and not user.is_admin:
                    user.is_admin = True
            else:
                user = UserModel(
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    trust_level=trust_level,
                    is_admin=is_admin,
                    linuxdo_id=user_id,
                    created_at=datetime.now(),
                    last_login=datetime.now()
                )
                session.add(user)

            await session.commit()
            await session.refresh(user)

            return User(**user.to_dict())
    
    async def get_user(self, user_id: str) -> Optional[User]:
        """获取用户"""
        from app.models.user import User as UserModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                return User(**user.to_dict())
            return None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """按邮箱查用户（大小写不敏感）"""
        from app.models.user import User as UserModel

        async with await self._get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.email == normalize_email(email))
            )
            user = result.scalar_one_or_none()
            return User(**user.to_dict()) if user else None

    async def get_user_by_linuxdo_id(self, linuxdo_id: str) -> Optional[User]:
        """按 Linux.do 用户 ID 查用户"""
        return await self.get_user(linuxdo_user_id(linuxdo_id))

    async def create_email_user(self, email: str, display_name: str) -> User:
        """创建邮箱注册用户：username 用完整邮箱（避免与本地用户名撞车），普通用户、trust_level 0。"""
        from app.models.user import User as UserModel

        email = normalize_email(email)
        user_id = email_user_id(email)
        async with await self._get_session() as session:
            user = UserModel(
                user_id=user_id,
                username=email,
                display_name=display_name,
                avatar_url=None,
                trust_level=0,
                is_admin=False,
                linuxdo_id=user_id,
                email=email,
                created_at=datetime.now(),
                last_login=datetime.now(),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return User(**user.to_dict())

    async def upsert_linuxdo_user(
        self,
        linuxdo_id: str,
        username: str,
        display_name: str,
        avatar_url: Optional[str],
        trust_level: int,
    ) -> User:
        """Linux.do 授权登录：不存在则创建普通用户，存在则同步资料。

        禁用状态独立存 user_account_status 表，trust_level 照实同步远端信任等级即可
        （被禁用的用户由 linuxdo_callback 的 is_disabled 判定挡在登录外）。
        """
        from app.models.user import User as UserModel

        user_id = linuxdo_user_id(linuxdo_id)
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if user:
                user.username = username
                user.display_name = display_name
                user.avatar_url = avatar_url
                user.trust_level = trust_level
                user.last_login = datetime.now()
            else:
                user = UserModel(
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    trust_level=trust_level,
                    is_admin=False,
                    linuxdo_id=linuxdo_id,
                    created_at=datetime.now(),
                    last_login=datetime.now(),
                )
                session.add(user)

            await session.commit()
            await session.refresh(user)
            return User(**user.to_dict())
    
    async def get_all_users(self) -> List[User]:
        """获取所有用户"""
        from app.models.user import User as UserModel
        
        async with await self._get_session() as session:
            result = await session.execute(select(UserModel))
            users = result.scalars().all()
            
            return [User(**user.to_dict()) for user in users]


# 全局用户管理器实例
user_manager = UserManager()
