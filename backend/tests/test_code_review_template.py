"""Mock 讲解模板测试（spec §8.4：Mock 模式下 ai_report 由 static_report 模板化生成）。"""

from app.domain.code.analysis import LANGUAGE_JAVASCRIPT, LANGUAGE_PYTHON, analyze
from app.domain.code.review import (
    COMPLEXITY_SPLIT_THRESHOLD,
    build_review_question,
    render_mock_review,
)

PY_SRC = """\
def area(radius):
    result = radius * 3.14
    unused = 2
    try:
        risky()
    except:
        pass
    return result
"""


def test_mock_review_lists_each_issue_with_lines():
    report = analyze(LANGUAGE_PYTHON, PY_SRC)
    text = render_mock_review(report)
    assert "unused" in text and "第 3 行" in text  # 未使用变量
    assert "第 6 行" in text  # 裸 except
    assert "area" in text  # 摘要里出现函数信息


def test_mock_review_says_clean_when_no_issues():
    report = analyze(LANGUAGE_PYTHON, "def f():\n    return 1\n")
    text = render_mock_review(report)
    assert "未发现" in text


def test_mock_review_suggests_split_when_complexity_is_high():
    body = "\n".join(f"    if a == {i}: return {i}" for i in range(COMPLEXITY_SPLIT_THRESHOLD + 1))
    report = analyze(LANGUAGE_PYTHON, f"def twisted(a):\n{body}\n    return 0\n")
    assert report.complexity.max > COMPLEXITY_SPLIT_THRESHOLD
    text = render_mock_review(report)
    assert "拆分" in text
    assert "twisted" in text


def test_mock_review_shows_syntax_error_and_skips_issues():
    report = analyze(LANGUAGE_PYTHON, "def f(:\n    pass\n")
    text = render_mock_review(report)
    assert "语法" in text
    assert "unused" not in text


def test_mock_review_wording_differs_by_language():
    """「裸 except」字段两语言共用：Python 指 except:，JS 指空 catch 块。"""
    js = analyze(LANGUAGE_JAVASCRIPT, "try {\n  risky();\n} catch (e) {\n}\n")
    assert "catch" in render_mock_review(js)

    py = analyze(LANGUAGE_PYTHON, "try:\n    risky()\nexcept:\n    pass\n")
    assert "except" in render_mock_review(py)


def test_mock_review_is_markdown():
    report = analyze(LANGUAGE_PYTHON, PY_SRC)
    assert render_mock_review(report).startswith("##")


def test_build_review_question_includes_summary_source_and_language():
    report = analyze(LANGUAGE_PYTHON, PY_SRC)
    question = build_review_question(LANGUAGE_PYTHON, PY_SRC, report)
    assert "python" in question
    assert PY_SRC in question
    assert "未使用变量" in question
    assert "Markdown" in question


def test_build_review_question_reports_syntax_error():
    report = analyze(LANGUAGE_PYTHON, "def f(:\n    pass\n")
    question = build_review_question(LANGUAGE_PYTHON, "def f(:\n    pass\n", report)
    assert "语法错误" in question
