import pytest
from sqlalchemy import delete, select

from app.core.errors import ApiError
from app.domain.knowledge.status import ACTION_KB_DELETE, KB_READY, KB_REINDEXING
from app.infrastructure.persistence.models import (
    AuditLog,
    Chunk,
    Document,
    KnowledgeBase,
)
from app.services.knowledge_service import KnowledgeBaseService
from tests.fakes import ExplodingVectorStore, FakeVectorStore, RecordingVectorStore


def _svc(session, store) -> KnowledgeBaseService:
    return KnowledgeBaseService(session, vector_store=store)


async def _seed(session, store, *, kb_id="kb1", chunks=2, doc_id="d1"):
    kb = await _svc(session, store).create(
        name="Python 基础", course_code="CS101", owner_id="u1"
    )
    kb.id = kb_id
    doc = Document(id=doc_id, kb_id=kb_id, title="第 1 讲", source_type="md", status="ready")
    session.add(doc)
    await session.flush()
    for i in range(chunks):
        session.add(
            Chunk(
                id=f"c{i}",
                document_id=doc_id,
                kb_id=kb_id,
                content=f"内容{i}",
                ordinal=i,
                char_count=3,
                vector_id=f"v{i}",
            )
        )
    await session.commit()
    return kb, doc


@pytest.mark.asyncio
async def test_create_persists_knowledge_base(session):
    await _svc(session, FakeVectorStore()).create(
        name="Python 基础", description="讲义", course_code="CS101", owner_id="u1"
    )
    await session.commit()

    got = (await session.execute(select(KnowledgeBase))).scalar_one()
    assert got.name == "Python 基础"
    assert got.course_code == "CS101"
    assert got.status == KB_READY


@pytest.mark.asyncio
async def test_list_filters_by_course_code(session):
    await _svc(session, FakeVectorStore()).create(name="a", course_code="CS101", owner_id="u")
    await _svc(session, FakeVectorStore()).create(name="b", course_code="CS102", owner_id="u")
    await _svc(session, FakeVectorStore()).create(name="c", course_code=None, owner_id="u")
    await session.commit()

    assert [k.name for k in await _svc(session, FakeVectorStore()).list_bases("CS101")] == ["a"]
    # course_code 为空表示不限课程（spec §6.2）
    assert len(await _svc(session, FakeVectorStore()).list_bases(None)) == 3


@pytest.mark.asyncio
async def test_update_changes_name_and_course_code(session):
    kb, _ = await _seed(session, FakeVectorStore())
    updated = await _svc(session, FakeVectorStore()).update(
        kb.id, name="新名称", course_code="CS999"
    )
    await session.commit()
    assert updated.name == "新名称"
    assert updated.course_code == "CS999"


@pytest.mark.asyncio
async def test_update_unknown_kb_returns_4040(session):
    with pytest.raises(ApiError) as exc:
        await _svc(session, FakeVectorStore()).update("nope", name="x")
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_delete_removes_vectors_before_rows(session):
    """spec §8.6：删除顺序固定三步、不可颠倒。"""
    store = RecordingVectorStore()
    kb, _ = await _seed(session, store)

    await _svc(session, store).delete(kb.id, user_id="admin", request_id="rid")
    await session.commit()

    assert store.deleted_kbs == [kb.id]  # 1. 先删 Chroma 向量
    assert (await session.execute(select(Chunk))).scalars().all() == []  # 2. 再删 Chunk 行
    assert (await session.execute(select(Document))).scalars().all() == []  # 3. 再删 Document
    assert (await session.execute(select(KnowledgeBase))).scalars().all() == []


@pytest.mark.asyncio
async def test_delete_continues_when_vector_cleanup_fails(session):
    """spec §8.6：Chroma 删除失败仍继续删 DB，并落审计告警。"""
    store = ExplodingVectorStore()
    kb, _ = await _seed(session, store)

    await _svc(session, store).delete(kb.id, user_id="admin", request_id="rid")
    await session.commit()

    assert (await session.execute(select(KnowledgeBase))).scalars().all() == []
    row = (await session.execute(select(AuditLog).where(AuditLog.action == ACTION_KB_DELETE))).scalar_one()
    assert row.detail["vector_cleanup"] == "failed"


@pytest.mark.asyncio
async def test_delete_audits_success(session):
    store = RecordingVectorStore()
    kb, _ = await _seed(session, store)
    await _svc(session, store).delete(kb.id, user_id="admin", request_id="rid")
    await session.commit()

    row = (await session.execute(select(AuditLog).where(AuditLog.action == ACTION_KB_DELETE))).scalar_one()
    assert row.detail["vector_cleanup"] == "ok"
    assert row.request_id == "rid"
    assert row.user_id == "admin"


