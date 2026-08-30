"""代码运行的执行策略（spec §8.3）—— 纯领域层，零 IO，可脱离数据库单测。

本模块只回答三个问题：**这段源码该不该拦**（黑名单）、**拦了报什么规则名**、
**放行时该用什么命令行与环境启动**。真正起子进程、设 rlimit、杀进程组的部分
在 `infrastructure/adapters/execution/subprocess_executor.py`。

### 黑名单的定位

spec §8.3 与 ADR-0003 说得很清楚：**黑名单防的是学生误操作，不是蓄意攻击**。
Python 下 `__import__('o'+'s')`、`getattr` 链、编码绕过都能轻易绕过，而本执行器
以当前 OS 用户身份运行、对本机文件系统有读权限 —— 这两点必须在 README 与页面
上显式声明，不要把它当成安全边界。

因此本模块的取舍是**可预测**而非**不可绕过**：

- 扫描前先剥离注释与字符串字面量。教学代码里「不要用 `os.system`」这类注释极为
  常见，不剥离会产生令人困惑的误报。
- 但 `require('child_process')` 的危险性恰恰**只在字符串里**。故规则分两种扫描面：
  常规规则看「代码骨架」（注释与字符串都剥掉），模块引入类规则看「仅剥注释、
  保留字面量」的源码。两者都不看注释。
- 剥离失败（源码写了一半、`tokenize` 抛错）时**回退到原始源码扫描** —— 宁可
  误报也不漏报，因为误报的代价只是学生看到一条 `blocked` 提示。
- `eval` 与 `exec` 单独出现都放行，只有**同时出现**才拦（spec §8.3 原文即
  「`eval` + `exec` 组合」）—— 单独一个 `eval` 是合法的教学内容。

### 环境装配

`build_env()` 返回一条固定白名单，**不继承宿主环境**（spec §8.3 步骤 2）。
"""

import io
import re
import tokenize
from dataclasses import dataclass
from typing import Optional

from app.domain.code.analysis import LANGUAGE_JAVASCRIPT, LANGUAGE_PYTHON

RUN_LANGUAGES = (LANGUAGE_PYTHON, LANGUAGE_JAVASCRIPT)

# spec §5 CodeRun.status 的封闭取值
STATUS_ACCEPTED = "accepted"
STATUS_RUNTIME_ERROR = "runtime_error"
STATUS_TIMEOUT = "timeout"
STATUS_MEMORY_EXCEEDED = "memory_exceeded"
STATUS_BLOCKED = "blocked"
RUN_STATUSES = (
    STATUS_ACCEPTED,
    STATUS_RUNTIME_ERROR,
    STATUS_TIMEOUT,
    STATUS_MEMORY_EXCEEDED,
    STATUS_BLOCKED,
)

# --- 四层资源限制阈值（spec §8.3 步骤 3 的表，ADR-0003 确认的可行组合）---
# 墙钟超时：父进程 select 轮询到点后 killpg(SIGKILL)
WALL_TIMEOUT_S = 5.0
# CPU 秒：子进程内 resource.setrlimit(RLIMIT_CPU)，超限内核发 SIGXCPU
CPU_LIMIT_S = 3
# 内存：psutil 轮询采样进程树 RSS。**不用 RLIMIT_AS / RLIMIT_DATA / RLIMIT_RSS**
# —— 实测 macOS darwin 下 setrlimit 对这三项一律抛
# "ValueError: current limit exceeds maximum limit"（ADR-0003 已记录）。
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
MEMORY_SAMPLE_INTERVAL_S = 0.1
# 文件写入：RLIMIT_FSIZE。注意它**对管道无效**，输出截断另走父进程读取时的 8KB 上限
FILE_SIZE_LIMIT_BYTES = 1024 * 1024
OUTPUT_LIMIT_BYTES = 8 * 1024

# 审计动作（spec §8.3 步骤 5）
ACTION_CODE_RUN = "code_run"

# 沙箱进程的固定 PATH。不含空项 —— 空项等价于把当前目录加入可执行搜索路径。
SANDBOX_PATH = "/usr/local/bin:/usr/bin:/bin"

