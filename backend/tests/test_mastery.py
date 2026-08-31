"""掌握度状态机（spec §8.5，P5 Task 3）。

掌握度可回滚是硬要求（spec §8.5 / 交接文档陷阱 4）：错误时必须
`mastered=false`、`mastered_at=null`，否则错题本默认过滤会把「已掌握又答错」
的条目永久排除，「错题驱动学习」退化为单向门。
"""

from datetime import UTC, datetime

from app.domain.exercise.mastery import (
    MASTERY_THRESHOLD,
    MasteryState,
    apply_answer,
)

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 31, 13, 0, 0, tzinfo=UTC)


def test_wrong_without_entry_creates_entry():
    state = apply_answer(None, is_correct=False, wrong_answer={"selected": ["A"]}, now=NOW)
    assert state.wrong_count == 1
    assert state.consecutive_correct == 0
    assert state.mastered is False
    assert state.last_wrong_answer == {"selected": ["A"]}
    assert state.last_wrong_at == NOW


def test_correct_without_entry_counts_streak():
    state = apply_answer(None, is_correct=True, now=NOW)
    assert state.consecutive_correct == 1
    assert state.wrong_count == 0
    assert state.mastered is False


def test_two_consecutive_correct_masters():
    state = apply_answer(None, is_correct=True, now=NOW)
    state = apply_answer(state, is_correct=True, now=LATER)
    assert state.mastered is True
    assert state.mastered_at == LATER
    assert state.consecutive_correct == MASTERY_THRESHOLD == 2


def test_streak_breaks_on_wrong():
    state = apply_answer(None, is_correct=True, now=NOW)
    state = apply_answer(state, is_correct=False, wrong_answer="x", now=LATER)
    assert state.consecutive_correct == 0
    assert state.mastered is False
    assert state.wrong_count == 1


def test_mastered_rolls_back_on_wrong():
    """回滚专项（变异测试目标）：已掌握后再答错必须回到未掌握。"""
    mastered = MasteryState(
        wrong_count=3, consecutive_correct=2, mastered=True, mastered_at=NOW
    )
    state = apply_answer(mastered, is_correct=False, wrong_answer="wrong!", now=LATER)

    assert state.mastered is False
    assert state.mastered_at is None
    assert state.wrong_count == 4
    assert state.consecutive_correct == 0
    assert state.last_wrong_answer == "wrong!"
    assert state.last_wrong_at == LATER


def test_mastered_stays_on_correct():
    mastered = MasteryState(wrong_count=1, consecutive_correct=2, mastered=True, mastered_at=NOW)
    state = apply_answer(mastered, is_correct=True, now=LATER)

    assert state.mastered is True
    assert state.mastered_at == NOW, "已掌握后答对不重置掌握时间"
    assert state.consecutive_correct == 3


def test_last_wrong_answer_is_overwritten_each_time():
    state = apply_answer(None, is_correct=False, wrong_answer="第一次", now=NOW)
    state = apply_answer(state, is_correct=True, now=LATER)
    state = apply_answer(state, is_correct=False, wrong_answer="第二次", now=LATER)
    assert state.last_wrong_answer == "第二次"


def test_apply_answer_is_pure():
    """纯函数语义：不得原地改传入状态（服务层靠返回值落库）。"""
    original = MasteryState(wrong_count=1, consecutive_correct=1)
    frozen = MasteryState(**original.__dict__)
    apply_answer(original, is_correct=False, wrong_answer="x", now=NOW)
    assert original.__dict__ == frozen.__dict__


def test_wrong_resets_mastery_time_to_null():
    state = apply_answer(None, is_correct=False, wrong_answer="a", now=NOW)
    assert state.mastered_at is None
