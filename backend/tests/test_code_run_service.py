"""CodeService.run / 草稿 CRUD 的服务层测试。

服务层只依赖 `CodeExecutor` 端口，故这里注入 `FakeExecutor` —— 断言的是
「编排发生了什么」（落库、审计、卸载、并发），而不是子进程行为（那归
`test_code_executor.py`）。
"""

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ApiError
from app.domain.code.execution import (
    ACTION_CODE_RUN,
    STATUS_ACCEPTED,
    STATUS_BLOCKED,
    STATUS_TIMEOUT,
)
from app.infrastructure.concurrency import reset_concurrency
from app.infrastructure.persistence.models import AuditLog, CodeRun, CodeSession
from app.infrastructure.ports.code_executor import ExecutionResult
from app.services import code_service as code_service_module
from app.services.code_service import CodeService

PY = "python"
SOURCE = "print('hi')\n"


def _result(
    status: str = STATUS_ACCEPTED,
    stdout: str = "hi\n",
    stderr: str = "",
    exit_code: int | None = 0,
    duration_ms: int = 12,
    limit_detail: dict | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        status=status,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        limit_detail=limit_detail
        or {
            "wall_clock": {"limit_s": 5.0, "elapsed_s": 0.012, "triggered": False},
            "cpu": {"limit_s": 3, "applied": True, "triggered": False, "error": None},
            "memory": {
                "limit_bytes": 268435456,
                "sampled": True,
                "interval_ms": 100,
                "peak_bytes": 9000000,
                "samples": 2,
                "triggered": False,
            },
            "file_size": {"limit_bytes": 1048576, "applied": True, "error": None},
            "output": {"limit_bytes": 8192, "stdout_truncated": False, "stderr_truncated": False},
        },
    )


class FakeExecutor:
    """记录调用、返回预设结果。"""

    def __init__(self, result: ExecutionResult | None = None):
        self.result = result or _result()
        self.calls: list[dict] = []

    def execute(self, *, language: str, source: str, stdin: str = "") -> ExecutionResult:
        self.calls.append({"language": language, "source": source, "stdin": stdin})
        return self.result


class SlowExecutor(FakeExecutor):
    """同步阻塞一段时间，用于并发与卸载测试。跑在线程池里，不占事件循环。"""

    def __init__(self, delay: float = 0.4, **kwargs):
        super().__init__(**kwargs)
        self.delay = delay

    def execute(self, *, language: str, source: str, stdin: str = "") -> ExecutionResult:
        self.calls.append({"language": language, "source": source, "stdin": stdin})
        time.sleep(self.delay)
        return self.result


@pytest_asyncio.fixture(autouse=True)
async def _reset_quota():
    """信号量绑在事件循环上；每个用例一个循环，必须重置。"""
    reset_concurrency()
    yield
    reset_concurrency()


def _svc(session, executor=None) -> CodeService:
    return CodeService(session, executor=executor or FakeExecutor())


# ---------------------------------------------------------------- 主路径

@pytest.mark.asyncio
async def test_run_persists_a_code_run_row(session):
    executor = FakeExecutor()
    row = await _svc(session, executor).run(
        user_id="u1", language=PY, source=SOURCE, stdin="in", request_id="r1"
    )
    await session.commit()

    loaded = (await session.execute(select(CodeRun))).scalar_one()
    assert loaded.id == row.id
    assert loaded.user_id == "u1"
    assert loaded.language == PY
    assert loaded.source_code == SOURCE
    assert loaded.stdin == "in"
    assert loaded.status == STATUS_ACCEPTED
    assert loaded.stdout == "hi\n"
    assert loaded.exit_code == 0
    assert loaded.duration_ms == 12
    # 端口拿到的入参与落库一致
    assert executor.calls == [{"language": PY, "source": SOURCE, "stdin": "in"}]


@pytest.mark.asyncio
async def test_run_persists_limit_detail_verbatim(session):
    await _svc(session).run(user_id="u1", language=PY, source=SOURCE, request_id="r1")
    await session.commit()
    loaded = (await session.execute(select(CodeRun))).scalar_one()
    assert loaded.limit_detail["memory"]["peak_bytes"] == 9000000
    assert loaded.limit_detail["cpu"]["applied"] is True


