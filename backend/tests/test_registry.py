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
