"""admin 日志查询与仪表盘聚合测试（spec §6.2 admin 行，P6 Task 5/6）。

Task 5：GET /admin/logs —— action/user_id 精确、start/end 时间区间（纯日期按
当日闭合区间）、倒序分页 {items, total}、非法参数 422。
Task 6：GET /admin/overview —— 各计数聚合、embedder 快照字段。
"""

from datetime import UTC, datetime, timedelta

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
from app.infrastructure.persistence.models import AuditLog, User
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
    """直插 admin 用户并签发 token。

    不走 register/login：auth 路由会在注册与登录时各写一条 AuditLog，
    本文件要精确断言审计行数，不能让辅助流程污染计数。
    """
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


# ------------------------------------------------------------ Task 5：logs


@pytest.mark.asyncio
async def test_logs_requires_admin(client, factory):
    token = await _register(client, "stu")
    r = await client.get("/api/v1/admin/logs", headers=_auth(token))
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_logs_returns_full_row_and_paginates(client, factory):
    token = await _admin_token(factory)
    async with factory() as s:
        s.add(AuditLog(user_id="u1", action="admin_user_create", detail={"k": 1}))
        s.add(AuditLog(user_id="u2", action="chat", detail=None))
        s.add(AuditLog(user_id="u3", action="admin_user_delete", detail={"n": 2}))
        await s.commit()

    r = await client.get(
        "/api/v1/admin/logs", headers=_auth(token), params={"page": 1, "page_size": 2}
    )
    data = r.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 2
    first = data["items"][0]
    assert first["action"] == "admin_user_delete"  # created_at 倒序（后写在前）
    assert set(first) >= {
        "id",
        "user_id",
        "action",
        "target_type",
        "target_id",
        "detail",
        "ip",
        "request_id",
        "created_at",
    }


@pytest.mark.asyncio
async def test_logs_filters_by_action_and_user(client, factory):
    token = await _admin_token(factory)
    async with factory() as s:
        s.add(AuditLog(user_id="u1", action="admin_user_create"))
        s.add(AuditLog(user_id="u1", action="chat"))
        s.add(AuditLog(user_id="u2", action="admin_user_create"))
        await s.commit()

    r = await client.get(
        "/api/v1/admin/logs", headers=_auth(token), params={"action": "chat"}
    )
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["user_id"] == "u1"

    r = await client.get(
        "/api/v1/admin/logs", headers=_auth(token), params={"user_id": "u1"}
    )
    assert r.json()["data"]["total"] == 2


@pytest.mark.asyncio
async def test_logs_filters_by_datetime_range(client, factory):
    token = await _admin_token(factory)
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    async with factory() as s:
        for i, day in enumerate([1, 5, 10]):
            s.add(
                AuditLog(
                    user_id="u1",
                    action="chat",
                    created_at=base + timedelta(days=day - 1),
                )
            )
        await s.commit()

    r = await client.get(
        "/api/v1/admin/logs",
        headers=_auth(token),
        params={"start": "2026-08-02", "end": "2026-08-09"},
    )
    # 纯日期闭合区间：08-02 00:00 起、08-09 23:59:59 止 → 只含 08-05（08-01 12:00 在起点前）
    assert r.json()["data"]["total"] == 1

    r = await client.get(
        "/api/v1/admin/logs", headers=_auth(token), params={"start": "not-a-date"}
    )
    assert r.status_code == 422
