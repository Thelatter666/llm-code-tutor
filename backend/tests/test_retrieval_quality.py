"""检索质量端到端回归：真模型 + 真 Chroma + 真切分 + 真阈值。

单元测试只验证了「模型能把语义相近与无关分开」；本文件把它放到 spec §7.2 的
完整链路上再验一次 —— embed → 相关度阈值 → 相对截断 → 多样性截取 → 引用，
任何一环出错都会让模型的质量白费。
"""

import pytest
from sqlalchemy import select

from app.domain.knowledge.status import DOC_READY
from app.infrastructure.adapters.embedding.sentence_transformer import (
    SentenceTransformerEmbedder,
    local_embed_available,
)
from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.services.indexing_service import IndexingService
from app.services.retrieval_service import RetrievalService

pytestmark = pytest.mark.skipif(
    not local_embed_available(), reason="未安装 local-embed extras"
)

CORPUS = {
    "排序算法": [
        (
            "快速排序采用分治思想：选定基准元素，把数组分成小于和大于基准的两部分，"
            "再对两部分分别递归排序。平均时间复杂度 O(n log n)，最坏情况 O(n²)。"
        ),
        (
            "冒泡排序重复走访数组，比较相邻元素并在顺序错误时交换。时间复杂度 O(n²)，"
            "实现简单但只适合小规模数据。"
        ),
        (
            "归并排序先把数组递归拆成单个元素，再两两合并有序序列。时间复杂度稳定为 "
            "O(n log n)，需要 O(n) 的额外空间。"
        ),
    ],
    "Python 语法": [
        (
            "闭包是函数与其定义时的引用环境的组合。内层函数可以访问外层函数的局部变量，"
            "即使外层函数已经返回，该变量依然存活。"
        ),
        (
            "列表推导式提供一种简洁的构造列表的方式，形如 [x * x for x in range(10)]，"
            "可读性与执行效率通常都优于等价的 for 循环。"
        ),
    ],
    "食堂": [
        "今天食堂的红烧肉味道不错，土豆炖得很烂，米饭也蒸得刚好，排队的人比昨天少。",
    ],
}

QUERY_SORTING = "讲讲排序算法"
QUERY_CANTEEN = "今天中午食堂的饭菜怎么样？"


@pytest.fixture
async def indexed(session, tmp_path):
    session.add(KnowledgeBase(id="kb1", name="Python 讲义", status="ready"))
    embedder = SentenceTransformerEmbedder()
    runtime = EmbedderRuntime(lambda level: embedder if level == 1 else None)
    await runtime.warmup()

    store = ChromaVectorStore(persist_dir=tmp_path / "chroma")
    for title, paragraphs in CORPUS.items():
        source = tmp_path / f"{title}.txt"
        source.write_text("\n\n".join(paragraphs), encoding="utf-8")
        doc = Document(
            id=f"doc-{title}",
            kb_id="kb1",
            title=title,
            source_type="txt",
            status="pending",
            source_uri=str(source),
        )
        session.add(doc)
        await session.commit()
        await IndexingService(
            session, embedder=runtime, vector_store=store
        ).index_document(doc.id)

    session.expunge_all()
    rows = (await session.execute(select(Document))).scalars().all()
    assert len(rows) == len(CORPUS)
    assert all(r.status == DOC_READY for r in rows), [r.status for r in rows]
    return runtime, store


def _svc(session, runtime, store) -> RetrievalService:
    return RetrievalService(session, embedder=runtime, vector_store=store)


def _score_of(result, doc_title):
    for c in result.citations:
        if c.doc_title == doc_title:
            return c.score
    return None


@pytest.mark.asyncio
async def test_every_document_produced_one_chunk(session, indexed):
    """每份文档的段落总量都远小于 1200 字符 → 各切出 1 片。"""
    session.expunge_all()
    rows = (await session.execute(select(Chunk))).scalars().all()
    assert len(rows) == len(CORPUS)
    assert all(r.vector_id for r in rows)
    assert all(r.embed_model == "paraphrase-multilingual-MiniLM-L12-v2" for r in rows)


@pytest.mark.asyncio
async def test_related_query_hits_related_chunk(session, indexed):
    runtime, store = indexed
    result = await _svc(session, runtime, store).search(QUERY_SORTING, kb_ids=["kb1"])

    assert result.rag_hit is True
    assert result.degraded is False
    assert result.threshold == 0.35  # MiniLM 档（spec §3.2 权衡 8）
    assert result.citations[0].doc_title == "排序算法"
    assert "快速排序" in result.citations[0].snippet
    assert result.citations[0].score > 0.35


@pytest.mark.asyncio
async def test_unrelated_query_hits_the_canteen_chunk(session, indexed):
    """食堂话题命中食堂那一段，而不是排序算法 —— 这是「分得开」的正面证据。"""
    runtime, store = indexed
    result = await _svc(session, runtime, store).search(QUERY_CANTEEN, kb_ids=["kb1"])

    assert result.rag_hit is True
    assert result.citations[0].doc_title == "食堂"
    assert result.citations[0].score > 0.5


@pytest.mark.asyncio
async def test_the_two_queries_are_clearly_separated(session, indexed):
    """同一语料下，两个查询各自把目标段的分数拉到远高于另一段。"""
    runtime, store = indexed
    svc = _svc(session, runtime, store)

    sorting = await svc.search(QUERY_SORTING, kb_ids=["kb1"], top_k=10)
    canteen = await svc.search(QUERY_CANTEEN, kb_ids=["kb1"], top_k=10)

    sorting_on_sorting = _score_of(sorting, "排序算法")
    sorting_on_canteen = _score_of(sorting, "食堂")
    canteen_on_canteen = _score_of(canteen, "食堂")
    canteen_on_sorting = _score_of(canteen, "排序算法")

    assert sorting_on_sorting is not None and canteen_on_canteen is not None
    assert sorting_on_sorting > 0.45
    assert canteen_on_canteen > 0.45
    # 交叉项要么被阈值/相对截断掉（None），要么显著低于本命项
    for cross, direct in (
        (sorting_on_canteen, sorting_on_sorting),
        (canteen_on_sorting, canteen_on_canteen),
    ):
        if cross is not None:
            assert direct - cross > 0.15, (direct, cross)


@pytest.mark.asyncio
async def test_citation_numbers_start_at_one(session, indexed):
    runtime, store = indexed
    result = await _svc(session, runtime, store).search(QUERY_SORTING, kb_ids=["kb1"], top_k=5)

    assert result.citations
    assert [c.number for c in result.citations] == list(range(1, len(result.citations) + 1))


@pytest.mark.asyncio
async def test_diversity_caps_chunks_per_document(session, indexed):
    runtime, store = indexed
    result = await _svc(session, runtime, store).search("排序", kb_ids=["kb1"], top_k=10)

    counts: dict[str, int] = {}
    for c in result.citations:
        counts[c.document_id] = counts.get(c.document_id, 0) + 1
    assert counts and all(v <= 3 for v in counts.values())
