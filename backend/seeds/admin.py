"""初始管理员种子（自 `app/seed.py` 平移，逻辑零改动 —— P5 Task 12，遗留 M2）。

幂等口径：按 `username` 查存在即跳过，**不覆盖**既有密码。演示机的默认密码写在
README 里，首次登录后必须自行修改（M3 归 P6 处理）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.domain.auth.user import ACTIVE, ADMIN
from app.infrastructure.persistence.models import User

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@12345"


async def seed_admin(session: AsyncSession) -> None:
    """写入初始管理员；已存在则跳过（不覆盖既有密码）。"""
    existing = (
        await session.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(
        User(
            username=DEFAULT_ADMIN_USERNAME,
            email="admin@example.com",
            hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
            role=ADMIN,
            status=ACTIVE,
        )
    )
