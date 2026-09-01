from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase


@pytest.mark.asyncio
async def test_three_tables_are_created(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    assert {"knowledge_bases", "documents", "chunks"} <= {r[0] for r in rows}


@pytest.mark.asyncio
async def test_document_exposes_indexing_progress(session):
    """spec §8.2：管理端轮询 chunk_indexed / chunk_total 展示索引进度。"""
    kb = KnowledgeBase(name="Python 基础", owner_id="u1")
    session.add(kb)
    await session.flush()
    doc = Document(kb_id=kb.id, title="第 1 讲", source_type="md", status="pending")
    session.add(doc)
    await session.commit()

    got = (await session.execute(select(Document))).scalar_one()
    assert got.status == "pending"
    assert got.chunk_indexed == 0 and got.chunk_total == 0


@pytest.mark.asyncio
async def test_chunk_carries_vector_reference_and_embed_model(session):
    """spec §8.7 步骤 4：Chunk.embed_model 记录实际索引所用模型。"""
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.flush()
    doc = Document(kb_id=kb.id, title="t", source_type="txt")
    session.add(doc)
    await session.flush()
    session.add(
        Chunk(
            document_id=doc.id,
            kb_id=kb.id,
            content="切片内容",
            ordinal=0,
            char_count=4,
            embed_model="paraphrase-multilingual-MiniLM-L12-v2",
            vector_id="vec-1",
        )
    )
    await session.commit()

    got = (await session.execute(select(Chunk))).scalar_one()
    assert got.vector_id == "vec-1"
    assert got.embed_model == "paraphrase-multilingual-MiniLM-L12-v2"


@pytest.mark.asyncio
async def test_timestamps_are_timezone_aware_utc(session):
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.commit()

    got = (await session.execute(select(KnowledgeBase))).scalar_one()
    assert isinstance(got.created_at, datetime)
    assert got.created_at.tzinfo is not None
    assert got.created_at.utcoffset() == UTC.utcoffset(None)


@pytest.mark.asyncio
async def test_knowledge_base_course_code_is_nullable(session):
    """CONTEXT.md「课程代码」：可空表示不限课程。"""
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.commit()
    assert (await session.execute(select(KnowledgeBase))).scalar_one().course_code is None
