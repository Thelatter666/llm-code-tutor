"""启动预热与 /health 就绪状态（用户拍板决策 1）。

关键契约：**启动时异步后台预热，不阻塞对外服务**；未就绪期间 /health
返回 `ready=false`，检索返回 5032。
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.runtime import (
    get_embedder_runtime,
    reset_runtime,
    set_embedder_runtime,
)
from app.main import app
from tests.fakes import FakeEmbedder


@pytest.fixture(autouse=True)
def _clean():
    reset_runtime()
    yield
    reset_runtime()


def test_health_reports_not_ready_before_warmup():
    body = TestClient(app).get("/health").json()["data"]
    assert body["status"] == "ok"
    assert body["embedder"] == {"name": None, "model": None, "ready": False, "error": None}


def test_health_reports_ready_after_warmup():
    set_embedder_runtime(_warmed(FakeEmbedder()))
    body = TestClient(app).get("/health").json()["data"]
    assert body["embedder"]["ready"] is True
    assert body["embedder"]["name"] == "fake"
    assert body["embedder"]["error"] is None


def test_health_reports_error_when_all_levels_fail():
    set_embedder_runtime(_warmed(None))
    body = TestClient(app).get("/health").json()["data"]
    assert body["embedder"]["ready"] is False
    assert body["embedder"]["error"]


@pytest.mark.asyncio
async def test_warmup_does_not_block_the_caller():
    """慢模型不得拖住启动：warmup 交给 create_task，调用方立即恢复。"""

    class SlowEmbedder(FakeEmbedder):
        def embed(self, texts):
            time.sleep(0.4)  # 模拟 13–20 秒的模型加载
            return super().embed(texts)

    runtime = EmbedderRuntime(lambda level: SlowEmbedder() if level == 1 else None)
    set_embedder_runtime(runtime)

    started = time.perf_counter()
    task = asyncio.create_task(runtime.warmup())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1, f"warmup 阻塞了调用方 {elapsed:.2f}s"
    assert runtime.is_ready is False  # 此刻仍可对外服务，只是检索返回 5032

    await task
    assert runtime.is_ready is True


@pytest.mark.asyncio
async def test_search_is_rejected_while_warming_up():
    """未就绪期间的检索请求返回 5032（spec §9 的知识库功能降级码）。"""
    runtime = EmbedderRuntime(lambda level: FakeEmbedder() if level == 1 else None)
    set_embedder_runtime(runtime)

    from app.core.errors import ApiError

    with pytest.raises(ApiError) as exc:
        runtime.require_ready()
    assert exc.value.code == 5032


def test_embedder_runtime_is_a_singleton():
    first = get_embedder_runtime()
    assert get_embedder_runtime() is first


def _warmed(embedder) -> EmbedderRuntime:
    runtime = EmbedderRuntime(
        lambda level: embedder if (level == 1 and embedder is not None) else None
    )
    asyncio.run(runtime.warmup())
    return runtime
