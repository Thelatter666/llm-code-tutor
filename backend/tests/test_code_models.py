"""CodeAnalysis 表测试（spec §5）。

spec §5 的 CodeAnalysis：user_id / language / source_hash / static_report(JSON)
/ ai_report(JSON?) / created_at。CodeSession 与 CodeRun 归 P4，本批不建。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.code.analysis import LANGUAGE_JAVASCRIPT, LANGUAGE_PYTHON, source_hash
from app.infrastructure.persistence.models import CodeAnalysis


@pytest.mark.asyncio
async def test_code_analysis_table_is_created(engine):
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    assert "code_analyses" in {r[0] for r in rows}


@pytest.mark.asyncio
async def test_code_session_and_code_run_tables_are_not_created(engine):
    """边界：这两张表归 P4（在线编辑器批次），本批不得提前创建。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    tables = {r[0] for r in rows}
    assert "code_sessions" not in tables
    assert "code_runs" not in tables


@pytest.mark.asyncio
async def test_json_columns_and_utc_timestamp(session):
    row = CodeAnalysis(
        user_id="u1",
        language=LANGUAGE_PYTHON,
        source_hash=source_hash(LANGUAGE_PYTHON, "x = 1"),
        static_report={"language": "python", "lines": {"total": 1, "code": 1}},
        ai_report={"content": "讲解", "provider": "mock", "usage_estimated": True},
    )
    session.add(row)
    await session.commit()

    got = (await session.execute(select(CodeAnalysis))).scalar_one()
    assert got.static_report["lines"]["code"] == 1
    assert got.ai_report["usage_estimated"] is True
    assert got.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_unique_constraint_on_user_language_hash(session):
    """「source_hash 命中复用、不重复算」在库层有唯一约束守卫。"""
    session.add(CodeAnalysis(user_id="u1", language=LANGUAGE_PYTHON, source_hash="h1", static_report={}))
    await session.flush()
    session.add(CodeAnalysis(user_id="u1", language=LANGUAGE_PYTHON, source_hash="h1", static_report={}))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_same_source_from_different_user_is_allowed(session):
    """复用按 user 隔离：不同学生分析同一份代码各自成行。"""
    session.add(CodeAnalysis(user_id="u1", language=LANGUAGE_PYTHON, source_hash="h1", static_report={}))
    session.add(CodeAnalysis(user_id="u2", language=LANGUAGE_PYTHON, source_hash="h1", static_report={}))
    await session.flush()
    rows = (await session.execute(select(CodeAnalysis))).scalars().all()
    assert len(rows) == 2


def test_source_hash_separates_language_and_content():
    h1 = source_hash(LANGUAGE_PYTHON, "x = 1")
    h2 = source_hash(LANGUAGE_PYTHON, "x = 2")
    h3 = source_hash(LANGUAGE_JAVASCRIPT, "x = 1")
    assert h1 != h2
    assert h1 != h3
