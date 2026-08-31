from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.auth.user import STUDENT
from app.infrastructure.persistence.models import User


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, username: str, email: str, password: str) -> User:
        exists = (
            await self._session.execute(
                select(User).where((User.username == username) | (User.email == email))
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ApiError(4090, "用户名或邮箱已存在")

        # bcrypt 约 100ms/次，属同步阻塞调用，须卸载到线程池（ADR-0002）
        hashed = await run_in_threadpool(hash_password, password)
        user = User(username=username, email=email, hashed_password=hashed, role=STUDENT)
        self._session.add(user)
        await self._session.flush()
        return user

    async def login(self, username: str, password: str) -> tuple[User, str, str]:
        user = (
            await self._session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(4010, "用户名或密码错误")

        if not await run_in_threadpool(verify_password, password, user.hashed_password):
            raise ApiError(4010, "用户名或密码错误")

        user.last_login_at = datetime.now(UTC)
        await self._session.flush()
        return user, create_access_token(user.id, user.role), create_refresh_token(user.id)

    async def get_by_id(self, user_id: str) -> User:
        user = (
            await self._session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(4010, "用户不存在")
        return user
