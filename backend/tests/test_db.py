from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.infrastructure.persistence.db import init_db
from app.infrastructure.persistence.models import (
    MODEL_CONFIG_SINGLETON_ID,
    ModelConfig,
    User,
)


@pytest.mark.asyncio
async def test_init_db_creates_tables(engine):
    await init_db(engine)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        names = {r[0] for r in rows}
    assert {"users", "model_configs", "audit_logs"} <= names


@pytest.mark.asyncio
async def test_user_roundtrip(session):
    user = User(username="stu001", email="stu001@example.com", hashed_password="x")
    session.add(user)
    await session.commit()

    got = (await session.execute(select(User).where(User.username == "stu001"))).scalar_one()
    assert got.email == "stu001@example.com"


@pytest.mark.asyncio
async def test_model_config_has_embedding_columns(session):
    """H1：spec §8.7 与 Chunk.embed_model 启动校验依赖这两列。"""
    cfg = ModelConfig(
        id=MODEL_CONFIG_SINGLETON_ID,
        embedding_provider="sentence_transformers",
        embedding_model="paraphrase-multilingual-MiniLM-L12-v2",
    )
    session.add(cfg)
    await session.commit()

    got = (await session.execute(select(ModelConfig))).scalar_one()
    assert got.embedding_provider == "sentence_transformers"
    assert got.embedding_model == "paraphrase-multilingual-MiniLM-L12-v2"


@pytest.mark.asyncio
async def test_datetime_roundtrip_preserves_utc_awareness(session):
    """UTCDateTime：落库转 naive UTC，读回附回 UTC，保证两端语义一致。

    未加该类型前，SQLite 回读为 naive，与 Python 端 aware 值比较直接抛 TypeError。
    """
    user = User(
        username="tz",
        email="tz@example.com",
        hashed_password="x",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    session.add(user)
    await session.commit()
    session.expire_all()

    got = (await session.execute(select(User).where(User.username == "tz"))).scalar_one()
    assert got.created_at.tzinfo is not None
    assert got.created_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_model_config_updated_at_changes_on_update(session):
    """H2：缺 onupdate 会导致 P6 改配置后 updated_at 不变、配置不生效。"""
    cfg = ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, revision=1)
    session.add(cfg)
    await session.commit()
    before = cfg.updated_at

    cfg.revision = 2
    await session.commit()
    await session.refresh(cfg)
    assert cfg.updated_at >= before
    assert cfg.updated_at != before
