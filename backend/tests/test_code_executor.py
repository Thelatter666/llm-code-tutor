"""SubprocessCodeExecutor 的适配器层测试 —— 全部真起子进程。

这是全项目唯一一批会真实 fork / kill 进程的测试，因此每条断言都取**实测数值**
而不只是状态字符串：
- 内存用例断言峰值 RSS 与耗时（证明是内存层杀的，不是墙钟兜底）
- CPU 用例断言 `exit_code == -SIGXCPU`（证明是 RLIMIT_CPU 杀的，不是墙钟）
- 墙钟用例断言耗时落在 5–6.5s

慢是预期的：本文件约 30 秒。

### 关于孙进程逃逸用例用的是 `os.fork` 而不是 `subprocess`

`subprocess` 在源码层就被黑名单拦下了（见 `test_execution_policy.py`），用它写逃逸
用例会先撞上 `blocked`。但黑名单**不是**安全边界（ADR-0003），`os.fork` 这条同样
能派生孙进程的路并不在黑名单里 —— 用它才能验证进程组 kill 本身是否成立。
"""

import inspect
import os
import re
import signal
import time

import psutil
import pytest

from app.domain.code.execution import (
    CPU_LIMIT_S,
    FILE_SIZE_LIMIT_BYTES,
    MEMORY_LIMIT_BYTES,
    OUTPUT_LIMIT_BYTES,
    STATUS_ACCEPTED,
    STATUS_BLOCKED,
    STATUS_MEMORY_EXCEEDED,
    STATUS_RUNTIME_ERROR,
    STATUS_TIMEOUT,
    WALL_TIMEOUT_S,
)
from app.infrastructure.adapters.execution.subprocess_executor import (
    SubprocessCodeExecutor,
)
from app.infrastructure.ports.code_executor import CodeExecutor

PY = "python"
JS = "javascript"


@pytest.fixture(scope="module")
def executor():
    return SubprocessCodeExecutor()


def _detail(result, layer):
    return result.limit_detail[layer]


# ---------------------------------------------------------------- 端口符合性

def test_adapter_satisfies_the_port_protocol(executor):
    assert isinstance(executor, CodeExecutor)


# ---------------------------------------------------------------- 1. 内存

def test_memory_hog_is_killed_by_memory_layer(executor):
    """spec §8.3：256MB RSS 上限由 psutil 轮询执行。"""
    source = "a = []\nwhile True:\n    a.append(1)\n"
    t0 = time.monotonic()
    result = executor.execute(language=PY, source=source)
    elapsed = time.monotonic() - t0

    assert result.status == STATUS_MEMORY_EXCEEDED
    peak = _detail(result, "memory")["peak_bytes"]
    assert peak > MEMORY_LIMIT_BYTES, f"峰值 RSS 应越过阈值，实测 {peak}"
    assert _detail(result, "memory")["triggered"] is True
    # 关键：必须明显早于墙钟 5s —— 否则就是墙钟兜底而非内存层生效
    assert elapsed < WALL_TIMEOUT_S, f"应被内存层提前杀掉，实测 {elapsed:.2f}s"
    print(
        f"\n[内存层] status={result.status} peak_rss={peak / 1048576:.1f}MB "
        f"elapsed={elapsed:.2f}s samples={_detail(result, 'memory')['samples']} "
        f"exit_code={result.exit_code}"
    )


# ---------------------------------------------------------------- 2. CPU 秒

def test_infinite_loop_is_killed_by_cpu_seconds(executor):
    source = "while True:\n    pass\n"
    t0 = time.monotonic()
    result = executor.execute(language=PY, source=source)
    elapsed = time.monotonic() - t0

    assert result.status == STATUS_TIMEOUT
    # -signal.SIGXCPU 是 CPU 秒耗尽的指纹；墙钟超时会是 -signal.SIGKILL
    assert result.exit_code == -signal.SIGXCPU
    assert _detail(result, "cpu")["applied"] is True
    assert _detail(result, "cpu")["triggered"] is True
    assert CPU_LIMIT_S - 0.5 < elapsed < CPU_LIMIT_S + 1.5
    print(
        f"\n[CPU 层] status={result.status} exit_code={result.exit_code} "
        f"elapsed={elapsed:.2f}s duration_ms={result.duration_ms}"
    )


# ---------------------------------------------------------------- 3. 墙钟

