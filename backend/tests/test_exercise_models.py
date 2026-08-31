"""Exercise / Submission / MistakeBookEntry 三表（spec §5，P5 Task 1）。

无 ForeignKey（M-2 现状：全库级联靠服务层手工序列）；datetime 一律 UTCDateTime。
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.persistence.models import Exercise, MistakeBookEntry, Submission


def _exercise(**over) -> Exercise:
    fields = dict(
        type="choice",
        stem="以下哪个是合法的变量名？",
        options={"A": "2name", "B": "user_name", "C": "class", "D": "my-name"},
        answer="B",
        knowledge_tags=["变量与赋值"],
        difficulty=1,
        source="seed",
        status="published",
    )
    fields.update(over)
    return Exercise(**fields)


def _submission(exercise_id: str, **over) -> Submission:
    fields = dict(
        user_id="u-1",
        exercise_id=exercise_id,
        answer={"source": "print(1)"},
        is_correct=False,
        score=50,
        judge_detail={"method": "direct", "missing": ["C"]},
        feedback=None,
        attempt_no=1,
    )
    fields.update(over)
    return Submission(**fields)


def _mistake_entry(exercise_id: str, **over) -> MistakeBookEntry:
    fields = dict(
        user_id="u-1",
        exercise_id=exercise_id,
        wrong_count=1,
        consecutive_correct=0,
        last_wrong_answer={"selected": ["A", "B"]},
        mastered=False,
    )
    fields.update(over)
    return MistakeBookEntry(**fields)


@pytest.mark.asyncio
async def test_json_columns_round_trip(session):
    """六个 JSON 列写入后重读内容一致（spec §5 的 JSON 字段全量覆盖）。"""
    session.add(
        _exercise(
            type="coding",
            answer={"language": "python", "solution": "print(1)"},
            test_cases={"language": "python", "cases": [{"stdin": "", "expected_stdout": "1"}]},
        )
    )
    await session.flush()

    row = (await session.execute(select(Exercise))).scalar_one()
    assert row.options == {"A": "2name", "B": "user_name", "C": "class", "D": "my-name"}
    assert row.answer == {"language": "python", "solution": "print(1)"}
    assert row.test_cases["cases"][0]["expected_stdout"] == "1"
    assert row.knowledge_tags == ["变量与赋值"]


@pytest.mark.asyncio
async def test_submission_and_entry_json_round_trip(session):
    session.add(_exercise())
    await session.flush()
    exercise_id = (await session.execute(select(Exercise))).scalar_one().id

    session.add(_submission(exercise_id))
    session.add(_mistake_entry(exercise_id))
    await session.flush()

    sub = (await session.execute(select(Submission))).scalar_one()
    assert sub.answer == {"source": "print(1)"}
    assert sub.judge_detail == {"method": "direct", "missing": ["C"]}

    entry = (await session.execute(select(MistakeBookEntry))).scalar_one()
    assert entry.last_wrong_answer == {"selected": ["A", "B"]}


@pytest.mark.asyncio
async def test_created_at_is_utc_aware(session):
    """SQLite 回读 naive datetime 是已知坑（交接文档陷阱 6），必须带 UTC 时区。"""
    session.add(_exercise())
    await session.flush()

    row = (await session.execute(select(Exercise))).scalar_one()
    assert row.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_submission_is_correct_nullable(session):
    """spec §5 的 is_correct(bool?) —— 列必须允许 None。"""
    session.add(_exercise())
    await session.flush()
    exercise_id = (await session.execute(select(Exercise))).scalar_one().id

    session.add(_submission(exercise_id, is_correct=None))
    await session.flush()

    row = (await session.execute(select(Submission))).scalar_one()
    assert row.is_correct is None


@pytest.mark.asyncio
async def test_mistake_entry_unique_per_user_and_exercise(session):
    """唯一约束 (user_id, exercise_id)：同一学生对同一习题只有一条错题条目。"""
    session.add(_exercise())
    await session.flush()
    exercise_id = (await session.execute(select(Exercise))).scalar_one().id

    session.add(_mistake_entry(exercise_id))
    session.add(_mistake_entry(exercise_id, wrong_count=2))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_no_foreign_keys_on_new_tables(session):
    """M-2 现状：全库无 ForeignKey，级联靠服务层手工序列 —— 新表不得引入。"""
    for model in (Exercise, Submission, MistakeBookEntry):
        for column in model.__table__.columns:
            assert not column.foreign_keys, f"{model.__tablename__}.{column.name} 带 FK"


def test_difficulty_schema_rejects_out_of_range():
    """difficulty 1-5 的边界在 Pydantic 入参拒绝（spec §5），DB 层不设防。"""
    from app.schemas.exercise import ExerciseIn

    with pytest.raises(ValidationError):
        ExerciseIn(
            type="choice",
            stem="题干",
            answer="A",
            knowledge_tags=["变量与赋值"],
            difficulty=0,
        )
    with pytest.raises(ValidationError):
        ExerciseIn(
            type="choice",
            stem="题干",
            answer="A",
            knowledge_tags=["变量与赋值"],
            difficulty=6,
        )
    ok_in = ExerciseIn(
        type="choice",
        stem="题干",
        answer="A",
        knowledge_tags=["变量与赋值"],
        difficulty=3,
    )
    assert ok_in.difficulty == 3


def test_exercise_in_rejects_unknown_type():
    from app.schemas.exercise import ExerciseIn

    with pytest.raises(ValidationError):
        ExerciseIn(
            type="judge",
            stem="题干",
            answer="A",
            knowledge_tags=["变量与赋值"],
            difficulty=1,
        )
