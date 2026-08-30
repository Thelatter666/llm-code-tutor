"""本地向量化器：sentence-transformers（spec §2 三级回退的第二级）。

**模型单例懒加载 + 线程安全**。实测 `paraphrase-multilingual-MiniLM-L12-v2`
在模型已缓存的情况下加载仍需 13–20 秒；若每次调用重新加载，索引 500 份文档
将退化到不可用。因此这里用双检锁保证：并发首次调用只加载一次，之后全部复用
同一实例。

同时该加载是**阻塞调用**，必须由调用方经 `run_in_threadpool` 卸载（ADR-0002）——
端口的 `embed()` 刻意声明为同步方法，正是为了把卸载责任留在调用方。
"""

import threading
from importlib.util import find_spec

DEFAULT_LOCAL_EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_LOCAL_EMBED_DIMENSION = 384

_BATCH_SIZE = 32

# 进程级模型缓存：key 为模型名。
# 适配器实例由 ProviderRegistry 按 revision 缓存，但 revision 变更会重建实例 ——
# 若模型随实例走，改一次配置就要重新加载一次 13–20 秒。缓存到模块级后，
# 无论多少个适配器实例、多少个线程，同一模型在进程内只加载一次。
_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def clear_model_cache() -> None:
    """仅供测试使用：释放已加载的模型。"""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


def local_embed_available() -> bool:
    """local-embed 是 optional extras，未装时必须能优雅判定（ADR-0004）。

    用 find_spec 而非 try/except ImportError：后者会真的把 torch 拉进内存，
    在「未安装」这条降级路径上白白付出一次失败的重量级导入。
    """
    return find_spec("sentence_transformers") is not None


def _load_shared_model(model_name: str):
    """按模型名共享已加载的模型（进程级单例）。"""
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    with _MODEL_CACHE_LOCK:
        if model_name not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer

            _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
    return _MODEL_CACHE[model_name]


class SentenceTransformerEmbedder:
    name = "sentence_transformers"
    is_sentinel = False

    def __init__(
        self,
        model: str = DEFAULT_LOCAL_EMBED_MODEL,
        dimension: int = DEFAULT_LOCAL_EMBED_DIMENSION,
    ):
        self._model_name = model
        self._dimension = dimension
        self._model = None
        self._load_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load(self):
        if self._model is None:
            with self._load_lock:
                # 双检：等锁的线程在此看到已加载的实例，避免重复加载
                if self._model is None:
                    self._model = _load_shared_model(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        # normalize_embeddings=True：使余弦相似度等价于点积，与 Chroma 的 cosine
        # 空间口径一致；show_progress_bar 在线程池里会污染日志，必须关闭
        vectors = model.encode(
            texts,
            batch_size=_BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]


__all__ = [
    "DEFAULT_LOCAL_EMBED_DIMENSION",
    "DEFAULT_LOCAL_EMBED_MODEL",
    "SentenceTransformerEmbedder",
    "clear_model_cache",
    "local_embed_available",
]
