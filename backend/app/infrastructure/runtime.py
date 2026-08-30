"""进程级运行时：向量库实例、向量化器运行时的单例访问与配置刷新。

单进程单 worker（ADR-0002）前提下，Chroma 的 `PersistentClient` 与已加载的
embedding 模型都必须是进程内单例 —— 前者多实例会损坏索引，后者重复加载每次
要 13–20 秒。

本模块同时是测试注入点：`set_vector_store()` / `set_embedder_runtime()` 让服务层
测试能换成 Fake，无需真的起 Chroma 或加载模型。
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.ports.vectorstore import VectorStore
from app.infrastructure.registry import (
    EmbeddingConfig,
    embedding_config,
    get_or_create_singleton,
    make_embedder_factory,
)

_vector_store: VectorStore | None = None
_embedder_runtime: EmbedderRuntime | None = None
_embedder_revision: int | None = None


def default_chroma_dir() -> Path:
    raw = Path(get_settings().chroma_persist_dir)
    if raw.is_absolute():
        return raw
    # 相对路径以 backend/ 为基准（uvicorn 的工作目录）
    return Path(__file__).resolve().parents[2] / raw


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = ChromaVectorStore(persist_dir=default_chroma_dir())
    return _vector_store


def set_vector_store(store: VectorStore | None) -> None:
    global _vector_store
    _vector_store = store


def get_embedder_runtime() -> EmbedderRuntime:
    """向量化器运行时单例。

    初次访问时尚无配置，factory 全部返回 None；待 `refresh_embedder_config()`
    载入配置后才会真正解析出向量化器。
    """
    global _embedder_runtime
    if _embedder_runtime is None:
        _embedder_runtime = EmbedderRuntime(make_embedder_factory(EmbeddingConfig()))
    return _embedder_runtime


def set_embedder_runtime(runtime: EmbedderRuntime | None) -> None:
    """替换运行时（测试注入，或配置变更后重建）。"""
    global _embedder_runtime, _embedder_revision
    _embedder_runtime = runtime
    _embedder_revision = None


async def refresh_embedder_config(session: AsyncSession) -> bool:
    """按 ModelConfig.revision 刷新向量化器配置；返回是否发生了变化。

    revision 变化（含 embedding 配置被切换）时，把降级级别重置回 0，
    让下一次 embed 从最高级重新解析 —— 否则刚切换过去的旧配置会被一直沿用。
    """
    global _embedder_revision

    cfg = embedding_config(await get_or_create_singleton(session))
    if _embedder_revision == cfg.revision:
        return False

    runtime = get_embedder_runtime()
    runtime.rebind(make_embedder_factory(cfg))
    _embedder_revision = cfg.revision
    return True


def reset_runtime() -> None:
    """仅供测试：清空全部进程级单例。"""
    global _vector_store, _embedder_runtime, _embedder_revision
    _vector_store = None
    _embedder_runtime = None
    _embedder_revision = None
