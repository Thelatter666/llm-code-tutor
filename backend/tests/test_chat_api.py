"""chat 端点的 HTTP 层测试（spec §6.2 chat 行 + §6.1 SSE 契约）。"""

import asyncio
import json

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
from app.infrastructure.persistence.models import (
    AuditLog,
    Chunk,
    Document,
    KnowledgeBase,
    Message,
)
from app.infrastructure.ports.llm import TextDelta
from app.infrastructure.ports.vectorstore import VectorRecord
from app.infrastructure.runtime import (
    get_vector_store,
    reset_runtime,
    set_embedder_runtime,
    set_llm_runtime,
    set_vector_store,
)
from app.main import app
from tests.fakes import ConstantEmbedder, FakeLLM, FakeVectorStore, fake_llm_runtime

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
    """不真起 Chroma、不真加载模型；LLM 用可脚本化的替身。"""
    reset_runtime()
    reset_cancellation()
    set_vector_store(FakeVectorStore())
    runtime = EmbedderRuntime(lambda level: ConstantEmbedder() if level == 1 else None)
    await runtime.warmup()
    set_embedder_runtime(runtime)
    set_llm_runtime(fake_llm_runtime(FakeLLM(reply="流式回答内容")))
    yield
    reset_cancellation()
    reset_runtime()


async def _token(c, username="stu"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    r = await c.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    return r.json()["data"]["access_token"]


def _auth(token, rid=None):
    headers = {"Authorization": f"Bearer {token}"}
    if rid:
        headers["x-request-id"] = rid
    return headers


async def _conversation(c, token, title="答疑"):
    r = await c.post(
        "/api/v1/chat/conversations", json={"title": title}, headers=_auth(token)
    )
    assert r.json()["code"] == 0, r.text
    return r.json()["data"]["id"]


def _parse_sse(body: str):
    """按前端的解析方式反解 SSE 帧。"""
    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        name, payload = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name:
            events.append((name, payload))
    return events


async def _seed_kb(_engine):
    """塞一个必定命中的切片：常量向量的余弦相似度恒为 1。"""
    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        s.add(KnowledgeBase(id="kb1", name="Python 讲义", course_code="CS101", status="ready"))
        s.add(Document(id="d1", kb_id="kb1", title="第1讲", source_type="md", status="ready"))
        s.add(
            Chunk(
                id="c1",
                document_id="d1",
                kb_id="kb1",
                content="排序有三大类",
                ordinal=0,
                char_count=6,
                vector_id="v1",
            )
        )
        await s.commit()
    await get_vector_store().upsert(
        [
            VectorRecord(
                vector_id="v1",
                kb_id="kb1",
                document_id="d1",
                embedding=[1.0, 0.0, 0.0, 0.0],
                content="排序有三大类",
            )
        ]
    )


# ------------------------------------------------------------------ SSE


@pytest.mark.asyncio
async def test_sse_emits_citation_then_tokens_then_done(client, _engine, tmp_path):
    await _seed_kb(_engine)
    token = await _token(client)
    conv = await _conversation(client, token)

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv}/messages",
        json={"content": "讲讲排序算法", "use_rag": True},
        headers=_auth(token, "rid-sse-1"),
    ) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-request-id"] == "rid-sse-1"
        body = "".join([chunk async for chunk in resp.aiter_text()])

    events = _parse_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "citation"
    assert names[-1] == "done"
    assert names.count("token") == len("流式回答内容")
    assert "".join(p["delta"] for n, p in events if n == "token") == "流式回答内容"

    done = events[-1][1]
    assert set(done) == {
        "message_id",
        "token_usage",
        "usage_estimated",
        "model",
        "provider",
        "rag_hit",
        "degraded",
        "fallback_reason",
    }
    assert done["rag_hit"] is True
    assert done["usage_estimated"] is True
    assert events[0][1]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_sse_body_is_not_wrapped_in_the_unified_envelope(client, _engine):
    """SSE 端点不走 `{code,message,data}` 统一响应体 —— 前端按裸 SSE 帧解析。"""
    token = await _token(client)
    conv = await _conversation(client, token)

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv}/messages",
        json={"content": "问题", "use_rag": False},
        headers=_auth(token),
    ) as resp:
        body = "".join([chunk async for chunk in resp.aiter_text()])

    assert body.startswith("event: token")
    assert '"code"' not in body


class SlowLLM(FakeLLM):
    """每个增量之间留出时间窗，让 /stop 能在流进行中被打进来。

    `httpx.ASGITransport` 会把整个响应体缓冲成一块返回，无法边收边发；
    因此中断必须靠「流还没跑完时从另一个 task 打 /stop」来验证，而不是靠
    客户端读到一半再发请求。
    """

    async def stream(self, messages, params, *, cancel=None):
        self.messages.append(list(messages))
        for ch in self.reply:
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
            await asyncio.sleep(0.02)
        yield self._usage(messages)


