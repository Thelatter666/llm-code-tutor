"""SSE 中断注册表（spec §8.1 / ADR-0002）。

中断信号是 **per-call** 的 `asyncio.Event`，键为 `(conversation_id, request_id)`。
P0 已裁定绝不可做成 provider 的实例方法 —— 注册表缓存的是单实例，实例级 cancel
会让一个学生点「停止」掐断所有进行中的流（B2）。
"""

import asyncio

import pytest

from app.infrastructure.cancellation import (
    CancellationRegistry,
    get_cancellation_registry,
    reset_cancellation,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_cancellation()
    yield
    reset_cancellation()


async def _produce(event: asyncio.Event, total: int = 20) -> list[int]:
    """模拟生成循环：每次产出前先检查 Event（spec §8.1）。"""
    out: list[int] = []
    for i in range(total):
        if event.is_set():
            break
        out.append(i)
        await asyncio.sleep(0)
    return out


async def _produce_and_cancel(event: asyncio.Event, *, cancel_at: int, total: int = 20) -> list[int]:
    out: list[int] = []
    for i in range(total):
        if event.is_set():
            break
        out.append(i)
        if i == cancel_at:
            event.set()
        await asyncio.sleep(0)
    return out


def test_create_returns_an_unset_event():
    event = CancellationRegistry().create("c1", "r1")
    assert isinstance(event, asyncio.Event)
    assert event.is_set() is False


def test_different_request_ids_get_different_events():
    reg = CancellationRegistry()
    a = reg.create("c1", "r1")
    b = reg.create("c1", "r2")
    assert a is not b


def test_cancel_sets_only_the_target_event():
    """B2：取消一个请求不得影响同一会话的另一条流。"""
    reg = CancellationRegistry()
    a = reg.create("c1", "r1")
    b = reg.create("c1", "r2")

    assert reg.cancel("c1", "r1") is True
    assert a.is_set() is True
    assert b.is_set() is False


def test_cancel_unknown_key_returns_false():
    """/stop 打到一个已结束的流上应当被识别为「没拦到」，而不是静默成功。"""
    reg = CancellationRegistry()
    assert reg.cancel("nope", "nope") is False


def test_events_in_different_conversations_are_isolated():
    reg = CancellationRegistry()
    a = reg.create("c1", "r1")
    b = reg.create("c2", "r1")
    reg.cancel("c1", "r1")
    assert a.is_set() and not b.is_set()


@pytest.mark.asyncio
async def test_new_request_in_same_conversation_cancels_the_previous_one():
    """spec §8.1：/stop 端点与「同一会话发起新请求」两种情形均置位。

    前端允许学生不点停止直接发下一条，此时上一条必须立刻停 —— 否则两条流会
    同时往同一个会话里追加内容。
    """
    reg = CancellationRegistry()
    first = reg.create("c1", "r1")
    second = reg.create("c1", "r2")

    assert first.is_set() is True
    assert second.is_set() is False


@pytest.mark.asyncio
async def test_new_request_in_another_conversation_does_not_cancel():
    reg = CancellationRegistry()
    mine = reg.create("c1", "r1")
    reg.create("c2", "r1")
    assert mine.is_set() is False


@pytest.mark.asyncio
async def test_cancel_conversation_reports_how_many_were_cancelled():
    reg = CancellationRegistry()
    reg.create("c1", "r1")
    reg.create("c1", "r2")
    reg.create("c2", "r1")

    assert reg.cancel_conversation("c1") == 2


@pytest.mark.asyncio
async def test_discard_removes_the_key():
    reg = CancellationRegistry()
    reg.create("c1", "r1")
    assert reg.size() == 1

    reg.discard("c1", "r1")
    assert reg.size() == 0
    assert reg.cancel("c1", "r1") is False


def test_discard_is_idempotent():
    reg = CancellationRegistry()
    reg.discard("c1", "r1")
    reg.discard("c1", "r1")


@pytest.mark.asyncio
async def test_generation_stops_right_after_the_event_is_set():
    reg = CancellationRegistry()
    event = reg.create("c1", "r1")
    produced = await _produce_and_cancel(event, cancel_at=2)
    assert produced == [0, 1, 2]


@pytest.mark.asyncio
async def test_event_set_before_start_produces_nothing():
    reg = CancellationRegistry()
    event = reg.create("c1", "r1")
    reg.cancel("c1", "r1")
    assert await _produce(event) == []


@pytest.mark.asyncio
async def test_two_concurrent_streams_in_different_conversations_are_isolated():
    """B2 并发回归（注册表层）：两名学生同时流式作答，取消一个不影响另一个。

    这是「实例级 cancel」缺陷最直接的探针 —— 若 cancel 挂在 adapter 实例上，
    或注册表按 conversation_id 单键存储，这里就会失败。

    注意：同一会话内的第二条流按 spec §8.1 会主动掐断第一条（见
    `test_new_request_in_same_conversation_cancels_the_previous_one`），
    因此「互不影响」只在跨会话场景下成立。
    """
    reg = CancellationRegistry()
    event_a = reg.create("c1", "r1")
    event_b = reg.create("c2", "r1")

    task_a = asyncio.create_task(_produce_and_cancel(event_a, cancel_at=1))
    task_b = asyncio.create_task(_produce(event_b))

    out_a, out_b = await asyncio.gather(task_a, task_b)

    assert out_a == [0, 1]
    assert len(out_b) == 20


@pytest.mark.asyncio
async def test_module_level_registry_is_a_singleton():
    assert get_cancellation_registry() is get_cancellation_registry()


@pytest.mark.asyncio
async def test_reset_clears_every_registration():
    get_cancellation_registry().create("c1", "r1")
    reset_cancellation()
    assert get_cancellation_registry().size() == 0
