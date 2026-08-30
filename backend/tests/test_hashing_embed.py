import math

from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.ports.embedding import Embedder


def _cos(x, y):
    return sum(i * j for i, j in zip(x, y))


def test_satisfies_embedder_port():
    assert isinstance(HashingEmbed(), Embedder)


def test_is_sentinel():
    """ADR-0004：哨兵标记是服务层强制 rag_hit=false 的唯一依据。"""
    assert HashingEmbed().is_sentinel is True


def test_embed_is_deterministic():
    emb = HashingEmbed()
    assert emb.embed(["闭包是什么"]) == emb.embed(["闭包是什么"])


def test_vectors_are_unit_length():
    emb = HashingEmbed()
    v = emb.embed(["列表推导式"])[0]
    assert len(v) == emb.dimension
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6


def test_lexical_overlap_outweighs_semantics():
    """哨兵无语义的判据：字面重合度压过语义相关度。

    对照组（2026-08-30 实测）：
      A「如何用 Python 实现快速排序？」
      B「怎样用 Python 写出快排代码？」      —— 语义相同，字面不同 → 0.3757
      C「如何用 Python 实现冒泡排序？」      —— 语义不同，字面雷同 → 0.8235
    哨兵把 C 排在 B 前面，正是 ADR-0004「不得注入 prompt」的实证依据。
    """
    emb = HashingEmbed()
    va, vb, vc = emb.embed(
        [
            "如何用 Python 实现快速排序？",
            "怎样用 Python 写出快排代码？",
            "如何用 Python 实现冒泡排序？",
        ]
    )
    assert _cos(va, vc) > _cos(va, vb)


def test_unrelated_texts_have_zero_overlap():
    emb = HashingEmbed()
    va, vb = emb.embed(["如何用 Python 实现快速排序？", "今天食堂的红烧肉味道不错。"])
    assert abs(_cos(va, vb)) < 1e-9


def test_empty_input_returns_empty_list():
    assert HashingEmbed().embed([]) == []


def test_whitespace_only_text_does_not_blow_up():
    v = HashingEmbed().embed(["   \n\t "])[0]
    assert len(v) == HashingEmbed().dimension
