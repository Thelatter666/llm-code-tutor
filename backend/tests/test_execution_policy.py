"""执行策略领域层测试（spec §8.3 步骤 1，零 IO）。

黑名单的定位是**防误触而非防攻击**（spec §8.3 / ADR-0003），因此这里的用例
锁的是「规则边界可预测」：该拦的拦、不该拦的不拦、注释与字符串不误伤。
"""

import re

import pytest

from app.domain.code import execution as ex
from app.domain.code.execution import (
    CPU_LIMIT_S,
    FILE_SIZE_LIMIT_BYTES,
    MEMORY_LIMIT_BYTES,
    MEMORY_SAMPLE_INTERVAL_S,
    OUTPUT_LIMIT_BYTES,
    RUN_LANGUAGES,
    RUN_STATUSES,
    WALL_TIMEOUT_S,
    ACTION_CODE_RUN,
    scan_blacklist,
)

PY = "python"
JS = "javascript"


# ---------------------------------------------------------------- 常量契约

def test_run_languages_cover_python_and_javascript():
    assert RUN_LANGUAGES == ("python", "javascript")


def test_run_statuses_match_spec_section_5():
    assert set(RUN_STATUSES) == {
        "accepted",
        "runtime_error",
        "timeout",
        "memory_exceeded",
        "blocked",
    }


def test_resource_limits_match_spec_section_8_3_table():
    """spec §8.3 的四层阈值表 —— 改一个数必须有测试先红。"""
    assert WALL_TIMEOUT_S == 5.0
    assert CPU_LIMIT_S == 3
    assert MEMORY_LIMIT_BYTES == 256 * 1024 * 1024
    assert MEMORY_SAMPLE_INTERVAL_S == 0.1
    assert FILE_SIZE_LIMIT_BYTES == 1024 * 1024
    assert OUTPUT_LIMIT_BYTES == 8 * 1024


def test_audit_action_is_code_run():
    assert ACTION_CODE_RUN == "code_run"


# ---------------------------------------------------------------- 黑名单：Python

@pytest.mark.parametrize(
    "source,rule",
    [
        ("import os\nos.system('ls')\n", "os_system"),
        ("from os import system\nsystem('ls')\n", "os_system"),
        ("import subprocess\nsubprocess.run(['ls'])\n", "subprocess"),
        ("import socket\nsocket.socket()\n", "socket"),
        ("import shutil\nshutil.rmtree('/tmp/x')\n", "shutil_rmtree"),
        ("__import__('os').system('ls')\n", "dunder_import"),
    ],
)
def test_python_blacklist_hits(source, rule):
    assert scan_blacklist(PY, source) == rule


def test_python_eval_exec_only_blocks_when_both_present():
    assert scan_blacklist(PY, "eval('1+1')\n") is None
    assert scan_blacklist(PY, "exec('x=1')\n") is None
    assert scan_blacklist(PY, "eval('1+1')\nexec('x=1')\n") == "eval_exec"


def test_python_plain_code_is_not_blocked():
    assert scan_blacklist(PY, "print(sum(range(10)))\n") is None
    assert scan_blacklist(PY, "import math\nprint(math.pi)\n") is None


def test_python_comment_mentioning_os_system_is_not_blocked():
    """教学代码里常见「不要用 os.system」这类注释，注释不该触发拦截。"""
    src = "import os\n# 不要用 os.system，这里用 os.getcwd 代替\nprint(os.getcwd())\n"
    assert scan_blacklist(PY, src) is None


def test_python_docstring_mentioning_subprocess_is_not_blocked():
    src = 'def f():\n    """不要使用 subprocess 模块。"""\n    return 1\n'
    assert scan_blacklist(PY, src) is None


def test_python_string_literal_mentioning_shutil_rmtree_is_not_blocked():
    src = 'print("shutil.rmtree 是危险操作")\n'
    assert scan_blacklist(PY, src) is None


def test_python_unparsable_source_falls_back_to_raw_scan():
    """源码写了一半（未闭合括号）时 tokenize 会抛错，回退原始扫描 —— 宁可误报。"""
    src = "def f(:\n    os.system('ls')\n"
    assert scan_blacklist(PY, src) == "os_system"


def test_python_unterminated_string_falls_back_to_raw_scan():
    src = 'x = """未闭合的文档字符串\nos.system("ls")\n'
    assert scan_blacklist(PY, src) == "os_system"


# ---------------------------------------------------------------- 黑名单：JavaScript