_SCRIPT_FILENAMES = {LANGUAGE_PYTHON: "main.py", LANGUAGE_JAVASCRIPT: "main.js"}
# stdin 走临时文件重定向而非管道写入：学生代码若不读 stdin，父进程写大块数据会死锁
STDIN_FILENAME = "stdin.txt"
# 子进程把「各层 rlimit 是否设置成功」写回这里，父进程读回后并入 limit_detail
STATUS_FILENAME = ".limit-status.json"


# 规则在两种扫描面上匹配：
#   "code"     —— 注释与字符串字面量都剥掉后的代码骨架（默认）
#   "literals" —— 只剥注释、保留字符串字面量（模块引入的危险性只在字面量里）
SCAN_CODE = "code"
SCAN_LITERALS = "literals"


@dataclass(frozen=True)
class BlacklistRule:
    name: str
    patterns: tuple[str, ...]
    languages: tuple[str, ...]
    # True 要求全部命中（spec §8.3 的「eval + exec 组合」），False 为任一命中
    require_all: bool = False
    scan_in: str = SCAN_CODE


BLACKLIST_RULES: tuple[BlacklistRule, ...] = (
    # `__import__` 排在最前：它本身就是绕过黑名单的手段，命中它时优先报告它，
    # 而不是报告它最终调用的 os.system —— 前者才是学生需要知道的那一件事。
    BlacklistRule("dunder_import", (r"__import__",), (LANGUAGE_PYTHON,)),
    # `system(` 覆盖 `from os import system` 的形式；Python 里裸 `system(` 几乎
    # 不可能是无害代码。
    BlacklistRule("os_system", (r"\bos\s*\.\s*system\b", r"\bsystem\s*\("), (LANGUAGE_PYTHON,)),
    BlacklistRule("subprocess", (r"\bsubprocess\b",), (LANGUAGE_PYTHON,)),
    BlacklistRule("socket", (r"\bsocket\b",), (LANGUAGE_PYTHON,)),
    BlacklistRule("shutil_rmtree", (r"\bshutil\s*\.\s*rmtree\b",), (LANGUAGE_PYTHON,)),
    BlacklistRule(
        "eval_exec", (r"\beval\s*\(", r"\bexec\s*\("), (LANGUAGE_PYTHON,), require_all=True
    ),
    BlacklistRule(
        "child_process",
        (r"""require\s*\(\s*['"]child_process['"]\s*\)""", r"""from\s+['"]child_process['"]"""),
        (LANGUAGE_JAVASCRIPT,),
        scan_in=SCAN_LITERALS,
    ),
    BlacklistRule("new_function", (r"\bnew\s+Function\s*\(",), (LANGUAGE_JAVASCRIPT,)),
    # 只拦**删除类**操作。写文件（`fs.writeFileSync`）不拦 —— 它写在临时目录里，
    # 且由 RLIMIT_FSIZE 兜底在 1MB；把它列进黑名单只会误伤「把结果存成文件」这类
    # 正常练习，而收益为零。
    BlacklistRule(
        "fs_destructive",
        (r"\bfs\s*\.\s*(?:rm|rmSync|rmdir|rmdirSync|unlink|unlinkSync)\b",),
        (LANGUAGE_JAVASCRIPT,),
    ),
    BlacklistRule("eval", (r"\beval\s*\(",), (LANGUAGE_JAVASCRIPT,)),
)

