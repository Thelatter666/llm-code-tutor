import pytest

from app.core.errors import ApiError
from app.domain.knowledge.status import DOC_READY, KB_READY, KB_REINDEXING
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import (
    MODEL_CONFIG_SINGLETON_ID,
    Chunk,
    Document,
    KnowledgeBase,
    ModelConfig,
)
from app.infrastructure.ports.vectorstore import VectorHit
from app.services.retrieval_service import (
    FALLBACK_NO_HIT,
    FALLBACK_SENTINEL,
    RetrievalService,
    SearchResult,
)
from tests.fakes import FakeEmbedder, FakeVectorStore, SentinelEmbedder


def _runtime(embedder) -> EmbedderRuntime:
    """level 0 返回该替身，其余级不可用。"""
    return EmbedderRuntime(lambda level: embedder if level == 0 else None, levels=1)


class StubVectorStore(FakeVectorStore):
    """按给定命中列表返回结果的向量库替身。"""

    def __init__(self, hits):
        super().__init__()
        self.hits = hits

    async def query(self, embedding, top_k, kb_ids):
        self.calls.append(f"query:{','.join(kb_ids)}:{top_k}")
        return self.hits[:top_k]


def _hit(vector_id, document_id="kb1-doc", score=0.9, kb_id="kb1"):
    return VectorHit(
        vector_id=vector_id,
        score=score,
        metadata={"kb_id": kb_id, "document_id": document_id},
    )


async def _mk_kb(session, *, kb_id="kb1", status=KB_READY, course_code="CS101", chunks=0):
    session.add(KnowledgeBase(id=kb_id, name="kb", status=status, course_code=course_code))
    doc = Document(
        id=f"{kb_id}-doc", kb_id=kb_id, title="第 1 讲", source_type="md", status=DOC_READY
    )
    session.add(doc)
    await session.flush()
    for i in range(chunks):
        session.add(
            Chunk(
                id=f"{doc.id}:{i}",
                document_id=doc.id,
                kb_id=kb_id,
                content=f"第{i}片内容",
                ordinal=i,
                char_count=5,
                vector_id=f"{doc.id}:{i}",
            )
        )
    await session.commit()
    return doc


async def _search(session, store, query="问题", *, embedder=None, **kw):
    """建服务 → 预热 → 检索。检索要求模型就绪，未就绪会返回 5032。"""
    runtime = _runtime(embedder or FakeEmbedder())
    await runtime.warmup()
    svc = RetrievalService(session, embedder=runtime, vector_store=store)
    return await svc.search(query, **kw)


@pytest.mark.asyncio
async def test_unknown_kb_returns_4040(session):
    with pytest.raises(ApiError) as exc:
        await _search(session, FakeVectorStore(), kb_ids=["nope"])
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_reindexing_kb_returns_5032(session):
    await _mk_kb(session, status=KB_REINDEXING)
    with pytest.raises(ApiError) as exc:
        await _search(session, FakeVectorStore(), kb_ids=["kb1"])
    assert exc.value.code == 5032
    assert "重建" in exc.value.message


@pytest.mark.asyncio
async def test_vector_store_failure_degrades_to_5032(session):
    """审计 PR-2：向量库自身故障必须落到 5032（spec §9），不能漏成 5000。"""
    await _mk_kb(session)

    class Broken(FakeVectorStore):
        async def query(self, embedding, top_k, kb_ids):
            raise RuntimeError("chroma persistent dir corrupted")

    with pytest.raises(ApiError) as exc:
        await _search(session, Broken(), kb_ids=["kb1"])
    assert exc.value.code == 5032
    assert "检索" in exc.value.message


@pytest.mark.asyncio
async def test_default_scope_excludes_reindexing_kb(session):
    """审计 PR-4：不带 kb_ids 的检索不得把重建中的库纳入作用域（spec §8.7）。

    显式指定 kb_ids → 5032（上一条用例）；默认作用域 → 静默排除。
    某库重建是秒级瞬态，不应让全站检索因此失败。
    """
    await _mk_kb(session, kb_id="kb-ok", status=KB_READY, chunks=1)
    await _mk_kb(session, kb_id="kb-bad", status=KB_REINDEXING, chunks=1)

    store = StubVectorStore([_hit("kb-ok-doc:0", kb_id="kb-ok")])
    result = await _search(session, store)
    assert result.rag_hit is True
    assert all("kb-bad" not in call for call in store.calls)


