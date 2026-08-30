"""LLM 端口契约测试（M4）。

**M4 的由来**：本文件原先的「契约测试」只断言了 `name` 是字符串、`stream` /
`complete` 可调用 —— 名不副实，两个 Provider 换掉任何一个都能照样通过。

契约测试的定义是：**同一组断言在两个实现上各跑一遍**，确保同签名同语义。
本文件因此改为：所有契约断言都经 `provider` fixture 参数化，对
`MockLLMProvider` 与 `OpenAICompatProvider` 各执行一次。

Provider 专属行为（SSE 解析、`include_usage`、HTTP 错误码）留在文件后半部分的
独立用例里 —— 那些不是契约，是实现细节。
"""

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
    LLMPort,
    TextDelta,
    Usage,
    collect_text,
)

PARAMS = LLMParams(model="m", temperature=0.0)
MESSAGES = [ChatMessage("system", "你是助教"), ChatMessage("user", "什么是闭包")]

# 六个文本增量（闭 / 包 / 是 / 什 / 么 / ？）后接 usage。
# 之所以要六段而非两段：`test_cancel_is_per_call_not_per_instance` 需要先各取
# 两个增量、再取消其中一条，剩下的增量必须够让另一条继续产出。
SSE_BODY = (
    b'data: {"choices":[{"delta":{"content":"\xe9\x97\xad"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xe5\x8c\x85"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xe6\x98\xaf"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xe4\xbb\x80"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xe4\xb9\x88"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"\xef\xbc\x9f"}}]}\n\n'
    b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":6,"total_tokens":11}}\n\n'
    b"data: [DONE]\n\n"
)


def _sse_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, content=SSE_BODY, headers={"content-type": "text/event-stream"}
    )


@pytest.fixture(params=["mock", "openai_compat"])
def provider(request):
    """两个实现，同一组断言 —— 这是「契约测试」的最低要求（M4）。"""
    if request.param == "mock":
        return MockLLMProvider()
    return OpenAICompatProvider("http://x", "k", transport=httpx.MockTransport(_sse_handler))


# ---------------------------------------------------------------- 契约断言


@pytest.mark.asyncio
async def test_satisfies_llm_port(provider):
    assert isinstance(provider, LLMPort)


@pytest.mark.asyncio
async def test_stream_ends_with_usage(provider):
    """B1：流末必须是 Usage —— 否则 done 事件拿不到 token_usage。"""
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS)]
    assert chunks, "流不得为空"
    assert isinstance(chunks[-1], Usage)


@pytest.mark.asyncio
async def test_every_chunk_before_the_last_is_text_delta(provider):
    """联合类型不得混用：除末位外一律是文本增量。"""
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS)]
    assert all(isinstance(c, TextDelta) for c in chunks[:-1])
    assert all(isinstance(c.text, str) for c in chunks[:-1])


@pytest.mark.asyncio
async def test_complete_text_matches_streamed_text(provider):
    """两条路径必须同语义：流式收集的文本与 complete 的结果一致。"""
    streamed = await collect_text(provider.stream(MESSAGES, PARAMS))
    assert (await provider.complete(MESSAGES, PARAMS)).text == streamed


@pytest.mark.asyncio
async def test_complete_reports_usage(provider):
    assert isinstance((await provider.complete(MESSAGES, PARAMS)).usage, Usage)


@pytest.mark.asyncio
async def test_stream_yields_at_least_one_delta_without_cancel(provider):
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS)]
    assert [c for c in chunks if isinstance(c, TextDelta)]


@pytest.mark.asyncio
async def test_cancel_set_before_start_yields_no_delta_but_still_usage(provider):
    """中断后调用方仍要拿得到用量 —— 否则 done 事件缺字段，前端拿不到 token_usage。"""
    cancel = asyncio.Event()
    cancel.set()
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS, cancel=cancel)]

    assert not [c for c in chunks if isinstance(c, TextDelta)]
    assert isinstance(chunks[-1], Usage)


