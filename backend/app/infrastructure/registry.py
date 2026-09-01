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
from app.infrastructure.llm_runtime import LLM_LEVEL_MOCK, LLM_LEVEL_PRIMARY
from app.infrastructure.persistence.models import MODEL_CONFIG_SINGLETON_ID, ModelConfig
from app.infrastructure.ports.embedding import Embedder
from app.infrastructure.ports.llm import LLMParams, LLMPort

# 显式声明 embedding 配置取值（spec §5 ModelConfig）
EMBEDDING_PROVIDER_OPENAI = "openai_compat"
EMBEDDING_PROVIDER_LOCAL = "sentence_transformers"
EMBEDDING_PROVIDER_HASHING = "hashing"

# LLM 配置取值（spec §5 ModelConfig.provider，默认 mock）
LLM_PROVIDER_OPENAI = "openai_compat"
LLM_PROVIDER_MOCK = "mock"

# 哨兵模型名（ADR-0004）。服务层判定「配置是否指向哨兵」用本常量而非
# import HashingEmbed —— 适配器知识收口在 registry（spec §4.2 硬约束 2 / H-3）。
HASHING_EMBED_MODEL = HashingEmbed.model


def default_embedding_model(provider: str | None) -> str:
    """未显式配置模型时，各 provider 实际会用的模型（与 `build_embedder` 对齐）。

    清理批次 H-3：自 `model_config_service` 上移至本层 —— 旧模型名比对与一致性
    告警需要它，但它绑定的是具体适配器常量，服务层不该 import 适配器。
    """
    if provider == EMBEDDING_PROVIDER_OPENAI:
        return DEFAULT_OPENAI_EMBED_MODEL
    if provider == EMBEDDING_PROVIDER_HASHING:
        return HASHING_EMBED_MODEL
    return DEFAULT_LOCAL_EMBED_MODEL


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
        if cfg.provider == EMBEDDING_PROVIDER_HASHING or not local_embed_available():
            return None
        # cfg.model 是**该 provider 名下**的模型名。OpenAI 的模型名（如
        # text-embedding-3-small）喂给 sentence-transformers 会去 HuggingFace 拉一个
        # 根本不存在的 repo，于是「第一级失败 → 第二级也失败 → 直接掉到哨兵」。
        # provider 不是本地时，本地这一级只用自己的默认模型。
        if cfg.provider == EMBEDDING_PROVIDER_OPENAI:
            return SentenceTransformerEmbedder(DEFAULT_LOCAL_EMBED_MODEL)
        return SentenceTransformerEmbedder(cfg.model or DEFAULT_LOCAL_EMBED_MODEL)

    if level == EMBED_LEVEL_HASHING:
        return HashingEmbed()

    return None


def make_embedder_factory(cfg: EmbeddingConfig):
    """把配置快照绑定成 EmbedderRuntime 需要的 factory(level) -> Embedder | None。"""
    return lambda level: build_embedder(cfg, level)


@dataclass(frozen=True)
class LLMConfig:
    """LLM 配置的进程内快照（API Key 已解密，仅驻留内存）。

    与 `EmbeddingConfig` 同理：ORM 对象绑在会话上，而运行时跨越请求生命周期。
    """

    revision: int = 0
    provider: str = LLM_PROVIDER_MOCK
    model: str = "mock-1"
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 2048


def llm_config(cfg: ModelConfig) -> LLMConfig:
    """从 ModelConfig 抽出 LLM 相关配置；API Key 在此解密（spec §8.8）。"""
    key = decrypt_api_key(cfg.api_key_encrypted) if cfg.api_key_encrypted else None
    return LLMConfig(
        revision=cfg.revision,
        provider=cfg.provider or LLM_PROVIDER_MOCK,
        model=cfg.model or "mock-1",
        base_url=cfg.base_url,
        api_key=key,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        max_tokens=cfg.max_tokens,
    )


def build_llm(cfg: LLMConfig, level: int) -> LLMPort | None:
    """构建**指定级别**的 LLM 提供方；该级不可用返回 None，由 LLMRuntime 降级。

    降级链（M10 / spec §9）：
      0 = 配置首选（OpenAI 兼容，需 provider=openai_compat 且有 API Key）
      1 = Mock 兜底

    首选不可用时 level 0 直接给出 Mock —— 这正是 spec §9「无 API Key → 解析为
    MockProvider」的落点。它是否算降级由 `LLMRuntime.degraded` 依据配置期望值判断。
    """
    if level == LLM_LEVEL_PRIMARY:
        if cfg.provider == LLM_PROVIDER_OPENAI and cfg.api_key:
            return OpenAICompatProvider(
                base_url=cfg.base_url or "",
                api_key=cfg.api_key,
            )
        return MockLLMProvider()

    if level == LLM_LEVEL_MOCK:
        return MockLLMProvider()

    return None


def make_llm_factory(cfg: LLMConfig):
    """把配置快照绑定成 LLMRuntime 需要的 factory(level) -> LLMPort | None。"""
    return lambda level: build_llm(cfg, level)


def build_primary_llm(cfg: LLMConfig) -> LLMPort:
    """按配置构建**首选级**提供方（不经运行时降级链）。

    唯一公开入口是这里而非 `build_llm` + 级别编号：级别编号（PRIMARY/MOCK）是
    registry/runtime 的内部知识，服务层拿它做「只测首选级」属越级感知
    （P6 审阅 L-3 / 清理批次裁定 R2）。`/admin/model-config/test` 用本函数 ——
    坏配置不经降级链伪装成 ok=True；provider=openai_compat 无 key 时首选级
    本就返回 Mock（`build_llm` 的 §9 落点），而该组合在 PUT 保存时已被 4220 拒绝。
    """
    return build_llm(cfg, LLM_LEVEL_PRIMARY) or build_llm(cfg, LLM_LEVEL_MOCK)


def llm_params(cfg: LLMConfig) -> LLMParams:
    """把配置快照转成单次调用参数（spec §5 ModelConfig 的 model / temperature / …）。"""
    return LLMParams(
        model=cfg.model,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        max_tokens=cfg.max_tokens,
    )