def test_sleep_is_killed_by_wall_clock(executor):
    source = "import time\ntime.sleep(10)\nprint('不应出现')\n"
    t0 = time.monotonic()
    result = executor.execute(language=PY, source=source)
    elapsed = time.monotonic() - t0

    assert result.status == STATUS_TIMEOUT
    assert result.exit_code == -signal.SIGKILL
    assert _detail(result, "wall_clock")["triggered"] is True
    assert WALL_TIMEOUT_S <= elapsed < WALL_TIMEOUT_S + 1.5
    assert "不应出现" not in result.stdout
    print(f"\n[墙钟层] status={result.status} elapsed={elapsed:.2f}s exit_code={result.exit_code}")


# ---------------------------------------------------------------- 4. 文件写入

_PY_BIG_WRITE = (
    "import sys\n"
    "f = open('big.bin', 'wb')\n"
    "try:\n"
    "    f.write(b'x' * (4 * 1024 * 1024))\n"
    "    f.flush()\n"
    "    print('写满了')\n"
    "except OSError as exc:\n"
    "    print('被拦下', exc.errno, file=sys.stderr)\n"
)

_JS_BIG_WRITE = (
    "const fs = require('fs');\n"
    "try { fs.writeFileSync('big.bin', Buffer.alloc(4 * 1024 * 1024)); console.log('写满了'); }\n"
    "catch (e) { console.error('被拦下', e.code); }\n"
)


@pytest.mark.parametrize(
    "language,source,marker",
    [
        (PY, _PY_BIG_WRITE, "27"),  # errno EFBIG
        (JS, _JS_BIG_WRITE, "EFBIG"),
    ],
)
def test_oversized_file_write_is_rejected(executor, language, source, marker):
    result = executor.execute(language=language, source=source)
    assert _detail(result, "file_size")["applied"] is True
    assert marker in result.stderr, f"应在 stderr 见到失败标记 {marker}，实测 {result.stderr!r}"
    assert "写满了" not in result.stdout
    print(f"\n[文件层] {language} stderr={result.stderr.strip()[:80]!r}")


def test_file_on_disk_never_exceeds_one_megabyte(executor):
    """不只看到报错，还要在沙箱内部量一次落盘字节数。"""
    source = (
        "import os\n"
        "f = open('big.bin', 'wb')\n"
        "try:\n"
        "    f.write(b'x' * (4 * 1024 * 1024))\n"
        "    f.flush()\n"
        "except OSError:\n"
        "    pass\n"
        "f.close()\n"
        "print(os.path.getsize('big.bin'))\n"
    )
    result = executor.execute(language=PY, source=source)
    assert result.status == STATUS_ACCEPTED
    size = int(result.stdout.strip())
    print(f"\n[文件层] 落盘实测 {size} 字节（上限 {FILE_SIZE_LIMIT_BYTES}）")
    assert size == FILE_SIZE_LIMIT_BYTES


# ---------------------------------------------------------------- 5. 输出截断

def test_huge_stdout_is_truncated_to_eight_kilobytes(executor):
    source = "import sys\nsys.stdout.write('x' * (1024 * 1024))\nprint('TAIL', flush=True)\n"
    result = executor.execute(language=PY, source=source)

    assert result.status == STATUS_ACCEPTED, "截断不应让进程卡到超时"
    assert len(result.stdout.encode("utf-8")) == OUTPUT_LIMIT_BYTES
    assert _detail(result, "output")["stdout_truncated"] is True
    assert _detail(result, "output")["stdout_bytes"] >= 1024 * 1024
    assert not result.stdout.endswith("TAIL\n"), "尾部应已被截断掉"
    print(
        f"\n[输出层] 截断后 {len(result.stdout.encode())} 字节，"
        f"实际产出 {_detail(result, 'output')['stdout_bytes']} 字节"
    )


def test_stderr_is_truncated_independently(executor):
    source = (
        "import sys\n"
        "sys.stderr.write('e' * (64 * 1024))\n"
        "sys.stdout.write('o' * 10)\n"
    )
    result = executor.execute(language=PY, source=source)
    assert len(result.stderr.encode("utf-8")) == OUTPUT_LIMIT_BYTES
    assert _detail(result, "output")["stderr_truncated"] is True
    assert _detail(result, "output")["stdout_truncated"] is False
    assert result.stdout == "o" * 10


def test_short_output_is_not_marked_truncated(executor):
    result = executor.execute(language=PY, source="print('hi')\n")
    assert result.stdout == "hi\n"
    assert _detail(result, "output")["stdout_truncated"] is False


def test_binary_output_does_not_raise_unicode_decode_error(executor):
    source = "import sys\nsys.stdout.buffer.write(bytes([0xFF, 0xFE, 0x00, 0x41]))\n"
    result = executor.execute(language=PY, source=source)
    assert result.status == STATUS_ACCEPTED
    assert "�" in result.stdout  # errors="replace" 的替换字符


