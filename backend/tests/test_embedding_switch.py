import pytest
from sqlalchemy import select

from app.core.errors import ApiError
from app.domain.knowledge.status import DOC_READY, KB_READY, KB_REINDEXING
from app.infrastructure.adapters.embedding.sentence_transformer import (
    local_embed_available,
)
from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import (
    Chunk,
    Document,
    KnowledgeBase,
    ModelConfig,
)
from app.infrastructure.ports.vectorstore import VectorRecord
from app.infrastructure.runtime import (
    get_embedder_runtime,
    refresh_embedder_config,
    reset_runtime,
)
from app.services.indexing_service import IndexingService
from app.services.model_config_service import ModelConfigService
from app.services.rebuild_service import RebuildService
from app.services.retrieval_service import RetrievalService
from tests.fakes import BrokenEmbedder, ConstantEmbedder, FakeEmbedder, FakeVectorStore

OLD_MODEL = "old-model"
NEW_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def _runtime(embedder) -> EmbedderRuntime:
    return EmbedderRuntime(lambda level: embedder if level == 1 else None)


def _cfg_svc(session) -> ModelConfigService:
    return ModelConfigService(session)


async def _seed(session, *, chunks=1, kb_id="kb1", model=OLD_MODEL, with_text=None, tmp_path=None):
    session.add(
        KnowledgeBase(
            id=kb_id, name="kb", status=KB_READY, embed_provider="old", embed_model=model
        )
    )
    doc = Document(
        id="d1",
        kb_id=kb_id,
        title="第 1 讲",
        source_type="txt",
        status=DOC_READY,
        source_uri=str(with_text) if with_text else None,
    )
    session.add(doc)
    await session.flush()
    for i in range(chunks):
        session.add(
            Chunk(
                id=f"c{i}",
                document_id="d1",
                kb_id=kb_id,
                content=f"内容{i}",
                ordinal=i,
                char_count=3,
                embed_model=model,
                vector_id=f"v{i}",
            )
        )
    await session.commit()


@pytest.fixture(autouse=True)
def _clean_runtime():
    reset_runtime()
    yield
    reset_runtime()


@pytest.mark.asyncio
async def test_switching_with_existing_chunks_returns_409(session):
    """spec §8.7 步骤 2：已有切片 → 409 + need_rebuild。"""
    await _seed(session, chunks=2)

    with pytest.raises(ApiError) as exc:
        await _cfg_svc(session).update_embedding(
            provider="sentence_transformers", model=NEW_MODEL, confirm=False
        )
    assert exc.value.code == 4090
    assert exc.value.data["need_rebuild"] is True
    assert exc.value.data["knowledge_base_ids"] == ["kb1"]


@pytest.mark.asyncio
async def test_unconfirmed_switch_does_not_persist(session):
    await _seed(session, chunks=1)
    with pytest.raises(ApiError):
        await _cfg_svc(session).update_embedding(
            provider="sentence_transformers", model=NEW_MODEL, confirm=False
        )
    await session.commit()

    cfg = (await session.execute(select(ModelConfig))).scalar_one_or_none()
    assert cfg is None or cfg.embedding_model != NEW_MODEL


@pytest.mark.asyncio
async def test_confirmed_switch_persists_and_bumps_revision(session):
    """二次确认后保存配置，并把待重建的知识库清单一并返回。"""
    await _seed(session, chunks=1)
    result = await _cfg_svc(session).update_embedding(
        provider="sentence_transformers", model=NEW_MODEL, confirm=True
    )
    await session.commit()

    cfg = (await session.execute(select(ModelConfig))).scalar_one()
    assert cfg.embedding_model == NEW_MODEL
    assert cfg.embedding_provider == "sentence_transformers"
    assert cfg.revision > 1
    assert result["need_rebuild"] is True
    assert result["knowledge_base_ids"] == ["kb1"]


@pytest.mark.asyncio
async def test_switch_without_existing_chunks_succeeds(session):
    """空知识库无需重建 —— 要求确认会让首次配置变得莫名其妙。"""
    session.add(KnowledgeBase(id="kb1", name="kb", status=KB_READY))
    await session.commit()

    result = await _cfg_svc(session).update_embedding(
        provider="sentence_transformers", model=NEW_MODEL, confirm=False
    )
    await session.commit()

    assert result["need_rebuild"] is False
    cfg = (await session.execute(select(ModelConfig))).scalar_one()
    assert cfg.embedding_model == NEW_MODEL


