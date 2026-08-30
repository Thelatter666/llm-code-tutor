"""向量化器端口（CONTEXT.md：向量化器 Embedder）。

`embed()` 设计为**同步**方法：底层是 CPU 密集或同步 HTTP 的阻塞调用，
由调用方统一经 `run_in_threadpool` 卸载（阻塞卸载 BlockingOffload，ADR-0002）。
若端口声明为 async，就把「是否卸载」的决定权推给了适配器 —— 任何忘记卸载的
实现都会在单 worker 下冻结整个后端（spec §3.2 权衡 14）。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def is_sentinel(self) -> bool:
        """是否为哨兵级降级实现（CONTEXT.md「哨兵级降级」/ ADR-0004）。

        True 表示其产出不参与业务逻辑：检索结果一律不注入 prompt，
        强制 rag_hit=false + degraded=true。
        """
        ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
