"""ExerciseService 判题编排（spec §5.1 §8.5，P5 Task 6）。

15s 累计预算是已裁定语义：端口无 per-call 超时，服务层跨用例自计，超预算
中止剩余用例并按已通过比例判分。测试注入小预算 + FakeExecutor 延迟，
不 monkeypatch 常量。
"""

import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select

from app.core.crypto import encrypt_api_key
from app.core.errors import ApiError
from app.domain.exercise.judging import TYPE_CODING
from app.infrastructure.persistence.models import (
    AuditLog,
    Exercise,
    MistakeBookEntry,
    Submission,
)
from app.infrastructure.registry import get_or_create_singleton
from app.services.exercise_service import ExerciseService
from tests.fakes import FakeExecutor, FakeLLM, execution_result, fake_llm_runtime

RID = "rid-exercise-service"


async def _add_exercise(session, **over) -> Exercise:
    fields: dict = {
        "type": "choice",
        "stem": "以下哪个是合法的变量名？",
        "options": {"A": "2name", "B": "user_name"},
        "answer": "B",
        "knowledge_tags": ["变量与赋值"],
        "difficulty": 1,
        "source": "seed",
        "status": "published",
    }
    fields.update(over)
    row = Exercise(**fields)
    session.add(row)
    await session.flush()
    return row


async def _mistake_entries(session, user_id: str) -> list[MistakeBookEntry]:
    rows = await session.execute(
        select(MistakeBookEntry).where(MistakeBookEntry.user_id == user_id)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------- 即时判分


@pytest.mark.asyncio
async def test_choice_correct_scores_100(session):
    ex = await _add_exercise(session)
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer="B", request_id=RID
    )

    assert sub.score == 100
    assert sub.is_correct is True
    assert sub.judge_detail["method"] == "direct"
    assert sub.attempt_no == 1
    assert sub.feedback is None
    assert await _mistake_entries(session, "u-1") == [], "答对不得入错题本"


@pytest.mark.asyncio
async def test_choice_wrong_scores_0(session):
    ex = await _add_exercise(session)
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(user_id="u-1", exercise_id=ex.id, answer="A", request_id=RID)

    assert (sub.score, sub.is_correct) == (0, False)
    entries = await _mistake_entries(session, "u-1")
    assert len(entries) == 1, "is_correct=false 即入错题本（spec §5.1）"
    assert entries[0].last_wrong_answer == "A"


@pytest.mark.asyncio
async def test_blank_tolerates_case_and_whitespace(session):
    ex = await _add_exercise(
        session, type="blank", options=None, answer="Hello World"
    )
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer="  hello world ", request_id=RID
    )
    assert sub.is_correct is True


@pytest.mark.asyncio
async def test_multi_subset_scores_50_and_is_wrong(session):
    """漏选判 50 且 is_correct=False（变异测试目标）。"""
    ex = await _add_exercise(
        session, type="multi", options={"A": "1", "B": "2", "C": "3"}, answer=["A", "C"]
    )
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer=["A"], request_id=RID
    )

    assert (sub.score, sub.is_correct) == (50, False)
    assert sub.judge_detail["missing"] == ["C"]
    entries = await _mistake_entries(session, "u-1")
    assert len(entries) == 1, "漏选按错误处理，计入错题本"


@pytest.mark.asyncio
async def test_multi_full_correct_scores_100(session):
    ex = await _add_exercise(
        session, type="multi", options={"A": "1", "B": "2", "C": "3"}, answer=["A", "C"]
    )
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer=["C", "A"], request_id=RID
    )
    assert (sub.score, sub.is_correct) == (100, True)
    assert await _mistake_entries(session, "u-1") == []


@pytest.mark.asyncio
async def test_multi_wrong_choice_scores_0(session):
    ex = await _add_exercise(
        session, type="multi", options={"A": "1", "B": "2", "C": "3"}, answer=["A", "C"]
    )
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer=["A", "B"], request_id=RID
    )
    assert (sub.score, sub.is_correct) == (0, False)


# ---------------------------------------------------------------- 编程判分


