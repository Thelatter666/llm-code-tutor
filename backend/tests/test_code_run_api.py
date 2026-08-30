"""code 运行端点的 HTTP 层测试（spec §6.2 code 行）。

沿用 `test_code_api.py` 的脚手架（内存库 + 替身基础设施）。执行器注入 `FakeExecutor`
—— 子进程行为归适配器层测，这里只测接线：鉴权、参数校验、统一响应、request_id、
并发 429。

`test_timeout_really_runs_the_sandbox` 是唯一一条**真起子进程**的用例：它证明
HTTP 层的阻塞卸载确实生效 —— 若执行没被卸载，这个 5 秒请求会把整条事件循环冻住，
同进程内的其它请求全部超时。
"""

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.infrastructure.concurrency import reset_concurrency
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence import db as db_module
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import AuditLog, CodeRun, CodeSession, User
from app.infrastructure.ports.code_executor import ExecutionResult
from app.infrastructure.runtime import (
    reset_runtime,
    set_embedder_runtime,
    set_llm_runtime,
    set_vector_store,
)
from app.main import app
from app.services.code_service import CodeService
from tests.fakes import ConstantEmbedder, FakeLLM, FakeVectorStore, fake_llm_runtime

PASSWORD = "Secret123!"
PY = "python"
SOURCE = "print('hello')\n"


class FakeExecutor:
    def __init__(self, result: ExecutionResult | None = None, delay: float = 0.0):
        self.result = result or ExecutionResult(
            status="accepted",
            stdout="hello\n",
            stderr="",
            exit_code=0,
            duration_ms=12,
            limit_detail={
                "wall_clock": {"limit_s": 5.0, "elapsed_s": 0.012, "triggered": False},
                "cpu": {"limit_s": 3, "applied": True, "triggered": False, "error": None},
                "memory": {
                    "limit_bytes": 268435456,
                    "sampled": True,
                    "interval_ms": 100,
                    "peak_bytes": 9000000,
                    "samples": 2,
                    "triggered": False,
                },
                "file_size": {"limit_bytes": 1048576, "applied": True, "error": None},
                "output": {
                    "limit_bytes": 8192,
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                },
                "degraded_layers": [],
            },
        )
        self.delay = delay
        self.calls: list[dict] = []

    def execute(self, *, language: str, source: str, stdin: str = "") -> ExecutionResult:
        import time

        self.calls.append({"language": language, "source": source, "stdin": stdin})
        if self.delay:
            time.sleep(self.delay)
        return self.result


# ---------------------------------------------------------------- 脚手架

# 执行器替身放在一个可变容器里：`test_timeout_run_really_runs_the_sandbox`
# 需要临时换成真实执行器，而 fixture 已经把注入逻辑包住了。
EXECUTOR = FakeExecutor()
_ORIGINAL_INIT = CodeService.__init__


def _init_with_fake_executor(self, session, *args, **kwargs):
    kwargs["executor"] = EXECUTOR
    _ORIGINAL_INIT(self, session, *args, **kwargs)


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
async def _fake_infra(monkeypatch):
    reset_runtime()
    reset_concurrency()
    set_vector_store(FakeVectorStore())
    runtime = EmbedderRuntime(lambda level: ConstantEmbedder() if level == 1 else None)
    await runtime.warmup()
    set_embedder_runtime(runtime)
    set_llm_runtime(fake_llm_runtime(FakeLLM()))

    monkeypatch.setattr(CodeService, "__init__", _init_with_fake_executor)
    EXECUTOR.calls.clear()
    yield
    reset_concurrency()
    reset_runtime()


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


# ---------------------------------------------------------------- POST /code/run

