"""LLM 端口定义。

B1：流必须能承载 token_usage。OpenAI 兼容协议下 usage 藏在流的最后一个 chunk
（需 stream_options.include_usage），纯文本流拿不到，因此流元素设计为
TextDelta | Usage 的联合类型，而非裸 str。
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMParams:
    model: str
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 2048


@dataclass(frozen=True)
class TextDelta:
    """流式输出的文本片段。"""

    text: str


@dataclass(frozen=True)
class Usage:
    """单次调用的 token 用量，作为流的最后一个元素发出。

    estimated=True 表示用量由系统估算（Mock 提供方无真实计数）。
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


LLMChunk = TextDelta | Usage


@dataclass(frozen=True)
class Completion:
    """非流式调用的结果：文本 + 用量。"""

    text: str
    usage: Usage


@runtime_checkable
class LLMPort(Protocol):
    """LLM 端口。

    `@runtime_checkable` 是为了让契约测试能用 `isinstance` 断言端口符合性
    （M4：Mock 与 OpenAICompat 必须跑同一组断言）。
    """

    @property
    def name(self) -> str: ...

    async def stream(
        self,
        messages: list[ChatMessage],
        params: LLMParams,
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]: ...

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> Completion: ...


async def collect_text(chunks: AsyncIterator[LLMChunk]) -> str:
    """从流中收集纯文本，忽略 Usage。"""
    return "".join([c.text async for c in chunks if isinstance(c, TextDelta)])
