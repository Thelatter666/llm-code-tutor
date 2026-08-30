import asyncio
import time

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


@pytest.mark.asyncio
async def test_extractive_generation_skips_markdown_headings():
    """标题行不含句读，抽出来既没信息量，还会和后面的话术粘成一串。"""
    user = ChatMessage(
        "user",
        "以下是课程知识库检索到的相关内容。\n\n"
        "[1] 来源：sorting.md\n# 排序算法讲义\n冒泡排序重复比较相邻元素。\n\n讲讲排序算法",
    )
    text = await collect_text(
        MockLLMProvider().stream([_system("【防抄袭档位：guided】"), user], PARAMS)
    )
    assert "依据知识库片段：冒泡排序重复比较相邻元素。" in text
    assert "排序算法讲义我不能" not in text


# ------------------------------------------------- 流式延迟（P2 遗留项裁定，并入 P3）
#
# 问题：Mock 约 0.1s 生成完毕，浏览器点「停止」几乎总来不及截断，无 API Key
# 演示看不到流式输出。要求：stream() 在每个 TextDelta 之间 sleep；complete()
# 是非流式调用，绝不受影响；只影响 Mock 提供方。
#
# 套件级默认经 conftest 显式置 0（MOCK_TOKEN_DELAY_MS=0），延迟用例用构造参数
# 显式开延迟 —— 不改 Settings 默认值（30），也不为提速删掉延迟实现。


def test_settings_declares_mock_token_delay_with_default_30():
    """Settings 必须声明 mock_token_delay_ms 且默认 30（裁定值）。

    经 model_fields 验证声明默认值，不受套件环境变量置 0 的影响。
    """
    from app.core.config import Settings

    field = Settings.model_fields["mock_token_delay_ms"]
    assert field.default == 30


@pytest.mark.asyncio
async def test_stream_takes_noticeably_longer_when_delay_is_enabled():
    provider = MockLLMProvider(token_delay_ms=5)
    start = time.perf_counter()
    text = await collect_text(provider.stream([ChatMessage("user", "讲讲递归")], PARAMS))
    elapsed = time.perf_counter() - start

    assert len(text) >= 30, "前提：渲染文本足够长，延迟才可测"
    assert elapsed >= 0.15, "≥30 个增量 × 5ms，总耗时必须显著大于 0"


@pytest.mark.asyncio
async def test_complete_is_not_delayed():
    """complete() 非流式：即便每字 50ms 的延迟开着，也必须立刻返回。"""
    provider = MockLLMProvider(token_delay_ms=50)
    start = time.perf_counter()
    await provider.complete(MESSAGES, PARAMS)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_cancelled_stream_does_not_crawl_through_the_delay():
    """中断前置位：零个增量、零次睡眠，不能被延迟拖慢中断路径。"""
    provider = MockLLMProvider(token_delay_ms=50)
    cancel = asyncio.Event()
    cancel.set()

    start = time.perf_counter()
    chunks = [c async for c in provider.stream(MESSAGES, PARAMS, cancel=cancel)]
    elapsed = time.perf_counter() - start

    assert not [c for c in chunks if isinstance(c, TextDelta)]
    assert isinstance(chunks[-1], Usage)
    assert elapsed < 0.1
