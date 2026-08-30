"""检索装配规则（spec §7.2 步骤 2–5），零 IO、纯函数。

命中对象是 `dict`，键为 `chunk_id` / `document_id` / `score`。这里刻意不定义
数据类：命中来自 VectorStore、要落 Citation、还要喂给 prompt 模板，用 dict
可免去三层之间的转换。
"""

from typing import Any

# --- 相关度阈值（CONTEXT.md「相关度阈值」） ---
# spec §3.2 权衡 8：默认值按 embedding 模型分别给出。余弦相似度的绝对值分布
# 随模型而异，硬编码单一默认值会让某些模型几乎全命中或几乎全丢弃。
DEFAULT_THRESHOLD_OPENAI = 0.25
DEFAULT_THRESHOLD_MINILM = 0.35
DEFAULT_THRESHOLD_OTHER = 0.30

# --- 相对截断（CONTEXT.md「相对截断」） ---
# 与「相关度阈值」互补：前者绑定模型，后者跨模型可比。
RELATIVE_TRUNCATION_MARGIN = 0.15

# 余弦相似度来自浮点运算，0.90 - 0.75 实际得到 0.15000000000000002。
# 不加容差的话「分差恰好 0.15」会被判为超过阈值而丢弃，与 spec 的表述相反。
_FLOAT_TOLERANCE = 1e-9

# --- 多样性截取（CONTEXT.md「多样性截取」） ---
MAX_CHUNKS_PER_DOCUMENT = 3

_THRESHOLD_BY_PROVIDER = {
    "openai_compat": DEFAULT_THRESHOLD_OPENAI,
    "sentence_transformers": DEFAULT_THRESHOLD_MINILM,
}
_MINILM_MARKER = "minilm"



def default_score_threshold(provider: str | None, model: str | None) -> float:
    """按 embedding 模型给出默认相关度阈值（M1）。

    `ModelConfig.score_threshold` 为 None 时走这里，表示「用按模型的默认值」。
    """
    if provider in _THRESHOLD_BY_PROVIDER:
        return _THRESHOLD_BY_PROVIDER[provider]
    # MiniLM 系列模型名形如 paraphrase-multilingual-MiniLM-L12-v2，大小写不定
    if model and _MINILM_MARKER in model.lower():
        return DEFAULT_THRESHOLD_MINILM
    return DEFAULT_THRESHOLD_OTHER


def resolve_score_threshold(
    configured: float | None, provider: str | None, model: str | None
) -> float:
    """管理员显式配置优先；未配置（None）时用按模型的默认值。"""
    if configured is not None:
        return configured
    return default_score_threshold(provider, model)


def apply_score_threshold[T: dict[str, Any]](hits: list[T], threshold: float) -> list[T]:
    """spec §7.2 步骤 2：相关度低于阈值的命中直接丢弃。"""
    return [h for h in hits if h["score"] >= threshold]


def apply_relative_truncation[T: dict[str, Any]](
    hits: list[T], margin: float = RELATIVE_TRUNCATION_MARGIN
) -> list[T]:
    """spec §7.2 步骤 3：与最佳命中分差 > margin 的命中一律丢弃。

    命中须已按 score 降序排列（Chroma 的返回即为此顺序）。
    """
    if not hits:
        return []
    best = max(h["score"] for h in hits)
    return [h for h in hits if best - h["score"] <= margin + _FLOAT_TOLERANCE]


def apply_diversity_truncation[T: dict[str, Any]](
    hits: list[T], max_per_document: int = MAX_CHUNKS_PER_DOCUMENT
) -> list[T]:
    """spec §7.2 步骤 4：单文档最多采纳 max_per_document 个切片。

    防止长文档霸占上下文。命中须已按 score 降序排列 —— 保留的是每个文档里
    分数最高的几片，且不改变整体顺序。
    """
    per_document: dict[str, int] = {}
    kept: list[T] = []
    for hit in hits:
        doc = hit["document_id"]
        used = per_document.get(doc, 0)
        if used >= max_per_document:
            continue
        per_document[doc] = used + 1
        kept.append(hit)
    return kept


def number_chunks[T: dict[str, Any]](hits: list[T]) -> list[tuple[int, T]]:
    """spec §7.2 步骤 5：片段编号 [1][2][3]，供模型内联引用。"""
    return list(enumerate(hits, start=1))
