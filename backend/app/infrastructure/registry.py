from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_api_key
from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.adapters.embedding.openai_compat_embed import (
    DEFAULT_OPENAI_EMBED_MODEL,
    OpenAICompatEmbedder,
)
from app.infrastructure.adapters.embedding.sentence_transformer import (
    DEFAULT_LOCAL_EMBED_MODEL,
    SentenceTransformerEmbedder,
    local_embed_available,
)
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.embedder_runtime import (
    EMBED_LEVEL_HASHING,
    EMBED_LEVEL_LOCAL,
    EMBED_LEVEL_OPENAI,
)
from app.infrastructure.persistence.models import MODEL_CONFIG_SINGLETON_ID, ModelConfig
from app.infrastructure.ports.embedding import Embedder
from app.infrastructure.ports.llm import LLMPort

# 显式声明 embedding 配置取值（spec §5 ModelConfig）
EMBEDDING_PROVIDER_OPENAI = "openai_compat"
EMBEDDING_PROVIDER_LOCAL = "sentence_transformers"
EMBEDDING_PROVIDER_HASHING = "hashing"


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


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding 配置的进程内快照（API Key 已解密，仅驻留内存）。

    ORM 对象绑在会话上，而 EmbedderRuntime 的生命周期跨越请求 —— 用它做快照，
    既避免会话泄漏，也让运行时的 factory 保持为纯函数。
    """

    revision: int = 0
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


def embedding_config(cfg: ModelConfig) -> EmbeddingConfig:
    """从 ModelConfig 抽出 embedding 相关配置；API Key 在此解密（spec §8.8）。

    解密只在构建快照时发生，快照本身不落库、不进日志。
    """
    key = decrypt_api_key(cfg.api_key_encrypted) if cfg.api_key_encrypted else None
    return EmbeddingConfig(
        revision=cfg.revision,
        provider=cfg.embedding_provider,
        model=cfg.embedding_model,
        base_url=cfg.base_url,
        api_key=key,
    )


def build_embedder(cfg: EmbeddingConfig, level: int) -> Embedder | None:
    """构建**指定级别**的向量化器；该级不可用时返回 None，由 EmbedderRuntime 降级。

    三级回退（spec §9 / ADR-0004）：
      0 = OpenAI 兼容 API  ·  1 = sentence-transformers 本地  ·  2 = HashingEmbed 哨兵

    这里刻意采用「精确级别」而非「该级及以下最优」语义：降级链的选择权归
    EmbedderRuntime，本函数只回答「第 N 级现在能不能用」。
    """
    if level == EMBED_LEVEL_OPENAI:
        if cfg.provider == EMBEDDING_PROVIDER_OPENAI and cfg.api_key:
            return OpenAICompatEmbedder(
                base_url=cfg.base_url or "",
                api_key=cfg.api_key,
                model=cfg.model or DEFAULT_OPENAI_EMBED_MODEL,
            )
        return None

    if level == EMBED_LEVEL_LOCAL:
        # 管理员可显式选 hashing 强制走哨兵；其余情形只要本地可用就用本地
        if cfg.provider != EMBEDDING_PROVIDER_HASHING and local_embed_available():
            return SentenceTransformerEmbedder(cfg.model or DEFAULT_LOCAL_EMBED_MODEL)
        return None

    if level == EMBED_LEVEL_HASHING:
        return HashingEmbed()

    return None


def make_embedder_factory(cfg: EmbeddingConfig):
    """把配置快照绑定成 EmbedderRuntime 需要的 factory(level) -> Embedder | None。"""
    return lambda level: build_embedder(cfg, level)