# ---------------------------------------------------------------- 6. 黑名单

def test_blacklisted_source_is_blocked_without_running(executor):
    """用副作用证明「真的没跑」：代码若能执行就会在探针目录里留下文件。"""
    import tempfile

    with tempfile.TemporaryDirectory() as probe:
        marker = os.path.join(probe, "SIDE_EFFECT.txt")
        source = (
            "import pathlib\n"
            f"pathlib.Path({marker!r}).write_text('执行了')\n"
            "import os\n"
            "os.system('echo pwned')\n"
        )
        result = executor.execute(language=PY, source=source)

        assert result.status == STATUS_BLOCKED
        assert result.exit_code is None
        assert result.stdout == ""
        assert result.duration_ms == 0
        assert _detail(result, "blacklist")["rule"] == "os_system"
        assert _detail(result, "blacklist")["executed"] is False
        assert not os.path.exists(marker), "命中黑名单的源码绝不能被执行"
    print(f"\n[黑名单] rule={_detail(result, 'blacklist')['rule']} 副作用文件未产生")


def test_blacklist_is_a_guardrail_not_a_security_boundary(executor):
    """ADR-0003 要求如实声明：黑名单可被轻易绕过，它防的是误触不是攻击。

    这条用例把「可绕过」写成断言，防止后来者误以为它是安全边界。
    """
    source = "print(getattr(__builtins__, 'ev' + 'al')('1+1'))\n"
    result = executor.execute(language=PY, source=source)
    assert result.status != STATUS_BLOCKED
    assert result.stdout.strip() == "2"


# ---------------------------------------------------------------- 7. 正常路径

@pytest.mark.parametrize(
    "language,source,expected",
    [
        (PY, "print('hello')\n", "hello\n"),
        (JS, "console.log('hello');\n", "hello\n"),
        (PY, "print(sum(range(11)))\n", "55\n"),
        (JS, "console.log([1, 2, 3].reduce((a, b) => a + b, 0));\n", "6\n"),
    ],
)
def test_normal_code_runs(executor, language, source, expected):
    result = executor.execute(language=language, source=source)
    assert result.status == STATUS_ACCEPTED
    assert result.stdout == expected
    assert result.exit_code == 0
    assert result.duration_ms >= 0


def test_stdin_is_delivered_to_the_program(executor):
    result = executor.execute(
        language=PY, source="print('got:', input())\n", stdin="来自 stdin\n"
    )
    assert result.status == STATUS_ACCEPTED
    assert result.stdout == "got: 来自 stdin\n"


def test_program_that_ignores_stdin_is_not_blocked(executor):
    """stdin 走临时文件重定向 —— 没人读它时不该有任何等待。"""
    t0 = time.monotonic()
    result = executor.execute(language=PY, source="print('不读 stdin')\n", stdin="x" * 200000)
    elapsed = time.monotonic() - t0
    assert result.status == STATUS_ACCEPTED
    assert elapsed < 3, f"不读 stdin 时不应被管道写入卡住，实测 {elapsed:.2f}s"


def test_nonzero_exit_is_runtime_error(executor):
    result = executor.execute(language=PY, source="import sys\nsys.exit(3)\n")
    assert result.status == STATUS_RUNTIME_ERROR
    assert result.exit_code == 3


def test_python_traceback_points_at_main_py_not_bootstrap(executor):
    """学生看到的 traceback 里不应出现 runpy 或引导脚本的内部帧。"""
    result = executor.execute(language=PY, source="raise ValueError('boom')\n")
    assert result.status == STATUS_RUNTIME_ERROR
    assert result.exit_code == 1
    assert 'File "main.py", line 1' in result.stderr
    assert "runpy" not in result.stderr
    assert "ValueError: boom" in result.stderr


def test_python_syntax_error_reports_line_and_file(executor):
    result = executor.execute(language=PY, source="def f(:\n    pass\n")
    assert result.status == STATUS_RUNTIME_ERROR
    assert "main.py" in result.stderr
    assert "SyntaxError" in result.stderr


def test_javascript_infinite_loop_is_killed(executor):
    t0 = time.monotonic()
    result = executor.execute(language=JS, source="while (true) {}\n")
    elapsed = time.monotonic() - t0
    assert result.status == STATUS_TIMEOUT
    assert elapsed < WALL_TIMEOUT_S + 1.5
    print(
        f"\n[JS 死循环] status={result.status} exit_code={result.exit_code} "
        f"elapsed={elapsed:.2f}s"
    )


