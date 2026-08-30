import asyncio

import pytest

from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.ports.llm import (
    ChatMessage,
    LLMParams,
    TextDelta,
    Usage,
    collect_text,
)

PARAMS = LLMParams(model="mock-1")
MESSAGES = [ChatMessage("user", "你好")]


async def _aiter(items):
    for i in items:
        yield i


@pytest.mark.asyncio
async def test_stream_yields_text_deltas_then_usage():
    provider = MockLLMProvider()
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS)]

    assert all(isinstance(c, TextDelta) for c in chunks[:-1])
    assert isinstance(chunks[-1], Usage)
    assert chunks[-1].estimated is True
    assert await collect_text(_aiter(chunks))


@pytest.mark.asyncio
async def test_usage_is_estimated_from_content_length():
    provider = MockLLMProvider()
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS)]
    usage = chunks[-1]
    text = "".join(c.text for c in chunks if isinstance(c, TextDelta))

    assert usage.completion_tokens == len(text) // 4
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


@pytest.mark.asyncio
async def test_stream_stops_when_cancel_event_set():
    provider = MockLLMProvider()
    cancel = asyncio.Event()
    deltas = []
    async for chunk in provider.stream([ChatMessage("user", "讲讲递归")], PARAMS, cancel=cancel):
        if isinstance(chunk, TextDelta):
            deltas.append(chunk.text)
            if len(deltas) == 2:
                cancel.set()
    assert len(deltas) == 2


@pytest.mark.asyncio
async def test_cancel_is_per_call_not_per_instance():
    """B2 回归用例：两个并发流共享同一实例，但 cancel 互不干扰。

    若把 cancel 做成实例方法，取消其中一个会掐断另一个。
    """
    provider = MockLLMProvider()
    c1, c2 = asyncio.Event(), asyncio.Event()
    c1.set()

    async def drain(cancel: asyncio.Event) -> list[str]:
        out = []
        async for chunk in provider.stream([ChatMessage("user", "x")], PARAMS, cancel=cancel):
            if isinstance(chunk, TextDelta):
                out.append(chunk.text)
        return out

    a, b = await asyncio.gather(drain(c1), drain(c2))
    assert len(a) == 0
    assert len(b) > 0


@pytest.mark.asyncio
async def test_complete_returns_text_and_usage():
    provider = MockLLMProvider()
    result = await provider.complete(MESSAGES, PARAMS)
    assert result.text
    assert isinstance(result.usage, Usage)


def test_name_is_mock():
    assert MockLLMProvider().name == "mock"
