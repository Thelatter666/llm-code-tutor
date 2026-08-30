"""防抄袭拦截率度量（spec §7.4）。

CONTEXT.md：拦截率是**度量口径，不是检测能力**。
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.auth.user import ADMIN
from app.infrastructure.persistence import db as db_module
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import Message, User
from app.main import app
from app.services.anti_plagiarism_stats import AntiPlagiarismStatsService

PASSWORD = "Secret123!"


async def _seed(session, mode, blocked, role="user"):
    session.add(
        Message(
            conversation_id="c1",
            role=role,
            content="问",
            anti_plagiarism_mode=mode,
            blocked_by_policy=blocked,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_all_three_modes_are_reported_even_when_empty(session):
    """三档都要出现 —— 管理端表格不该因为某档没有数据就缺行。"""
    data = await AntiPlagiarismStatsService(session).stats()
    assert [i["mode"] for i in data["items"]] == ["strict", "guided", "loose"]
    assert all(i["total"] == 0 and i["block_rate"] == 0.0 for i in data["items"])


@pytest.mark.asyncio
async def test_block_rate_is_blocked_over_total(session):
    await _seed(session, "strict", True)
    await _seed(session, "strict", False)
    await _seed(session, "guided", False)
    await session.commit()

    by_mode = {i["mode"]: i for i in (await AntiPlagiarismStatsService(session).stats())["items"]}
    assert by_mode["strict"] == {"mode": "strict", "total": 2, "blocked": 1, "block_rate": 0.5}
    assert by_mode["guided"]["block_rate"] == 0.0


@pytest.mark.asyncio
async def test_zero_total_does_not_divide_by_zero(session):
    data = await AntiPlagiarismStatsService(session).stats()
    assert data["overall"]["block_rate"] == 0.0


@pytest.mark.asyncio
async def test_only_user_messages_are_counted(session):
    """一次请求只计一次：assistant 消息也带同样的 mode / blocked 标记。"""
    await _seed(session, "loose", True, role="user")
    await _seed(session, "loose", True, role="assistant")
    await session.commit()

    data = await AntiPlagiarismStatsService(session).stats()
    loose = next(i for i in data["items"] if i["mode"] == "loose")
    assert loose["total"] == 1 and loose["blocked"] == 1


@pytest.mark.asyncio
async def test_overall_aggregates_every_mode(session):
    await _seed(session, "strict", True)
    await _seed(session, "guided", False)
    await _seed(session, "loose", False)
    await session.commit()

    data = await AntiPlagiarismStatsService(session).stats()
    assert data["overall"] == {"mode": "all", "total": 3, "blocked": 1, "block_rate": pytest.approx(0.3333, abs=1e-4)}


# ------------------------------------------------------------------ HTTP 层


@pytest_asyncio.fixture
async def _engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(_engine):
    factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    original = db_module.SessionFactory
    db_module.SessionFactory = factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    db_module.SessionFactory = original


async def _login(c, username, promote=False, _engine=None):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@e.com", "password": PASSWORD},
    )
    if promote:
        factory = async_sessionmaker(_engine, expire_on_commit=False)
        async with factory() as s:
            user = (await s.execute(select(User).where(User.username == username))).scalar_one()
            user.role = ADMIN
            await s.commit()
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_endpoint_requires_admin(client, _engine):
    student = await _login(client, "stu")
    r = await client.get("/api/v1/admin/anti-plagiarism/stats", headers=student)
    assert r.json()["code"] == 4030

    r = await client.get("/api/v1/admin/anti-plagiarism/stats")
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_endpoint_returns_stats_and_request_id(client, _engine):
    admin = await _login(client, "boss", promote=True, _engine=_engine)
    r = await client.get(
        "/api/v1/admin/anti-plagiarism/stats", headers={**admin, "x-request-id": "rid-stat"}
    )
    body = r.json()

    assert body["code"] == 0
    assert body["request_id"] == "rid-stat"
    assert r.headers["x-request-id"] == "rid-stat"
    assert [i["mode"] for i in body["data"]["items"]] == ["strict", "guided", "loose"]
    assert body["data"]["intent"] == "seek_answer"