def _coding_exercise(cases: list[dict]) -> dict:
    return {
        "type": TYPE_CODING,
        "options": None,
        "answer": {"language": "python", "solution": "print(input())"},
        "test_cases": {"language": "python", "cases": cases},
    }


@pytest.mark.asyncio
async def test_coding_all_pass_scores_100(session):
    cases = [{"stdin": "1", "expected_stdout": "1"}, {"stdin": "2", "expected_stdout": "2"}]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    fake = FakeExecutor(
        results=[execution_result(stdout="1\n"), execution_result(stdout="2\n")]
    )
    svc = ExerciseService(session, executor=fake)

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer={"source": "print(input())"}, request_id=RID
    )

    assert (sub.score, sub.is_correct) == (100, True)
    detail = sub.judge_detail
    assert detail["method"] == "executed"
    assert detail["language"] == "python"
    assert detail["budget_exceeded"] is False
    assert [c["expected_stdout"] for c in detail["cases"]] == ["1", "2"]
    assert [c["actual_stdout"] for c in detail["cases"]] == ["1\n", "2\n"]
    assert len(fake.calls) == 2
    assert fake.calls[0]["stdin"] == "1", "用例输入必须经 stdin 透传"


@pytest.mark.asyncio
async def test_coding_partial_pass_scores_by_ratio(session):
    cases = [{"stdin": "", "expected_stdout": "1"}, {"stdin": "", "expected_stdout": "2"}]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    fake = FakeExecutor(
        results=[execution_result(stdout="1\n"), execution_result(stdout="oops\n")]
    )
    svc = ExerciseService(session, executor=fake)

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer={"source": "print(1)"}, request_id=RID
    )
    assert (sub.score, sub.is_correct) == (50, False)


@pytest.mark.asyncio
async def test_coding_budget_abort_marks_skipped_and_scores_by_ratio(session):
    """15s 累计预算（已裁定）：超预算中止剩余用例，judge_detail 体现中止。"""
    cases = [{"stdin": "", "expected_stdout": str(i)} for i in range(5)]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    fake = FakeExecutor(
        results=[execution_result(stdout=f"{i}\n") for i in range(5)],
        delay_s=0.2,
    )
    svc = ExerciseService(session, executor=fake, budget_seconds=0.35)

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer={"source": "print(1)"}, request_id=RID
    )

    detail = sub.judge_detail
    assert detail["budget_exceeded"] is True
    skipped = [c for c in detail["cases"] if c.get("skipped")]
    executed = [c for c in detail["cases"] if not c.get("skipped")]
    assert len(skipped) >= 3, "0.35s 预算 + 0.2s/用例：最多跑 2 个用例"
    assert len(skipped) + len(executed) == 5
    assert all(c["skip_reason"] == "budget_exceeded" for c in skipped)
    passed = len(executed)
    assert sub.score == round(passed / 5 * 100)
    assert sub.is_correct is False, "未全部通过即错误"


@pytest.mark.asyncio
async def test_coding_offloads_to_threadpool_and_slot(session):
    """ADR-0002 / 权衡 14：执行经 run_in_threadpool + execution_slot。"""
    import app.services.exercise_service as svc_module

    cases = [{"stdin": "", "expected_stdout": "ok"}]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    fake = FakeExecutor(results=[execution_result(stdout="ok\n")])

    real_threadpool = svc_module.run_in_threadpool
    real_slot = svc_module.execution_slot
    calls = {"threadpool": 0, "slot": 0}

    async def counting_slot():
        calls["slot"] += 1
        async with real_slot():
            yield

    counting_slot = asynccontextmanager(counting_slot)

    async def counting_threadpool(fn, *args, **kwargs):
        calls["threadpool"] += 1
        return await real_threadpool(fn, *args, **kwargs)

    svc = ExerciseService(session, executor=fake)
    orig_slot = svc_module.execution_slot
    orig_tp = svc_module.run_in_threadpool
    svc_module.execution_slot = counting_slot
    svc_module.run_in_threadpool = counting_threadpool
    try:
        await svc.submit(
            user_id="u-1",
            exercise_id=ex.id,
            answer={"source": "print('ok')"},
            request_id=RID,
        )
    finally:
        svc_module.execution_slot = orig_slot
        svc_module.run_in_threadpool = orig_tp

    assert calls["threadpool"] == 1
    assert calls["slot"] == 1


