"""习题写入的跨题型形状规则（契约定稿 7，零 IO）。

spec §5 只写了 `answer` / `test_cases` 是 JSON，各题型的形态由 P5 契约定稿 7
定稿。admin CRUD（Task 11）与习题种子（Task 13）共用这一份规则，避免
「创建时校验一套、种子校验另一套」这种两套口径各自漂移的局面。

返回**问题清单**而不抛异常：调用方可能是 Pydantic 校验器（转 422）、也可能是
种子自校验（转断言失败），两者对「怎么报告」各有主张，规则本身只负责回答
「这组字段配不配套」。
"""

from app.domain.exercise.judging import (
    EXERCISE_TYPES,
    TYPE_BLANK,
    TYPE_CHOICE,
    TYPE_CODING,
    TYPE_MULTI,
    TYPE_SHORT,
)

# 只有选择题族有选项
_TYPES_WITH_OPTIONS = (TYPE_CHOICE, TYPE_MULTI)


def check_exercise_shape(
    *,
    type: str,
    options: object = None,
    answer: object = None,
    test_cases: object = None,
) -> list[str]:
    """按题型检查 options / answer / test_cases 是否配套；返回问题清单（空=合法）。"""
    # 未知题型不静默通过：Pydantic 的枚举先拒是常规路径，但种子与直接调用本函数的
    # 调用方绕过了 Pydantic，这里必须自己兜住（否则一道 type 拼错的习题永远不会被拒）
    if type not in EXERCISE_TYPES:
        return [f"未知题型：{type}"]

    problems: list[str] = []

    if type not in _TYPES_WITH_OPTIONS and options:
        problems.append(f"{type} 题型不应携带 options")
    if type != TYPE_CODING and test_cases:
        problems.append(f"{type} 题型不应携带 test_cases")

    if type == TYPE_CHOICE:
        problems += _check_options(options)
        if not isinstance(answer, str) or not answer:
            problems.append("单选题的 answer 必须是选项键字符串")
        elif isinstance(options, dict) and answer not in options:
            problems.append(f"单选题的答案键 {answer} 不在 options 中")
    elif type == TYPE_MULTI:
        problems += _check_options(options)
        problems += _check_multi_answer(answer, options)
    elif type in (TYPE_BLANK, TYPE_SHORT):
        if not isinstance(answer, str) or not answer.strip():
            label = "填空题" if type == TYPE_BLANK else "简答题"
            problems.append(f"{label}的 answer 必须是非空的参考答案文本")
    elif type == TYPE_CODING:
        problems += _check_coding(answer, test_cases)

    return problems


def _check_options(options: object) -> list[str]:
    if not isinstance(options, dict) or not options:
        return ["选择题必须提供非空的 options（形如 {\"A\": 选项文本}）"]
    bad_keys = [k for k, v in options.items() if not isinstance(k, str) or not k.strip()]
    bad_values = [k for k, v in options.items() if not isinstance(v, str) or not v.strip()]
    problems = []
    if bad_keys:
        problems.append("options 的键必须是非空字符串")
    if bad_values:
        problems.append(f"options 的选项文本必须非空：{bad_values}")
    return problems


def _check_multi_answer(answer: object, options: object) -> list[str]:
    if not isinstance(answer, list) or not answer:
        return ["多选题的 answer 必须是选项键数组（形如 [\"A\",\"C\"]）"]
    if any(not isinstance(item, str) for item in answer):
        return ["多选题的 answer 数组元素必须是选项键字符串"]
    problems = []
    if len(set(answer)) != len(answer):
        problems.append("多选题的 answer 存在重复选项键")
    if isinstance(options, dict):
        unknown = [item for item in answer if item not in options]
        if unknown:
            problems.append(f"多选题的答案键不在 options 中：{unknown}")
    return problems


def _check_coding(answer: object, test_cases: object) -> list[str]:
    if not isinstance(answer, dict) or not answer:
        return ["编程题的 answer 必须是对象（形如 {\"language\", \"solution\"}，契约定稿 7）"]
    if not isinstance(test_cases, dict) or not test_cases:
        return ["编程题必须提供 test_cases（它决定用什么语言、怎么跑）"]

    problems = []
    language = test_cases.get("language")
    if not isinstance(language, str) or not language.strip():
        problems.append("test_cases 必须指明 language")

    cases = test_cases.get("cases")
    if not isinstance(cases, list) or not cases:
        problems.append("test_cases.cases 必须是非空数组")
    else:
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                problems.append(f"test_cases.cases[{index}] 必须是对象")
                continue
            if "expected_stdout" not in case:
                problems.append(f"test_cases.cases[{index}] 缺 expected_stdout")
            elif not isinstance(case["expected_stdout"], str):
                problems.append(f"test_cases.cases[{index}].expected_stdout 必须是字符串")
            stdin = case.get("stdin", "")
            if not isinstance(stdin, str):
                problems.append(f"test_cases.cases[{index}].stdin 必须是字符串")
    return problems