@pytest.mark.asyncio
async def test_delete_unknown_kb_returns_4040(session):
    with pytest.raises(ApiError) as exc:
        await _svc(session, FakeVectorStore()).delete("nope")
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_gc_removes_only_orphan_vectors(session):
    """CONTEXT.md「孤儿向量」：Chroma 中有、Chunk 表中无。"""
    store = FakeVectorStore(preloaded={"kb1": ["v0", "v1", "orphan1", "orphan2"]})
    kb, _ = await _seed(session, store, chunks=2)  # Chunk 行持有 v0 / v1

    result = await _svc(session, store).gc_orphan_vectors(kb.id)
    await session.commit()

    assert result["scanned"] == 4
    assert result["orphans"] == 2
    assert result["deleted"] == 2
    assert sorted(await store.list_ids("kb1")) == ["v0", "v1"]


@pytest.mark.asyncio
async def test_gc_is_noop_when_no_orphans(session):
    store = FakeVectorStore(preloaded={"kb1": ["v0", "v1"]})
    kb, _ = await _seed(session, store, chunks=2)

    result = await _svc(session, store).gc_orphan_vectors(kb.id)
    assert result["deleted"] == 0
    assert sorted(await store.list_ids("kb1")) == ["v0", "v1"]


@pytest.mark.asyncio
async def test_gc_does_not_touch_other_kb(session):
    store = FakeVectorStore(preloaded={"kb1": ["v0"], "kb2": ["other"]})
    kb, _ = await _seed(session, store, chunks=1)

    await _svc(session, store).gc_orphan_vectors(kb.id)
    assert await store.list_ids("kb2") == ["other"]


@pytest.mark.asyncio
async def test_set_status_is_persisted(session):
    kb, _ = await _seed(session, FakeVectorStore())
    await _svc(session, FakeVectorStore()).set_status(kb.id, KB_REINDEXING)
    await session.commit()

    assert (await session.execute(select(KnowledgeBase))).scalar_one().status == KB_REINDEXING


@pytest.mark.asyncio
async def test_documents_can_be_listed_and_filtered_by_status(session):
    kb, _ = await _seed(session, FakeVectorStore())
    session.add(Document(id="d2", kb_id=kb.id, title="第 2 讲", source_type="md", status="failed"))
    await session.commit()

    all_docs = await _svc(session, FakeVectorStore()).list_documents(kb.id)
    failed = await _svc(session, FakeVectorStore()).list_documents(kb.id, status="failed")
    assert len(all_docs) == 2
    assert [d.id for d in failed] == ["d2"]


@pytest.mark.asyncio
async def test_delete_document_removes_vectors_then_rows(session):
    store = RecordingVectorStore()
    _kb, doc = await _seed(session, store, chunks=2)

    await _svc(session, store).delete_document(doc.id, user_id="admin", request_id="rid")
    await session.commit()

    assert sorted(store.deleted_ids) == ["v0", "v1"]
    assert (await session.execute(select(Chunk))).scalars().all() == []
    assert (await session.execute(select(Document))).scalars().all() == []
    # 知识库本身必须保留
    assert (await session.execute(select(KnowledgeBase))).scalars().all()


@pytest.mark.asyncio
async def test_delete_document_continues_when_chroma_fails(session):
    store = ExplodingVectorStore()
    _kb, doc = await _seed(session, store, chunks=1)

    await _svc(session, store).delete_document(doc.id, user_id="admin", request_id="rid")
    await session.commit()

    assert (await session.execute(select(Document))).scalars().all() == []


@pytest.mark.asyncio
async def test_orphan_chunks_without_vector_id_are_skipped_in_cleanup(session):
    """Chunk 行可能没有 vector_id（索引中途失败），清理时不得因此报错。"""
    store = RecordingVectorStore()
    kb, doc = await _seed(session, store, chunks=0)
    session.add(
        Chunk(
            id="c-no-vec",
            document_id=doc.id,
            kb_id=kb.id,
            content="x",
            ordinal=0,
            char_count=1,
            vector_id=None,
        )
    )
    await session.commit()

    await _svc(session, store).delete_document(doc.id)
    await session.commit()
    assert store.deleted_ids == []
    assert (await session.execute(select(Chunk))).scalars().all() == []


@pytest.mark.asyncio
async def test_chunk_rows_are_deletable_in_bulk(session):
    """重建流程需要一次性清掉某 KB 的全部 Chunk 行。"""
    kb, _ = await _seed(session, FakeVectorStore(), chunks=3)
    await session.execute(delete(Chunk).where(Chunk.kb_id == kb.id))
    await session.commit()
    assert (await session.execute(select(Chunk))).scalars().all() == []
