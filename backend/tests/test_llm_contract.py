import asyncio
import json

import httpx
import pytest

from app.core.errors import ApiError
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.ports.llm import (
    ChatMessage,
    LLMParams,
    TextDelta,
    Usage,
    collect_text,
)

PARAMS = LLMParams(model="m", temperature=0.0)
MESSAGES = [ChatMessage("system", "你是助教"), ChatMessage("user", "什么是闭包")]

SSE_BODY = (
    b'data: {"choices":[{"delta":{"content":"\xe9\x97\xad"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xe5\x8c\x85"}}]}\n\n'
    b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.mark.parametrize(
    "provider",
    [MockLLMProvider(), OpenAICompatProvider("http://x", "k")],
)
def test_contract_providers_expose_llm_port_surface(provider):
    assert isinstance(provider.name, str) and provider.name
    assert callable(provider.stream) and callable(provider.complete)


@pytest.mark.asyncio
async def test_mock_stream_ends_with_usage():
    chunks = [c async for c in MockLLMProvider().stream(MESSAGES, PARAMS)]
    assert isinstance(chunks[-1], Usage)


@pytest.mark.asyncio
async def test_mock_complete_matches_stream_text():
    provider = MockLLMProvider()
    streamed = await collect_text(provider.stream(MESSAGES, PARAMS))
    assert (await provider.complete(MESSAGES, PARAMS)).text == streamed


@pytest.mark.asyncio
async def test_openai_compat_parses_sse_and_usage():
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200, content=SSE_BODY, headers={"content-type": "text/event-stream"}
        )
    )
    chunks = [
        c
        async for c in OpenAICompatProvider("http://x", "k", transport=transport).stream(
            MESSAGES, PARAMS
        )
    ]

    assert "".join(c.text for c in chunks if isinstance(c, TextDelta)) == "闭包"
    usage = chunks[-1]
    assert isinstance(usage, Usage)
    assert usage.total_tokens == 7
    assert usage.estimated is False


@pytest.mark.asyncio
async def test_openai_compat_requests_usage_in_stream():
    """B1：不请求 include_usage 就永远拿不到真实 token 用量。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatProvider("http://x", "k", transport=transport)
    [c async for c in provider.stream(MESSAGES, PARAMS)]

    assert captured["body"]["stream_options"]["include_usage"] is True


@pytest.mark.asyncio
async def test_openai_compat_honours_cancel_event():
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200, content=SSE_BODY, headers={"content-type": "text/event-stream"}
        )
    )
    cancel = asyncio.Event()
    cancel.set()
    chunks = [
        c
        async for c in OpenAICompatProvider("http://x", "k", transport=transport).stream(
            MESSAGES, PARAMS, cancel=cancel
        )
    ]

    assert not [c for c in chunks if isinstance(c, TextDelta)]


@pytest.mark.asyncio
async def test_openai_compat_raises_5021_on_http_500():
    transport = httpx.MockTransport(lambda _r: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as exc:
        [
            c
            async for c in OpenAICompatProvider("http://x", "k", transport=transport).stream(
                MESSAGES, PARAMS
            )
        ]
    assert exc.value.code == 5021
