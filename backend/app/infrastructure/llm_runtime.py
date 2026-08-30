"""LLM 运行时：提供方降级链（M10 / spec §9）。

spec §9 要求「LLM 调用失败 / 超时 → 降级到下一 Provider；全部失败返回 5021」。
P0 的 `ProviderRegistry` 是单槽缓存，没有 fallback 概念，因此这里补一个与 P1
`EmbedderRuntime` 同构的运行时：

- **解析期回退**：`build_llm(cfg, level)` 按可用性构建，首选不可用时 level 0
  直接给出 Mock（对应 spec §9 的「无 API Key → 解析为 MockProvider」）
- **运行期回退**：`stream()` / `complete()` 从当前级向下遍历，任一级在**产出首个
  元素之前**失败即降级，并记住降级后的级别，避免每次请求都从首选重新试错
- **流中途失败不重试**：已经有内容吐给客户端了，重来一次会重复输出。此时直接
  抛 `ApiError(5021)`，由 `ChatService` 发 `error` 事件

级别编号越小越「真」：0 = 配置首选（OpenAI 兼容），1 = Mock 兜底。
"""

import logging
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from app.core.errors import ApiError
from app.infrastructure.ports.llm import (
    ChatMessage,
    Completion,
    LLMChunk,
    LLMPort,
    LLMParams,
)

logger = logging.getLogger(__name__)

LLM_LEVEL_PRIMARY = 0
LLM_LEVEL_MOCK = 1
LLM_LEVELS = 2

# spec §9：降级必须可见，前端据此展示提示条
FALLBACK_TO_MOCK = "llm_fallback_to_mock"


@dataclass(frozen=True)
class LLMSnapshot:
    """本次调用的提供方状态，直接进 `done` 事件的 `provider` / `degraded` 字段。"""

    provider: str | None
    degraded: bool
    fallback_reason: str | None

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "degraded": self.degraded,
            "fallback_reason": self.fallback_reason,
        }


class LLMRuntime:
    """持有当前生效的 LLM 提供方，并对外暴露降级状态。"""

    def __init__(
        self,
        factory: Callable[[int], LLMPort | None],
        *,
        expected: str = "mock",
        levels: int = LLM_LEVELS,
    ):
        self._factory = factory
        self._expected = expected
        self._levels = levels
        self._level = LLM_LEVEL_PRIMARY
        self._provider: LLMPort | None = None

    @property
    def current(self) -> LLMPort | None:
        return self._provider

    @property
    def level(self) -> int:
        return self._level

    def rebind(
        self, factory: Callable[[int], LLMPort | None], *, expected: str = "mock"
    ) -> None:
        """配置变更后换掉 factory，并把降级级别重置回首选。

        不重置的话，管理员改完配置仍会一直沿用降级后的级别，新配置永远不生效
        （spec §4.2 硬约束 4「配置热生效」）。
        """
        self._factory = factory
        self._expected = expected
        self._level = LLM_LEVEL_PRIMARY
        self._provider = None

    @property
    def degraded(self) -> bool:
        """实际生效的提供方与配置期望不一致即为降级。

        注意：**无 API Key 且配置本就是 Mock 时不算降级** —— spec §9 把它列为
        既定路径（「无 API Key → 解析为 MockProvider，全链路可用 + 前端角标」），
        不是故障。只有「配置想要真模型、实际只能给 Mock」才是降级。
        """
        return self._provider is not None and self._provider.name != self._expected

    @property
    def fallback_reason(self) -> str | None:
        return FALLBACK_TO_MOCK if self.degraded else None

    def snapshot(self) -> LLMSnapshot:
        """供 `done` 事件与 `/health` 使用。"""
        return LLMSnapshot(
            provider=self._provider.name if self._provider else None,
            degraded=self.degraded,
            fallback_reason=self.fallback_reason,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        params: LLMParams,
        *,
        cancel=None,
    ) -> AsyncIterator[LLMChunk]:
        """按降级链流式生成；全部失败抛 `5021`。"""
        for level in range(self._level, self._levels):
            provider = self._factory(level)
            if provider is None:
                continue

            iterator = provider.stream(messages, params, cancel=cancel)
            try:
                first = await iterator.__anext__()
            except StopAsyncIteration:
                # 空流不算失败： adopt 之后正常结束，调用方会补一个估算用量
                self._adopt(level, provider)
                return
            except Exception as exc:  # noqa: BLE001 - 任何异常都触发降级
                logger.warning("提供方 %s 调用失败，降级到下一级：%s", provider.name, exc)
                continue

            self._adopt(level, provider)
            yield first
            try:
                async for chunk in iterator:
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, ApiError):
                    raise
                # 流已开始，不能再降级重来（会重复输出已吐出的内容）
                raise ApiError(5021, "模型服务不可用") from exc
            return

        raise ApiError(5021, "模型服务不可用，请稍后重试")

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> Completion:
        for level in range(self._level, self._levels):
            provider = self._factory(level)
            if provider is None:
                continue
            try:
                result = await provider.complete(messages, params)
            except Exception as exc:  # noqa: BLE001
                logger.warning("提供方 %s 调用失败，降级到下一级：%s", provider.name, exc)
                continue
            self._adopt(level, provider)
            return result

        raise ApiError(5021, "模型服务不可用，请稍后重试")

    def _adopt(self, level: int, provider: LLMPort) -> None:
        self._level = level
        self._provider = provider
