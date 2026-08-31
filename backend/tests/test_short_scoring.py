"""简答题 AI 评分领域层（spec §5.1 路 4，P5 Task 4）。

内部判分调用（Judging 意图完全豁免）：prompt 不走 PromptAssembler（四套主
模板面向学生辅导，会注入无关的防抄袭内容污染 JSON 输出，契约定稿 5）。
Mock 启发式必须确定性；`score<60 强制 is_correct=False` 是 spec §5.1 硬规则。
"""

import inspect

import pytest

from app.domain.exercise import short_scoring
from app.domain.exercise.short_scoring import (
    SHORT_PASS_SCORE,
    ShortJudgeParseError,
    build_short_judge_user_prompt,
    mock_short_score,
    parse_judge_json,
)

REFERENCE = "切片用 seq[start:stop:step]，stop 不含在结果内。"
EXPLANATION = "考察切片区间语义与步长。"
GOOD_ANSWER = "seq[start:stop:step]，stop 不含在结果内；省略 start 表示从头开始。"
BAD_ANSWER = "切片就是把列表切开的意思。"


def test_system_prompt_declares_json_contract():
    from app.domain.exercise.short_scoring import SHORT_JUDGE_SYSTEM_PROMPT

    assert "JSON" in SHORT_JUDGE_SYSTEM_PROMPT
    for key in ("score", "is_correct", "feedback"):
        assert key in SHORT_JUDGE_SYSTEM_PROMPT
    assert "60" in SHORT_JUDGE_SYSTEM_PROMPT


def test_user_prompt_contains_four_elements():
    prompt = build_short_judge_user_prompt("什么是切片？", REFERENCE, EXPLANATION, GOOD_ANSWER)
    assert "什么是切片？" in prompt, "缺题干"
    assert REFERENCE in prompt, "缺参考答案"
    assert EXPLANATION in prompt, "缺解析"
    assert GOOD_ANSWER in prompt, "缺学生作答"


def test_mock_heuristic_scores_good_answer_high():
    score, is_correct, feedback = mock_short_score(REFERENCE, EXPLANATION, GOOD_ANSWER)
    assert score >= SHORT_PASS_SCORE
    assert is_correct is True
    assert feedback


def test_mock_heuristic_scores_irrelevant_answer_low():
    score, is_correct, _ = mock_short_score(REFERENCE, EXPLANATION, BAD_ANSWER)
    assert score < SHORT_PASS_SCORE
    assert is_correct is False


def test_mock_heuristic_empty_answer_is_zero():
    score, is_correct, _ = mock_short_score(REFERENCE, EXPLANATION, "")
    assert score == 0
    assert is_correct is False


def test_mock_heuristic_is_deterministic():
    first = mock_short_score(REFERENCE, EXPLANATION, GOOD_ANSWER)
    second = mock_short_score(REFERENCE, EXPLANATION, GOOD_ANSWER)
    assert first == second


def test_parse_bare_json():
    score, is_correct, feedback = parse_judge_json(
        '{"score": 85, "is_correct": true, "feedback": "要点齐全"}'
    )
    assert (score, is_correct, feedback) == (85, True, "要点齐全")


def test_parse_json_in_code_fence():
    text = '```json\n{"score": 72, "is_correct": true, "feedback": "基本正确"}\n```'
    score, is_correct, feedback = parse_judge_json(text)
    assert (score, is_correct, feedback) == (72, True, "基本正确")


def test_parse_json_with_surrounding_prose():
    text = '评分如下：{"score": 40, "is_correct": true, "feedback": "欠缺"} 以上。'
    score, is_correct, feedback = parse_judge_json(text)
    assert (score, is_correct, feedback) == (40, False, "欠缺")


def test_parse_forces_incorrect_below_60():
    """spec §5.1「得分 <60 视为错误」：模型说对也不行。"""
    _, is_correct, _ = parse_judge_json('{"score": 30, "is_correct": true, "feedback": "x"}')
    assert is_correct is False


def test_parse_clamps_score_into_0_100():
    assert parse_judge_json('{"score": 150, "is_correct": true, "feedback": ""}')[0] == 100
    assert parse_judge_json('{"score": -5, "is_correct": false, "feedback": ""}')[0] == 0


def test_parse_rejects_non_json():
    with pytest.raises(ShortJudgeParseError):
        parse_judge_json("我觉得答案是列表切片，这个回答不错。")


def test_short_scoring_module_is_pure():
    src = inspect.getsource(short_scoring)
    for forbidden in ("sqlalchemy", "httpx", "requests", "asyncio", "open(", "Path("):
        assert forbidden not in src, f"简答评分领域层出现 {forbidden}"
