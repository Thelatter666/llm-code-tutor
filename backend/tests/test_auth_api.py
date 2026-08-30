import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.auth.user import DISABLED
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import User
from app.main import app


@pytest_asyncio.fixture
async def _engine():
    """内存库须 StaticPool：否则每个连接都是独立的空库（M7）。"""
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

    # 覆盖键必须是路由注册时使用的同一个函数对象，不能重载模块后重绑
    app.dependency_overrides[get_session] = _override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db(_engine):
    """供需要直接改库状态的用例（如停用账号）使用。"""
    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        yield s


async def _register(c, username: str):
    return await c.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Secret123!",
        },
    )


@pytest.mark.asyncio
async def test_register_then_login(client):
    r = await _register(client, "stu001")
    assert r.status_code == 200 and r.json()["code"] == 0

    r = await client.post(
        "/api/v1/auth/login", json={"username": "stu001", "password": "Secret123!"}
    )
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["access_token"] and body["data"]["refresh_token"]


@pytest.mark.asyncio
async def test_register_defaults_to_student(client):
    await _register(client, "s2")
    r = await client.post("/api/v1/auth/login", json={"username": "s2", "password": "Secret123!"})
    token = r.json()["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["role"] == "student"


@pytest.mark.asyncio
async def test_duplicate_username_is_rejected(client):
    assert (await _register(client, "dup")).json()["code"] == 0
    assert (await _register(client, "dup")).json()["code"] == 4090


@pytest.mark.asyncio
async def test_wrong_password_rejected(client):
    await _register(client, "s3")
    r = await client.post("/api/v1/auth/login", json={"username": "s3", "password": "bad"})
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_missing_token_rejected(client):
    assert (await client.get("/api/v1/auth/me")).json()["code"] == 4010


@pytest.mark.asyncio
async def test_admin_route_blocks_student(client):
    await _register(client, "s4")
    r = await client.post("/api/v1/auth/login", json={"username": "s4", "password": "Secret123!"})
    token = r.json()["data"]["access_token"]
    r = await client.get("/api/v1/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_refresh_issues_new_access_token(client):
    await _register(client, "s5")
    tokens = (
        await client.post("/api/v1/auth/login", json={"username": "s5", "password": "Secret123!"})
    ).json()["data"]
    r = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 200 and r.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client):
    await _register(client, "s6")
    tokens = (
        await client.post("/api/v1/auth/login", json={"username": "s6", "password": "Secret123!"})
    ).json()["data"]
    r = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_disabled_user_is_rejected_with_4030(client, db):
    """M11：安全关键路径——停用账号必须被拦截。"""
    await _register(client, "s7")
    token = (
        await client.post("/api/v1/auth/login", json={"username": "s7", "password": "Secret123!"})
    ).json()["data"]["access_token"]

    u = (await db.execute(select(User).where(User.username == "s7"))).scalar_one()
    u.status = DISABLED
    await db.commit()

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_request_id_in_body_matches_header(client):
    """H3：响应体与响应头的 request_id 必须一致，否则日志无法 grep。"""
    r = await _register(client, "s8")
    assert r.json()["request_id"] == r.headers["x-request-id"]


@pytest.mark.asyncio
async def test_password_is_not_stored_in_plaintext(client, db):
    await _register(client, "s9")
    u = (await db.execute(select(User).where(User.username == "s9"))).scalar_one()
    assert u.hashed_password != "Secret123!"
    assert u.hashed_password.startswith("$2b$")
