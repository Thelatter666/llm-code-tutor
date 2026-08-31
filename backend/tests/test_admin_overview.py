"""admin 仪表盘聚合测试（spec §6.2 admin 行 / 裁定 3，P6 Task 6）。

最小集字段面：users / conversations / messages / knowledge_bases / documents /
code_* / exercises / submissions / mistake_entries / audit_logs / model_config /
embedder（与 /health 同源）。
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.domain.auth.user import ADMIN
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import (
    AuditLog,
    Conversation,
    Exercise,
    Message,
    Submission,
    User,
)
from app.main import app

PASSWORD = "Secret123!"


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
async def factory(_engine):
    return async_sessionmaker(_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(_engine, factory):
    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _register(c, username: str, password: str = PASSWORD) -> str:
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": password})
    return r.json()["data"]["access_token"]


async def _admin_token(factory, username="root") -> str:
    """直插 admin（不走 register/login，避免审计行污染计数断言）。"""
    async with factory() as s:
        row = User(
            username=username,
            email=f"{username}@x.com",
            hashed_password="x",
            role=ADMIN,
        )
        s.add(row)
        await s.commit()
        uid = row.id
    return create_access_token(uid, ADMIN)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_overview_requires_admin(client, factory):
    token = await _register(client, "stu")
    r = await client.get("/api/v1/admin/overview", headers=_auth(token))
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_overview_empty_db_returns_zeros(client, factory):
    token = await _admin_token(factory)
    r = await client.get("/api/v1/admin/overview", headers=_auth(token))
    assert r.json()["code"] == 0
    data = r.json()["data"]
    assert data["users"]["total"] == 1  # 只有 root
    assert data["users"]["admin"] == 1
    assert data["conversations"] == 0
    assert data["messages"] == 0
    assert data["knowledge_bases"] == 0
    assert data["documents"] == 0
    assert data["exercises"]["published"] == 0
    assert data["submissions"] == 0
    assert data["mistake_entries"]["unmastered"] == 0
    assert data["audit_logs"] == 0
    assert "model_config" in data and "embedder" in data


@pytest.mark.asyncio
async def test_overview_aggregates_counts(client, factory):
    token = await _admin_token(factory)
    async with factory() as s:
        s.add(AuditLog(user_id="u1", action="chat"))
        s.add(AuditLog(user_id="u1", action="chat"))
        conv = Conversation(user_id="root", title="c")
        s.add(conv)
        await s.flush()
        s.add(Message(conversation_id=conv.id, role="user", content="hi"))
        exercise = Exercise(
            type="choice",
            stem="q",
            answer="A",
            difficulty=1,
            source="seed",
            status="published",
        )
        s.add(exercise)
        await s.flush()
        s.add(
            Submission(
                user_id="stu9",
                exercise_id=exercise.id,
                answer="A",
                is_correct=True,
                score=100,
            )
        )
        await s.commit()

    r = await client.get("/api/v1/admin/overview", headers=_auth(token))
    data = r.json()["data"]
    assert data["users"]["total"] == 1
    assert data["conversations"] == 1
    assert data["messages"] == 1
    assert data["exercises"]["published"] == 1
    assert data["exercises"]["draft"] == 0
    assert data["submissions"] == 1
    assert data["audit_logs"] == 2
    assert data["model_config"]["revision"] >= 1
    # embedder 快照与 /health 同源
    assert "ready" in data["embedder"]
