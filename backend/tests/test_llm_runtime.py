"""LLM 降级链（M10 / spec §9）。"""

import asyncio

import pytest

from app.core.errors import ApiError
from app.infrastructure.llm_runtime import (
    FALLBACK_TO_MOCK,
    LLM_LEVEL_MOCK,
    LLM_LEVEL_PRIMARY,
    LLMRuntime,
)
from app.infrastructure.ports.llm import (
    ChatMessage,
    Completion,
    LLMParams,
    TextDelta,
    Usage,
)

PARAMS = LLMParams(model="m")
MESSAGES = [ChatMessage("user", "什么是闭包")]


class FakeProvider:
    """有状态、行为正确的替身：能控制「第几个元素抛错」，以覆盖流中途失败。"""

    def __init__(self, name="fake", *, fail_at=None, chunks=("a", "b", "c")):
        self._name = name
        self._fail_at = fail_at
        self._chunks = chunks
        self.stream_calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def stream(self, messages, params, *, cancel=None):
        self.stream_calls += 1
        for i, ch in enumerate(self._chunks):
            if self._fail_at is not None and i == self._fail_at:
                raise RuntimeError("上游中断")
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
            await asyncio.sleep(0)
        if self._fail_at is not None and self._fail_at >= len(self._chunks):
            raise RuntimeError("上游中断")
        yield Usage(1, len(self._chunks), 1 + len(self._chunks), estimated=self._name == "mock")

    async def complete(self, messages, params):
        if self._fail_at is not None:
            raise RuntimeError("上游中断")
        text = "".join(self._chunks)
        return Completion(text=text, usage=Usage(1, len(text), 1 + len(text)))


class ExplodingProvider(FakeProvider):
    """第一个元素就失败 —— 可被降级。"""

    def __init__(self, name="openai_compat"):
        super().__init__(name, fail_at=0)


class EmptyProvider(FakeProvider):
    """一个元素都不产出 —— 空流不算失败，不得触发降级。"""

    async def stream(self, messages, params, *, cancel=None):
        self.stream_calls += 1
        # 仅为使其成为异步生成器：空流不算失败，不得触发降级
        if False:  # pragma: no cover
            yield


def _runtime(levels: dict, expected: str):
    calls: list[int] = []

    def factory(level):
        calls.append(level)
        return levels.get(level)

    runtime = LLMRuntime(factory, expected=expected)
    return runtime, calls


@pytest.mark.asyncio
async def test_primary_available_means_not_degraded():
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: FakeProvider("openai_compat")}, "openai_compat")
    chunks = [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert runtime.current.name == "openai_compat"
    assert runtime.degraded is False
    assert runtime.fallback_reason is None
    assert len([c for c in chunks if isinstance(c, TextDelta)]) == 3


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_mock():
    """M10 / spec §9：调用失败 → 降级到下一 Provider。"""
    runtime, _ = _runtime(
        {LLM_LEVEL_PRIMARY: ExplodingProvider(), LLM_LEVEL_MOCK: FakeProvider("mock")},
        "openai_compat",
    )
    chunks = [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert runtime.current.name == "mock"
    assert runtime.degraded is True
    assert runtime.fallback_reason == FALLBACK_TO_MOCK
    assert len([c for c in chunks if isinstance(c, TextDelta)]) == 3


@pytest.mark.asyncio
async def test_fallback_level_is_remembered():
    """降级后记住级别：下一次调用不得再从首选重新试错。"""
    primary = ExplodingProvider()
    runtime, calls = _runtime(
        {LLM_LEVEL_PRIMARY: primary, LLM_LEVEL_MOCK: FakeProvider("mock")}, "openai_compat"
    )
    [c async for c in runtime.stream(MESSAGES, PARAMS)]
    [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert calls.count(LLM_LEVEL_PRIMARY) == 1
    assert primary.stream_calls == 1


@pytest.mark.asyncio
async def test_all_levels_fail_raises_5021():
    """spec §9：全部失败返回 5021。"""
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: ExplodingProvider(), LLM_LEVEL_MOCK: ExplodingProvider("mock")}, "openai_compat")
    with pytest.raises(ApiError) as exc:
        [c async for c in runtime.stream(MESSAGES, PARAMS)]
    assert exc.value.code == 5021


@pytest.mark.asyncio
async def test_no_api_key_with_mock_config_is_not_degraded():
    """spec §9「无 API Key → 解析为 MockProvider」是既定路径，不是降级。

    否则演示环境（默认 provider=mock）每次回答都挂一条「已降级」提示条。
    """
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: FakeProvider("mock")}, "mock")
    [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert runtime.current.name == "mock"
    assert runtime.degraded is False


@pytest.mark.asyncio
async def test_config_wants_reality_but_only_mock_available_is_degraded():
    """配了 openai_compat 却拿不到首选（含无 Key 情形），这才是降级。"""
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: FakeProvider("mock")}, "openai_compat")
    [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert runtime.degraded is True
    assert runtime.fallback_reason == FALLBACK_TO_MOCK


@pytest.mark.asyncio
async def test_mid_stream_failure_is_not_retried_and_raises_5021():
    """流已开始就不能降级重来 —— 重来会重复输出已吐出的内容。"""
    primary = FakeProvider("openai_compat", fail_at=2)
    runtime, calls = _runtime(
        {LLM_LEVEL_PRIMARY: primary, LLM_LEVEL_MOCK: FakeProvider("mock")}, "openai_compat"
    )

    seen: list = []
    with pytest.raises(ApiError) as exc:
        async for chunk in runtime.stream(MESSAGES, PARAMS):
            seen.append(chunk)

    assert exc.value.code == 5021
    assert len([c for c in seen if isinstance(c, TextDelta)]) == 2
    # 首选只被调用了一次，Mock 兜底没有被启动
    assert primary.stream_calls == 1
    assert calls.count(LLM_LEVEL_MOCK) == 0


@pytest.mark.asyncio
async def test_complete_falls_back_too():
    runtime, _ = _runtime(
        {LLM_LEVEL_PRIMARY: ExplodingProvider(), LLM_LEVEL_MOCK: FakeProvider("mock")},
        "openai_compat",
    )
    result = await runtime.complete(MESSAGES, PARAMS)

    assert result.text == "abc"
    assert runtime.degraded is True


@pytest.mark.asyncio
async def test_complete_raises_5021_when_all_fail():
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: ExplodingProvider()}, "openai_compat")
    with pytest.raises(ApiError) as exc:
        await runtime.complete(MESSAGES, PARAMS)
    assert exc.value.code == 5021