@pytest.mark.asyncio
async def test_cancel_stops_the_stream_midway(provider):
    cancel = asyncio.Event()
    seen: list[str] = []

    async for chunk in provider.stream(MESSAGES, PARAMS, cancel=cancel):
        if isinstance(chunk, TextDelta):
            seen.append(chunk.text)
            cancel.set()

    assert len(seen) <= 1, "置位后不应再产出文本增量"


@pytest.mark.asyncio
async def test_cancel_is_per_call_not_per_instance(provider):
    """B2 并发回归：adapter 实例被注册表缓存并被所有请求共享。

    cancel 若是实例级方法（如 `provider.cancel()`），一个学生点「停止」会掐断
    所有进行中的流。本用例让两条流共享同一个 provider 实例，只取消其中一条。
    """
    a_cancel, b_cancel = asyncio.Event(), asyncio.Event()
    stream_a = provider.stream(MESSAGES, PARAMS, cancel=a_cancel)
    stream_b = provider.stream(MESSAGES, PARAMS, cancel=b_cancel)

    ahead = [await stream_a.__anext__() for _ in range(2)]
    bhead = [await stream_b.__anext__() for _ in range(2)]
    assert all(isinstance(c, TextDelta) for c in ahead + bhead)

    a_cancel.set()
    a_rest = [c async for c in stream_a]
    b_rest = [c async for c in stream_b]

    assert not [c for c in a_rest if isinstance(c, TextDelta)]
    assert [c for c in b_rest if isinstance(c, TextDelta)], "取消 A 不得影响 B"


@pytest.mark.asyncio
async def test_empty_messages_do_not_raise(provider):
    """边界健壮性：空消息列表不得让装配链路炸掉。"""
    chunks = [c async for c in provider.stream([], PARAMS)]
    assert isinstance(chunks[-1], Usage)


# ------------------------------------------------- Provider 专属行为（非契约）


@pytest.mark.asyncio
async def test_mock_usage_is_estimated():
    """估算用量 EstimatedUsage：Mock 无真实计数，按 len//4 估算并置 estimated。"""
    usage = (await MockLLMProvider().complete(MESSAGES, PARAMS)).usage
    assert usage.estimated is True
    text = (await MockLLMProvider().complete(MESSAGES, PARAMS)).text
    assert usage.completion_tokens == len(text) // 4


@pytest.mark.asyncio
async def test_openai_compat_usage_is_not_estimated():
    """真实用量 Usage：由提供方在流末给出，estimated=False。"""
    provider = OpenAICompatProvider("http://x", "k", transport=httpx.MockTransport(_sse_handler))
    usage = (await provider.complete(MESSAGES, PARAMS)).usage
    assert usage.total_tokens == 11
    assert usage.estimated is False


@pytest.mark.asyncio
async def test_openai_compat_requests_usage_in_stream():
    """B1：不请求 include_usage 就永远拿不到真实 token 用量。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    provider = OpenAICompatProvider("http://x", "k", transport=httpx.MockTransport(handler))
    [c async for c in provider.stream(MESSAGES, PARAMS)]

    assert captured["body"]["stream_options"]["include_usage"] is True


@pytest.mark.asyncio
async def test_openai_compat_falls_back_to_estimated_usage_when_absent():
    """提供方没给 usage 时也必须补一个，且标为估算。"""
    provider = OpenAICompatProvider(
        "http://x", "k", transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"data: [DONE]\n\n"))
    )
    usage = (await provider.complete(MESSAGES, PARAMS)).usage
    assert usage.estimated is True


@pytest.mark.asyncio
async def test_openai_compat_raises_5021_on_http_500():
    provider = OpenAICompatProvider(
        "http://x", "k", transport=httpx.MockTransport(lambda _r: httpx.Response(500, text="boom"))
    )
    with pytest.raises(ApiError) as exc:
        [c async for c in provider.stream(MESSAGES, PARAMS)]
    assert exc.value.code == 5021


@pytest.mark.asyncio
async def test_openai_compat_parses_sse_text():
    provider = OpenAICompatProvider("http://x", "k", transport=httpx.MockTransport(_sse_handler))
    text = await collect_text(provider.stream(MESSAGES, PARAMS))
    assert text == "闭包是什么？"