@pytest.mark.parametrize(
    "source,rule",
    [
        ("const cp = require('child_process');\n", "child_process"),
        ("const f = new Function('return 1');\n", "new_function"),
        ("fs.rmSync('/tmp/x', { recursive: true });\n", "fs_destructive"),
        ("fs.unlinkSync('a.txt');\n", "fs_destructive"),
        ("eval('1+1');\n", "eval"),
    ],
)
def test_javascript_blacklist_hits(source, rule):
    assert scan_blacklist(JS, source) == rule


def test_javascript_file_write_is_not_blacklisted():
    """写文件不进黑名单 —— 它落在临时目录里，且由 RLIMIT_FSIZE 卡在 1MB。

    把 writeFileSync 列进黑名单只会误伤「把结果存成文件」这类正常练习。
    """
    assert scan_blacklist(JS, "fs.writeFileSync('out.txt', 'hello');\n") is None


def test_javascript_plain_code_is_not_blocked():
    assert scan_blacklist(JS, "console.log([1, 2, 3].reduce((a, b) => a + b, 0));\n") is None


def test_javascript_comment_mentioning_child_process_is_not_blocked():
    src = "// 不要引入 child_process\nconsole.log('ok');\n"
    assert scan_blacklist(JS, src) is None


def test_javascript_block_comment_mentioning_eval_is_not_blocked():
    src = "/* eval 有风险 */\nconsole.log('ok');\n"
    assert scan_blacklist(JS, src) is None


def test_javascript_string_literal_mentioning_fs_rmsync_is_not_blocked():
    src = "console.log('fs.rmSync 会删文件');\n"
    assert scan_blacklist(JS, src) is None


# ---------------------------------------------------------------- 命令装配

def test_build_python_command_uses_isolated_interpreter():
    cmd = ex.build_command(
        language=PY,
        python_executable="/venv/bin/python",
        node_executable="/usr/local/bin/node",
        bootstrap="BOOT",
        script_path="/tmp/w/main.py",
        status_path="/tmp/w/status.json",
    )
    assert cmd == [
        "/venv/bin/python",
        "-I",
        "-S",
        "-c",
        "BOOT",
        "/tmp/w/main.py",
        "/tmp/w/status.json",
    ]


def test_build_javascript_command_goes_through_python_bootstrap_then_node():
    """JS 无 rlimit API，故由 Python 引导脚本设好限制再 execv 让位给 node。"""
    cmd = ex.build_command(
        language=JS,
        python_executable="/venv/bin/python",
        node_executable="/usr/local/bin/node",
        bootstrap="BOOT",
        script_path="/tmp/w/main.js",
        status_path="/tmp/w/status.json",
    )
    assert cmd == [
        "/venv/bin/python",
        "-I",
        "-S",
        "-c",
        "BOOT",
        "/usr/local/bin/node",
        "/tmp/w/main.js",
        "/tmp/w/status.json",
    ]


def test_build_command_rejects_unknown_language():
    with pytest.raises(ValueError):
        ex.build_command(
            language="ruby",
            python_executable="python",
            node_executable="node",
            bootstrap="BOOT",
            script_path="/tmp/w/main.rb",
            status_path="/tmp/w/status.json",
        )


def test_script_filenames_are_stable():
    assert ex.script_filename(PY) == "main.py"
    assert ex.script_filename(JS) == "main.js"


# ---------------------------------------------------------------- 环境装配

def test_build_env_clears_inherited_environment():
    """spec §8.3 步骤 2：env 清空继承。只允许一条固定白名单。"""
    env = ex.build_env()
    assert env == {
        "PATH": ex.SANDBOX_PATH,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for leaked in ("HOME", "PYTHONPATH", "VIRTUAL_ENV", "USER", "SHELL", "TMPDIR"):
        assert leaked not in env


def test_sandbox_path_has_no_empty_entry():
    """空的 PATH 项等价于把当前目录加入搜索路径 —— 沙箱里不允许。"""
    assert "" not in ex.SANDBOX_PATH.split(":")


# ---------------------------------------------------------------- 零 IO 约束

def test_domain_module_performs_no_io():
    """领域层禁止 IO：源码级断言，比 import 检查更难被绕过。"""
    src = open(ex.__file__, encoding="utf-8").read()
    forbidden = r"^\s*(?:import|from)\s+(?:sqlalchemy|requests|httpx|psutil|subprocess|socket|pathlib|shutil)\b"
    assert re.search(forbidden, src, re.MULTILINE) is None
    assert "open(" not in src
    assert "Popen" not in src