@pytest.mark.asyncio
async def test_run_writes_audit_log(session):
    await _svc(session).run(user_id="u1", language=PY, source=SOURCE, request_id="r1")
    await session.commit()
    logs = (
        await session.execute(select(AuditLog).where(AuditLog.action == ACTION_CODE_RUN))
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].user_id == "u1"
    assert logs[0].request_id == "r1"
    assert logs[0].detail["status"] == STATUS_ACCEPTED
    assert logs[0].target_type == "code_run"


@pytest.mark.asyncio
async def test_blocked_run_is_still_recorded(session):
    """命中黑名单也要留痕 —— 否则「谁在反复尝试危险调用」完全没有可见性。"""
    executor = FakeExecutor(
        _result(status=STATUS_BLOCKED, stdout="", stderr="命中黑名单", exit_code=None)
    )
    row = await _svc(session, executor).run(user_id="u1", language=PY, source="os.system(1)")
    assert row.status == STATUS_BLOCKED
    assert row.exit_code is None
    logs = (
        await session.execute(select(AuditLog).where(AuditLog.action == ACTION_CODE_RUN))
    ).scalars().all()
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_execution_is_offloaded_to_threadpool(session, monkeypatch):
    """ADR-0002：整段执行（含 psutil 轮询）是阻塞调用，必须卸载。"""
    seen: list[str] = []
    real = code_service_module.run_in_threadpool

    async def spy(func, *args, **kwargs):
        seen.append(getattr(func, "__name__", str(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(code_service_module, "run_in_threadpool", spy)
    await _svc(session).run(user_id="u1", language=PY, source=SOURCE)
    assert seen == ["execute"]


# ---------------------------------------------------------------- 并发上限

async def _run_in_own_session(session_factory, *, source: str, executor=None):
    """并发用例必须各自开会话 —— 真实请求也是一人一会话，共用会撞 flush。"""
    async with session_factory() as s:
        row = await CodeService(s, executor=executor).run(
            user_id="u1", language=PY, source=source
        )
        await s.commit()
        return row


@pytest.mark.asyncio
async def test_third_concurrent_run_gets_429(session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "execution_quota_timeout_s", 0.15)
    monkeypatch.setattr(get_settings(), "execution_concurrency", 2)
    executor = SlowExecutor(delay=0.4)

    running = [
        asyncio.create_task(
            _run_in_own_session(session_factory, source=SOURCE, executor=executor)
        )
        for _ in range(2)
    ]
    await asyncio.sleep(0.05)  # 让两路占住执行位

    with pytest.raises(ApiError) as exc:
        await _run_in_own_session(session_factory, source="第三个", executor=executor)
    assert exc.value.code == 4290
    assert exc.value.status == 429
    assert exc.value.data["retry_after"] == 0.15

    await asyncio.gather(*running)
    async with session_factory() as s:
        rows = (await s.execute(select(CodeRun))).scalars().all()
    assert len(rows) == 2, "被 429 的请求不该留下运行记录"


@pytest.mark.asyncio
async def test_quota_permits_are_not_leaked_after_a_timeout(session_factory, monkeypatch):
    """`wait_for` 取消等待者时若丢了许可，队列会永久少一格。

    这条用例就是那张网：429 之后必须还能跑满 2 路，否则说明许可泄漏。
    """
    monkeypatch.setattr(get_settings(), "execution_quota_timeout_s", 0.15)
    monkeypatch.setattr(get_settings(), "execution_concurrency", 2)
    executor = SlowExecutor(delay=0.4)

    first = [
        asyncio.create_task(
            _run_in_own_session(session_factory, source=SOURCE, executor=executor)
        )
        for _ in range(2)
    ]
    await asyncio.sleep(0.05)
    with pytest.raises(ApiError):
        await _run_in_own_session(session_factory, source="第三个", executor=executor)
    await asyncio.gather(*first)

    # 队列已空：再并发两路必须同时成功（任何一路 429 都说明许可泄漏）
    await asyncio.gather(
        *[
            _run_in_own_session(session_factory, source="再来一次", executor=executor)
            for _ in range(2)
        ]
    )
    async with session_factory() as s:
        rows = (await s.execute(select(CodeRun))).scalars().all()
    assert len(rows) == 4


@pytest.mark.asyncio
async def test_runs_are_isolated_between_users(session):
    await _svc(session).run(user_id="u1", language=PY, source=SOURCE)
    await _svc(session).run(user_id="u2", language=PY, source=SOURCE)
    await session.commit()
    rows = (await session.execute(select(CodeRun).where(CodeRun.user_id == "u1"))).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------- 草稿 CRUD

@pytest.mark.asyncio
async def test_draft_crud_lifecycle(session):
    svc = _svc(session)
    draft = await svc.create_draft(user_id="u1", language=PY, title="冒泡", source_code="a=1\n")
    await session.commit()
    assert draft.title == "冒泡"

    drafts = await svc.list_drafts(user_id="u1")
    assert [d.id for d in drafts] == [draft.id]

    updated = await svc.update_draft(
        user_id="u1", draft_id=draft.id, title="快排", source_code="b=2\n"
    )
    await session.commit()
    assert updated.title == "快排"
    assert updated.source_code == "b=2\n"

    await svc.delete_draft(user_id="u1", draft_id=draft.id)
    await session.commit()
    assert await svc.list_drafts(user_id="u1") == []


@pytest.mark.asyncio
async def test_drafts_are_isolated_between_users(session):
    svc = _svc(session)
    mine = await svc.create_draft(user_id="u1", language=PY, title="我的", source_code="x")
    await svc.create_draft(user_id="u2", language=PY, title="别人的", source_code="y")
    await session.commit()

    assert [d.id for d in await svc.list_drafts(user_id="u1")] == [mine.id]
    from app.core.errors import ApiError as _ApiError

    with pytest.raises(_ApiError) as exc:
        await svc.update_draft(user_id="u2", draft_id=mine.id, title="篡改")
    assert exc.value.code == 4040
    with pytest.raises(_ApiError):
        await svc.delete_draft(user_id="u2", draft_id=mine.id)


@pytest.mark.asyncio
async def test_draft_defaults_title(session):
    draft = await _svc(session).create_draft(user_id="u1", language=PY)
    await session.commit()
    assert draft.title == "未命名会话"
    assert draft.source_code == ""


# ---------------------------------------------------------------- 运行历史

@pytest.mark.asyncio
async def test_run_history_is_paginated_and_newest_first(session):
    svc = _svc(session)
    for i in range(5):
        await svc.run(user_id="u1", language=PY, source=f"print({i})\n")
    await session.commit()

    items, total = await svc.list_runs(user_id="u1", page=1, page_size=2)
    assert total == 5
    assert len(items) == 2
    assert items[0].source_code == "print(4)\n"
    assert items[1].source_code == "print(3)\n"

    items, total = await svc.list_runs(user_id="u1", page=3, page_size=2)
    assert len(items) == 1
    assert items[0].source_code == "print(0)\n"


@pytest.mark.asyncio
async def test_run_history_only_returns_own_runs(session):
    svc = _svc(session)
    await svc.run(user_id="u1", language=PY, source="a")
    await svc.run(user_id="u2", language=PY, source="b")
    await session.commit()
    _, total = await svc.list_runs(user_id="u1", page=1, page_size=10)
    assert total == 1


@pytest.mark.asyncio
async def test_run_history_records_timeout_status(session):
    svc = _svc(session, FakeExecutor(_result(status=STATUS_TIMEOUT, stdout="", exit_code=-9)))
    row = await svc.run(user_id="u1", language=PY, source="while True: pass")
    await session.commit()
    assert row.status == STATUS_TIMEOUT
    assert row.exit_code == -9


@pytest.mark.asyncio
async def test_draft_rows_are_code_sessions(session):
    """术语落库校验：草稿走 CodeSession 表，不是 CodeAnalysis。"""
    await _svc(session).create_draft(user_id="u1", language=PY, title="t", source_code="s")
    await session.commit()
    rows = (await session.execute(select(CodeSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].language == PY
