import pytest

from app.infrastructure.adapters.vectorstore.chroma_store import (
    ChromaVectorStore,
    collection_name,
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


def test_collection_is_partitioned_by_dimension():
    """spec §3.2 权衡 4：单集合 + kb_id 元数据过滤；集合名带维度后缀。

    维度后缀是必需的：Chroma 集合首次写入后维度即固定，**删光记录也不重置**。
    不分区的话，切换 embedding 模型后即便全量重建，新维度的 upsert 仍会被拒。
    """
    assert collection_name(384) == "course_chunks_d384"
    assert len(collection_name(384)) >= 3  # Chroma 要求 3–512 字符


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


# --- 维度切换：spec §8.7 的强制重建必须真能换维度 -------------------------------


def _rec_dim(vid: str, kb: str, dim: int, unit: int = 0) -> VectorRecord:
    vec = [0.0] * dim
    vec[unit % dim] = 1.0
    return VectorRecord(
        vector_id=vid,
        kb_id=kb,
        document_id="d1",
        embedding=vec,
        content=f"内容-{vid}",
    )


@pytest.mark.asyncio
async def test_rebuild_with_a_different_dimension_succeeds(store):
    """回归：删除全部记录后换维度，upsert 必须仍能成功。

    不按维度分区时这里会抛
    `InvalidArgumentError: Collection expecting embedding with dimension of 4, got 8`。
    """
    await store.upsert([_rec_dim("v1", "kb1", 4)])
    await store.delete_by_kb("kb1")
    assert await store.list_ids("kb1") == []

    await store.upsert([_rec_dim("v2", "kb1", 8)])
    hits = await store.query([1.0] + [0.0] * 7, top_k=5, kb_ids=["kb1"])
    assert [h.vector_id for h in hits] == ["v2"]


@pytest.mark.asyncio
async def test_query_with_a_dimension_that_was_never_indexed_returns_empty(store):
    """用未重建过的模型检索 → 空结果（而不是抛错）。"""
    await store.upsert([_rec_dim("v1", "kb1", 4)])
    assert await store.query([1.0] * 8, top_k=5, kb_ids=["kb1"]) == []


@pytest.mark.asyncio
async def test_list_ids_spans_dimensions_for_gc(store):
    """未重建的知识库其向量还在旧维度集合里，GC 必须能枚举到。"""
    await store.upsert([_rec_dim("v1", "kb1", 4)])
    await store.upsert([_rec_dim("v2", "kb1", 8)])
    assert sorted(await store.list_ids("kb1")) == ["v1", "v2"]


@pytest.mark.asyncio
async def test_delete_by_kb_clears_every_dimension(store):
    await store.upsert([_rec_dim("v1", "kb1", 4)])
    await store.upsert([_rec_dim("v2", "kb1", 8)])
    await store.delete_by_kb("kb1")
    assert await store.list_ids("kb1") == []


@pytest.mark.asyncio
async def test_empty_collections_are_pruned_after_cleanup(store, tmp_path):
    """维度切换留下空集合会占空间且无法再用，删空后应清掉。"""
    await store.upsert([_rec_dim("v1", "kb1", 4)])
    await store.upsert([_rec_dim("v2", "kb1", 8)])
    await store.delete_ids(["v1", "v2"])

    reopened = ChromaVectorStore(persist_dir=tmp_path / "chroma")
    names = reopened.list_collection_names()
    assert len(names) <= 1, f"空集合未被清理：{names}"
