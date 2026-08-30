import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.domain.auth.user import ADMIN
from app.domain.knowledge.status import DOC_FAILED
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence import db as db_module
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import User
from app.infrastructure.ports.vectorstore import VectorRecord
from app.infrastructure.runtime import (
    get_vector_store,
    reset_runtime,
    set_embedder_runtime,
    set_vector_store,
)
from app.main import app
from tests.fakes import ConstantEmbedder, FakeVectorStore

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
async def client(_engine, tmp_path, monkeypatch):
    factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    # 上传落盘目录指向临时目录，避免测试污染工作区
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    # 上传后的索引走 BackgroundTasks，它自带会话。默认工厂被 conftest 绑到了另一个
    # 内存库上，这里必须改指向本用例的库，否则后台任务查不到刚创建的 Document。
    monkeypatch.setattr(
        db_module, "SessionFactory", async_sessionmaker(_engine, expire_on_commit=False)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def _fake_infra():
    """API 测试不真起 Chroma、也不真加载模型；向量用常量替身。"""
    reset_runtime()
    set_vector_store(FakeVectorStore())
    runtime = EmbedderRuntime(lambda level: ConstantEmbedder() if level == 1 else None)
    await runtime.warmup()
    set_embedder_runtime(runtime)
    yield
    reset_runtime()


async def _promote(_engine, username):
    f = async_sessionmaker(_engine, expire_on_commit=False)
    async with f() as s:
        user = (await s.execute(select(User).where(User.username == username))).scalar_one()
        user.role = ADMIN
        await s.commit()


async def _token(c, username):
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return r.json()["data"]["access_token"]


async def _as_admin(c, _engine, username="boss"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    await _promote(_engine, username)
    return await _token(c, username)


async def _as_student(c, username="stu"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    return await _token(c, username)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_kb(c, token, name="Python 基础", course_code="CS101"):
    r = await c.post(
        "/api/v1/admin/knowledge/bases",
        json={"name": name, "course_code": course_code, "description": "讲义"},
        headers=_auth(token),
    )
    assert r.json()["code"] == 0, r.text
    return r.json()["data"]["id"]


def _upload(name, content=None, content_type="text/plain"):
    if content is None:
        content = ("正文内容。" * 60).encode()
    return {"file": (name, io.BytesIO(content), content_type)}


# ---------------- 学生端 ----------------


@pytest.mark.asyncio
async def test_student_lists_ready_knowledge_bases(client, _engine):
    admin = await _as_admin(client, _engine)
    await _make_kb(client, admin, course_code="CS101")
    stu = await _as_student(client)

    r = await client.get("/api/v1/knowledge/bases", headers=_auth(stu))
    assert r.json()["code"] == 0
    assert [b["name"] for b in r.json()["data"]] == ["Python 基础"]


@pytest.mark.asyncio
async def test_student_filters_bases_by_course_code(client, _engine):
    admin = await _as_admin(client, _engine)
    await _make_kb(client, admin, name="A", course_code="CS101")
    await _make_kb(client, admin, name="B", course_code="CS102")
    stu = await _as_student(client)

    r = await client.get("/api/v1/knowledge/bases?course_code=CS102", headers=_auth(stu))
    assert [b["name"] for b in r.json()["data"]] == ["B"]


@pytest.mark.asyncio
async def test_knowledge_endpoints_require_auth(client):
    assert (await client.get("/api/v1/knowledge/bases")).json()["code"] == 4010
    assert (await client.get("/api/v1/knowledge/search?query=x")).json()["code"] == 4010


@pytest.mark.asyncio
async def test_search_on_unknown_kb_returns_4040(client, _engine):
    stu = await _as_student(client)
    r = await client.get("/api/v1/knowledge/search?query=闭包&kb_ids=nope", headers=_auth(stu))
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_search_on_empty_library_returns_rag_hit_false(client, _engine):
    stu = await _as_student(client)
    r = await client.get("/api/v1/knowledge/search?query=闭包", headers=_auth(stu))
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["rag_hit"] is False
    assert body["data"]["fallback_reason"] == "no_relevant_chunk"


@pytest.mark.asyncio
async def test_search_before_model_ready_returns_5032(client, _engine):
    """用户拍板决策 1：未就绪期间的检索请求返回 5032。"""
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    stu = await _as_student(client)

    class NeverReady(EmbedderRuntime):
        @property
        def is_ready(self):
            return False

    set_embedder_runtime(NeverReady(lambda level: None))

    r = await client.get(
        f"/api/v1/knowledge/search?query=闭包&kb_ids={kb_id}", headers=_auth(stu)
    )
    assert r.json()["code"] == 5032
    assert "加载" in r.json()["message"]


@pytest.mark.asyncio
async def test_search_returns_citations_after_indexing(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", ("闭包是函数与其引用环境的组合。" * 80).encode()),
        headers=_auth(admin),
    )

    stu = await _as_student(client)
    r = await client.get(
        f"/api/v1/knowledge/search?query=闭包&kb_ids={kb_id}", headers=_auth(stu)
    )
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["rag_hit"] is True
    assert body["data"]["citations"]
    assert body["data"]["citations"][0]["number"] == 1
    assert body["data"]["embedder"] == "fake"


# ---------------- 管理端：鉴权 ----------------


@pytest.mark.asyncio
async def test_admin_kb_endpoints_reject_student(client, _engine):
    stu = await _as_student(client)
    paths = [
        ("post", "/api/v1/admin/knowledge/bases", {"json": {"name": "x"}}),
        ("patch", "/api/v1/admin/knowledge/bases/kb1", {"json": {"name": "x"}}),
        ("delete", "/api/v1/admin/knowledge/bases/kb1", {}),
        ("get", "/api/v1/admin/knowledge/bases/kb1/documents", {}),
        ("post", "/api/v1/admin/knowledge/documents/d1/reindex", {}),
        ("delete", "/api/v1/admin/knowledge/documents/d1", {}),
        ("get", "/api/v1/admin/knowledge/documents/d1/chunks", {}),
        ("post", "/api/v1/admin/knowledge/bases/kb1/rebuild-vector", {}),
        ("post", "/api/v1/admin/knowledge/bases/kb1/gc-orphan-vectors", {}),
        (
            "put",
            "/api/v1/admin/model-config/embedding",
            {"json": {"provider": "hashing", "model": "hashing-256"}},
        ),
    ]
    for method, path, kwargs in paths:
        r = await getattr(client, method)(path, headers=_auth(stu), **kwargs)
        assert r.json()["code"] == 4030, path


# ---------------- 管理端：知识库 CRUD ----------------


@pytest.mark.asyncio
async def test_admin_creates_updates_and_deletes_kb(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    r = await client.patch(
        f"/api/v1/admin/knowledge/bases/{kb_id}",
        json={"name": "新名称", "course_code": "CS999"},
        headers=_auth(admin),
    )
    assert r.json()["data"]["name"] == "新名称"
    assert r.json()["data"]["course_code"] == "CS999"

    r = await client.delete(f"/api/v1/admin/knowledge/bases/{kb_id}", headers=_auth(admin))
    assert r.json()["code"] == 0

    r = await client.get("/api/v1/knowledge/bases", headers=_auth(admin))
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_update_unknown_kb_returns_4040(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.patch(
        "/api/v1/admin/knowledge/bases/nope", json={"name": "x"}, headers=_auth(admin)
    )
    assert r.json()["code"] == 4040


# ---------------- 管理端：文档上传与索引 ----------------


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension_with_415(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.exe"),
        headers=_auth(admin),
    )
    assert r.status_code == 415
    assert r.json()["code"] == 4150


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file_with_413(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    big = b"x" * (10 * 1024 * 1024 + 1)
    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", big),
        headers=_auth(admin),
    )
    assert r.status_code == 413
    assert r.json()["code"] == 4130


@pytest.mark.asyncio
async def test_upload_then_list_documents_then_chunks(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", ("闭包是函数与其引用环境的组合。" * 80).encode()),
        headers=_auth(admin),
    )
    assert r.json()["code"] == 0, r.text
    doc_id = r.json()["data"]["id"]

    r = await client.get(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents", headers=_auth(admin)
    )
    docs = r.json()["data"]
    assert len(docs) == 1
    assert docs[0]["status"] == "ready"
    assert docs[0]["chunk_total"] >= 1
    assert docs[0]["chunk_indexed"] == docs[0]["chunk_total"]

    r = await client.get(
        f"/api/v1/admin/knowledge/documents/{doc_id}/chunks", headers=_auth(admin)
    )
    chunks = r.json()["data"]
    assert chunks and chunks[0]["content"]
    assert chunks[0]["embed_model"] == "fake-1"


@pytest.mark.asyncio
async def test_upload_of_unreadable_file_marks_failed(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("blank.md", b"   \n  "),
        headers=_auth(admin),
    )
    doc_id = r.json()["data"]["id"]

    r = await client.get(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents?status=failed",
        headers=_auth(admin),
    )
    docs = r.json()["data"]
    assert [d["id"] for d in docs] == [doc_id]
    assert docs[0]["status"] == DOC_FAILED
    assert docs[0]["error_msg"]


@pytest.mark.asyncio
async def test_reindex_document(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    doc_id = (
        await client.post(
            f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
            files=_upload("a.md", ("第一版内容。" * 80).encode()),
            headers=_auth(admin),
        )
    ).json()["data"]["id"]

    r = await client.post(
        f"/api/v1/admin/knowledge/documents/{doc_id}/reindex", headers=_auth(admin)
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["status"] == "ready"


@pytest.mark.asyncio
async def test_reindex_unknown_document_returns_4040(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.post(
        "/api/v1/admin/knowledge/documents/nope/reindex", headers=_auth(admin)
    )
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_delete_document_keeps_knowledge_base(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    doc_id = (
        await client.post(
            f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
            files=_upload("a.md", ("内容。" * 80).encode()),
            headers=_auth(admin),
        )
    ).json()["data"]["id"]

    r = await client.delete(
        f"/api/v1/admin/knowledge/documents/{doc_id}", headers=_auth(admin)
    )
    assert r.json()["code"] == 0

    r = await client.get(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents", headers=_auth(admin)
    )
    assert r.json()["data"] == []
    remaining = (await client.get("/api/v1/knowledge/bases", headers=_auth(admin))).json()["data"]
    assert len(remaining) == 1


# ---------------- 管理端：重建与 GC ----------------


@pytest.mark.asyncio
async def test_rebuild_vector(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", ("内容。" * 80).encode()),
        headers=_auth(admin),
    )

    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/rebuild-vector", headers=_auth(admin)
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["status"] == "ready"


@pytest.mark.asyncio
async def test_rebuild_unknown_kb_returns_4040(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.post(
        "/api/v1/admin/knowledge/bases/nope/rebuild-vector", headers=_auth(admin)
    )
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_gc_orphan_vectors(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)

    await get_vector_store().upsert(
        [
            VectorRecord(
                vector_id="orphan-1",
                kb_id=kb_id,
                document_id="d1",
                embedding=[0.1, 0.2, 0.3, 0.4],
                content="孤儿",
            )
        ]
    )

    r = await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/gc-orphan-vectors", headers=_auth(admin)
    )
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["orphans"] == 1
    assert body["data"]["deleted"] == 1


@pytest.mark.asyncio
async def test_gc_unknown_kb_returns_4040(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.post(
        "/api/v1/admin/knowledge/bases/nope/gc-orphan-vectors", headers=_auth(admin)
    )
    assert r.json()["code"] == 4040


# ---------------- embedding 切换（spec §8.7） ----------------


@pytest.mark.asyncio
async def test_embedding_switch_returns_409_then_confirmed_switch(client, _engine):
    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", ("内容。" * 80).encode()),
        headers=_auth(admin),
    )

    r = await client.put(
        "/api/v1/admin/model-config/embedding",
        json={"provider": "hashing", "model": "hashing-256", "confirm": False},
        headers=_auth(admin),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 4090
    assert r.json()["data"]["need_rebuild"] is True
    assert r.json()["data"]["knowledge_base_ids"] == [kb_id]

    r = await client.put(
        "/api/v1/admin/model-config/embedding",
        json={"provider": "hashing", "model": "hashing-256", "confirm": True},
        headers=_auth(admin),
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["rebuilt"] == [kb_id]


@pytest.mark.asyncio
async def test_failed_switch_returns_500_and_rolls_back_the_config(
    client, _engine, monkeypatch
):
    """重建失败必须抛业务错误码并回滚配置，不能静默返回 200。

    静默成功意味着管理员以为切好了，学生端却拿新模型的维度去查空集合 ——
    零命中且没有任何错误码，降级对学生端完全不可见（违反 spec §9）。
    """
    from app.services import rebuild_service

    admin = await _as_admin(client, _engine)
    kb_id = await _make_kb(client, admin)
    await client.post(
        f"/api/v1/admin/knowledge/bases/{kb_id}/documents",
        files=_upload("a.md", ("内容。" * 80).encode()),
        headers=_auth(admin),
    )
    # 先成功切一次，作为回滚的基准
    before = await client.put(
        "/api/v1/admin/model-config/embedding",
        json={"provider": "hashing", "model": "hashing-256", "confirm": True},
        headers=_auth(admin),
    )
    assert before.json()["code"] == 0

    # 第二次切换让重建炸掉 —— 只有这次要失败
    async def _explode(self, target_kb_id, **kwargs):
        raise RuntimeError("重建中途数据库不可用")

    monkeypatch.setattr(rebuild_service.RebuildService, "rebuild", _explode)

    r = await client.put(
        "/api/v1/admin/model-config/embedding",
        json={"provider": "sentence_transformers", "model": "new-model", "confirm": True},
        headers=_auth(admin),
    )
    assert r.status_code == 500
    assert r.json()["code"] == 5000
    assert r.json()["data"]["failed"] == [kb_id]
    assert r.json()["data"]["rolled_back_to"] == {
        "provider": "hashing",
        "model": "hashing-256",
    }

    # 回滚必须真的落到库里，而不是只在响应里说一声
    from app.infrastructure.persistence.models import ModelConfig

    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        cfg = (await s.execute(select(ModelConfig))).scalar_one()
    assert cfg.embedding_provider == "hashing"
    assert cfg.embedding_model == "hashing-256"


@pytest.mark.asyncio
async def test_embedding_consistency_endpoint(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.get(
        "/api/v1/admin/model-config/embedding-consistency", headers=_auth(admin)
    )
    assert r.json()["code"] == 0
    assert r.json()["data"] == []


# ---------------- 契约：request_id（H3） ----------------


@pytest.mark.asyncio
async def test_request_id_in_body_matches_header(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.get(
        "/api/v1/admin/knowledge/bases/kb1/documents", headers=_auth(admin)
    )
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert r.json()["request_id"]


@pytest.mark.asyncio
async def test_unknown_kb_documents_returns_4040(client, _engine):
    admin = await _as_admin(client, _engine)
    r = await client.get(
        "/api/v1/admin/knowledge/bases/nope/documents", headers=_auth(admin)
    )
    assert r.json()["code"] == 4040
