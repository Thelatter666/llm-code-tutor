"""静态解析（spec §8.4）—— 纯领域层，零 IO，可脱离数据库单测。

Python 走标准库 `ast` 精确解析；JavaScript 用正则 + 花括号配对的轻量解析
（不引入 esprima 等外部依赖），结果是**确定性近似**：不识别字符串与正则
字面量，方法清单靠行首模式匹配。教学场景足够，不要拿它当 lint 工具。

「裸 except」字段为两种语言共用：Python 指 `except:`，JavaScript 指
**空 catch 块** `catch (e) {}` —— 两者同属「吞掉异常不处理」。

圈复杂度规则（固化并由测试锁定）：
  Python = 1 + If / For / While / AsyncFor / ExceptHandler / IfExp / Assert
           / match_case 各 +1；每个 comprehension +1，其每个 if 再 +1；
           BoolOp 按 (操作数数 - 1) 计。
  JS     = 1 + if / for / while / case / catch / && / || 各 +1。
  嵌套函数 / Lambda / 类不进入外层作用域的统计（它们的分支归它们自己）。

未使用变量规则：只分析**函数作用域**（模块级不分析）；`_` 前缀与方法的
`self` / `cls` 豁免；`x += 1` 既是写也是读；闭包内的读取算使用；
`global` / `nonlocal` 声明的名字无法静态判断，跳过。
JS 只检查 `const / let / var` 声明，不检查函数参数。

语法错误不抛异常：返回 `syntax_error`（行号 + 消息）并保留行数统计 ——
教学工具对写了一半的代码更要给出反馈。
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field

LANGUAGE_PYTHON = "python"
LANGUAGE_JAVASCRIPT = "javascript"
ANALYSIS_LANGUAGES = (LANGUAGE_PYTHON, LANGUAGE_JAVASCRIPT)

# 审计动作（spec §8.4 的业务行为留痕，与 chat 同模式）
ACTION_CODE_ANALYZE = "code_analyze"


def source_hash(language: str, source: str) -> str:
    """spec §8.4：source_hash 命中历史则复用，不重复算。

    语言并入哈希 —— 同一文本按不同语言解析结果不同，不得串号。
    """
    return hashlib.sha256(f"{language}\x00{source}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LineStats:
    total: int
    code: int
    blank: int
    comment: int


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    line: int
    args: int
    complexity: int


@dataclass(frozen=True)
class ClassInfo:
    name: str
    line: int
    methods: int


@dataclass(frozen=True)
class ComplexitySummary:
    max: int
    average: float
    worst: str | None


@dataclass(frozen=True)
class UnusedVariable:
    name: str
    line: int


@dataclass(frozen=True)
class BareExcept:
    line: int


@dataclass(frozen=True)
class IssueList:
    unused_variables: list[UnusedVariable] = field(default_factory=list)
    bare_excepts: list[BareExcept] = field(default_factory=list)


@dataclass(frozen=True)
class SyntaxIssue:
    line: int
    message: str


@dataclass(frozen=True)
class StaticReport:
    """静态报告 StaticReport（CONTEXT.md）：不依赖大模型的客观结构化结果。"""

    language: str
    lines: LineStats
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    complexity: ComplexitySummary = ComplexitySummary(max=0, average=0.0, worst=None)
    issues: IssueList = field(default_factory=IssueList)
    syntax_error: SyntaxIssue | None = None


def analyze(language: str, source: str) -> StaticReport:
    if language == LANGUAGE_PYTHON:
        return analyze_python(source)
    if language == LANGUAGE_JAVASCRIPT:
        return analyze_javascript(source)
    raise ValueError(f"不支持的语言：{language}，可选 {ANALYSIS_LANGUAGES}")


# ================================================================ Python


def analyze_python(source: str) -> StaticReport:
    lines = _python_line_stats(source)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return StaticReport(
            language=LANGUAGE_PYTHON,
            lines=lines,
            syntax_error=SyntaxIssue(line=exc.lineno or 0, message=exc.msg or "语法错误"),
        )

    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []
    unused: list[UnusedVariable] = []
    bare: list[BareExcept] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                FunctionInfo(
                    name=node.name,
                    line=node.lineno,
                    args=_py_arg_count(node.args),
                    complexity=_py_complexity(node),
                )
            )
            unused.extend(
                UnusedVariable(name=name, line=line)
                for name, line in _py_unused_in_scope(node)
            )
        elif isinstance(node, ast.ClassDef):
            classes.append(
                ClassInfo(
                    name=node.name,
                    line=node.lineno,
                    methods=sum(
                        1
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ),
                )
            )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            bare.append(BareExcept(line=node.lineno))

    # ast.walk 的顺序是实现细节；按行号排序让输出对调用方稳定
    functions.sort(key=lambda f: f.line)
    classes.sort(key=lambda c: c.line)
    unused.sort(key=lambda v: (v.line, v.name))
    bare.sort(key=lambda b: b.line)
    return StaticReport(
        language=LANGUAGE_PYTHON,
        lines=lines,
        functions=functions,
        classes=classes,
        complexity=_summary(functions),
        issues=IssueList(unused_variables=unused, bare_excepts=bare),
    )


def _python_line_stats(source: str) -> LineStats:
    """整行分类：空行 / 注释行 / 代码行；行尾注释所在行算代码行。"""
    total = blank = comment = 0
    for line in source.splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif stripped.startswith("#"):
            comment += 1
    return LineStats(total=total, code=total - blank - comment, blank=blank, comment=comment)


def _py_arg_count(args: ast.arguments) -> int:
    n = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    if args.vararg is not None:
        n += 1
    if args.kwarg is not None:
        n += 1
    return n


# 嵌套作用域：它们的 Store 归它们自己，分支复杂度也归它们自己
_SKIPPED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_PY_DECISIONS = (
    ast.If,
    ast.For,
    ast.While,
    ast.AsyncFor,
    ast.ExceptHandler,
    ast.IfExp,
    ast.Assert,
    ast.match_case,
)


def _own_scope(root: ast.AST):
    """遍历自身作用域，不进入嵌套函数 / Lambda / 类。"""
    for node in ast.iter_child_nodes(root):
        if isinstance(node, _SKIPPED_SCOPES):
            continue
        yield node
        yield from _own_scope(node)


def _py_complexity(fn: ast.AST) -> int:
    score = 1
    for node in _own_scope(fn):
        if isinstance(node, _PY_DECISIONS):
            score += 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
    return score


def _py_unused_in_scope(fn) -> list[tuple[str, int]]:
    stores: dict[str, int] = {}
    for arg in (
        *fn.args.posonlyargs,
        *fn.args.args,
        *fn.args.kwonlyargs,
        fn.args.vararg,
        fn.args.kwarg,
    ):
        if arg is not None:
            stores.setdefault(arg.arg, getattr(arg, "lineno", fn.lineno))

    for node in _own_scope(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores.setdefault(node.id, node.lineno)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            # `except E as e:` 的 e 是字符串属性，不是 Name 节点
            stores.setdefault(node.name, node.lineno)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                stores.pop(name, None)

    loads: set[str] = set()
    for node in ast.walk(fn):  # 全子树：闭包内的读取也算使用
        if isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Store):  # Load / Del 都算读过
                loads.add(node.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            loads.add(node.target.id)  # x += 1 既是写也是读

    skipped = {"self", "cls"}
    return [
        (name, line)
        for name, line in sorted(stores.items(), key=lambda kv: (kv[1], kv[0]))
        if name not in loads and not name.startswith("_") and name not in skipped
    ]


# ================================================================ JavaScript


_JS_FUNCTION = re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)[ \t]*\(([^()]*)\)")
_JS_ARROW_PAREN = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async[ \t]*)?\(([^()]*)\)\s*=>"
)
_JS_ARROW_SINGLE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async[ \t]+)?([A-Za-z_$][\w$]*)\s*=>"
)
_JS_CLASS = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")
# 行首「name(params) {」模式匹配方法简写；排除语句关键字避免把 if/for 当方法
_JS_METHOD = re.compile(
    r"(?m)^[ \t]*(?!if\b|for\b|while\b|switch\b|catch\b|function\b|return\b"
    r"|else\b|try\b|do\b)([A-Za-z_$][\w$]*)[ \t]*\(([^()]*)\)[ \t]*\{"
)
_JS_DECISION = re.compile(r"\b(?:if|for|while|case|catch)\b|&&|\|\|")
_JS_EMPTY_CATCH = re.compile(r"\bcatch\s*(?:\([^()]*\))?[ \t]*\{[ \t\n]*\}")
_JS_DECL = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")


def analyze_javascript(source: str) -> StaticReport:
    """轻量解析：正则 + 花括号配对。结果为确定性近似，不做语法校验。"""
    stripped = _blank_js_comments(source)
    lines = _js_line_stats(source)

    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []

    def _add_function(match: re.Match, name: str, params: str) -> None:
        span = _js_brace_span(stripped, match.end())
        complexity = 1
        if span is not None:
            body = stripped[span[0] : span[1]]
            complexity = 1 + len(_JS_DECISION.findall(body))
        functions.append(
            FunctionInfo(
                name=name,
                line=stripped.count("\n", 0, match.start()) + 1,
                args=_js_arg_count(params),
                complexity=complexity,
            )
        )

    for match in _JS_FUNCTION.finditer(stripped):
        _add_function(match, match.group(1), match.group(2))
    for match in _JS_ARROW_PAREN.finditer(stripped):
        _add_function(match, match.group(1), match.group(2))
    for match in _JS_ARROW_SINGLE.finditer(stripped):
        _add_function(match, match.group(1), match.group(2))

    for match in _JS_CLASS.finditer(stripped):
        span = _js_brace_span(stripped, match.end())
        methods = 0
        if span is not None:
            body = stripped[span[0] : span[1]]
            methods = sum(1 for _ in _JS_METHOD.finditer(body))
        classes.append(
            ClassInfo(
                name=match.group(1),
                line=stripped.count("\n", 0, match.start()) + 1,
                methods=methods,
            )
        )
    # 类体里的方法简写同时也是函数，进入函数清单（与 Python 口径一致）
    for match in _JS_METHOD.finditer(stripped):
        _add_function(match, match.group(1), match.group(2))

    unused = [
        UnusedVariable(
            name=match.group(1),
            line=stripped.count("\n", 0, match.start()) + 1,
        )
        for match in _JS_DECL.finditer(stripped)
        if not match.group(1).startswith("_")
        and not re.search(rf"\b{re.escape(match.group(1))}\b", stripped[: match.start()] + stripped[match.end():])
    ]
    bare = [
        BareExcept(line=stripped.count("\n", 0, match.start()) + 1)
        for match in _JS_EMPTY_CATCH.finditer(stripped)
    ]

    functions.sort(key=lambda f: f.line)
    classes.sort(key=lambda c: c.line)
    unused.sort(key=lambda v: (v.line, v.name))
    bare.sort(key=lambda b: b.line)
    return StaticReport(
        language=LANGUAGE_JAVASCRIPT,
        lines=lines,
        functions=functions,
        classes=classes,
        complexity=_summary(functions),
        issues=IssueList(unused_variables=unused, bare_excepts=bare),
    )


def _blank_js_comments(source: str) -> str:
    """把注释替换为等长空白（保留换行），后续行号因此不漂移。"""
    source = re.sub(
        r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), source, flags=re.DOTALL
    )
    return re.sub(r"//[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)


def _js_line_stats(source: str) -> LineStats:
    total = blank = comment = 0
    in_block = False
    for line in source.splitlines():
        total += 1
        stripped = line.strip()
        if in_block:
            comment += 1
            if "*/" in stripped:
                in_block = False
        elif not stripped:
            blank += 1
        elif stripped.startswith("//"):
            comment += 1
        elif stripped.startswith("/*"):
            comment += 1
            if "*/" not in stripped:
                in_block = True
    code = total - blank - comment
    return LineStats(total=total, code=code, blank=blank, comment=comment)


def _js_brace_span(source: str, start: int) -> tuple[int, int] | None:
    """从 start 起找第一个 '{'，返回 (open_idx, close_idx)；未闭合返回 None。"""
    open_idx = source.find("{", start)
    if open_idx == -1:
        return None
    depth = 0
    for idx in range(open_idx, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return open_idx, idx
    return None


def _js_arg_count(params: str) -> int:
    params = params.strip()
    return 0 if not params else params.count(",") + 1


def _summary(functions: list[FunctionInfo]) -> ComplexitySummary:
    if not functions:
        return ComplexitySummary(max=0, average=0.0, worst=None)
    worst = max(functions, key=lambda f: f.complexity)
    return ComplexitySummary(
        max=worst.complexity,
        average=round(sum(f.complexity for f in functions) / len(functions), 2),
        worst=worst.name,
    )
