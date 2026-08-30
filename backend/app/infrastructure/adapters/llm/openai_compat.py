import asyncio
import json
from typing import AsyncIterator

import httpx

from app.core.errors import ApiError
from app.infrastructure.ports.llm import (
    ChatMessage,
    Completion,
    LLMChunk,
    LLMParams,
    TextDelta,
    Usage,
)

# M17：SSE 下推理模型可能数十秒无 token，read 必须单独放宽
_TIMEOUT = httpx.Timeout(10.0, read=300.0)


class OpenAICompatProvider:
    """OpenAI 兼容协议提供方；base_url 可指向 DeepSeek / 通义 / Ollama。

    transport 参数仅用于测试注入 httpx.MockTransport。
    本实例被所有请求共享，不保存任何 per-request 状态（B2）。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    @property
    def name(self) -> str:
        return "openai_compat"

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": _TIMEOUT}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def _payload(self, messages: list[ChatMessage], params: LLMParams, stream: bool) -> dict:
        payload = {
            "model": params.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": stream,
        }
        if stream:
            # B1：不带上此项，流的最后一个 chunk 不含 usage
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def stream(
        self,
        messages: list[ChatMessage],
        params: LLMParams,
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        usage: Usage | None = None

        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=self._payload(messages, params, stream=True),
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    raise ApiError(5021, "模型服务不可用")

                async for line in resp.aiter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue

                    if raw := obj.get("usage"):
                        usage = Usage(
                            prompt_tokens=raw.get("prompt_tokens", 0),
                            completion_tokens=raw.get("completion_tokens", 0),
                            total_tokens=raw.get("total_tokens", 0),
                            estimated=False,
                        )
                        continue

                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    if content := choices[0].get("delta", {}).get("content"):
                        yield TextDelta(content)

        if usage is None:
            usage = Usage(0, 0, 0, estimated=True)
        yield usage

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> Completion:
        text, usage = "", None
        async for chunk in self.stream(messages, params):
            if isinstance(chunk, TextDelta):
                text += chunk.text
            else:
                usage = chunk
        return Completion(text=text, usage=usage or Usage(0, 0, 0, estimated=True))
