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


# ------------------------------------------------- spec §7.3：Mock 也遵守防抄袭三档


def _system(marker: str) -> ChatMessage:
    return ChatMessage("system", f"你是助教。\n{marker}")


def _ask(text: str = "怎么用 Python 写快排？") -> ChatMessage:
    return ChatMessage("user", text)


async def _render(marker: str) -> str:
    return await collect_text(MockLLMProvider().stream([_system(marker), _ask()], PARAMS))


@pytest.mark.asyncio
async def test_strict_mode_outputs_guidance_instead_of_implementation():
    """spec §7.3：strict 档输出固定引导话术。"""
    text = await _render("【防抄袭档位：strict】")
    assert "伪代码骨架" in text
    assert "我不能给出完整可运行代码" in text
    assert "请先自行尝试" not in text


@pytest.mark.asyncio
async def test_guided_mode_outputs_a_minimal_snippet_only():
    text = await _render("【防抄袭档位：guided】")
    assert "不超过 10 行" in text
    assert "不是完整实现" in text


@pytest.mark.asyncio
async def test_loose_mode_outputs_implementation_with_walkthrough():
    text = await _render("【防抄袭档位：loose】")
    assert "请先自行尝试" in text
    assert "逐段讲解" in text


@pytest.mark.asyncio
async def test_three_modes_produce_different_output():
    """三档输出必须真的不同 —— 否则演示与联调时「防抄袭是否生效」无从观察。"""
    outputs = {mode: await _render(f"【防抄袭档位：{mode}】") for mode in ("strict", "guided", "loose")}
    assert len(set(outputs.values())) == 3


@pytest.mark.asyncio
async def test_exempt_intent_is_not_shaped_by_the_mode():
    text = await _render("【防抄袭档位：本次豁免】")
    assert "我不能给出完整可运行代码" not in text
    assert "豁免" in text


@pytest.mark.asyncio
async def test_floor_hit_turns_the_request_into_guidance():
    text = await _render("【防抄袭档位：loose】【本次请求已触发底线：homework_ghostwriting】")
    assert "代做作业" in text
    assert "可直接提交" in text


@pytest.mark.asyncio
async def test_exam_floor_refuses_to_give_the_answer():
    text = await _render("【防抄袭档位：loose】【本次请求已触发底线：exam_in_progress】")
    assert "不能直接给答案" in text


@pytest.mark.asyncio
async def test_extractive_generation_quotes_the_hit_snippet():
    """spec §7.3：对命中片段做抽取式生成。"""
    user = ChatMessage(
        "user",
        "以下是课程知识库检索到的相关内容。\n\n[1] 来源：第1讲\n排序有三大类。其中快排属于分治。\n\n怎么用 Python 写快排？",
    )
    text = await collect_text(
        MockLLMProvider().stream([_system("【防抄袭档位：guided】"), user], PARAMS)
    )
    assert "依据知识库片段：排序有三大类。" in text
