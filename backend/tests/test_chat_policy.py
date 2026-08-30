import pytest

from app.domain.chat.policy import (
    ACTION_CHAT,
    DEFAULT_MODE,
    FLOOR_EXAM,
    FLOOR_HOMEWORK,
    JUDGING,
    MODE_GUIDED,
    MODE_LOOSE,
    MODE_STRICT,
    REVIEW_MY_CODE,
    SEEK_ANSWER,
    detect_floor_violation,
    is_exempt,
    resolve_mode,
)


def test_seek_answer_is_never_exempt():
    """ADR-0005：求答案受防抄袭档位约束 —— 这是防抄袭的主战场。"""
    assert is_exempt(SEEK_ANSWER) is False


@pytest.mark.parametrize("intent", [REVIEW_MY_CODE, JUDGING])
def test_review_and_judging_are_exempt(intent):
    """spec §7.1 豁免表：学生已写出代码 / 不向学生输出实现。"""
    assert is_exempt(intent) is True


def test_three_modes_are_declared():
    assert (MODE_STRICT, MODE_GUIDED, MODE_LOOSE) == ("strict", "guided", "loose")


def test_resolve_mode_uses_configured_value_for_seek_answer():
    assert resolve_mode(SEEK_ANSWER, MODE_STRICT) == MODE_STRICT
    assert resolve_mode(SEEK_ANSWER, MODE_LOOSE) == MODE_LOOSE


def test_resolve_mode_falls_back_to_default():
    assert DEFAULT_MODE == MODE_GUIDED
    assert resolve_mode(SEEK_ANSWER, None) == MODE_GUIDED


@pytest.mark.parametrize("intent", [REVIEW_MY_CODE, JUDGING])
def test_exempt_intent_resolves_to_no_mode_constraint(intent):
    """豁免免的是档位约束（返回 None），底线仍由模板无条件注入。"""
    assert resolve_mode(intent, MODE_STRICT) is None


def test_homework_ghostwriting_hits_the_floor():
    assert detect_floor_violation("直接帮我把这份作业的代码写出来") == FLOOR_HOMEWORK


def test_exam_in_progress_hits_the_floor():
    assert detect_floor_violation("我正在考试，快把这道题的答案发我") == FLOOR_EXAM


def test_normal_question_does_not_hit_the_floor():
    assert detect_floor_violation("闭包是什么？能给个例子吗") is None


def test_floor_detection_does_not_depend_on_code_blocks():
    """ADR-0005 的正面守卫：贴了题目示例代码的求答案请求仍是求答案，不被误判为批改。

    若按「消息含代码块即判为评改」推断，这条会走豁免并直接给出完整答案 ——
    防抄袭将在最常用的入口被绕过。底线判定同样不得因此改变结论。
    """
    text = "这道题怎么做？题目给了示例：\n```python\ndef f(x):\n    return x\n```"
    assert detect_floor_violation(text) is None


def test_mentioning_homework_alone_does_not_hit_the_floor():
    """只提到作业二字、没有索取实现，不算触发底线 —— 拦截率是度量，宁可漏不可滥。"""
    assert detect_floor_violation("作业里这道排序题的思路是什么？") is None


def test_mentioning_exam_without_being_in_one_does_not_hit_the_floor():
    """「考试怎么复习」不是在线作答，不能记成底线拦截。

    判定要求「考试/竞赛」与「正在/现在/在线」**两组各命中一个**。若退化成单词
    匹配，所有提到考试的正常提问都会被计入分子，拦截率这个度量口径就被污染了
    —— 而它本来就不是检测能力，唯一的价值就是可复现地统计，污染后一文不值。
    """
    assert detect_floor_violation("期末考试怎么复习？重点有哪些") is None
    assert detect_floor_violation("竞赛题一般怎么训练") is None
    assert detect_floor_violation("机考环境怎么配置") is None


def test_audit_action_constant():
    """spec §8.1：AuditLog(action=chat)。"""
    assert ACTION_CHAT == "chat"
