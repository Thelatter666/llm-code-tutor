import os

import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# M5：用固定 env 注入测试密钥，避免写 .secret_key.test 文件污染工作区
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest-only-32bytes-min")
os.environ.setdefault("APP_SECRET", Fernet.generate_key().decode())
# Mock 流式延迟（P3 并入任务 1）会让既有用例按增量数 × 30ms 变慢：套件级显式
# 置 0。Settings 默认值（30）不动，延迟用例经构造参数显式开延迟自行验证。
os.environ.setdefault("MOCK_TOKEN_DELAY_MS", "0")
# P4 实测（报告 §9）：sentence-transformers 加载**已缓存**的本地模型时默认仍会
# 联网查 Hugging Face Hub，受限网络下无限等待 test_rebuild_uses_the_newly_configured_model。
# 测试不应依赖网络 —— 强制离线。setdefault 不覆盖用户显式设置；若某条用例确需
# 首次下载模型，应显式标记而非让整个套件挂起。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


@pytest_asyncio.fixture
async def engine():
    from app.infrastructure.persistence.db import Base, _apply_pragmas

    # M7：内存库必须 StaticPool，否则每个连接都是独立的空库
    eng = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def session_factory(engine):
    """后台任务用的会话工厂，与 `_bind_session_factory` 绑到同一个库上。

    需要独立会话的用例（例如「检索后重新读库验证」）应当注入本 fixture，
    而不要自己拿 `session.bind` 造 —— `AsyncSession.bind` 每次返回新的引擎
    包装，绕开它建的会话会落到另一个库上。
    """
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _bind_session_factory(engine):
    """把后台任务的会话工厂绑到测试库上。

    索引由 BackgroundTasks 拉起，不能复用请求会话（响应返回时会话已关），
    因此 IndexingService 会自行开新会话。默认工厂指向真实数据库文件，测试若不
    替换就会静默写进 `data/app.db` —— 这类 bug 极难定位，故在此统一兜住。
    """
    from app.infrastructure.persistence import db as db_module

    original = db_module.SessionFactory
    db_module.SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    db_module.SessionFactory = original
