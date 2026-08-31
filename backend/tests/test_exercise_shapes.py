"""跨题型形状规则（契约定稿 7，P5 Task 11 的领域层部分）。

admin CRUD 与习题种子（Task 13）共用这一份规则，故它需要自己的纯单测：
HTTP 层的 422 只能证明「某处拒了」，证不了规则本身的取值边界。
"""

import inspect

import pytest

from app.domain.exercise import shapes as shapes_module
from app.domain.exercise.shapes import check_exercise_shape


def test_shapes_module_is_pure():
    """零 IO 是领域层硬约束（spec §4.2）。"""
    src = inspect.getsource(shapes_module)
    for forbidden in ("sqlalchemy", "httpx", "requests", "asyncio", "open(", "Path("):
        assert forbidden not in src, f"形状规则领域层出现 {forbidden}"


def test_no_problems_for_each_declared_shape():
    """契约定稿 7 的五种形态逐一放行。"""
    valid = [
        {
            "type": "choice",
            "options": {"A": "1", "B": "2"},
            "answer": "B",
        },
        {
            "type": "multi",
            "options": {"A": "1", "B": "2", "C": "3"},
            "answer": ["A", "C"],
        },
        {"type": "blank", "answer": "int"},
        {"type": "short", "answer": "参考答案文本"},
        {
            "type": "coding",
            "answer": {"language": "python", "solution": "print(1)"},
            "test_cases": {"language": "python", "cases": [{"stdin": "", "expected_stdout": "1"}]},
        },
    ]
    for body in valid:
        assert check_exercise_shape(**body) == [], body


@pytest.mark.parametrize(
    ("body", "expected_fragment"),
    [
        ({"type": "choice", "options": None, "answer": "A"}, "options"),
        ({"type": "choice", "options": {}, "answer": "A"}, "options"),
        ({"type": "choice", "options": {"A": "1"}, "answer": "Z"}, "不在 options"),
        ({"type": "choice", "options": {"A": "1"}, "answer": ["A"]}, "选项键字符串"),
        ({"type": "choice", "options": {"A": ""}, "answer": "A"}, "选项文本"),
        ({"type": "multi", "options": {"A": "1"}, "answer": []}, "选项键数组"),
        ({"type": "multi", "options": {"A": "1", "B": "2"}, "answer": ["A", "A"]}, "重复"),
        ({"type": "multi", "options": {"A": "1"}, "answer": [1]}, "元素必须是选项键字符串"),
        ({"type": "blank", "answer": ""}, "非空"),
        ({"type": "blank", "answer": "   "}, "非空"),
        ({"type": "blank", "answer": ["int"]}, "非空"),
        ({"type": "blank", "options": {"A": "x"}, "answer": "int"}, "不应携带 options"),
        ({"type": "short", "answer": 3}, "非空"),
        ({"type": "short", "answer": "x", "test_cases": {"language": "python"}}, "test_cases"),
        ({"type": "coding", "answer": "print(1)"}, "必须是对象"),
        ({"type": "coding", "answer": {"solution": "x"}}, "test_cases"),
        (
            {"type": "coding", "answer": {"solution": "x"}, "test_cases": {"cases": [{}]}},
            "language",
        ),
        (
            {
                "type": "coding",
                "answer": {"solution": "x"},
                "test_cases": {"language": "python", "cases": [{"stdin": "1"}]},
            },
            "expected_stdout",
        ),
        (
            {
                "type": "coding",
                "answer": {"solution": "x"},
                "test_cases": {"language": "python", "cases": [{"expected_stdout": 1}]},
            },
            "必须是字符串",
        ),
        (
            {
                "type": "coding",
                "answer": {"solution": "x"},
                "test_cases": {"language": "python", "cases": ["print(1)"]},
            },
            "必须是对象",
        ),
        # 未知题型不报错也不放行：它由 Pydantic 的题型枚举先拒
        ({"type": "essay", "answer": "x"}, "essay"),
    ],
)
def test_shape_problems_are_reported(body, expected_fragment):
    problems = check_exercise_shape(**body)
    assert problems, f"{body} 应报出问题"
    assert any(expected_fragment in p for p in problems), problems


def test_unknown_type_yields_its_own_message():
    """未知题型：不静默通过。"""
    problems = check_exercise_shape(type="essay", answer="x")
    assert problems
    assert "essay" in " ".join(problems)


def test_empty_expected_stdout_is_allowed():
    """「什么都不输出」是合法用例（例如要求定义函数而不调用）。"""
    assert check_exercise_shape(
        type="coding",
        answer={"solution": "def f():\n    pass"},
        test_cases={"language": "python", "cases": [{"stdin": "", "expected_stdout": ""}]},
    ) == []
