from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path

from sqlalchemy import DateTime, event
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings


class UTCDateTime(TypeDecorator):
    """SQLite 的 DATETIME 回读时返回无时区 datetime，与 Python 端的 aware 值无法比较。

    本类型统一两侧语义：落库前转 naive UTC，读取后附回 UTC 时区。
    Python 端因此始终是 aware datetime，可直接比较与序列化。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect: Dialect):
        if value is None:
            return None
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect: Dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


def _apply_pragmas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _build_engine():
    url = get_settings().database_url
    if url.startswith("sqlite") and ":///" in url and ":memory:" not in url:
        Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, future=True)
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


engine = _build_engine()
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db(target_engine=None) -> None:
    from app.infrastructure.persistence import models  # noqa: F401

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