def test_javascript_runtime_error(executor):
    result = executor.execute(language=JS, source="throw new Error('boom');\n")
    assert result.status == STATUS_RUNTIME_ERROR
    assert result.exit_code != 0
    assert "boom" in result.stderr


# ---------------------------------------------------------------- 8. 孙进程逃逸

def test_grandchild_is_killed_along_with_the_parent(executor):
    """拍板决策 3：必须杀掉整个进程组，不能只杀直接子进程。"""
    source = (
        "import os, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "print('child', pid, flush=True)\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    )
    t0 = time.monotonic()
    result = executor.execute(language=PY, source=source)
    elapsed = time.monotonic() - t0

    assert result.status == STATUS_TIMEOUT
    assert result.stdout.startswith("child ")
    grandchild_pid = int(result.stdout.split()[1])

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and psutil.pid_exists(grandchild_pid):
        time.sleep(0.05)
    alive = psutil.pid_exists(grandchild_pid)
    print(f"\n[进程组] 孙进程 pid={grandchild_pid} 执行后存活={alive} 耗时={elapsed:.2f}s")
    assert alive is False, f"孙进程 {grandchild_pid} 逃逸了 —— 进程组 kill 未生效"


# ---------------------------------------------------------------- limit_detail

def test_limit_detail_records_every_layer(executor):
    result = executor.execute(language=PY, source="print('ok')\n")
    detail = result.limit_detail

    assert detail["wall_clock"]["limit_s"] == WALL_TIMEOUT_S
    assert detail["wall_clock"]["triggered"] is False
    assert detail["cpu"]["limit_s"] == CPU_LIMIT_S
    assert detail["cpu"]["applied"] is True  # 本机实测可设
    assert detail["cpu"]["error"] is None
    assert detail["memory"]["limit_bytes"] == MEMORY_LIMIT_BYTES
    assert detail["memory"]["sampled"] is True
    assert detail["memory"]["interval_ms"] == 100
    assert detail["memory"]["triggered"] is False
    assert detail["file_size"]["limit_bytes"] == FILE_SIZE_LIMIT_BYTES
    assert detail["file_size"]["applied"] is True  # 本机实测可设
    assert detail["output"]["limit_bytes"] == OUTPUT_LIMIT_BYTES
    assert detail["degraded_layers"] == []


def test_implementation_never_sets_rlimit_as_data_or_rss():
    """ADR-0003 的硬约束：这三项在 macOS 下设不进去，绝不能真的去设。

    只在代码里查 `resource.setrlimit(resource.RLIMIT_*)` 的调用 —— 模块文档里
    提到这三个名字是**要求**（说明为什么不用），不该被当成违规。
    """
    module = __import__(
        "app.infrastructure.adapters.execution.subprocess_executor", fromlist=["x"]
    )
    src = inspect.getsource(module)
    for forbidden in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_RSS"):
        pattern = rf"resource\.setrlimit\(\s*resource\.{forbidden}\b"
        assert re.search(pattern, src) is None, f"{forbidden} 在本平台设不进去（ADR-0003）"
    # 顺带确认引导脚本里也没偷偷用它们（模板是字符串，不在上述正则的射程内）
    for template in (module._BOOTSTRAP_PYTHON_TEMPLATE, module._BOOTSTRAP_EXEC_TEMPLATE):
        assert "_apply(\"RLIMIT_AS\"" not in template
        assert "_apply(\"RLIMIT_DATA\"" not in template
        assert "_apply(\"RLIMIT_RSS\"" not in template


def test_subprocess_runs_with_a_cleared_environment(executor):
    """env 清空继承：子进程里不应看到宿主的 HOME / VIRTUAL_ENV。"""
    source = (
        "import os\n"
        "for k in ('HOME', 'VIRTUAL_ENV', 'USER', 'PYTHONPATH'):\n"
        "    print(k, k in os.environ)\n"
    )
    result = executor.execute(language=PY, source=source)
    assert result.status == STATUS_ACCEPTED
    for line in result.stdout.strip().splitlines():
        name, present = line.split()
        assert present == "False", f"{name} 泄漏进了沙箱环境"


def test_python_runs_in_isolated_mode(executor):
    """`-I -S`：隔离模式 + 不导入 site-packages。"""
    source = "import sys\nprint(sys.flags.isolated, sys.flags.no_site)\n"
    result = executor.execute(language=PY, source=source)
    assert result.stdout.strip() == "1 1"
