import pytest
from sqlalchemy import select

from app.domain.auth.user import ADMIN
from app.infrastructure.persistence.models import ModelConfig, User
from app.seed import DEFAULT_ADMIN_USERNAME, seed


@pytest.mark.asyncio
async def test_seed_creates_admin_and_model_config(session):
    await seed(session)
    await session.commit()

    admin = (
        await session.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    ).scalar_one()
    assert admin.role == ADMIN
    assert (await session.execute(select(ModelConfig))).scalars().first() is not None


@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    await seed(session)
    await session.commit()
    await seed(session)
    await session.commit()

    assert len((await session.execute(select(User))).scalars().all()) == 1
    assert len((await session.execute(select(ModelConfig))).scalars().all()) == 1
