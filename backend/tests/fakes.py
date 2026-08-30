"""测试替身：服务层只依赖端口，因此这里给出 Fake 实现。

Fake 比 Mock 更合适：它们是**有状态的、行为正确的**端口实现，能让服务层测试
断言「发生了什么」而不是「调用了什么」。
"""

import itertools

from app.infrastructure.ports.vectorstore import VectorHit, VectorRecord


class FakeVectorStore:
    """内存向量库：记录调用顺序，供断言删除顺序等契约。"""

    def __init__(self, preloaded: dict[str, list[str]] | None = None):
        self.calls: list[str] = []
        self.records: dict[str, VectorRecord] = {}
        # 预置向量（用于孤儿向量 GC：Chroma 里有、Chunk 表里没有）
        for kb_id, ids in (preloaded or {}).items():
            for vid in ids:
                self.records[vid] = VectorRecord(
                    vector_id=vid,
                    kb_id=kb_id,
                    document_id="preloaded",
                    embedding=[0.1, 0.2],
                    content="预置",
                )

    async def upsert(self, records: list[VectorRecord]) -> None:
        self.calls.append(f"upsert:{len(records)}")
        for r in records:
            self.records[r.vector_id] = r

    async def query(self, embedding, top_k, kb_ids):
        self.calls.append(f"query:{','.join(kb_ids)}")
        hits = [
            VectorHit(
                vector_id=r.vector_id,
                score=_cosine(embedding, r.embedding),
                metadata={"kb_id": r.kb_id, "document_id": r.document_id},
            )
            for r in self.records.values()
            if r.kb_id in kb_ids
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    async def delete_ids(self, vector_ids) -> None:
        self.calls.append(f"delete_ids:{len(list(vector_ids))}")
        for vid in vector_ids:
            self.records.pop(vid, None)

    async def delete_by_kb(self, kb_id: str) -> None:
        self.calls.append(f"delete_by_kb:{kb_id}")
        for vid in [k for k, r in self.records.items() if r.kb_id == kb_id]:
            self.records.pop(vid, None)

    async def list_ids(self, kb_id: str) -> list[str]:
        return [k for k, r in self.records.items() if r.kb_id == kb_id]


class ExplodingVectorStore(FakeVectorStore):
    """向量库不可用：spec §8.6 要求此时仍继续删 DB 并落审计告警。"""

    def __init__(self):
        super().__init__()
        self._fail_next_delete = True

    async def delete_by_kb(self, kb_id: str) -> None:
        self.calls.append(f"delete_by_kb:{kb_id}")
        raise RuntimeError("Chroma 不可用")

    async def delete_ids(self, vector_ids) -> None:
        self.calls.append(f"delete_ids:{len(list(vector_ids))}")
        raise RuntimeError("Chroma 不可用")


class RecordingVectorStore(FakeVectorStore):
    """记录精确的删除 id，用于断言「先删向量再删行」。"""

    def __init__(self):
        super().__init__()
        self.deleted_ids: list[str] = []
        self.deleted_kbs: list[str] = []

    async def delete_ids(self, vector_ids) -> None:
        self.deleted_ids.extend(vector_ids)
        await super().delete_ids(vector_ids)

    async def delete_by_kb(self, kb_id: str) -> None:
        self.deleted_kbs.append(kb_id)
        await super().delete_by_kb(kb_id)


class FakeEmbedder:
    """确定性向量化器：把文本长度编码进向量，够用于区分不同切片。"""

    name = "fake"
    model = "fake-1"
    dimension = 4
    is_sentinel = False

    def __init__(self, dimension: int = 4):
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t, self.dimension) for t in texts]


class ConstantEmbedder(FakeEmbedder):
    """所有文本返回同一向量：相似度恒为 1。

    API 层测试关心的是链路接线，不是向量质量 —— 向量质量由
    test_retrieval_quality.py 用真模型覆盖。用常量向量可让阈值判定完全确定。
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


class SentinelEmbedder(FakeEmbedder):
    """哨兵级替身：ADR-0004 要求其产出不注入 prompt。"""

    name = "hashing"
    model = "hashing-256"
    is_sentinel = True


class BrokenEmbedder(FakeEmbedder):
    """调用即失败，用于验证索引失败路径。"""

    def embed(self, texts):
        raise RuntimeError("embedding 服务不可用")


def _fake_vector(text: str, dimension: int) -> list[float]:
    """按字符生成确定性向量并归一化，使长度相同的文本相似度可控。"""
    vec = [0.0] * dimension
    for i, ch in enumerate(text):
        vec[i % dimension] += ord(ch) % 97
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        vec[0] = 1.0
        return vec
    return [x / norm for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    size = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(size))


# 供测试按需生成唯一 id
_counter = itertools.count()


def next_id(prefix: str = "id") -> str:
    return f"{prefix}-{next(_counter)}"
