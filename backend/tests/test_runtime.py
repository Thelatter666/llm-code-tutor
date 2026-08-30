import pytest

from app.core.config import get_settings
from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import MODEL_CONFIG_SINGLETON_ID, ModelConfig
from app.infrastructure.registry import EmbeddingConfig
from app.infrastructure.runtime import (
    get_embedder_runtime,
    get_vector_store,
    refresh_embedder_config,
    reset_runtime,
    set_vector_store,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    reset_runtime()
    # 避免测试真的在 backend/data 下建出 Chroma 持久化目录
    monkeypatch.setattr(get_settings(), "chroma_persist_dir", str(tmp_path / "chroma"))
    yield
    reset_runtime()


def test_vector_store_is_a_process_singleton():
    assert get_vector_store() is get_vector_store()
    assert isinstance(get_vector_store(), ChromaVectorStore)


def test_vector_store_can_be_injected():
    class _Fake:
        pass

    fake = _Fake()
    set_vector_store(fake)
    assert get_vector_store() is fake


def test_embedder_runtime_is_a_process_singleton():
    assert get_embedder_runtime() is get_embedder_runtime()


@pytest.mark.asyncio
async def test_refresh_reports_change_only_on_new_revision(session):
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, revision=3, embedding_provider="hashing"))
    await session.commit()

    assert await refresh_embedder_config(session) is True
    assert await refresh_embedder_config(session) is False


@pytest.mark.asyncio
async def test_config_change_rebinds_factory_and_resets_level(session):
    """切换配置后必须重置降级级别，否则新配置永远不生效。"""
    session.add(ModelConfig(id=MODEL_CONFIG_SINGLETON_ID, revision=1, embedding_provider="hashing"))
    await session.commit()
    await refresh_embedder_config(session)

    runtime = get_embedder_runtime()
    await runtime.warmup()  # 落到哨兵（第 2 级）
    assert runtime.level == 2

    cfg = (await session.execute(_select_cfg())).scalar_one()
    cfg.revision = 2
    cfg.embedding_provider = "sentence_transformers"
    await session.commit()

    await refresh_embedder_config(session)
    assert runtime.level == 0
    assert runtime.is_ready is False  # 旧模型不代表新配置，必须重新预热


def _select_cfg():
    from sqlalchemy import select

    return select(ModelConfig)


def test_rebind_marks_runtime_not_ready():
    runtime = EmbedderRuntime(lambda level: None)
    assert runtime.snapshot()["ready"] is False


def test_default_chroma_dir_is_under_data(tmp_path, monkeypatch):
    from app.infrastructure.runtime import default_chroma_dir

    monkeypatch.setattr(get_settings(), "chroma_persist_dir", "data/chroma")
    assert default_chroma_dir().name == "chroma"
    assert default_chroma_dir().parts[-2] == "data"


def test_embedding_config_decrypts_key_only_in_memory(session):
    from app.core.crypto import encrypt_api_key
    from app.infrastructure.registry import embedding_config

    cfg = ModelConfig(
        id=MODEL_CONFIG_SINGLETON_ID,
        api_key_encrypted=encrypt_api_key("sk-secret-1234"),
        embedding_provider="openai_compat",
    )
    snapshot = embedding_config(cfg)
    assert snapshot.api_key == "sk-secret-1234"
    assert snapshot.revision == cfg.revision


def test_embedding_config_handles_missing_key():
    from app.infrastructure.registry import embedding_config

    assert embedding_config(ModelConfig()).api_key is None


def test_embedding_config_defaults_are_empty():
    snap = EmbeddingConfig()
    assert (snap.provider, snap.model, snap.api_key) == (None, None, None)
