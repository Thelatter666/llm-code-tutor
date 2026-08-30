"""向量库端口（CONTEXT.md：向量库 VectorStore）。

Chroma 的 IO 是同步阻塞的，因此端口方法声明为 `async`，由适配器内部统一
经 `run_in_threadpool` 卸载 —— 与服务层自己卸载相比，把卸载责任收在适配器内
可保证「任何实现都不会漏掉」这一条，代价是端口无法用于纯同步上下文。

`query()` 的 `kb_ids` 是**必填**参数：spec §3.2 权衡 4 明确了「Chroma 单集合 +
元数据过滤」的代价是每次检索必须带过滤条件，用签名把这个约束固定下来，
比靠调用方自觉更可靠。
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class VectorRecord:
    """一次写入的向量：业务侧的 Chunk.id 直接作为 vector_id。"""

    vector_id: str
    kb_id: str
    document_id: str
    embedding: list[float]
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    """一次检索命中。`score` 是**余弦相似度**（0–1，越大越相关），不是距离。"""

    vector_id: str
    score: float
    metadata: dict


@runtime_checkable
class VectorStore(Protocol):
    async def upsert(self, records: list[VectorRecord]) -> None: ...

    async def query(
        self, embedding: list[float], top_k: int, kb_ids: list[str]
    ) -> list[VectorHit]: ...

    async def delete_ids(self, vector_ids: list[str]) -> None: ...

    async def delete_by_kb(self, kb_id: str) -> None: ...

    async def list_ids(self, kb_id: str) -> list[str]: ...
