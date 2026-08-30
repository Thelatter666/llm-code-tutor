from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.adapters.embedding.openai_compat_embed import OpenAICompatEmbedder
from app.infrastructure.adapters.embedding.sentence_transformer import (
    SentenceTransformerEmbedder,
    local_embed_available,
)
from app.infrastructure.embedder_runtime import (
    EMBED_LEVEL_HASHING,
    EMBED_LEVEL_LOCAL,
    EMBED_LEVEL_OPENAI,
)
from app.infrastructure.registry import EmbeddingConfig, build_embedder


def _cfg(**kw) -> EmbeddingConfig:
    return EmbeddingConfig(**kw)


def test_no_embedding_config_uses_local_level_when_available():
    """默认（未配置）且本地可用 → 第二级生效，这是无 API Key 演示的主路径。"""
    assert build_embedder(_cfg(), EMBED_LEVEL_OPENAI) is None  # 未配置 openai → 该级不可用
    emb = build_embedder(_cfg(), EMBED_LEVEL_LOCAL)
    if local_embed_available():
        assert isinstance(emb, SentenceTransformerEmbedder)
    else:
        assert emb is None


def test_openai_config_with_key_uses_openai_level():
    cfg = _cfg(provider="openai_compat", model="text-embedding-3-small", api_key="sk-test-1234")
    assert isinstance(build_embedder(cfg, EMBED_LEVEL_OPENAI), OpenAICompatEmbedder)


def test_openai_config_without_key_skips_first_level():
    """无 API Key 时不该卡在第一级 —— 必须先落到本地，否则演示直接退化成哨兵。"""
    cfg = _cfg(provider="openai_compat", model="text-embedding-3-small")
    assert build_embedder(cfg, EMBED_LEVEL_OPENAI) is None
    emb = build_embedder(cfg, EMBED_LEVEL_LOCAL)
    if local_embed_available():
        assert isinstance(emb, SentenceTransformerEmbedder)


def test_hashing_provider_forces_sentinel():
    cfg = _cfg(provider="hashing")
    assert build_embedder(cfg, EMBED_LEVEL_OPENAI) is None
    assert build_embedder(cfg, EMBED_LEVEL_LOCAL) is None
    assert isinstance(build_embedder(cfg, EMBED_LEVEL_HASHING), HashingEmbed)


def test_hashing_level_is_always_available_as_last_resort():
    assert isinstance(build_embedder(_cfg(), EMBED_LEVEL_HASHING), HashingEmbed)


def test_level_beyond_last_is_none():
    assert build_embedder(_cfg(), EMBED_LEVEL_HASHING + 1) is None


def test_local_model_name_is_honoured():
    cfg = _cfg(provider="sentence_transformers", model="custom-model")
    emb = build_embedder(cfg, EMBED_LEVEL_LOCAL)
    if local_embed_available():
        assert emb.model == "custom-model"
