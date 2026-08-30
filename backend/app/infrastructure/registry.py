from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_api_key
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.persistence.models import MODEL_CONFIG_SINGLETON_ID, ModelConfig
from app.infrastructure.ports.llm import LLMPort


async def get_or_create_singleton(session: AsyncSession) -> ModelConfig:
    """ModelConfig 为单例记录（spec §5）。

    统一走本函数取配置，避免「查不到就 insert」产生第二行孤儿配置。
    """
    cfg = (await session.execute(select(ModelConfig).limit(1))).scalar_one_or_none()
    if cfg is None:
        cfg = ModelConfig(id=MODEL_CONFIG_SINGLETON_ID)
        session.add(cfg)
        await session.flush()
    return cfg


class ProviderRegistry:
    """依据 ModelConfig.revision 解析并缓存 LLM 适配器。

    缓存位于进程内存，依赖单 worker（ADR-0002）。
    适配器实例被所有请求共享 —— 因此**任何 per-request 状态都不得存放在适配器实例上**，
    中断信号必须经 stream(cancel=...) 按调用传入（B2）。
    """

    def __init__(self) -> None:
        self._cache: LLMPort | None = None
        self._revision: int | None = None

    async def get_llm(self, session: AsyncSession) -> LLMPort:
        cfg = await get_or_create_singleton(session)
        if self._cache is not None and self._revision == cfg.revision:
            return self._cache

        self._cache = self._build(cfg)
        self._revision = cfg.revision
        return self._cache

    def _build(self, cfg: ModelConfig) -> LLMPort:
        if cfg.provider == "openai_compat" and cfg.api_key_encrypted:
            return OpenAICompatProvider(
                base_url=cfg.base_url or "",
                api_key=decrypt_api_key(cfg.api_key_encrypted),
            )
        return MockLLMProvider()
