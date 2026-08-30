"""并发控制：知识库锁与索引并发上限（CONTEXT.md「知识库锁」「执行队列上限」）。

- **per-`kb_id` 的 `asyncio.Lock`**：保护索引 / 删除 / 重建 / GC。**检索不持锁**
  （spec §3.2 权衡 16）—— 让最常演示的检索路径排队得不偿失，允许读到中间态。
- **索引全局并发上限 1**（spec §3.2 权衡 14）：embedding 推理是 CPU 密集的，
  并发跑只会互相拖慢，不如排队。

锁对象按 `kb_id` 懒创建并在释放后清理，防止知识库数量增长导致内存泄漏
（spec §8.2）。以上内存结构**依赖单进程前提**（ADR-0002）；若将来改多 worker，
本模块与 SSE 中断注册表需一并替换为跨进程实现。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import get_settings

_locks: dict[str, asyncio.Lock] = {}
# 引用计数：锁在最后一个持有者释放后移除
_refcounts: dict[str, int] = {}
_index_semaphore: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _index_semaphore
    if _index_semaphore is None:
        _index_semaphore = asyncio.Semaphore(get_settings().index_concurrency)
    return _index_semaphore


@asynccontextmanager
async def kb_lock(kb_id: str) -> AsyncIterator[asyncio.Lock]:
    """获取（必要时创建）某个知识库的写锁。"""
    lock = _locks.get(kb_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[kb_id] = lock
        _refcounts[kb_id] = 0
    _refcounts[kb_id] += 1
    try:
        async with lock:
            yield lock
    finally:
        _release(kb_id)


def _release(kb_id: str) -> None:
    remaining = _refcounts.get(kb_id, 0) - 1
    if remaining > 0:
        _refcounts[kb_id] = remaining
        return
    _locks.pop(kb_id, None)
    _refcounts.pop(kb_id, None)


@asynccontextmanager
async def index_slot() -> AsyncIterator[None]:
    """全局索引并发位；超限时排队等待（索引任务本身在后台，无需 429）。"""
    async with _semaphore():
        yield


def pending_lock_count() -> int:
    """当前持有的锁数量，供测试断言清理是否生效。"""
    return len(_locks)


def reset_concurrency() -> None:
    """仅供测试：清空全部锁与信号量。

    每个 asyncio 用例跑在独立的事件循环里，跨用例复用同一个 Lock 会绑到已关闭
    的循环上，因此测试必须能重置。
    """
    global _index_semaphore
    _locks.clear()
    _refcounts.clear()
    _index_semaphore = None
