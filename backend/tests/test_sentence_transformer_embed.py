import math
import threading

import pytest

from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.adapters.embedding.sentence_transformer import (
    DEFAULT_LOCAL_EMBED_MODEL,
    SentenceTransformerEmbedder,
    local_embed_available,
)
from app.infrastructure.ports.embedding import Embedder

pytestmark = pytest.mark.skipif(
    not local_embed_available(), reason="未安装 local-embed extras（make install-lite 后跳过）"
)


def _cos(x, y):
    return sum(i * j for i, j in zip(x, y))


def test_satisfies_embedder_port():
    assert isinstance(SentenceTransformerEmbedder(), Embedder)


def test_default_model_matches_spec():
    """spec §2 / §7.3：paraphrase-multilingual-MiniLM-L12-v2，384 维。"""
    assert DEFAULT_LOCAL_EMBED_MODEL == "paraphrase-multilingual-MiniLM-L12-v2"
    assert SentenceTransformerEmbedder().dimension == 384


def test_embed_is_normalized():
    v = SentenceTransformerEmbedder().embed(["列表推导式"])[0]
    assert len(v) == 384
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-5


def test_empty_input_returns_empty_list():
    assert SentenceTransformerEmbedder().embed([]) == []


def test_model_is_lazily_loaded_once():
    """单例懒加载：连续调用不得重复加载模型（实测加载 13–20 秒）。"""
    emb = SentenceTransformerEmbedder()
    assert emb._model is None
    emb.embed(["预热"])
    first = emb._model
    emb.embed(["第二次"])
    assert emb._model is first


def test_distinct_adapter_instances_share_the_loaded_model():
    """进程级单例：revision 变更会重建适配器实例，但模型不得跟着重新加载。"""
    a, b = SentenceTransformerEmbedder(), SentenceTransformerEmbedder()
    a.embed(["预热"])
    b.embed(["预热"])
    assert a._model is b._model


def test_concurrent_embed_shares_one_model_instance():
    """线程安全：10 个线程并发触发加载，模型实例必须唯一。"""
    emb = SentenceTransformerEmbedder()
    seen: list = []
    lock = threading.Lock()

    def work(i: int) -> None:
        emb.embed([f"第{i}段内容"])
        with lock:
            seen.append(emb._model)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 10
    assert all(m is seen[0] for m in seen)


def test_semantic_quality_regression():
    """检索质量回归：语义相近与语义无关必须被明显分开。

    实测基准（2026-08-30，Apple Silicon / CPU）：相近 ≈ 0.92，无关 ≈ 0.02。
    """
    emb = SentenceTransformerEmbedder()
    va, vb, vc = emb.embed(
        [
            "如何用 Python 实现快速排序？",
            "Python 里快速排序的代码要怎么写？",
            "今天食堂的红烧肉味道不错。",
        ]
    )
    near, far = _cos(va, vb), _cos(va, vc)
    assert near > 0.80, f"语义相近句相似度偏低：{near}"
    assert far < 0.20, f"语义无关句相似度偏高：{far}"
    assert near - far > 0.60


def test_paraphrase_without_lexical_overlap_still_matches():
    """与 HashingEmbed 的对照断言：真模型靠语义匹配，哨兵只靠字面重合。

    A「如何用 Python 实现快速排序？」
    B「怎样编写代码把一个序列按大小重新排列？」—— 语义等价，但字符 bigram 零重合。
    实测（2026-08-30）：真模型 0.5489，HashingEmbed 0.0。
    """
    a = "如何用 Python 实现快速排序？"
    b = "怎样编写代码把一个序列按大小重新排列？"

    va, vb = SentenceTransformerEmbedder().embed([a, b])
    ha, hb = HashingEmbed().embed([a, b])

    assert _cos(va, vb) > 0.45, f"零字面重合的改写句匹配度过低：{_cos(va, vb)}"
    assert abs(_cos(ha, hb)) < 0.05
