"""LLM 各级可用性判定（M10 的解析期回退）。

与 P1 的 `test_embedder_resolution.py` 同构：只验 `build_llm` 按配置与级别给出
正确的提供方，不涉及降级时序（那归 `test_llm_runtime.py`）。
"""

import pytest

from app.core.crypto import encrypt_api_key
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.llm_runtime import LLM_LEVEL_MOCK, LLM_LEVEL_PRIMARY, LLM_LEVELS
from app.infrastructure.persistence.models import ModelConfig
from app.infrastructure.registry import LLMConfig, build_llm, llm_config, llm_params
from app.infrastructure.ports.llm import LLMParams


def _cfg(**kw) -> LLMConfig:
    base = {"provider": "mock", "model": "mock-1"}
    base.update(kw)
    return LLMConfig(**base)


def test_openai_compat_is_built_when_key_present():
    provider = build_llm(
        _cfg(provider="openai_compat", base_url="https://api.example.com/v1", api_key="sk-1"),
        LLM_LEVEL_PRIMARY,
    )
    assert isinstance(provider, OpenAICompatProvider)


def test_mock_is_built_at_primary_without_api_key():
    """spec §9：无 API Key → 解析为 MockProvider。"""
    provider = build_llm(_cfg(provider="openai_compat", api_key=None), LLM_LEVEL_PRIMARY)
    assert isinstance(provider, MockLLMProvider)


def test_level_one_is_always_mock():
    """兜底级恒为 Mock —— 无 API Key 时它是唯一能跑通全链路的提供方。"""
    assert isinstance(build_llm(_cfg(), LLM_LEVEL_MOCK), MockLLMProvider)
    assert isinstance(build_llm(_cfg(provider="openai_compat", api_key="sk-1"), LLM_LEVEL_MOCK), MockLLMProvider)


def test_unknown_level_yields_none():
    assert build_llm(_cfg(), LLM_LEVELS) is None


def test_llm_config_decrypts_api_key():
    """spec §8.8：密钥只在构建快照时解密，快照本身不落库、不进日志。"""
    cfg = ModelConfig(provider="openai_compat", api_key_encrypted=encrypt_api_key("sk-secret-9"))
    assert llm_config(cfg).api_key == "sk-secret-9"


def test_llm_config_defaults_to_mock_without_provider():
    assert llm_config(ModelConfig(provider=None)).provider == "mock"


def test_llm_params_carries_sampling_settings():
    cfg = LLMConfig(model="gpt-x", temperature=0.2, top_p=0.9, max_tokens=512)
    params = llm_params(cfg)
    assert isinstance(params, LLMParams)
    assert (params.model, params.temperature, params.top_p, params.max_tokens) == (
        "gpt-x",
        0.2,
        0.9,
        512,
    )


@pytest.mark.asyncio
async def test_refresh_llm_config_rebinds_on_revision_change(session):
    """spec §4.2 硬约束 4：配置热生效 —— revision 一变就 rebind，不重启。

    这里只验刷新时序，**不发真实网络请求**（真去连 OpenAI 兼容端点会让用例
    依赖外网；运行期降级由 `test_llm_runtime.py` 用替身覆盖）。
    """
    from app.infrastructure.runtime import get_llm_runtime, refresh_llm_config, reset_runtime

    reset_runtime()
    try:
        cfg = await _singleton(session)
        cfg.revision = 3
        await session.commit()
        assert await refresh_llm_config(session) is True
        # revision 未变 → 不重复 rebind，否则每次请求都会重建 provider
        assert await refresh_llm_config(session) is False

        runtime = get_llm_runtime()
        runtime._adopt(LLM_LEVEL_MOCK, MockLLMProvider())
        cfg.revision = 4
        await session.commit()

        assert await refresh_llm_config(session) is True
        assert runtime.level == LLM_LEVEL_PRIMARY, "rebind 必须把降级级别重置回首选"
    finally:
        reset_runtime()


async def _singleton(session):
    from app.infrastructure.registry import get_or_create_singleton

    cfg = await get_or_create_singleton(session)
    await session.commit()
    return cfg
