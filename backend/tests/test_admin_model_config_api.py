"""admin 模型配置 GET/PUT 的 HTTP 层测试（spec §6.2 / §4.2 硬约束 4，P6 Task 3）。

裁定 2（2026-08-31）：api_key 缺省/null=不变更、空串 422；openai_compat 且库中
无 key → 4220 拒绝保存；embedding 两字段不在 PUT 面（extra=forbid 422）；
保存即 revision += 1（热生效，无需重启）。
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.crypto import decrypt_api_key, encrypt_api_key
from app.domain.auth.user import ADMIN
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import AuditLog, ModelConfig, User
from app.infrastructure.ports.llm import ChatMessage, LLMParams
from app.infrastructure.runtime import (
    get_llm_runtime,
    refresh_llm_config,
    reset_runtime,
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


async def _admin_token(c, factory, username="root") -> str:
    token = await _register(c, username)
    async with factory() as s:
        row = (await s.execute(select(User).where(User.username == username))).scalar_one()
        row.role = ADMIN
        await s.commit()
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _singleton(factory) -> ModelConfig | None:
    async with factory() as s:
        return (
            await s.execute(select(ModelConfig))
        ).scalars().one_or_none()


async def _ensure_singleton_row(factory) -> None:
    """直接物化 ModelConfig 单例行（GET 端点只 flush 不 commit，读库要自己建行）。"""
    async with factory() as s:
        row = (await s.execute(select(ModelConfig))).scalars().one_or_none()
        if row is None:
            s.add(ModelConfig())
            await s.commit()


# ------------------------------------------------------------ GET


@pytest.mark.asyncio
async def test_get_model_config_requires_admin(client, factory):
    token = await _register(client, "stu")
    r = await client.get("/api/v1/admin/model-config", headers=_auth(token))
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_get_model_config_returns_masked_api_key(client, factory):
    token = await _admin_token(client, factory)
    await _ensure_singleton_row(factory)
    async with factory() as s:
        cfg = (await s.execute(select(ModelConfig))).scalars().one()
        cfg.api_key_encrypted = encrypt_api_key("sk-super-secret-key-1234")
        await s.commit()

    r = await client.get("/api/v1/admin/model-config", headers=_auth(token))
    data = r.json()["data"]
    assert data["api_key"] == "sk-****1234"
    assert "sk-super-secret-key-1234" not in str(data)
    assert set(data) >= {
        "provider",
        "model",
        "base_url",
        "api_key",
        "temperature",
        "top_p",
        "max_tokens",
        "anti_plagiarism_mode",
        "score_threshold",
        "top_k",
        "embedding_provider",
        "embedding_model",
        "revision",
        "updated_by",
        "updated_at",
    }


# ------------------------------------------------------------ PUT


@pytest.mark.asyncio
async def test_put_updates_fields_bumps_revision_and_audits(client, factory):
    token = await _admin_token(client, factory)
    await _ensure_singleton_row(factory)
    before = await _singleton(factory)

    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "anti_plagiarism_mode": "strict",
            "score_threshold": 0.4,
            "top_k": 8,
        },
    )
    assert r.json()["code"] == 0
    data = r.json()["data"]
    assert data["model"] == "gpt-4o-mini"
    assert data["temperature"] == 0.3
    assert data["anti_plagiarism_mode"] == "strict"
    assert data["score_threshold"] == 0.4
    assert data["top_k"] == 8
    assert data["revision"] == before.revision + 1
    assert data["updated_by"] == (await _singleton(factory)).updated_by

    async with factory() as s:
        log = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "admin_model_config_update")
            )
        ).scalar_one()
    assert "model" in log.detail["fields"]
    assert log.detail["api_key_updated"] is False


@pytest.mark.asyncio
async def test_put_api_key_encrypts_and_masks(client, factory):
    token = await _admin_token(client, factory)
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"provider": "openai_compat", "api_key": "sk-provided-9999"},
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["api_key"] == "sk-****9999"

    cfg = await _singleton(factory)
    assert decrypt_api_key(cfg.api_key_encrypted) == "sk-provided-9999"


@pytest.mark.asyncio
async def test_put_absent_or_null_api_key_keeps_existing(client, factory):
    token = await _admin_token(client, factory)
    await _ensure_singleton_row(factory)
    async with factory() as s:
        cfg = (await s.execute(select(ModelConfig))).scalars().one()
        cfg.api_key_encrypted = encrypt_api_key("sk-keep-me-0000")
        await s.commit()

    # 字段缺省（前端掩码回显后常态回传 null）→ 不变更
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"model": "m2"},
    )
    assert r.json()["code"] == 0
    assert decrypt_api_key((await _singleton(factory)).api_key_encrypted) == "sk-keep-me-0000"

    # 显式传 null 同样不变更
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"model": "m3", "api_key": None},
    )
    assert r.json()["code"] == 0
    assert decrypt_api_key((await _singleton(factory)).api_key_encrypted) == "sk-keep-me-0000"


@pytest.mark.asyncio
async def test_put_rejects_empty_api_key(client, factory):
    token = await _admin_token(client, factory)
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"api_key": ""},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_openai_compat_without_key_rejected(client, factory):
    """裁定 2 追加：静默降级会把「配置错误」伪装成「降级运行」。"""
    token = await _admin_token(client, factory)
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"provider": "openai_compat", "model": "gpt-4o"},
    )
    assert r.json()["code"] == 4220

    # mock 无 key 是既定路径，允许
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"provider": "mock", "model": "mock-1"},
    )
    assert r.json()["code"] == 0


@pytest.mark.asyncio
async def test_put_rejects_extra_and_invalid_fields(client, factory):
    token = await _admin_token(client, factory)

    # embedding 字段不在 PUT 面（extra=forbid 显式拒绝，不静默忽略）
    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"embedding_provider": "hashing"},
    )
    assert r.status_code == 422

    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"temperature": 3.0},
    )
    assert r.status_code == 422

    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"anti_plagiarism_mode": "chaotic"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_hot_reload_takes_effect_without_restart(client, factory):
    """spec §4.2 硬约束 4：保存即 revision += 1，下一次调用即用新值。

    PUT 前运行时是 Mock（provider=mock 无 key）；PUT openai_compat + key 后，
    服务侧（chat/hint 同款）执行 `refresh_llm_config` 按 revision 重绑，
    下一次调用的运行时即解析出 OpenAI 兼容适配器 —— 全程不重启进程。
    """
    reset_runtime()
    token = await _admin_token(client, factory)

    r = await client.put(
        "/api/v1/admin/model-config",
        headers=_auth(token),
        json={"provider": "openai_compat", "model": "gpt-4o-mini", "api_key": "sk-hot-1"},
    )
    assert r.json()["code"] == 0

    # 模拟 chat/hint 服务下一次调用前的刷新路径：revision 变了 → 重绑
    async with factory() as s:
        changed = await refresh_llm_config(s)
    assert changed is True

    # 下一次真实调用即用新配置：期望 provider=openai_compat（本地无真服务 →
    # 解析期降级到 Mock，snapshot 必须报 degraded —— 这正是「新配置已生效」的证据；
    # 若刷新没发生，期望仍是 mock，degraded 应为 False）
    runtime = get_llm_runtime()
    await runtime.complete(
        [ChatMessage(role="user", content="hi")],
        LLMParams(model="gpt-4o-mini"),
    )
    snap = runtime.snapshot()
    assert snap.provider == "mock"
    assert snap.degraded is True
    assert snap.fallback_reason == "llm_fallback_to_mock"
