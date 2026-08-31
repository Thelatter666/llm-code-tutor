"""判题四路的纯规则（spec §5.1，P5 Task 2）。

四路的归集统一规则：`is_correct == false` 即入错题本（归集动作在服务层，
本模块只产判定）。multi 漏选判 50 且 is_correct=False 是变异测试目标。
"""

import inspect

from app.domain.exercise import judging
from app.domain.exercise.judging import (
    judge_blank,
    judge_choice,
    judge_coding,
    judge_multi,
)


def test_choice_correct_and_wrong():
    assert judge_choice("B", "B").score == 100
    assert judge_choice("B", "B").is_correct is True
    assert judge_choice("B", "A").score == 0
    assert judge_choice("B", "A").is_correct is False


def test_choice_missing_submission_is_wrong():
    """缺交（None / 空串）不是正确，也不得炸。"""
    assert judge_choice("B", None).is_correct is False
    assert judge_choice("B", "").is_correct is False


def test_blank_exact_match():
    outcome = judge_blank("print", "print")
    assert (outcome.score, outcome.is_correct) == (100, True)


def test_blank_tolerates_whitespace_and_case():
    """比对规则：去首尾空白 + casefold 忽略大小写（契约定稿 7）。"""
    assert judge_blank("Hello World", "  hello world ").is_correct is True


def test_blank_wrong_answer():
    outcome = judge_blank("len", "size")
    assert (outcome.score, outcome.is_correct) == (0, False)


def test_multi_all_correct():
    outcome = judge_multi(["A", "C"], ["C", "A"])
    assert (outcome.score, outcome.is_correct) == (100, True)


def test_multi_subset_scores_50_and_is_wrong():
    """漏选（所选为正确答案的真子集）→ 50 分且 is_correct=False（spec §5.1）。"""
    outcome = judge_multi(["A", "C"], ["A"])
    assert (outcome.score, outcome.is_correct) == (50, False)


def test_multi_with_wrong_choice_scores_zero():
    outcome = judge_multi(["A", "C"], ["A", "B"])
    assert (outcome.score, outcome.is_correct) == (0, False)


def test_multi_empty_selection_scores_zero():
    """空作答按未作答处理：0 分，不算漏选（裁定 8：不答不得 50）。"""
    outcome = judge_multi(["A", "C"], [])
    assert (outcome.score, outcome.is_correct) == (0, False)
    assert judge_multi(["A", "C"], None).is_correct is False


def test_multi_detail_reports_missing_and_wrong():
    outcome = judge_multi(["A", "C"], ["A", "B"])
    assert outcome.detail["missing"] == ["C"]
    assert outcome.detail["wrong"] == ["B"]

    outcome = judge_multi(["A", "C"], ["A"])
    assert outcome.detail["missing"] == ["C"]
    assert outcome.detail["wrong"] == []


def test_coding_partial_pass_ratio():
    outcome = judge_coding(passed=3, total=4, budget_exceeded=False, cases=[])
    assert (outcome.score, outcome.is_correct) == (75, False)


def test_coding_all_pass():
    outcome = judge_coding(passed=4, total=4, budget_exceeded=False, cases=[])
    assert (outcome.score, outcome.is_correct) == (100, True)


def test_coding_zero_pass():
    outcome = judge_coding(passed=0, total=4, budget_exceeded=False, cases=[])
    assert (outcome.score, outcome.is_correct) == (0, False)


def test_coding_budget_abort_counts_skipped_in_denominator():
    """15s 预算中止：未跑用例不计通过但计入分母 —— 2/5 通过给 40 分。"""
    outcome = judge_coding(passed=2, total=5, budget_exceeded=True, cases=[])
    assert (outcome.score, outcome.is_correct) == (40, False)
    assert outcome.detail["budget_exceeded"] is True


def test_direct_detail_shape():
    """契约定稿 8：direct 详情统一 method + passed；multi 另有 missing/wrong。"""
    assert judge_choice("B", "B").detail == {"method": "direct", "passed": True}
    assert judge_blank("x", "y").detail == {"method": "direct", "passed": False}


def test_judging_module_is_pure():
    """零 IO 是领域层硬约束（spec §4.2）：不许出现任何基础设施或 IO 痕迹。"""
    src = inspect.getsource(judging)
    for forbidden in ("sqlalchemy", "httpx", "requests", "asyncio", "open(", "Path("):
        assert forbidden not in src, f"判题领域层出现 {forbidden}"