@pytest.mark.asyncio
async def test_same_model_is_not_a_switch(session):
    """配置没变就不是切换 —— 即便已有切片也不该要求确认。"""
    await _seed(session, chunks=1, model=NEW_MODEL)
    session.add(
        ModelConfig(
            id="singleton",
            embedding_provider="sentence_transformers",
            embedding_model=NEW_MODEL,
            revision=2,
        )
    )
    await session.commit()

    result = await _cfg_svc(session).update_embedding(
        provider="sentence_transformers", model=NEW_MODEL, confirm=False
    )
    assert result["need_rebuild"] is False


@pytest.mark.asyncio
async def test_rebuild_reindexes_every_chunk_with_new_model(session, tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=3, with_text=source, tmp_path=tmp_path)

    store = FakeVectorStore()
    embedder = FakeEmbedder()
    await RebuildService(
        session, embedder=_runtime(embedder), vector_store=store
    ).rebuild("kb1")

    session.expunge_all()
    rows = (await session.execute(select(Chunk))).scalars().all()
    assert rows
    assert {r.embed_model for r in rows} == {"fake-1"}
    assert {r.vector_id for r in rows} == set(store.records)


@pytest.mark.asyncio
async def test_rebuild_sets_kb_reindexing_then_ready(session, tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=1, with_text=source, tmp_path=tmp_path)

    observed: list[str] = []

    class SpyEmbedder(FakeEmbedder):
        def embed(self, texts):
            observed.append("embedding")
            return super().embed(texts)

    await RebuildService(
        session, embedder=_runtime(SpyEmbedder()), vector_store=FakeVectorStore()
    ).rebuild("kb1")

    session.expunge_all()
    kb = (await session.execute(select(KnowledgeBase))).scalar_one()
    assert kb.status == KB_READY
    assert kb.embed_model == "fake-1"
    assert observed


@pytest.mark.asyncio
async def test_rebuild_marks_kb_reindexing_during_the_run(session, tmp_path):
    """spec §8.7 步骤 3：重建期间 KB 置 reindexing，检索返回 5032。"""
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=1, with_text=source, tmp_path=tmp_path)

    seen: list[str] = []

    class PeekingEmbedder(FakeEmbedder):
        def embed(self, texts):
            seen.append("busy")
            return super().embed(texts)

    await RebuildService(
        session, embedder=_runtime(PeekingEmbedder()), vector_store=FakeVectorStore()
    ).rebuild("kb1", on_status=lambda status: seen.append(status))

    assert KB_REINDEXING in seen


@pytest.mark.asyncio
async def test_rebuild_of_unknown_kb_returns_4040(session):
    from app.core.errors import ApiError

    with pytest.raises(ApiError) as exc:
        await RebuildService(
            session, embedder=_runtime(FakeEmbedder()), vector_store=FakeVectorStore()
        ).rebuild("nope")
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_startup_consistency_check_reports_mismatch(session):
    """spec §8.7 步骤 4：配置与索引不一致时告警（防手动改库或改 .env 绕过）。"""
    await _seed(session, chunks=1, model="hand-edited-model")
    session.add(
        ModelConfig(
            id="singleton",
            embedding_provider="sentence_transformers",
            embedding_model=NEW_MODEL,
            revision=2,
        )
    )
    await session.commit()

    warnings = await _cfg_svc(session).check_embedding_consistency()
    assert warnings and warnings[0]["kb_id"] == "kb1"
    assert warnings[0]["indexed_model"] == "hand-edited-model"


@pytest.mark.asyncio
async def test_no_false_positive_when_model_was_never_configured(session):
    """管理员从未显式配置 embedding 模型是常态，此时不得误报不一致。"""
    await _seed(session, chunks=1, model="paraphrase-multilingual-MiniLM-L12-v2")
    await session.commit()  # ModelConfig 行不存在 → embedding_model 为 NULL

    assert await _cfg_svc(session).check_embedding_consistency() == []


@pytest.mark.asyncio
async def test_expected_model_can_be_supplied_by_the_caller(session):
    """就绪后由调用方传入运行时实际生效的模型，比按配置推断更准。"""
    await _seed(session, chunks=1, model="hand-edited-model")
    await session.commit()

    warnings = await _cfg_svc(session).check_embedding_consistency("fake-1")
    assert warnings and warnings[0]["configured_model"] == "fake-1"