@pytest.mark.asyncio
async def test_coding_blacklisted_source_scores_zero(session):
    """黑名单由执行器拦截：每用例 blocked → 0 分且错误。"""
    cases = [{"stdin": "", "expected_stdout": "1"}]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    svc = ExerciseService(session, executor=FakeExecutor())

    sub = await svc.submit(
        user_id="u-1",
        exercise_id=ex.id,
        answer={"source": "import os\nos.system('echo hi')"},
        request_id=RID,
    )
    assert (sub.score, sub.is_correct) == (0, False)
    assert sub.judge_detail["cases"][0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_coding_answer_without_source_is_4220(session):
    cases = [{"stdin": "", "expected_stdout": "1"}]
    ex = await _add_exercise(session, **_coding_exercise(cases))
    svc = ExerciseService(session, executor=FakeExecutor())

    with pytest.raises(ApiError) as exc:
        await svc.submit(user_id="u-1", exercise_id=ex.id, answer="print(1)", request_id=RID)
    assert exc.value.code == 4220


# ---------------------------------------------------------------- 简答评分


async def _make_real_provider_config(session) -> None:
    cfg = await get_or_create_singleton(session)
    cfg.provider = "openai_compat"
    cfg.api_key_encrypted = encrypt_api_key("sk-test")
    await session.flush()


@pytest.mark.asyncio
async def test_short_real_provider_scores_from_json(session):
    ex = await _add_exercise(session, type="short", options=None, answer="参考答案")
    await _make_real_provider_config(session)
    reply = json.dumps({"score": 85, "is_correct": True, "feedback": "要点齐全"})
    fake_llm = FakeLLM(reply=reply)
    svc = ExerciseService(session, executor=FakeExecutor(), llm=fake_llm_runtime(fake_llm))

    sub = await svc.submit(user_id="u-1", exercise_id=ex.id, answer="我的作答", request_id=RID)

    assert (sub.score, sub.is_correct) == (85, True)
    assert sub.feedback == "要点齐全"
    assert sub.judge_detail["ai_scored"] is True
    assert sub.judge_detail["judge_mode"] == "model"
    assert len(fake_llm.messages) == 1, "判分是非流式 complete 调用"
    system = fake_llm.messages[0][0].content
    user = fake_llm.messages[0][-1].content
    assert "JSON" in system
    assert "参考答案" in user and "我的作答" in user


@pytest.mark.asyncio
async def test_short_mock_config_uses_heuristic_without_llm(session):
    """Mock 判定取配置层（同 §8.4 口径）：不发起 LLM 调用。"""
    ex = await _add_exercise(session, type="short", options=None, answer="参考答案")
    fake_llm = FakeLLM(reply="不应被调用")
    svc = ExerciseService(session, executor=FakeExecutor(), llm=fake_llm_runtime(fake_llm))

    sub = await svc.submit(
        user_id="u-1", exercise_id=ex.id, answer="参考答案", request_id=RID
    )

    assert len(fake_llm.messages) == 0, "Mock 模式零 LLM 调用"
    assert sub.judge_detail["ai_scored"] is True
    assert sub.judge_detail["judge_mode"] == "mock_heuristic"
    assert sub.is_correct is True


@pytest.mark.asyncio
async def test_short_unparseable_output_raises_5021_and_persists_nothing(session):
    """把「模型故障」记成「学生答错」比丢一次提交更糟：5021 且不落库。"""
    ex = await _add_exercise(session, type="short", options=None, answer="参考答案")
    await _make_real_provider_config(session)
    fake_llm = FakeLLM(reply="我觉得答得不错，给个好评。")
    svc = ExerciseService(session, executor=FakeExecutor(), llm=fake_llm_runtime(fake_llm))

    with pytest.raises(ApiError) as exc:
        await svc.submit(user_id="u-1", exercise_id=ex.id, answer="作答", request_id=RID)
    assert exc.value.code == 5021

    count = (
        await session.execute(select(func.count()).select_from(Submission))
    ).scalar_one()
    assert count == 0, "评分失败不得落 Submission"
    assert await _mistake_entries(session, "u-1") == [], "评分失败不得入错题本"


@pytest.mark.asyncio
async def test_short_below_60_enters_mistake_book(session):
    ex = await _add_exercise(session, type="short", options=None, answer="参考答案")
    await _make_real_provider_config(session)
    fake_llm = FakeLLM(reply=json.dumps({"score": 45, "is_correct": True, "feedback": "不足"}))
    svc = ExerciseService(session, executor=FakeExecutor(), llm=fake_llm_runtime(fake_llm))

    sub = await svc.submit(user_id="u-1", exercise_id=ex.id, answer="作答", request_id=RID)
    assert sub.score == 45
    assert sub.is_correct is False, "score<60 强制 is_correct=false（spec §5.1）"
    assert len(await _mistake_entries(session, "u-1")) == 1


@pytest.mark.asyncio
async def test_short_pass_does_not_create_entry(session):
    """从未答错的正确提交不建错题条目 —— 错题本只收错误。"""
    ex = await _add_exercise(session, type="short", options=None, answer="参考答案")
    await _make_real_provider_config(session)
    fake_llm = FakeLLM(reply=json.dumps({"score": 80, "is_correct": True, "feedback": "好"}))
    svc = ExerciseService(session, executor=FakeExecutor(), llm=fake_llm_runtime(fake_llm))

    sub = await svc.submit(user_id="u-1", exercise_id=ex.id, answer="作答", request_id=RID)
    assert sub.is_correct is True
    assert await _mistake_entries(session, "u-1") == []


# ---------------------------------------------------------------- 其他编排


@pytest.mark.asyncio
async def test_attempt_no_increments(session):
    ex = await _add_exercise(session)
    svc = ExerciseService(session, executor=FakeExecutor())

    for expected_no in (1, 2, 3):
        sub = await svc.submit(
            user_id="u-1", exercise_id=ex.id, answer="B" if expected_no == 3 else "A", request_id=RID
        )
        assert sub.attempt_no == expected_no


@pytest.mark.asyncio
async def test_submit_missing_or_draft_exercise_is_4040(session):
    await _add_exercise(session, status="draft")
    svc = ExerciseService(session, executor=FakeExecutor())

    with pytest.raises(ApiError) as exc:
        await svc.submit(user_id="u-1", exercise_id="no-such", answer="B", request_id=RID)
    assert exc.value.code == 4040

    draft_id = (await session.execute(select(Exercise))).scalar_one().id
    with pytest.raises(ApiError) as exc:
        await svc.submit(user_id="u-1", exercise_id=draft_id, answer="B", request_id=RID)
    assert exc.value.code == 4040, "学生端只暴露 published（spec §6.2）"


@pytest.mark.asyncio
async def test_submit_writes_audit_log(session):
    ex = await _add_exercise(session)
    svc = ExerciseService(session, executor=FakeExecutor())

    await svc.submit(user_id="u-1", exercise_id=ex.id, answer="B", request_id=RID)

    row = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "exercise_submit")
        )
    ).scalar_one()
    assert row.user_id == "u-1"
    assert row.request_id == RID


@pytest.mark.asyncio
async def test_wrong_then_correct_advances_mastery_state(session):
    """错误 → 建条目；答对 → consecutive_correct 推进（服务层端到端）。"""
    ex = await _add_exercise(session)
    svc = ExerciseService(session, executor=FakeExecutor())

    await svc.submit(user_id="u-1", exercise_id=ex.id, answer="A", request_id=RID)
    await svc.submit(user_id="u-1", exercise_id=ex.id, answer="B", request_id=RID)

    entry = (await _mistake_entries(session, "u-1"))[0]
    assert entry.wrong_count == 1
    assert entry.consecutive_correct == 1
    assert entry.mastered is False


@pytest.mark.asyncio
async def test_service_uses_default_budget_constant(session):
    """缺省预算取领域常量 15s（生产语义），构造参数只用于测试注入。"""
    from app.domain.exercise.judging import JUDGING_BUDGET_S

    svc = ExerciseService(session, executor=FakeExecutor())
    assert svc._budget_seconds == JUDGING_BUDGET_S == 15.0