@pytest.mark.asyncio
async def test_embedder_not_ready_returns_5032(session):
    """用户拍板决策 1：未就绪期间的检索请求返回 5032 并给出明确提示。"""
    await _mk_kb(session)

    class NeverReady(EmbedderRuntime):
        @property
        def is_ready(self):
            return False

    svc = RetrievalService(
        session, embedder=NeverReady(lambda level: None), vector_store=FakeVectorStore()
    )
    with pytest.raises(ApiError) as exc:
        await svc.search("问题", kb_ids=["kb1"])
    assert exc.value.code == 5032
    assert "加载" in exc.value.message


@pytest.mark.asyncio
async def test_sentinel_embedder_forces_rag_hit_false(session):
    """ADR-0004：哨兵级降级的产出一律不注入 prompt。"""
    await _mk_kb(session, chunks=3)
    result = await _search(
        session,
        StubVectorStore([_hit("kb1-doc:0", "kb1-doc", 0.95)]),
        embedder=SentinelEmbedder(),
        kb_ids=["kb1"],
    )

    assert result.rag_hit is False
    assert result.degraded is True
    assert result.fallback_reason == FALLBACK_SENTINEL
    assert result.citations == []


@pytest.mark.asyncio
async def test_zero_hit_reports_rag_hit_false(session):
    """spec §7.2 步骤 7：零命中要明确告知，防止模型幻觉冒充知识库答案。"""
    await _mk_kb(session, chunks=3)
    result = await _search(session, StubVectorStore([]), kb_ids=["kb1"])

    assert result.rag_hit is False
    assert result.degraded is True
    assert result.fallback_reason == FALLBACK_NO_HIT
    assert result.citations == []


async def _mk_chunk(session, vector_id, document_id, kb_id="kb1"):
    session.add(
        Chunk(
            id=vector_id,
            document_id=document_id,
            kb_id=kb_id,
            content=f"内容-{vector_id}",
            ordinal=0,
            char_count=5,
            vector_id=vector_id,
        )
    )


async def _mk_doc(session, doc_id, kb_id="kb1"):
    session.add(
        Document(id=doc_id, kb_id=kb_id, title=f"文档-{doc_id}", source_type="md", status=DOC_READY)
    )


@pytest.mark.asyncio
async def test_pipeline_applies_threshold_then_relative_then_diversity(session):
    """spec §7.2 步骤 2→3→4。"""
    await _mk_kb(session, chunks=0)
    # _mk_kb 已建出 kb1-doc，这里只补另两份文档
    for doc_id, ids in ((("kb1-doc2"), ["b1"]), (("kb1-doc3"), ["c1"])):
        await _mk_doc(session, doc_id)
        for vid in ids:
            await _mk_chunk(session, vid, doc_id)
    for vid in ("a1", "a2", "a3", "a4"):
        await _mk_chunk(session, vid, "kb1-doc")
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, score_threshold=None, top_k=6))
    await session.commit()

    hits = [
        _hit("a1", "kb1-doc", 0.95),
        _hit("a2", "kb1-doc", 0.94),
        _hit("a3", "kb1-doc", 0.93),
        _hit("a4", "kb1-doc", 0.92),  # 第 4 片：被多样性截取掉
        _hit("b1", "kb1-doc2", 0.60),  # 与最佳分差 0.35：被相对截断掉
        _hit("c1", "kb1-doc3", 0.20),  # 低于阈值 0.30：被绝对阈值掉
    ]
    result = await _search(session, StubVectorStore(hits), kb_ids=["kb1"])

    assert result.rag_hit is True
    assert result.degraded is False
    assert [c.chunk_id for c in result.citations] == ["a1", "a2", "a3"]
    assert result.threshold == 0.30  # fake →「其他」档


