"""静态解析领域层测试（spec §8.4）。

StaticReport 的字段结构与两种语言的解析规则在这里定稿：
- Python 走 ast 精确解析；JavaScript 是正则 + 花括号配对的轻量解析（近似）。
- 圈复杂度规则、未使用变量豁免规则、行数分类规则逐条用例锁定。
- 本模块零 IO（纯领域层，可脱离数据库与网络单测）。
"""

import inspect

import pytest

from app.domain.code.analysis import (
    LANGUAGE_JAVASCRIPT,
    LANGUAGE_PYTHON,
    LineStats,
    StaticReport,
    analyze,
)

# ---------------------------------------------------------------- 通用


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError):
        analyze("ruby", "puts 1")


def test_domain_module_has_no_io_or_infra_imports():
    """零 IO 是领域层硬约束（spec §4.2）：不许出现任何基础设施或 IO 痕迹。"""
    import app.domain.code.analysis as mod

    src = inspect.getsource(mod)
    for forbidden in ("sqlalchemy", "httpx", "requests", "asyncio", "open(", "Path("):
        assert forbidden not in src, f"领域层出现 {forbidden}"


# ---------------------------------------------------------------- Python


def test_python_line_stats_classify_code_blank_and_comment():
    report = analyze(LANGUAGE_PYTHON, "x = 1\n# note\n\ny = 2  # trailing\n")
    assert report.lines == LineStats(total=4, code=2, blank=1, comment=1)


def test_python_empty_source_produces_zeroed_report():
    report = analyze(LANGUAGE_PYTHON, "")
    assert report.lines == LineStats(total=0, code=0, blank=0, comment=0)
    assert report.functions == []
    assert report.classes == []
    assert report.complexity.max == 0
    assert report.complexity.worst is None
    assert report.issues.unused_variables == []
    assert report.syntax_error is None


