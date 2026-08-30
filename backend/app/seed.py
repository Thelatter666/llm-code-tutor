import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.domain.auth.user import ACTIVE, ADMIN
from app.infrastructure.persistence.db import SessionFactory, engine, init_db
from app.infrastructure.persistence.models import User
from app.infrastructure.registry import get_or_create_singleton

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@12345"


async def seed(session: AsyncSession) -> None:
    """幂等：已存在则跳过，不覆盖既有数据。"""
    existing = (
        await session.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            User(
                username=DEFAULT_ADMIN_USERNAME,
                email="admin@example.com",
                hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
                role=ADMIN,
                status=ACTIVE,
            )
        )

    await get_or_create_singleton(session)
    await session.flush()


async def _main() -> None:
    await init_db(engine)
    async with SessionFactory() as session:
        await seed(session)
        await session.commit()
    print(f"seed 完成：管理员 {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
    print("README 须写明：首次登录后请立即修改默认密码。")


if __name__ == "__main__":
    url = get_settings().database_url
    if ":///" in url and ":memory:" not in url:
        Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_main())
