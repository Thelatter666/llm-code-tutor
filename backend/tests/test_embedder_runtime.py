import pytest

from app.core.errors import ApiError
from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.embedder_runtime import (
    EMBED_LEVEL_HASHING,
    EMBED_LEVEL_LOCAL,
    EMBED_LEVEL_OPENAI,
    EmbedderRuntime,
)


class _FakeEmbedder:
    def __init__(self, name="fake", model="fake-1", dimension=8, sentinel=False, boom=False):
        self.name = name
        self.model = model
        self.dimension = dimension
        self.is_sentinel = sentinel
        self._boom = boom
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        if self._boom:
            raise RuntimeError("上游不可用")
        return [[0.1] * self.dimension for _ in texts]


def _broken(name="broken"):
    return _FakeEmbedder(name=name, boom=True)


def _runtime(levels):
    """levels 按下标对应级别；缺失的级别视为不可用。"""
    return EmbedderRuntime(lambda level: levels[level] if level < len(levels) else None)


def test_level_ordering_puts_hashing_last():
    assert EMBED_LEVEL_OPENAI < EMBED_LEVEL_LOCAL < EMBED_LEVEL_HASHING


@pytest.mark.asyncio
async def test_not_ready_before_warmup():
    rt = _runtime([_FakeEmbedder()])
    assert rt.is_ready is False
    with pytest.raises(ApiError) as exc:
        rt.require_ready()
    assert exc.value.code == 5032
    assert "加载" in exc.value.message


@pytest.mark.asyncio
async def test_warmup_marks_ready_and_pins_current_embedder():
    rt = _runtime([_FakeEmbedder()])
    await rt.warmup()
    assert rt.is_ready is True
    assert rt.current.name == "fake"


@pytest.mark.asyncio
async def test_embed_falls_back_to_next_level_on_runtime_failure():
    """spec §9 / M10：任一级调用失败即降级到下一级，并记住降级后的级别。"""
    rt = _runtime([_broken(), _FakeEmbedder()])
    await rt.warmup()
    assert rt.current.name == "fake"
    assert await rt.embed(["x"]) == [[0.1] * 8]


@pytest.mark.asyncio
async def test_degraded_level_is_remembered_across_calls():
    """降级后不得每次请求都从最高级重新试错。"""
    failing, working = _broken(), _FakeEmbedder()
    rt = _runtime([failing, working])
    await rt.warmup()  # 0 级失败 1 次，1 级成功 1 次
    await rt.embed(["x"])
    await rt.embed(["y"])
    assert failing.calls == 1  # 降级后不再重试 0 级
    assert working.calls == 3  # 1 次预热 + 2 次业务


@pytest.mark.asyncio
async def test_embed_falls_back_to_hashing_sentinel_when_all_real_levels_fail():
    rt = _runtime([_broken(), _broken(), HashingEmbed()])
    await rt.warmup()
    assert rt.current.is_sentinel is True
    assert rt.is_ready is True


@pytest.mark.asyncio
async def test_embed_raises_5032_when_every_level_fails():
    rt = _runtime([_broken()])
    await rt.warmup()
    assert rt.is_ready is False
    with pytest.raises(ApiError) as exc:
        await rt.embed(["x"])
    assert exc.value.code == 5032


@pytest.mark.asyncio
async def test_unavailable_levels_are_skipped():
    """未装 local-embed 时第 1 级不可用，应直接落到哨兵。"""
    rt = _runtime([None, None, HashingEmbed()])
    await rt.warmup()
    assert rt.current.is_sentinel is True


@pytest.mark.asyncio
async def test_snapshot_exposes_status_for_health():
    rt = _runtime([_FakeEmbedder()])
    assert rt.snapshot() == {"name": None, "model": None, "ready": False, "error": None}
    await rt.warmup()
    snap = rt.snapshot()
    assert snap == {"name": "fake", "model": "fake-1", "ready": True, "error": None}


@pytest.mark.asyncio
async def test_snapshot_exposes_error_when_all_levels_fail():
    rt = _runtime([_broken()])
    await rt.warmup()
    snap = rt.snapshot()
    assert snap["ready"] is False
    assert snap["error"]