@pytest.mark.asyncio
async def test_no_warning_when_consistent(session):
    await _seed(session, chunks=1, model=NEW_MODEL)
    session.add(
        ModelConfig(
            id="singleton",
            embedding_provider="sentence_transformers",
            embedding_model=NEW_MODEL,
            revision=2,
        )
    )
    await session.commit()

    assert await _cfg_svc(session).check_embedding_consistency() == []


@pytest.mark.asyncio
async def test_config_change_rebinds_the_runtime(session):
    """切换后运行时的 factory 必须换掉，否则新配置永远不生效。"""
    await _seed(session, chunks=0)
    await refresh_embedder_config(session)
    first = get_embedder_runtime()

    await _cfg_svc(session).update_embedding(
        provider="sentence_transformers", model=NEW_MODEL, confirm=False
    )
    await session.commit()

    assert await refresh_embedder_config(session) is True
    assert get_embedder_runtime() is first  # 单例不变，但 factory 被 rebind
    assert first.level == 0


@pytest.mark.asyncio
async def test_rebuild_survives_a_dimension_change(session, tmp_path):
    """回归：切换后维度不同，重建必须仍能成功。

    Chroma 集合首次写入后维度即固定，删光记录也不重置 —— 不按维度分区集合时，
    这里会在 upsert 阶段抛
    `InvalidArgumentError: Collection expecting embedding with dimension of X, got Y`。
    """

    class Dim4Embedder(FakeEmbedder):
        name = "fake-4"
        model = "fake-4"

        def __init__(self):
            super().__init__(dimension=4)

    class Dim8Embedder(FakeEmbedder):
        name = "fake-8"
        model = "fake-8"

        def __init__(self):
            super().__init__(dimension=8)

    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=2, with_text=source, tmp_path=tmp_path)

    store = ChromaVectorStore(persist_dir=tmp_path / "chroma")
    await RebuildService(
        session, embedder=_runtime(Dim4Embedder()), vector_store=store
    ).rebuild("kb1")

    session.expunge_all()
    assert (await session.execute(select(Chunk))).scalars().all()

    await RebuildService(
        session, embedder=_runtime(Dim8Embedder()), vector_store=store
    ).rebuild("kb1")

    session.expunge_all()
    rows = (await session.execute(select(Chunk))).scalars().all()
    assert rows and {r.embed_model for r in rows} == {"fake-8"}


# --- 重建失败必须回滚配置（B1） ----------------------------------------------


async def _exploding_rebuild(kb_id):
    """模拟重建在逐份文档的错误边界之外失败（库写入失败、KB 状态写不回去等）。"""
    raise RuntimeError("重建中途数据库不可用")


async def _seed_switchable(session, *, store, chunks=2):
    """建一个「已用 old-model 索引过、向量库里也确有向量」的知识库。

    切片行与向量库的 vector_id 必须对齐 —— 检索要靠 Chunk 行把命中转成可溯源引用。
    """
    await _seed(session, chunks=chunks)
    session.add(
        ModelConfig(
            id="singleton",
            embedding_provider="sentence_transformers",
            embedding_model=OLD_MODEL,
            revision=2,
        )
    )
    await session.commit()
    for i in range(chunks):
        store.records[f"v{i}"] = VectorRecord(
            vector_id=f"v{i}",
            kb_id="kb1",
            document_id="d1",
            embedding=[1.0, 0.0, 0.0, 0.0],
            content=f"内容{i}",
        )
    return store


@pytest.mark.asyncio
async def test_failed_rebuild_rolls_back_the_embedding_config(session):
    """B1 必测 1：重建失败 → provider/model 回滚，revision 再自增一次。

    不回滚的话，配置指向新模型而切片还是旧维度，查询会去查空的
    `course_chunks_d{新维度}` 集合，静默零命中 —— 降级对学生端完全不可见。
    """
    await _seed_switchable(session, store=FakeVectorStore())
    before = (await session.execute(select(ModelConfig))).scalar_one().revision

    with pytest.raises(ApiError) as exc:
        await _cfg_svc(session).switch_embedding_with_rebuild(
            provider="hashing",
            model="hashing-256",
            confirm=True,
            rebuild=_exploding_rebuild,
        )

    assert exc.value.code == 5000
    assert "kb1" in exc.value.message
    assert exc.value.data["failed"] == ["kb1"]
    assert exc.value.data["rolled_back_to"] == {
        "provider": "sentence_transformers",
        "model": OLD_MODEL,
    }

    cfg = (await session.execute(select(ModelConfig))).scalar_one()
    assert cfg.embedding_provider == "sentence_transformers"
    assert cfg.embedding_model == OLD_MODEL
    assert cfg.revision == before + 2, "切换 +1、回滚 +1，保证运行时缓存失效"


