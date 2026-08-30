import asyncio
from typing import AsyncIterator

from app.infrastructure.ports.llm import (
    ChatMessage,
    Completion,
    LLMChunk,
    LLMParams,
    TextDelta,
    Usage,
)


class MockLLMProvider:
    """无需 API Key 即可跑通全链路的提供方（spec §7.3）。

    抽取式生成：以用户末条消息与系统提示拼装话术，逐字流式吐出，
    并在流末发出估算用量（估算用量 EstimatedUsage）。

    本实例被所有请求共享，**不保存任何 per-request 状态**。
    """

    @property
    def name(self) -> str:
        return "mock"

    def _render(self, messages: list[ChatMessage]) -> str:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        system = next((m.content for m in messages if m.role == "system"), "")
        topic = last_user.strip() or "该问题"
        guard = "教学提示：请先自行尝试，再对照下面的思路。" if system else ""
        return (
            f"[Mock 模式] 关于「{topic}」，给出如下思路："
            f"1) 先明确输入与输出；2) 拆解为最小可验证步骤；3) 逐步实现并测试。{guard}"
        )

    def _usage(self, text: str, messages: list[ChatMessage]) -> Usage:
        prompt = sum(len(m.content) for m in messages) // 4
        completion = len(text) // 4
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            estimated=True,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        params: LLMParams,
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        text = self._render(messages)
        for ch in text:
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
            await asyncio.sleep(0)
        # 被中断时仍发出用量，保证调用方能拿到 done 所需的 usage
        yield self._usage(text, messages)

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> Completion:
        text = self._render(messages)
        return Completion(text=text, usage=self._usage(text, messages))
