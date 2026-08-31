import pytest
from sqlalchemy import select

from app.core.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.infrastructure.persistence.models import MODEL_CONFIG_SINGLETON_ID, ModelConfig
from app.infrastructure.registry import ProviderRegistry, get_or_create_singleton


def test_api_key_roundtrip():
    cipher = encrypt_api_key("sk-test-1234")
    assert "sk-test-1234" not in cipher
    assert decrypt_api_key(cipher) == "sk-test-1234"


def test_mask_api_key():
    assert mask_api_key("sk-test-1234") == "sk-****1234"
    assert mask_api_key(None) == ""


def test_mask_api_key_short_key_leaks_nothing():
    """L-2：≤7 位时「前 3 + 后 4」会重叠或全量暴露，短密钥不透露任何片段。"""
    assert mask_api_key("abcdef") == "****"
    assert mask_api_key("abcdefg") == "****"
    # 8 位起前 3 与后 4 不再重叠，恢复标准掩码形态
    assert mask_api_key("abcdefgh") == "abc****efgh"


@pytest.mark.asyncio
async def test_get_or_create_singleton_is_idempotent(session):
    """H2：单例必须唯一，否则第二行变孤儿、registry 可能取到旧行。"""
    a = await get_or_create_singleton(session)
    b = await get_or_create_singleton(session)
    await session.commit()

    assert a.id == b.id == MODEL_CONFIG_SINGLETON_ID
    assert len((await session.execute(select(ModelConfig))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_registry_caches_by_revision(session):
    cfg = await get_or_create_singleton(session)
    cfg.provider = "mock"
    cfg.revision = 7
    await session.commit()

    registry = ProviderRegistry()
    first = await registry.get_llm(session)
    assert await registry.get_llm(session) is first

    cfg.revision = 8
    await session.commit()
    assert await registry.get_llm(session) is not first


@pytest.mark.asyncio
async def test_registry_returns_mock_without_api_key(session):
    cfg = await get_or_create_singleton(session)
    cfg.provider = "openai_compat"
    cfg.api_key_encrypted = None
    await session.commit()

    assert (await ProviderRegistry().get_llm(session)).name == "mock"


@pytest.mark.asyncio
async def test_registry_returns_openai_compat_with_api_key(session):
    cfg = await get_or_create_singleton(session)
    cfg.provider = "openai_compat"
    cfg.base_url = "https://api.example.com/v1"
    cfg.api_key_encrypted = encrypt_api_key("sk-real-key-0001")
    await session.commit()

    provider = await ProviderRegistry().get_llm(session)
    assert provider.name == "openai_compat"
    assert provider._api_key == "sk-real-key-0001"


# --- 清理批次 H-3：适配器知识收口在 registry，服务层只拿语义 ---

def test_default_embedding_model_maps_each_provider():
    """C2 锁：三 provider 的默认模型映射（回退/改坏常量即死）。"""
    from app.infrastructure.registry import (
        EMBEDDING_PROVIDER_HASHING,
        EMBEDDING_PROVIDER_LOCAL,
        EMBEDDING_PROVIDER_OPENAI,
        HASHING_EMBED_MODEL,
        default_embedding_model,
    )

    assert default_embedding_model(EMBEDDING_PROVIDER_OPENAI) == "text-embedding-3-small"
    assert default_embedding_model(EMBEDDING_PROVIDER_HASHING) == "hashing-256"
    assert default_embedding_model(EMBEDDING_PROVIDER_LOCAL) == (
        "paraphrase-multilingual-MiniLM-L12-v2"
    )
    # 未配置/未知 provider → 本地默认（与 build_embedder 的 level 1 对齐）
    assert default_embedding_model(None) == "paraphrase-multilingual-MiniLM-L12-v2"
    assert HASHING_EMBED_MODEL == "hashing-256"


def test_build_primary_llm_never_uses_fallback_chain():
    """R2 锁：首选级公开入口对任何配置都给出提供方（openai 无 key → Mock 兜底）。"""
    from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
    from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
    from app.infrastructure.registry import LLMConfig, build_primary_llm

    assert isinstance(build_primary_llm(LLMConfig()), MockLLMProvider)
    assert isinstance(
        build_primary_llm(LLMConfig(provider="openai_compat", api_key="sk-1")),
        OpenAICompatProvider,
    )
    assert isinstance(
        build_primary_llm(LLMConfig(provider="openai_compat", api_key=None)),
        MockLLMProvider,
    )
