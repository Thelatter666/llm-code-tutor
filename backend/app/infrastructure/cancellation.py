"""SSE 中断注册表（spec §8.1）。

**为什么中断信号是 per-call 的 `asyncio.Event`，而不是 provider 的方法**（B2 /
ADR-0002 的伴生结论）：`ProviderRegistry` 按 `ModelConfig.revision` 缓存适配器，
缓存的是**进程内单实例**，所有请求共享。若把 cancel 做成实例方法（如
`provider.cancel()`），一个学生点「停止」会掐断所有进行中的流。因此中断信号
必须按调用传入（`stream(cancel=...)`），注册表只负责按 `(conversation_id,
request_id)` 找到那一个 Event。

**该内存注册表依赖单 worker**（ADR-0002）。多 worker 下 `/stop` 可能打到另一个
进程，那个进程的内存表里根本没有对应的 Event，中断会静默失效。若将来改多
worker，本模块需与 per-`kb_id` 的 `asyncio.Lock` 一并替换为跨进程实现（如 Redis
发布订阅）。

生命周期：流开始 `create()` → 结束或异常在 `finally` 中 `discard()`。
未 discard 的键会一直留在内存里，故 `discard` 是强制的，不是可选的清理。
"""

import asyncio

_Key = tuple[str, str]


class CancellationRegistry:
    """`(conversation_id, request_id)` → `asyncio.Event`。"""

    def __init__(self) -> None:
        self._events: dict[_Key, asyncio.Event] = {}

    def create(self, conversation_id: str, request_id: str) -> asyncio.Event:
        """为一次请求登记新的中断信号。

        spec §8.1：同一会话发起新请求时，此前的进行中请求一律置位 —— 学生不点
        「停止」直接发下一条时，上一条必须立刻停，否则两条流会同时往同一个会话
        里追加内容。
        """
        self.cancel_conversation(conversation_id)
        event = asyncio.Event()
        self._events[(conversation_id, request_id)] = event
        return event

    def cancel(self, conversation_id: str, request_id: str) -> bool:
        """/stop 端点入口；返回是否真的拦到了一条进行中的流。"""
        event = self._events.get((conversation_id, request_id))
        if event is None:
            return False
        event.set()
        return True

    def cancel_conversation(self, conversation_id: str) -> int:
        """置位该会话的全部进行中流；返回置位条数。"""
        hit = 0
        for (conv_id, _rid), event in self._events.items():
            if conv_id == conversation_id:
                event.set()
                hit += 1
        return hit

    def discard(self, conversation_id: str, request_id: str) -> None:
        """流结束或异常后在 `finally` 中调用，防止内存泄漏。"""
        self._events.pop((conversation_id, request_id), None)

    def size(self) -> int:
        """当前登记数，供测试断言清理是否生效。"""
        return len(self._events)


_registry: CancellationRegistry | None = None


def get_cancellation_registry() -> CancellationRegistry:
    """进程级单例（单 worker 前提，ADR-0002）。"""
    global _registry
    if _registry is None:
        _registry = CancellationRegistry()
    return _registry


def reset_cancellation() -> None:
    """仅供测试：清空注册表。

    每个 asyncio 用例跑在独立事件循环里，跨用例复用同一个 Event 会绑到已关闭的
    循环上，因此测试必须能重置。
    """
    global _registry
    _registry = None