# Python：tokenize 会为 f-string 拆出 FSTRING_START / MIDDLE / END，字面量在中段，
# 一并丢弃；NUMBER 无害但与 NAME 混排会干扰词边界，一并保留原样（不丢）。
_PY_NOISE_NAMES = frozenset({"COMMENT", "STRING"})
_PY_LAYOUT = frozenset(
    {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
)

_JS_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

_JS_NOISE = re.compile(
    r"/\*.*?\*/"  # 块注释
    r"|//[^\n]*"  # 行注释
    r"|'(?:\\.|[^'\\\n])*'"  # 单引号字符串
    r'|\"(?:\\.|[^\"\\\n])*"'  # 双引号字符串
    r"|`(?:\\.|[^`\\])*`",  # 模板字符串
    re.DOTALL,
)


def script_filename(language: str) -> str:
    return _SCRIPT_FILENAMES[language]


def _is_python_noise(token_type: int) -> bool:
    name = tokenize.tok_name.get(token_type, "")
    return name in _PY_NOISE_NAMES or name.startswith("FSTRING")


def strip_noise(language: str, source: str) -> str:
    """剥离注释与字符串字面量，只留「代码骨架」供黑名单正则匹配。

    剥离失败时原样返回 —— 源码写了一半是教学场景的常态，此时宁可误报。
    """
    if language == LANGUAGE_JAVASCRIPT:
        return _JS_NOISE.sub(" ", source)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        kept = [
            tok.string
            for tok in tokens
            if not _is_python_noise(tok.type) and tok.type not in _PY_LAYOUT
        ]
    except Exception:
        # TokenError / IndentationError / SyntaxError 都可能：回退原始源码
        return source
    return " ".join(kept)


def strip_comments(language: str, source: str) -> str:
    """只剥注释，保留字符串字面量（供模块引入类规则匹配）。

    JS 侧是纯正则，字符串里的 `//`（如 URL）会被误判为行注释。这只会多剥一点，
    不会给 `require('...')` 这类模式制造假阳性，故可接受。
    """
    if language == LANGUAGE_JAVASCRIPT:
        return _JS_COMMENT.sub(" ", source)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        kept = [tok.string for tok in tokens if tok.type != tokenize.COMMENT]
    except Exception:
        return source
    return "".join(kept)


def scan_blacklist(language: str, source: str) -> Optional[str]:
    """返回命中的规则名；未命中返回 None。"""
    scanned: dict[str, str] = {}
    for rule in BLACKLIST_RULES:
        if language not in rule.languages:
            continue
        if rule.scan_in not in scanned:
            scanned[rule.scan_in] = (
                strip_noise(language, source)
                if rule.scan_in == SCAN_CODE
                else strip_comments(language, source)
            )
        text = scanned[rule.scan_in]
        hits = [re.search(p, text) is not None for p in rule.patterns]
        if all(hits) if rule.require_all else any(hits):
            return rule.name
    return None


def build_command(
    *,
    language: str,
    python_executable: str,
    node_executable: str,
    bootstrap: str,
    script_path: str,
    status_path: str,
) -> list[str]:
    """装配受限命令。

    Python：引导脚本与用户代码共用同一个解释器，因此 `-I -S` 同时生效于两者
    —— `-I` 隔离模式忽略 `PYTHONPATH` 等环境变量且不把脚本目录加入 `sys.path`，
    `-S` 跳过 site 导入（学生代码因此只能用到标准库）。

    JavaScript：Node 没有设置 rlimit 的 API，故由 Python 引导脚本先把限制设好，
    再 `os.execv` 让位给 node —— rlimit 是进程属性，跨 `exec` 保留。
    """
    if language == LANGUAGE_PYTHON:
        return [
            python_executable,
            "-I",
            "-S",
            "-c",
            bootstrap,
            script_path,
            status_path,
        ]
    if language == LANGUAGE_JAVASCRIPT:
        return [
            python_executable,
            "-I",
            "-S",
            "-c",
            bootstrap,
            node_executable,
            script_path,
            status_path,
        ]
    raise ValueError(f"不支持的运行语言：{language}")


def build_env() -> dict[str, str]:
    """沙箱进程环境：固定白名单，不继承宿主环境（spec §8.3 步骤 2）。

    `PYTHONIOENCODING` 固定 stdout / stderr 编码，避免 locale 差异导致中文输出
    在管道里变成别的编码；`PYTHONDONTWRITEBYTECODE` 避免在临时目录里留下
    `__pycache__`（虽然整个目录跑完就删）。
    """
    return {
        "PATH": SANDBOX_PATH,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
