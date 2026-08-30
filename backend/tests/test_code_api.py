"""code 端点的 HTTP 层测试（spec §6.2 code 行：POST /code/analyze）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.infrastructure.cancellation import reset_cancellation
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence import db as db_module
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import AuditLog, CodeAnalysis
from app.infrastructure.runtime import (
    reset_runtime,
    set_embedder_runtime,
    set_llm_runtime,
    set_vector_store,
)
from app.main import app
from tests.fakes import ConstantEmbedder, FakeVectorStore, fake_llm_runtime

PASSWORD = "Secret123!"

PY_SOURCE = "def area(radius):\n    return radius * 3.14\n"

JS_SOURCE = "function add(a, b) {\n  return a + b;\n}\n"


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
    monkeypatched = db_module.SessionFactory
    db_module.SessionFactory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

    app.dependency_overrides.clear()
    db_module.SessionFactory = monkeypatched


@pytest_asyncio.fixture(autouse=True)
async def _fake_infra():
    """不真起 Chroma、不真加载模型；LLM 与向量库用替身。"""
    reset_runtime()
    reset_cancellation()
    set_vector_store(FakeVectorStore())
    runtime = EmbedderRuntime(lambda level: ConstantEmbedder() if level == 1 else None)
    await runtime.warmup()
    set_embedder_runtime(runtime)
    set_llm_runtime(fake_llm_runtime(FakeLLMCode()))
    yield
    reset_cancellation()
    reset_runtime()


class FakeLLMCode:
    """流式替身：本端点在 Mock 配置下不会调它；若被调到则说明 Mock 模式判定失效。"""

    name = "fake"

    async def stream(self, messages, params, *, cancel=None):
        from app.infrastructure.ports.llm import TextDelta, Usage

        for ch in "讲解":
            yield TextDelta(ch)
        yield Usage(1, 2, 3, estimated=False)

    async def complete(self, messages, params):
        raise AssertionError("Mock 模式下 /code/analyze 不得调用 LLM")

    def snapshot(self):
        from app.infrastructure.llm_runtime import LLMSnapshot

        return LLMSnapshot(provider=self.name, degraded=False, fallback_reason=None)


async def _token(c, username="stu"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return r.json()["data"]["access_token"]


def _auth(token, rid=None):
    headers = {"Authorization": f"Bearer {token}"}
    if rid:
        headers["x-request-id"] = rid
    return headers


@pytest.mark.asyncio
async def test_analyze_requires_auth(client):
    r = await client.post(
        "/api/v1/code/analyze", json={"language": "python", "source": PY_SOURCE}
    )
    assert r.status_code == 401
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_analyze_python_returns_full_static_report(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": PY_SOURCE},
        headers=_auth(token, rid="rid-py-1"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["request_id"] == "rid-py-1"
    assert r.headers["x-request-id"] == "rid-py-1"

    data = body["data"]
    assert data["analysis_id"]
    assert data["reused"] is False
    assert data["static_report"]["language"] == "python"
    assert data["static_report"]["functions"][0]["name"] == "area"
    assert data["static_report"]["lines"]["total"] == 2
    assert data["static_report"]["issues"]["unused_variables"] == []
    ai = data["ai_report"]
    assert ai["provider"] == "mock"
    assert ai["usage_estimated"] is True
    assert "area" in ai["content"]  # 模板由 static_report 生成，引用函数名


@pytest.mark.asyncio
async def test_analyze_javascript_returns_report(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/analyze",
        json={"language": "javascript", "source": JS_SOURCE},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["static_report"]["language"] == "javascript"
    names = [f["name"] for f in data["static_report"]["functions"]]
    assert "add" in names


@pytest.mark.asyncio
async def test_analyze_reuses_history_for_same_user(client):
    token = await _token(client)
    payload = {"language": "python", "source": PY_SOURCE}
    first = (
        await client.post("/api/v1/code/analyze", json=payload, headers=_auth(token))
    ).json()["data"]
    second = (
        await client.post("/api/v1/code/analyze", json=payload, headers=_auth(token))
    ).json()["data"]

    assert second["reused"] is True
    assert second["analysis_id"] == first["analysis_id"]


@pytest.mark.asyncio
async def test_analyze_rejects_unknown_language(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/analyze",
        json={"language": "ruby", "source": "puts 1"},
        headers=_auth(token),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_oversized_source(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": "x = 1\n" * 30000},
        headers=_auth(token),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{"source": PY_SOURCE}, {"language": "python"}, {"language": "", "source": ""}],
)
async def test_analyze_rejects_missing_fields(client, payload):
    token = await _token(client)
    r = await client.post("/api/v1/code/analyze", json=payload, headers=_auth(token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_syntax_error_returns_report_not_500(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": "def f(:\n    pass\n"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["static_report"]["syntax_error"]["line"] == 1


@pytest.mark.asyncio
async def test_analyze_writes_audit_log(client):
    token = await _token(client)
    await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": PY_SOURCE},
        headers=_auth(token),
    )
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    user_id = r.json()["data"]["id"]

    from app.infrastructure.persistence.db import SessionFactory as _  # noqa: F401

    # 审计行写在请求会话里，经 commit 落库；用被覆写的会话工厂重读
    async with db_module.SessionFactory() as s:
        logs = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "code_analyze", AuditLog.user_id == user_id
                )
            )
        ).scalars().all()
    assert len(logs) == 1
    assert logs[0].detail["language"] == "python"


@pytest.mark.asyncio
async def test_analyze_persists_one_row_per_unique_source(client):
    token = await _token(client)
    await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": PY_SOURCE},
        headers=_auth(token),
    )
    await client.post(
        "/api/v1/code/analyze",
        json={"language": "python", "source": "x = 1\n"},
        headers=_auth(token),
    )

    async with db_module.SessionFactory() as s:
        rows = (await s.execute(select(CodeAnalysis))).scalars().all()
    assert len(rows) == 2
