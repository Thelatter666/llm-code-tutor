"""向量化器运行时：三级回退 + 异步后台预热 + 就绪状态。

spec §9 要求「Embedding 失败 → 三级回退：OpenAI 兼容 → sentence-transformers
→ HashingEmbed」。审阅报告 M10 指出该降级链此前无落点，这里就是它的落点：

- **解析期回退**：`build_embedder(cfg, level)` 按可用性逐级构建，不可用的级返回 None
- **运行期回退**：`embed()` 从当前级向下遍历，任一级抛错即降级，并**记住降级后的
  级别**，避免每次请求都从最高级重新试错
- **异步后台预热**：`warmup()` 只做一次探针编码，供 lifespan 用 `create_task`
  拉起，不阻塞启动（用户拍板决策 1）

级别编号越小越「真」：0=OpenAI 兼容，1=sentence-transformers，2=HashingEmbed 哨兵。
"""

import logging
from typing import Callable

from fastapi.concurrency import run_in_threadpool

from app.core.errors import ApiError
from app.infrastructure.ports.embedding import Embedder

logger = logging.getLogger(__name__)

EMBED_LEVEL_OPENAI = 0
EMBED_LEVEL_LOCAL = 1
EMBED_LEVEL_HASHING = 2
EMBED_LEVELS = 3

_WARMUP_PROBE = "预热探针"


class EmbedderRuntime:
    """持有当前生效的向量化器，并对外暴露就绪状态。"""

    def __init__(self, factory: Callable[[int], Embedder | None], levels: int = EMBED_LEVELS):
        self._factory = factory
        self._levels = levels
        self._level = EMBED_LEVEL_OPENAI
        self._embedder: Embedder | None = None
        self._ready = False
        self._error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def current(self) -> Embedder | None:
        return self._embedder

    @property
    def level(self) -> int:
        return self._level

    def rebind(self, factory: Callable[[int], Embedder | None]) -> None:
        """配置变更后换掉 factory，并把降级级别重置回最高级。

        不重置的话，切换 embedding 后会一直沿用降级前的级别，新配置永远不生效。
        重置后 `_ready` 立即置 False —— 旧模型已不代表当前配置，必须重新预热。
        """
        self._factory = factory
        self._level = EMBED_LEVEL_OPENAI
        self._embedder = None
        self._ready = False
        self._error = None

    def snapshot(self) -> dict:
        """/health 的模型就绪状态载荷。"""
        return {
            "name": self._embedder.name if self._embedder else None,
            "model": self._embedder.model if self._embedder else None,
            "ready": self._ready,
            "error": self._error,
        }

    def require_ready(self) -> Embedder:
        """未就绪时抛出 spec §9 约定的 5032，供检索路径使用。"""
        if not self._ready or self._embedder is None:
            raise ApiError(5032, "向量模型正在加载，请稍后重试")
        return self._embedder

    async def warmup(self) -> None:
        """异步后台预热：加载模型并完成一次探针编码。

        禁止在启动路径上同步等待本方法 —— 实测模型加载 13–20 秒，
        同步阻塞会让演示环境启动后长时间无响应。
        """
        try:
            await self.embed([_WARMUP_PROBE])
        except ApiError:
            # 三级全部失败：保持未就绪，由 /health 暴露 error
            pass

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """按三级回退链取向量；全链路失败抛 5032。"""
        if not texts:
            return []

        for level in range(self._level, self._levels):
            embedder = self._factory(level)
            if embedder is None:
                continue
            try:
                vectors = await run_in_threadpool(embedder.embed, texts)
            except Exception as exc:  # noqa: BLE001 - 任何异常都触发降级
                logger.warning("向量化器 %s 调用失败，降级到下一级：%s", embedder.name, exc)
                continue
            self._level = level
            self._embedder = embedder
            self._ready = True
            self._error = None
            return vectors

        self._ready = False
        self._error = "所有向量化器均不可用"
        raise ApiError(5032, "向量化服务不可用，知识库功能暂时降级")
