import asyncio

import pytest

from app.infrastructure.concurrency import (
    index_slot,
    kb_lock,
    pending_lock_count,
    reset_concurrency,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_concurrency()
    yield
    reset_concurrency()


async def _hold(kb_id: str, entered: asyncio.Event, release: asyncio.Event, seen: list):
    async with kb_lock(kb_id) as lock:
        seen.append(lock)
        entered.set()
        await release.wait()


@pytest.mark.asyncio
async def test_same_kb_shares_one_lock():
    """同一 kb 的并发写必须争抢同一把锁（asyncio.Lock 不可重入，故用两个任务验证）。"""
    seen: list = []
    release = asyncio.Event()

    entered = asyncio.Event()
    first = asyncio.create_task(_hold("kb1", entered, release, seen))
    await entered.wait()

    entered2 = asyncio.Event()
    second = asyncio.create_task(_hold("kb1", entered2, release, seen))
    await asyncio.sleep(0)  # 让第二个任务跑到 acquire 处
    assert not entered2.is_set()  # 同一 kb → 被串行化

    release.set()
    await asyncio.gather(first, second)
    assert seen[0] is seen[1]


@pytest.mark.asyncio
async def test_different_kb_have_different_locks():
    seen: list = []
    release = asyncio.Event()

    entered1, entered2 = asyncio.Event(), asyncio.Event()
    t1 = asyncio.create_task(_hold("kb1", entered1, release, seen))
    t2 = asyncio.create_task(_hold("kb2", entered2, release, seen))
    await asyncio.wait_for(asyncio.gather(entered1.wait(), entered2.wait()), timeout=1)

    release.set()
    await asyncio.gather(t1, t2)
    assert seen[0] is not seen[1]


@pytest.mark.asyncio
async def test_lock_serializes_writes_for_same_kb():
    """CONTEXT.md「知识库锁」：索引 / 删除 / 重建 / GC 互斥。"""
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with kb_lock("kb1"):
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


@pytest.mark.asyncio
async def test_different_kb_run_concurrently():
    """不同 KB 之间不互斥 —— 否则批量上传会被完全串行化。"""
    live = 0
    peak = 0

    async def worker(kb: str) -> None:
        nonlocal live, peak
        async with kb_lock(kb):
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(worker("kb1"), worker("kb2"), worker("kb3"))
    assert peak == 3


@pytest.mark.asyncio
async def test_index_slot_allows_only_one_concurrent():
    """spec §3.2 权衡 14：索引全局并发上限 1。"""
    live = 0
    peak = 0

    async def worker() -> None:
        nonlocal live, peak
        async with index_slot():
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*[worker() for _ in range(4)])
    assert peak == 1


@pytest.mark.asyncio
async def test_lock_is_removed_after_release():
    """spec §8.2：锁对象懒创建并清理，否则 KB 多了会内存泄漏。"""
    async with kb_lock("kb1"):
        assert pending_lock_count() >= 1
    assert pending_lock_count() == 0


@pytest.mark.asyncio
async def test_locks_do_not_accumulate():
    for i in range(20):
        async with kb_lock(f"kb{i}"):
            pass
    assert pending_lock_count() == 0
