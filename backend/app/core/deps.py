from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import decode_token
from app.domain.auth.user import can_login, is_admin
from app.infrastructure.persistence.db import get_session
from app.infrastructure.persistence.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def current_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


CurrentRidDep = Annotated[str, Depends(current_request_id)]


def _bearer(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(4010, "未提供登录凭证")
    return decode_token(header[7:], expect="access")


async def get_current_user(request: Request, session: SessionDep) -> User:
    payload = _bearer(request)
    user = (
        await session.execute(select(User).where(User.id == payload["sub"]))
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(4010, "用户不存在")
    if not can_login(user.status):
        raise ApiError(4030, "账号已被停用")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not is_admin(user.role):
        raise ApiError(4030, "需要管理员权限")
    return user
