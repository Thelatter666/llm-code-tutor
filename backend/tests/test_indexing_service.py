import asyncio
import threading
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.knowledge.status import DOC_FAILED, DOC_READY
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import Chunk, Document
from app.services.indexing_service import IndexingService
from tests.fakes import BrokenEmbedder, FakeEmbedder, FakeVectorStore, SentinelEmbedder


def _runtime(embedder) -> EmbedderRuntime:
    """把替身包成运行时：level 0 返回该替身，其余级不可用。"""
    return EmbedderRuntime(lambda level: embedder if level == 0 else None, levels=1)


def _svc(session, store, embedder) -> IndexingService:
    return IndexingService(session, embedder=_runtime(embedder), vector_store=store)


async def _mk(session, tmp_path, text="## 标题\n\n" + "内容。" * 400, name="a.md", doc_id="d1"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    doc = Document(
        id=doc_id,
        kb_id="kb1",
        title="第 1 讲",
        source_type="md",
        source_uri=str(p),
        status="pending",
    )
    session.add(doc)
    await session.commit()
    return doc


async def _doc_state(session, doc_id="d1"):
    """索引在**独立会话**中提交，外层会话的身份映射里还是旧对象。

    用 expunge_all 而非 expire_all：后者会让已有实体进入「待惰性加载」状态，
    随后在同步上下文访问 doc.id 会抛 MissingGreenlet。
    """
    session.expunge_all()
    row = (
        await session.execute(
            select(
                Document.status,
                Document.chunk_total,
                Document.chunk_indexed,
                Document.error_msg,
            ).where(Document.id == doc_id)
        )
    ).one()
    return {
        "status": row[0],
        "chunk_total": row[1],
        "chunk_indexed": row[2],
        "error_msg": row[3],
    }


async def _chunks(session):
    session.expunge_all()
    return list((await session.execute(select(Chunk).order_by(Chunk.ordinal))).scalars().all())


async def _point_to(session, doc_id: str, path: Path):
    """改指向另一个源文件。

    必须重新查询：前面的 _chunks/_doc_state 会 expunge_all，直接改那个已脱离
    会话的对象，改动不会被 flush —— 这是测试脚手架的坑，不是产物代码的问题。
    """
    session.expunge_all()
    doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
    doc.source_uri = str(path)
    await session.commit()


@pytest.mark.asyncio
async def test_index_document_produces_chunks_and_marks_ready(session, tmp_path):
    doc = await _mk(session, tmp_path)
    store = FakeVectorStore()

    await _svc(session, store, FakeEmbedder()).index_document(doc.id)

    got = await _doc_state(session)
    assert got["status"] == DOC_READY
    assert got["chunk_total"] > 1
    assert got["chunk_indexed"] == got["chunk_total"]

    rows = await _chunks(session)
    assert len(rows) == got["chunk_total"]
    assert all(r.vector_id for r in rows)
    assert all(r.embed_model == "fake-1" for r in rows)
    assert [r.ordinal for r in rows] == list(range(len(rows)))
    assert [r.char_count for r in rows] == [len(r.content) for r in rows]


@pytest.mark.asyncio
async def test_chunks_are_linked_to_document_and_kb(session, tmp_path):
    doc_id = "d1"
    await _mk(session, tmp_path, doc_id=doc_id)
    await _svc(session, FakeVectorStore(), FakeEmbedder()).index_document(doc_id)

    row = (await _chunks(session))[0]
    assert row.document_id == doc_id
    assert row.kb_id == "kb1"


@pytest.mark.asyncio
async def test_vectors_are_upserted_with_kb_id_metadata(session, tmp_path):
    doc = await _mk(session, tmp_path)
    store = FakeVectorStore()
    await _svc(session, store, FakeEmbedder()).index_document(doc.id)

    assert len(store.records) > 1
    assert all(r.kb_id == "kb1" for r in store.records.values())
    assert set(store.records) == {c.vector_id for c in await _chunks(session)}


@pytest.mark.asyncio
async def test_progress_is_committed_incrementally(session, engine, tmp_path):
    """spec §8.2 进度可见：chunk_indexed 分批提交，而非索引完才一次性跳到 total。"""
    doc = await _mk(session, tmp_path, text="段落。" * 8000)
    store = FakeVectorStore()

    progress: list[int] = []

    class SpySession(AsyncSession):
        async def commit(self):
            current = await self.get(Document, "d1")
            if current is not None:
                progress.append(current.chunk_indexed)
            await super().commit()

    def factory():
        return SpySession(engine, expire_on_commit=False)

    svc = IndexingService(
        session,
        embedder=_runtime(FakeEmbedder()),
        vector_store=store,
        session_factory=factory,
    )
    await svc.index_document(doc.id)

    got = await _doc_state(session)
    assert got["chunk_total"] > 1
    assert got["chunk_indexed"] == got["chunk_total"]
    # 提交过程中必须出现「尚未完成」的中间态，否则前端轮询看不到进度
    assert any(0 <= v < got["chunk_total"] for v in progress), f"未观察到中间进度：{progress}"


@pytest.mark.asyncio
async def test_missing_file_marks_document_failed(session, tmp_path):
    doc = await _mk(session, tmp_path)
    (tmp_path / "a.md").unlink()

    await _svc(session, FakeVectorStore(), FakeEmbedder()).index_document(doc.id)

    got = await _doc_state(session)
    assert got["status"] == DOC_FAILED
    assert got["error_msg"]


@pytest.mark.asyncio
async def test_empty_document_marks_failed_with_ocr_hint(session, tmp_path):
    doc = await _mk(session, tmp_path, text="   \n  ", name="empty.md")

    await _svc(session, FakeVectorStore(), FakeEmbedder()).index_document(doc.id)

    got = await _doc_state(session)
    assert got["status"] == DOC_FAILED
    assert "OCR" in got["error_msg"]


@pytest.mark.asyncio
async def test_embedding_failure_marks_document_failed(session, tmp_path):
    doc = await _mk(session, tmp_path)

    await _svc(session, FakeVectorStore(), BrokenEmbedder()).index_document(doc.id)

    got = await _doc_state(session)
    assert got["status"] == DOC_FAILED
    assert got["error_msg"]


@pytest.mark.asyncio
async def test_chunk_ids_are_deterministic_so_reindex_is_idempotent(session, tmp_path):
    """切片 id 由 (document_id, ordinal) 决定，重复索引不会产生重复向量。"""
    doc = await _mk(session, tmp_path)
    store = FakeVectorStore()
    svc = _svc(session, store, FakeEmbedder())

    await svc.index_document(doc.id)
    first = {c.vector_id for c in await _chunks(session)}
    await svc.reindex_document(doc.id)
    second = {c.vector_id for c in await _chunks(session)}

    assert first == second
    assert set(store.records) == second


@pytest.mark.asyncio
async def test_reindex_drops_stale_chunks_when_content_shrinks(session, tmp_path):
    doc = await _mk(session, tmp_path, text="第一版内容。" * 400, name="v1.md")
    store = FakeVectorStore()
    await _svc(session, store, FakeEmbedder()).index_document(doc.id)
    assert len(await _chunks(session)) > 1

    await _mk(session, tmp_path, text="第二版很短的内容。", name="v2.md", doc_id="tmp")
    await _point_to(session, doc.id, tmp_path / "v2.md")

    await _svc(session, store, FakeEmbedder()).reindex_document(doc.id)

    remaining = await _chunks(session)
    assert len(remaining) == 1
    assert set(store.records) == {c.vector_id for c in remaining}, "旧向量未被清理"


@pytest.mark.asyncio
async def test_reindex_of_failed_document_recovers(session, tmp_path):
    doc = await _mk(session, tmp_path, text="   ", name="empty.md")
    await _svc(session, FakeVectorStore(), FakeEmbedder()).index_document(doc.id)
    assert (await _doc_state(session))["status"] == DOC_FAILED

    await _mk(session, tmp_path, text="恢复后的内容。" * 200, name="ok.md", doc_id="tmp")
    await _point_to(session, doc.id, tmp_path / "ok.md")

    await _svc(session, FakeVectorStore(), FakeEmbedder()).reindex_document(doc.id)
    assert (await _doc_state(session))["status"] == DOC_READY


@pytest.mark.asyncio
async def test_sentinel_embedder_still_indexes(session, tmp_path):
    """ADR-0004：哨兵仍照常写入，保证链路可跑通；是否注入由检索阶段决定。"""
    doc = await _mk(session, tmp_path)
    await _svc(session, FakeVectorStore(), SentinelEmbedder()).index_document(doc.id)

    got = await _doc_state(session)
    assert got["status"] == DOC_READY
    rows = await _chunks(session)
    assert rows and rows[0].embed_model == "hashing-256"


@pytest.mark.asyncio
async def test_unknown_document_id_is_ignored(session):
    """后台任务可能落在已被删除的文档上，静默返回好过抛错刷屏。"""
    await _svc(session, FakeVectorStore(), FakeEmbedder()).index_document("nope")


@pytest.mark.asyncio
async def test_reindex_unknown_document_returns_4040(session):
    with pytest.raises(ApiError) as exc:
        await _svc(session, FakeVectorStore(), FakeEmbedder()).reindex_document("nope")
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_blocking_work_runs_off_the_event_loop(session, tmp_path):
    """ADR-0002：embedding 推理不得在事件循环上执行。"""

    class ThreadRecordingEmbedder(FakeEmbedder):
        def __init__(self):
            super().__init__()
            self.threads: set[str] = set()

        def embed(self, texts):
            self.threads.add(threading.current_thread().name)
            return super().embed(texts)

    doc = await _mk(session, tmp_path, text="内容。" * 800)
    embedder = ThreadRecordingEmbedder()
    await _svc(session, FakeVectorStore(), embedder).index_document(doc.id)

    assert embedder.threads, "embedding 未被调用"
    assert "MainThread" not in embedder.threads, "阻塞调用仍在主线程上执行"


@pytest.mark.asyncio
async def test_concurrent_index_tasks_are_serialized(session, tmp_path):
    """spec §3.2 权衡 14：索引全局并发上限 1。"""
    await _mk(session, tmp_path, name="a.md", doc_id="a")
    await _mk(session, tmp_path, name="b.md", doc_id="b")

    live = 0
    peak = 0

    class SlowEmbedder(FakeEmbedder):
        def embed(self, texts):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            try:
                return super().embed(texts)
            finally:
                live -= 1

    svc = _svc(session, FakeVectorStore(), SlowEmbedder())
    await asyncio.gather(svc.index_document("a"), svc.index_document("b"))
    assert peak == 1
