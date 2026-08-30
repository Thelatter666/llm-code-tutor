import pytest

from app.infrastructure.adapters.vectorstore.chroma_store import (
    COLLECTION_NAME,
    ChromaVectorStore,
)
from app.infrastructure.ports.vectorstore import VectorRecord, VectorStore

DIM = 4


def _one(unit: int) -> list[float]:
    v = [0.0] * DIM
    v[unit] = 1.0
    return v


def _rec(vid: str, kb: str, doc: str = "d1", unit: int = 0) -> VectorRecord:
    return VectorRecord(
        vector_id=vid,
        kb_id=kb,
        document_id=doc,
        embedding=_one(unit),
        content=f"内容-{vid}",
        metadata={"kb_id": kb, "document_id": doc},
    )


@pytest.fixture
def store(tmp_path):
    return ChromaVectorStore(persist_dir=tmp_path / "chroma")


def test_satisfies_vector_store_port(store):
    assert isinstance(store, VectorStore)


def test_collection_name_is_single_shared_collection():
    """spec §3.2 权衡 4：单集合 + kb_id 元数据过滤（Chroma 要求 3–512 字符）。"""
    assert COLLECTION_NAME == "course_chunks"


@pytest.mark.asyncio
async def test_upsert_then_query_filters_by_kb(store):
    await store.upsert([_rec("v1", "kb1"), _rec("v2", "kb2")])

    hits = await store.query(_one(0), top_k=5, kb_ids=["kb1"])
    assert [h.vector_id for h in hits] == ["v1"]


@pytest.mark.asyncio
async def test_score_is_cosine_similarity_not_distance(store):
    """Chroma 返回余弦距离，端口必须换算为相似度，否则阈值语义完全反了。"""
    await store.upsert([_rec("same", "kb", unit=0), _rec("orth", "kb", unit=1)])

    hits = await store.query(_one(0), top_k=2, kb_ids=["kb"])
    by_id = {h.vector_id: h.score for h in hits}
    assert by_id["same"] == pytest.approx(1.0, abs=1e-5)
    assert by_id["orth"] == pytest.approx(0.0, abs=1e-5)


@pytest.mark.asyncio
async def test_query_across_multiple_kb_ids(store):
    await store.upsert([_rec("v1", "kb1"), _rec("v2", "kb2"), _rec("v3", "kb3")])

    hits = await store.query(_one(0), top_k=5, kb_ids=["kb1", "kb3"])
    assert {h.vector_id for h in hits} == {"v1", "v3"}


@pytest.mark.asyncio
async def test_top_k_limits_results(store):
    await store.upsert([_rec(f"v{i}", "kb") for i in range(5)])
    hits = await store.query(_one(0), top_k=2, kb_ids=["kb"])
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_upsert_is_idempotent(store):
    await store.upsert([_rec("v1", "kb")])
    await store.upsert([_rec("v1", "kb", unit=2)])
    hits = await store.query(_one(2), top_k=5, kb_ids=["kb"])
    assert [h.vector_id for h in hits] == ["v1"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_delete_ids_removes_only_targets(store):
    await store.upsert([_rec("v1", "kb"), _rec("v2", "kb")])
    await store.delete_ids(["v1"])

    assert await store.list_ids("kb") == ["v2"]


@pytest.mark.asyncio
async def test_delete_by_kb_leaves_other_kb_intact(store):
    await store.upsert([_rec("v1", "kb1"), _rec("v2", "kb2")])
    await store.delete_by_kb("kb1")

    assert await store.list_ids("kb1") == []
    assert await store.list_ids("kb2") == ["v2"]


@pytest.mark.asyncio
async def test_list_ids_supports_orphan_gc(store):
    """孤儿向量清理需要枚举 Chroma 中某 kb 的全部 vector_id。"""
    await store.upsert([_rec("v1", "kb1"), _rec("v2", "kb1"), _rec("v3", "kb2")])
    assert sorted(await store.list_ids("kb1")) == ["v1", "v2"]


@pytest.mark.asyncio
async def test_unknown_kb_query_returns_empty(store):
    await store.upsert([_rec("v1", "kb1")])
    assert await store.query(_one(0), top_k=5, kb_ids=["nope"]) == []


@pytest.mark.asyncio
async def test_data_survives_client_reopen(tmp_path):
    """持久化目录：重启进程后向量必须还在（ADR-0002 单 worker 的前提）。"""
    store = ChromaVectorStore(persist_dir=tmp_path / "chroma")
    await store.upsert([_rec("v1", "kb1")])

    reopened = ChromaVectorStore(persist_dir=tmp_path / "chroma")
    assert await reopened.list_ids("kb1") == ["v1"]