@pytest.mark.asyncio
async def test_stop_interrupts_the_stream_and_persists_partial_content(client, _engine):
    set_llm_runtime(fake_llm_runtime(SlowLLM(reply="甲乙丙丁戊己庚辛壬癸" * 10)))
    token = await _token(client)
    conv = await _conversation(client, token)
    rid = "rid-stop-1"

    async def _stop_later():
        await asyncio.sleep(0.15)
        return await client.post(
            f"/api/v1/chat/conversations/{conv}/stop",
            json={"request_id": rid},
            headers=_auth(token),
        )

    stop_task = asyncio.create_task(_stop_later())
    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv}/messages",
        json={"content": "问题", "use_rag": False},
        headers=_auth(token, rid),
    ) as resp:
        received = "".join([chunk async for chunk in resp.aiter_text()])
    stopped = await stop_task

    assert stopped.json()["data"]["cancelled"] is True

    events = _parse_sse(received)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == 4990
    tokens = [n for n, _ in events if n == "token"]
    assert 0 < len(tokens) < 200, "中断后应只剩部分增量"

    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(select(Message).where(Message.role == "assistant"))
        ).scalar_one()
        assert row.truncated is True
        assert row.content == "".join(p["delta"] for n, p in events if n == "token")
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "chat"))).scalar_one()
        assert audit.request_id == rid


@pytest.mark.asyncio
async def test_stop_on_a_finished_stream_returns_cancelled_false(client, _engine):
    """幂等：流已结束时点「停止」不该报错。"""
    token = await _token(client)
    conv = await _conversation(client, token)

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv}/messages",
        json={"content": "问题", "use_rag": False},
        headers=_auth(token),
    ) as resp:
        [chunk async for chunk in resp.aiter_text()]

    r = await client.post(
        f"/api/v1/chat/conversations/{conv}/stop",
        json={"request_id": "rid-never-existed"},
        headers=_auth(token),
    )
    assert r.json()["data"]["cancelled"] is False


# ------------------------------------------------------------------ CRUD 与鉴权


@pytest.mark.asyncio
async def test_conversation_crud_round_trip(client, _engine):
    token = await _token(client)
    conv = await _conversation(client, token, title="闭包答疑")

    listed = await client.get("/api/v1/chat/conversations", headers=_auth(token))
    assert [c["id"] for c in listed.json()["data"]] == [conv]

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv}/messages",
        json={"content": "闭包是什么", "use_rag": False},
        headers=_auth(token),
    ) as resp:
        [chunk async for chunk in resp.aiter_text()]

    messages = await client.get(
        f"/api/v1/chat/conversations/{conv}/messages", headers=_auth(token)
    )
    rows = messages.json()["data"]
    assert [m["role"] for m in rows] == ["user", "assistant"]
    assert rows[1]["provider"] == "fake"
    assert rows[1]["truncated"] is False

    deleted = await client.delete(
        f"/api/v1/chat/conversations/{conv}", headers=_auth(token)
    )
    assert deleted.json()["data"]["deleted"] is True
    assert (await client.get("/api/v1/chat/conversations", headers=_auth(token))).json()[
        "data"
    ] == []


@pytest.mark.asyncio
async def test_another_users_conversation_is_invisible(client, _engine):
    owner = await _token(client, "owner")
    other = await _token(client, "other")
    conv = await _conversation(client, owner)

    for method, url in (
        ("GET", f"/api/v1/chat/conversations/{conv}/messages"),
        ("DELETE", f"/api/v1/chat/conversations/{conv}"),
    ):
        r = await client.request(method, url, headers=_auth(other))
        assert r.json()["code"] == 4040, url

    r = await client.post(
        f"/api/v1/chat/conversations/{conv}/stop",
        json={"request_id": "x"},
        headers=_auth(other),
    )
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_chat_endpoints_require_authentication(client, _engine):
    r = await client.get("/api/v1/chat/conversations")
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_request_id_is_echoed_on_every_endpoint(client, _engine):
    """H3：端点一律注入 CurrentRidDep，禁止硬编码 request_id=""。"""
    token = await _token(client)
    rid = "rid-check-1"

    r = await client.post(
        "/api/v1/chat/conversations", json={"title": "t"}, headers=_auth(token, rid)
    )
    assert r.json()["request_id"] == rid
    assert r.headers["x-request-id"] == rid

    r = await client.get("/api/v1/chat/conversations", headers=_auth(token, rid))
    assert r.json()["request_id"] == rid