@pytest.mark.asyncio
async def test_configured_threshold_overrides_model_default(session):
    await _mk_kb(session, chunks=0)  # 已建出 kb1-doc
    for vid in ("a1", "a2"):
        await _mk_chunk(session, vid, "kb1-doc")
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, score_threshold=0.90, top_k=5))
    await session.commit()

    hits = [_hit("a1", "kb1-doc", 0.95), _hit("a2", "kb1-doc", 0.80)]
    result = await _search(session, StubVectorStore(hits), kb_ids=["kb1"])

    assert result.threshold == 0.90
    assert [c.chunk_id for c in result.citations] == ["a1"]


@pytest.mark.asyncio
async def test_citations_carry_snippet_and_score(session):
    await _mk_kb(session, chunks=2)
    result = await _search(
        session, StubVectorStore([_hit("kb1-doc:0", "kb1-doc", 0.95)]), kb_ids=["kb1"]
    )

    citation = result.citations[0]
    assert citation.chunk_id == "kb1-doc:0"
    assert citation.document_id == "kb1-doc"
    assert citation.doc_title == "第 1 讲"
    assert citation.snippet == "第0片内容"
    assert citation.score == 0.95
    assert citation.number == 1  # spec §7.2 步骤 5：编号从 1 开始


@pytest.mark.asyncio
async def test_course_code_scopes_the_search(session):
    """spec §6.2：course_code 为空表示不限课程。"""
    await _mk_kb(session, kb_id="kb1", course_code="CS101", chunks=1)
    await _mk_kb(session, kb_id="kb2", course_code="CS102", chunks=1)
    store = StubVectorStore([])

    await _search(session, store, course_code="CS101")
    assert "kb1" in store.calls[-1] and "kb2" not in store.calls[-1]

    await _search(session, store, course_code=None)
    assert "kb1" in store.calls[-1] and "kb2" in store.calls[-1]


@pytest.mark.asyncio
async def test_top_k_defaults_to_model_config(session):
    await _mk_kb(session, chunks=1)
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, top_k=2))
    await session.commit()
    store = StubVectorStore(
        [_hit("a", "kb1-doc", 0.9), _hit("b", "kb1-doc", 0.8), _hit("c", "kb1-doc", 0.7)]
    )

    await _search(session, store, kb_ids=["kb1"])
    assert store.calls[-1].endswith(":2")


@pytest.mark.asyncio
async def test_explicit_top_k_overrides_config(session):
    await _mk_kb(session, chunks=1)
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, top_k=2))
    await session.commit()
    store = StubVectorStore([_hit("a", "kb1-doc", 0.9)])

    await _search(session, store, kb_ids=["kb1"], top_k=1)
    assert store.calls[-1].endswith(":1")


@pytest.mark.asyncio
async def test_no_knowledge_base_at_all_returns_zero_hit(session):
    """没有任何知识库时不该 404 —— 空库是合法状态。"""
    result = await _search(session, StubVectorStore([]))
    assert result.rag_hit is False
    assert result.fallback_reason == FALLBACK_NO_HIT


@pytest.mark.asyncio
async def test_hits_without_matching_chunk_row_are_skipped(session):
    """孤儿向量（有向量无 Chunk 行）不得进引用 —— 点击溯源会 404。"""
    await _mk_kb(session, chunks=1)
    result = await _search(
        session, StubVectorStore([_hit("ghost-vector", "kb1-doc", 0.99)]), kb_ids=["kb1"]
    )

    assert result.citations == []
    assert result.rag_hit is False


@pytest.mark.asyncio
async def test_result_exposes_embedder_name(session):
    await _mk_kb(session, chunks=1)
    result = await _search(
        session, StubVectorStore([_hit("kb1-doc:0", "kb1-doc", 0.95)]), kb_ids=["kb1"]
    )
    assert result.embedder == "fake"


def test_search_result_defaults():
    result = SearchResult(
        rag_hit=False, degraded=True, fallback_reason="x", threshold=0.3
    )
    assert result.citations == []
    assert result.embedder is None


def test_search_result_payload_shape():
    result = SearchResult(
        rag_hit=True, degraded=False, fallback_reason=None, threshold=0.3, embedder="fake"
    )
    payload = result.as_payload()
    assert payload["rag_hit"] is True
    assert payload["citations"] == []
    assert payload["embedder"] == "fake"
