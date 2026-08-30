"""哨兵级向量化器（ADR-0004）。

字符 bigram 哈希 + L2 归一化。向量**无语义**，检索结果近似随机。

本实现的定位是「保证调用链路可跑通」，而非「可用降级」：索引照常写入，
但检索阶段由服务层依据 `is_sentinel` 强制 `rag_hit=false` +
`degraded=true` + `fallback_reason=hashing_embed_no_semantics`，
命中结果一律不注入 prompt。

宁可少一个功能，不要一个错的功能 —— 若注入，模型会基于完全无关的片段
理直气壮地作答，这比知识库不可用更糟。
"""

import hashlib
import math

from app.infrastructure.ports.embedding import Embedder


class HashingEmbed:
    name = "hashing"
    model = "hashing-256"
    dimension = 256
    is_sentinel = True

    _NGRAM = 2
    _DIGEST_SIZE = 8

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        grams = self._grams(text)
        if not grams:
            return vec

        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=self._DIGEST_SIZE).digest()
            idx = int.from_bytes(digest[:2], "big") % self.dimension
            sign = 1.0 if digest[2] & 1 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    def _grams(self, text: str) -> list[str]:
        s = "".join(ch for ch in text if not ch.isspace())
        if len(s) < self._NGRAM:
            return [s] if s else []
        return [s[i : i + self._NGRAM] for i in range(len(s) - self._NGRAM + 1)]


__all__ = ["HashingEmbed"]