def test_python_functions_classes_and_args_are_listed():
    src = (
        "def free(a, b=1, *rest, **kw):\n"
        "    return a\n"
        "\n"
        "class Widget:\n"
        "    def render(self, ctx):\n"
        "        return ctx\n"
        "\n"
        "    async def stream(self):\n"
        "        yield 1\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)

    fn = {f.name: f for f in report.functions}
    assert set(fn) == {"free", "render", "stream"}
    assert fn["free"].args == 4  # 位置参数 2 + *rest + **kw
    assert fn["free"].line == 1
    assert fn["render"].args == 2
    assert fn["render"].line == 5

    assert [c.name for c in report.classes] == ["Widget"]
    assert report.classes[0].line == 4
    assert report.classes[0].methods == 2


def test_python_complexity_counts_documented_decision_nodes():
    src = (
        "def f(x):\n"
        "    if x > 0:\n"  # +1 If
        "        for i in range(x):\n"  # +1 For
        "            while i:\n"  # +1 While
        "                i -= 1\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"  # +1 ExceptHandler
        "        pass\n"
        "    return x if x else 0\n"  # +1 IfExp
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert report.functions[0].complexity == 6


def test_python_match_case_counts_toward_complexity():
    src = (
        "def handle(cmd):\n"
        "    match cmd:\n"
        "        case 'go':\n"
        "            return 1\n"
        "        case _:\n"
        "            return 0\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert report.functions[0].complexity == 3  # 1 + match_case ×2


def test_python_straight_line_code_has_complexity_one():
    report = analyze(LANGUAGE_PYTHON, "def f():\n    return 1\n")
    assert report.functions[0].complexity == 1


def test_python_complexity_summary_names_the_worst_function():
    src = (
        "def simple(a):\n"
        "    return a\n"
        "\n"
        "def twisted(a):\n"
        "    if a:\n"
        "        return 1\n"
        "    return 0\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert report.complexity.max == 2
    assert report.complexity.worst == "twisted"
    assert report.complexity.average == 1.5


def test_python_unused_variable_is_reported_with_line():
    src = "def f():\n    x = 1\n    y = 2\n    return y\n"
    report = analyze(LANGUAGE_PYTHON, src)
    assert [(v.name, v.line) for v in report.issues.unused_variables] == [("x", 2)]


def test_python_unused_reports_across_functions_in_line_order():
    src = (
        "def first():\n"
        "    dead = 1\n"
        "    return 0\n"
        "\n"
        "def second():\n"
        "    gone = 2\n"
        "    return 0\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert [(v.name, v.line) for v in report.issues.unused_variables] == [
        ("dead", 2),
        ("gone", 6),
    ]


def test_python_underscore_self_and_cls_are_exempt_from_unused():
    src = (
        "class C:\n"
        "    def method(self, _ignored, cls):\n"
        "        tmp = 1\n"
        "        return 0\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert [(v.name, v.line) for v in report.issues.unused_variables] == [("tmp", 3)]


def test_python_closure_read_counts_as_usage():
    src = (
        "def outer():\n"
        "    captured = 1\n"
        "    def inner():\n"
        "        return captured\n"
        "    return inner\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    names = [v.name for v in report.issues.unused_variables]
    assert "captured" not in names
    # 嵌套函数与外层函数都进入函数清单，但彼此的变量不互相污染
    assert {f.name for f in report.functions} == {"outer", "inner"}


def test_python_augassign_counts_as_read():
    src = (
        "def f(items):\n"
        "    total = 0\n"
        "    for it in items:\n"
        "        total += it\n"
        "    return total\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert report.issues.unused_variables == []


def test_python_global_declared_names_are_skipped():
    src = "counter = 0\n\ndef bump():\n    global counter\n    counter = counter + 1\n"
    report = analyze(LANGUAGE_PYTHON, src)
    assert report.issues.unused_variables == []


def test_python_bare_except_is_flagged_but_typed_is_not():
    src = (
        "def f():\n"
        "    try:\n"
        "        risky()\n"
        "    except:\n"
        "        pass\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    report = analyze(LANGUAGE_PYTHON, src)
    assert [b.line for b in report.issues.bare_excepts] == [4]


def test_python_syntax_error_is_reported_not_raised():
    """教学工具对写了一半的代码更要给出反馈：返回语法错误而非 500。"""
    report = analyze(LANGUAGE_PYTHON, "def f(:\n    pass\n")
    assert report.syntax_error is not None
    assert report.syntax_error.line == 1
    assert report.syntax_error.message  # 错误消息非空即可，具体文本随 Python 版本变化
    assert report.functions == []
    assert report.lines.total == 2  # 行数统计仍然可用


# ---------------------------------------------------------------- JavaScript


def test_js_functions_classes_methods_and_lines():
    src = (
        "// 主入口\n"
        "function greet(name) {\n"
        '  return "hi " + name;\n'
        "}\n"
        "\n"
        "const add = (a, b) => a + b;\n"
        "\n"
        "class Counter {\n"
        "  bump() { this.n += 1; }\n"
        "}\n"
        "\n"
        "/* 多行\n"
        "   注释 */\n"
        "let total = 0;\n"
    )
    report = analyze(LANGUAGE_JAVASCRIPT, src)

    fn = {f.name: f for f in report.functions}
    assert {"greet", "add", "bump"} <= set(fn)
    assert fn["greet"].args == 1
    assert fn["add"].args == 2
    assert fn["bump"].args == 0

    assert [c.name for c in report.classes] == ["Counter"]
    assert report.classes[0].methods == 1

    assert report.lines == LineStats(total=14, code=8, blank=3, comment=3)


def test_js_async_arrow_and_single_param():
    src = "const load = async (url) => url;\nconst tick = x => x + 1;\n"
    report = analyze(LANGUAGE_JAVASCRIPT, src)
    fn = {f.name: f for f in report.functions}
    assert fn["load"].args == 1
    assert fn["tick"].args == 1


def test_js_complexity_counts_branches():
    src = (
        "function grade(score) {\n"
        "  if (score >= 90) {\n"
        '    return "A";\n'
        "  } else if (score >= 60) {\n"
        '    return "B";\n'
        "  }\n"
        "  for (let i = 0; i < score; i++) {\n"
        "    total += i && 1;\n"
        "  }\n"
        "  return null;\n"
        "}\n"
    )
    report = analyze(LANGUAGE_JAVASCRIPT, src)
    assert report.functions[0].complexity == 5  # 1 + if + if + for + &&


def test_js_unused_variable_is_reported_with_line():
    src = (
        "function run(data) {\n"
        "  const limit = 10;\n"
        "  let doubled = data * 2;\n"
        "  return doubled;\n"
        "}\n"
    )
    report = analyze(LANGUAGE_JAVASCRIPT, src)
    assert [(v.name, v.line) for v in report.issues.unused_variables] == [("limit", 2)]


def test_js_empty_catch_is_flagged_but_handled_is_not():
    """JavaScript 没有 except；「裸 except」的对应物是空 catch 块（同字段）。"""
    src = (
        "try {\n"
        "  risky();\n"
        "} catch (e) {\n"
        "}\n"
        "\n"
        "try {\n"
        "  risky();\n"
        "} catch (e) {\n"
        "  log(e);\n"
        "}\n"
    )
    report = analyze(LANGUAGE_JAVASCRIPT, src)
    assert [b.line for b in report.issues.bare_excepts] == [3]


def test_js_report_is_typed_as_static_report():
    report = analyze(LANGUAGE_JAVASCRIPT, "const a = 1;")
    assert isinstance(report, StaticReport)
    assert report.language == "javascript"
    assert report.syntax_error is None  # 轻量解析不做语法校验