@pytest.mark.asyncio
async def test_search_still_hits_after_a_rolled_back_switch(session):
    """B1 必测 2：回滚后「旧配置 + 旧维度向量」自洽，检索照常命中。

    这是回滚的意义所在 —— 宁可切换失败，也不能留下配置与向量维度错配的状态。
    """
    store = FakeVectorStore()
    await _seed_switchable(session, store=store)

    with pytest.raises(ApiError):
        await _cfg_svc(session).switch_embedding_with_rebuild(
            provider="hashing",
            model="hashing-256",
            confirm=True,
            rebuild=_exploding_rebuild,
        )

    # 回滚的意义就在这一条：配置与切片回到同一个模型，不再错配。
    # 不回滚的话这里会报出不一致 —— 那正是「新配置 + 旧维度向量」的静默不一致态。
    session.expunge_all()
    assert await _cfg_svc(session).check_embedding_consistency() == []

    session.expunge_all()
    runtime = EmbedderRuntime(
        lambda level: ConstantEmbedder(dimension=4) if level == 1 else None
    )
    await runtime.warmup()
    result = await RetrievalService(
        session, embedder=runtime, vector_store=store
    ).search("内容", kb_ids=["kb1"])

    assert result.rag_hit is True
    assert result.degraded is False
    assert result.citations


@pytest.mark.asyncio
async def test_a_rebuild_that_converted_nothing_counts_as_failed(session, tmp_path):
    """「全部文档索引失败」会被逐份文档的错误边界吞掉，rebuild() 不抛异常。

    此时库里一片不剩，配置却已指向新模型 —— 与 B1 是同一类静默不一致，
    因此按结果判定：进重建清单的知识库重建前必有切片，重建后为 0 即失败。
    """
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed_switchable(session, store=FakeVectorStore(), chunks=1)

    async def _all_documents_fail(kb_id):
        await RebuildService(
            session,
            embedder=_runtime(BrokenEmbedder()),
            vector_store=FakeVectorStore(),
            indexing=IndexingService(
                session,
                embedder=_runtime(BrokenEmbedder()),
                vector_store=FakeVectorStore(),
            ),
        ).rebuild(kb_id)

    with pytest.raises(ApiError) as exc:
        await _cfg_svc(session).switch_embedding_with_rebuild(
            provider="hashing",
            model="hashing-256",
            confirm=True,
            rebuild=_all_documents_fail,
        )
    assert exc.value.code == 5000
    assert exc.value.data["failed"] == ["kb1"]

    cfg = (await session.execute(select(ModelConfig))).scalar_one()
    assert cfg.embedding_model == OLD_MODEL


@pytest.mark.asyncio
async def test_successful_switch_reports_rebuilt_and_failed_lists(session, tmp_path):
    """成功路径照常返回 rebuilt / failed 清单（M1：区分两者）。"""
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=1, with_text=source, tmp_path=tmp_path)

    async def _rebuild(kb_id):
        await RebuildService(
            session,
            embedder=_runtime(FakeEmbedder()),
            vector_store=FakeVectorStore(),
            indexing=IndexingService(
                session, embedder=_runtime(FakeEmbedder()), vector_store=FakeVectorStore()
            ),
        ).rebuild(kb_id)

    result = await _cfg_svc(session).switch_embedding_with_rebuild(
        provider="hashing", model="hashing-256", confirm=True, rebuild=_rebuild
    )
    assert result["rebuilt"] == ["kb1"]
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_rebuild_uses_the_newly_configured_model(session, tmp_path):
    """回归：切到新模型后重建，切片上记的必须是新模型名。"""
    source = tmp_path / "a.txt"
    source.write_text("重建用的正文内容。" * 60, encoding="utf-8")
    await _seed(session, chunks=1, with_text=source, tmp_path=tmp_path)

    await _cfg_svc(session).update_embedding(
        provider="sentence_transformers", model=NEW_MODEL, confirm=True
    )
    await session.commit()
    await refresh_embedder_config(session)

    if not local_embed_available():
        pytest.skip("未安装 local-embed extras")

    await RebuildService(
        session, embedder=get_embedder_runtime(), vector_store=FakeVectorStore()
    ).rebuild("kb1")

    session.expunge_all()
    rows = (await session.execute(select(Chunk))).scalars().all()
    assert rows and rows[0].embed_model == NEW_MODEL