@pytest.mark.asyncio
async def test_run_requires_auth(client):
    r = await client.post("/api/v1/code/run", json={"language": PY, "source": SOURCE})
    assert r.status_code == 401
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_run_returns_the_seven_spec_fields(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/run",
        json={"language": PY, "source": SOURCE, "stdin": ""},
        headers=_auth(token, rid="rid-run-1"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["request_id"] == "rid-run-1"
    assert r.headers["x-request-id"] == "rid-run-1"

    data = body["data"]
    for field in (
        "status",
        "stdout",
        "stderr",
        "exit_code",
        "duration_ms",
        "limit_detail",
        "run_id",
    ):
        assert field in data, f"spec §6.2 要求字段 {field}"
    assert data["run_id"]
    assert data["status"] == "accepted"
    assert data["limit_detail"]["memory"]["peak_bytes"] == 9000000


@pytest.mark.asyncio
async def test_run_accepts_javascript(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/run",
        json={"language": "javascript", "source": "console.log(1);\n"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"language": "ruby", "source": SOURCE},
        {"language": PY, "source": ""},
        {"language": PY, "source": "x" * 20001},
        {"language": PY},
        {"source": SOURCE},
    ],
)
async def test_run_rejects_invalid_payload(client, payload):
    token = await _token(client)
    r = await client.post("/api/v1/code/run", json=payload, headers=_auth(token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_rejects_oversized_stdin(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/run",
        json={"language": PY, "source": SOURCE, "stdin": "x" * 200001},
        headers=_auth(token),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_persists_and_audits(client, _engine):
    token = await _token(client)
    await client.post(
        "/api/v1/code/run",
        json={"language": PY, "source": SOURCE},
        headers=_auth(token, rid="rid-audit"),
    )

    async with db_module.SessionFactory() as s:
        rows = (await s.execute(select(CodeRun))).scalars().all()
        logs = (
            await s.execute(select(AuditLog).where(AuditLog.action == "code_run"))
        ).scalars().all()
    assert len(rows) == 1
    assert len(logs) == 1
    assert logs[0].request_id == "rid-audit"


@pytest.mark.asyncio
async def test_blocked_run_returns_blocked_status(client, monkeypatch):
    monkeypatch.setattr(
        EXECUTOR,
        "execute",
        lambda *, language, source, stdin="": ExecutionResult(
            status="blocked",
            stdout="",
            stderr="命中黑名单规则：os_system；代码未执行。",
            exit_code=None,
            duration_ms=0,
            limit_detail={"blacklist": {"rule": "os_system", "executed": False}},
        ),
    )
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/run",
        json={"language": PY, "source": "import os\nos.system('ls')\n"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "blocked"
    assert data["exit_code"] is None
    assert data["limit_detail"]["blacklist"]["rule"] == "os_system"


# ---------------------------------------------------------------- 并发 429

@pytest.mark.asyncio
async def test_third_concurrent_run_returns_429(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "execution_quota_timeout_s", 0.2)
    monkeypatch.setattr(get_settings(), "execution_concurrency", 2)
    monkeypatch.setattr(EXECUTOR, "delay", 0.5)
    token = await _token(client)

    async def fire():
        return await client.post(
            "/api/v1/code/run",
            json={"language": PY, "source": SOURCE},
            headers=_auth(token),
        )

    running = [asyncio.create_task(fire()) for _ in range(2)]
    await asyncio.sleep(0.1)
    third = await fire()
    assert third.status_code == 429
    assert third.json()["code"] == 4290
    assert third.json()["data"]["retry_after"] == 0.2

    done = await asyncio.gather(*running)
    assert all(r.status_code == 200 for r in done)


# ---------------------------------------------------------------- 阻塞卸载

@pytest.mark.asyncio
async def test_timeout_run_really_runs_the_sandbox(client, monkeypatch):
    """换上真实执行器跑一次死循环：5 秒请求不得冻住事件循环。

    同时发一个 `/health`：若执行没被卸载，它会被一起拖到 5 秒后才有响应。
    """
    from app.infrastructure.adapters.execution.subprocess_executor import (
        SubprocessCodeExecutor,
    )

    real = SubprocessCodeExecutor()

    def init_with_real_executor(self, session, *args, **kwargs):
        kwargs["executor"] = real
        _ORIGINAL_INIT(self, session, *args, **kwargs)

    monkeypatch.setattr(CodeService, "__init__", init_with_real_executor)

    token = await _token(client)

    async def slow():
        return await client.post(
            "/api/v1/code/run",
            json={"language": PY, "source": "while True:\n    pass\n"},
            headers=_auth(token),
        )

    task = asyncio.create_task(slow())
    await asyncio.sleep(0.5)
    health = await client.get("/health")

    assert health.status_code == 200, "执行期间 /health 应立即响应 —— 事件循环没被冻住"
    assert health.elapsed.total_seconds() < 1.0, f"/health 被拖慢到 {health.elapsed}"

    r = await task
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "timeout"
    assert data["limit_detail"]["cpu"]["triggered"] is True


# ---------------------------------------------------------------- 草稿 CRUD

@pytest.mark.asyncio
async def test_session_crud_over_http(client):
    token = await _token(client)
    created = await client.post(
        "/api/v1/code/sessions",
        json={"language": PY, "title": "冒泡", "source_code": "a=1\n"},
        headers=_auth(token),
    )
    assert created.status_code == 200
    draft_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/code/sessions", headers=_auth(token))
    assert [d["id"] for d in listed.json()["data"]["items"]] == [draft_id]

    patched = await client.patch(
        f"/api/v1/code/sessions/{draft_id}",
        json={"title": "快排", "source_code": "b=2\n"},
        headers=_auth(token),
    )
    assert patched.json()["data"]["title"] == "快排"

    deleted = await client.delete(f"/api/v1/code/sessions/{draft_id}", headers=_auth(token))
    assert deleted.status_code == 200
    assert (await client.get("/api/v1/code/sessions", headers=_auth(token))).json()["data"][
        "items"
    ] == []


@pytest.mark.asyncio
async def test_session_of_another_user_is_404(client):
    token_a = await _token(client, "stuA")
    token_b = await _token(client, "stuB")
    created = await client.post(
        "/api/v1/code/sessions",
        json={"language": PY, "title": "A 的草稿", "source_code": "a"},
        headers=_auth(token_a),
    )
    draft_id = created.json()["data"]["id"]

    r = await client.patch(
        f"/api/v1/code/sessions/{draft_id}",
        json={"title": "篡改"},
        headers=_auth(token_b),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 4040
    assert (
        await client.delete(f"/api/v1/code/sessions/{draft_id}", headers=_auth(token_b))
    ).status_code == 404


@pytest.mark.asyncio
async def test_session_creation_validates_language(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/code/sessions",
        json={"language": "ruby", "title": "x"},
        headers=_auth(token),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sessions_require_auth(client):
    assert (await client.get("/api/v1/code/sessions")).status_code == 401


# ---------------------------------------------------------------- 运行历史

@pytest.mark.asyncio
async def test_runs_history_is_paginated(client):
    token = await _token(client)
    for i in range(3):
        await client.post(
            "/api/v1/code/run",
            json={"language": PY, "source": f"print({i})\n"},
            headers=_auth(token),
        )
    r = await client.get("/api/v1/code/runs?page=1&page_size=2", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["source_code"] == "print(2)\n"


@pytest.mark.asyncio
async def test_runs_history_only_shows_own_runs(client):
    token_a = await _token(client, "stuA")
    token_b = await _token(client, "stuB")
    await client.post(
        "/api/v1/code/run", json={"language": PY, "source": SOURCE}, headers=_auth(token_a)
    )
    r = await client.get("/api/v1/code/runs", headers=_auth(token_b))
    assert r.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_runs_history_rejects_bad_page_size(client):
    token = await _token(client)
    r = await client.get("/api/v1/code/runs?page=0&page_size=0", headers=_auth(token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_and_session_rows_are_code_run_and_code_session(client):
    """术语落库校验：端点写的是 spec §5 的两张表。"""
    token = await _token(client)
    await client.post(
        "/api/v1/code/run", json={"language": PY, "source": SOURCE}, headers=_auth(token)
    )
    await client.post(
        "/api/v1/code/sessions", json={"language": PY, "title": "t"}, headers=_auth(token)
    )
    async with db_module.SessionFactory() as s:
        runs = (await s.execute(select(CodeRun))).scalars().all()
        drafts = (await s.execute(select(CodeSession))).scalars().all()
        users = (await s.execute(select(User))).scalars().all()
    assert len(runs) == 1
    assert len(drafts) == 1
    assert len(users) == 1
