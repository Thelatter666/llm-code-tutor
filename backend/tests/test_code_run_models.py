"""CodeSession / CodeRun 表（spec §5，P4）。

`limit_detail` 是本批次的证据载体 —— 四层限制各自记录 `applied` / `triggered`
与实测值。测试锁住的是「嵌套结构能原样往返」与「五种 status 都能落库」。
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.domain.code.execution import RUN_STATUSES
from app.infrastructure.persistence.models import CodeRun, CodeSession


@pytest_asyncio.fixture
async def _rows(session):
    """两表各插一行，返回 (session_row, run_row)。"""
    draft = CodeSession(
        user_id="u-1",
        language="python",
        title="冒泡排序",
        source_code="def bubble(xs):\n    return xs\n",
    )
    session.add(draft)
    run = CodeRun(
        user_id="u-1",
        language="python",
        source_code="print(1)\n",
        stdin="",
        status="accepted",
        stdout="1\n",
        stderr="",
        exit_code=0,
        duration_ms=42,
        limit_detail={
            "wall_clock": {"limit_s": 5.0, "elapsed_s": 0.042, "triggered": False},
            "cpu": {"limit_s": 3, "applied": True, "triggered": False},
            "memory": {
                "limit_bytes": 268435456,
                "sampled": True,
                "interval_ms": 100,
                "peak_bytes": 12345678,
                "samples": 3,
                "triggered": False,
            },
            "file_size": {"limit_bytes": 1048576, "applied": True, "error": None},
            "output": {"limit_bytes": 8192, "stdout_truncated": False, "stderr_truncated": False},
        },
    )
    session.add(run)
    await session.commit()
    return draft, run


async def test_tables_are_created_by_create_all(engine):
    async with engine.connect() as conn:
        names = set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))
    assert {"code_sessions", "code_runs"} <= names


async def test_code_session_roundtrip(session, _rows):
    draft, _ = _rows
    loaded = (await session.execute(select(CodeSession))).scalar_one()
    assert loaded.id == draft.id
    assert loaded.user_id == "u-1"
    assert loaded.language == "python"
    assert loaded.title == "冒泡排序"
    assert loaded.source_code == "def bubble(xs):\n    return xs\n"


async def test_code_session_updated_at_advances_on_change(session, _rows):
    """P2 的 Conversation 因缺 onupdate 出过 bug（H2）；草稿改名必须推进 updated_at。"""
    draft, _ = _rows
    before = draft.updated_at
    draft.title = "快排"
    await session.commit()
    await session.refresh(draft)
    assert draft.updated_at > before


async def test_code_run_limit_detail_roundtrips_nested_dict(session, _rows):
    session.expunge_all()
    loaded = (await session.execute(select(CodeRun))).scalar_one()
    detail = loaded.limit_detail
    assert detail["memory"]["peak_bytes"] == 12345678
    assert detail["memory"]["interval_ms"] == 100
    assert detail["cpu"]["applied"] is True
    assert detail["file_size"]["limit_bytes"] == 1048576
    assert detail["output"]["stdout_truncated"] is False
    assert detail["wall_clock"]["elapsed_s"] == 0.042


@pytest.mark.parametrize("status", RUN_STATUSES)
async def test_all_run_statuses_persist(session, status):
    session.add(
        CodeRun(
            user_id="u-2",
            language="python",
            source_code="x",
            stdin="",
            status=status,
            stdout="",
            stderr="",
            duration_ms=0,
        )
    )
    await session.commit()
    rows = (
        await session.execute(select(CodeRun).where(CodeRun.user_id == "u-2"))
    ).scalars().all()
    assert [r.status for r in rows] == [status]


async def test_exit_code_is_nullable_for_blocked_runs(session):
    """命中黑名单时代码根本没跑，exit_code 为 None 而不是 0。"""
    session.add(
        CodeRun(
            user_id="u-3",
            language="python",
            source_code="os.system('ls')",
            stdin="",
            status="blocked",
            stdout="",
            stderr="命中黑名单规则：os_system",
            exit_code=None,
            duration_ms=0,
            limit_detail={"blacklist": {"rule": "os_system", "executed": False}},
        )
    )
    await session.commit()
    row = (await session.execute(select(CodeRun).where(CodeRun.user_id == "u-3"))).scalar_one()
    assert row.exit_code is None
    assert row.limit_detail["blacklist"]["executed"] is False


async def test_created_at_carries_utc_timezone(session, _rows):
    draft, run = _rows
    for row in (draft, run):
        assert row.created_at.tzinfo is not None
        assert row.created_at.utcoffset() == datetime.now(UTC).utcoffset()


async def test_code_run_is_indexed_by_user_id(engine):
    """历史查询恒定按 user_id 过滤（GET /code/runs），必须有索引。"""
    async with engine.connect() as conn:
        indexes = await conn.run_sync(
            lambda sync: {i["name"] for i in inspect(sync).get_indexes("code_runs")}
        )
    assert any("user_id" in (name or "") for name in indexes)


async def test_code_run_requires_status(session):
    session.add(
        CodeRun(user_id="u-4", language="python", source_code="x", stdin="", stdout="", stderr="")
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