@pytest.mark.asyncio
async def test_snapshot_exposes_provider_and_degradation():
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: FakeProvider("mock")}, "mock")
    assert runtime.snapshot().as_dict() == {
        "provider": None,
        "degraded": False,
        "fallback_reason": None,
    }

    [c async for c in runtime.stream(MESSAGES, PARAMS)]
    assert runtime.snapshot().as_dict() == {
        "provider": "mock",
        "degraded": False,
        "fallback_reason": None,
    }


@pytest.mark.asyncio
async def test_rebind_resets_level_and_expected():
    """spec §4.2 硬约束 4：改完配置立即生效，不得沿用降级后的级别。"""
    runtime, _ = _runtime({LLM_LEVEL_PRIMARY: ExplodingProvider(), LLM_LEVEL_MOCK: FakeProvider("mock")}, "openai_compat")
    [c async for c in runtime.stream(MESSAGES, PARAMS)]
    assert runtime.level == LLM_LEVEL_MOCK

    runtime.rebind(lambda level: FakeProvider("mock") if level == LLM_LEVEL_PRIMARY else None, expected="mock")
    [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert runtime.level == LLM_LEVEL_PRIMARY
    assert runtime.degraded is False


@pytest.mark.asyncio
async def test_empty_stream_is_treated_as_success_not_failure():
    """空流（提供方一个元素都没给）不该被当成失败去降级 —— 它会把兜底级的
    内容吐给客户端，而首选其实「成功」了，只是没内容。"""
    primary = EmptyProvider("openai_compat")
    runtime, calls = _runtime(
        {LLM_LEVEL_PRIMARY: primary, LLM_LEVEL_MOCK: FakeProvider("mock")}, "openai_compat"
    )
    chunks = [c async for c in runtime.stream(MESSAGES, PARAMS)]

    assert chunks == []
    assert runtime.degraded is False
    assert runtime.current.name == "openai_compat"
    assert calls.count(LLM_LEVEL_MOCK) == 0


@pytest.mark.asyncio
async def test_cancel_is_forwarded_to_the_provider():
    provider = FakeProvider("mock", chunks=("a", "b", "c"))
    runtime = LLMRuntime(lambda level: provider if level == LLM_LEVEL_PRIMARY else None, expected="mock")
    cancel = asyncio.Event()
    cancel.set()

    chunks = [c async for c in runtime.stream(MESSAGES, PARAMS, cancel=cancel)]
    assert not [c for c in chunks if isinstance(c, TextDelta)]
