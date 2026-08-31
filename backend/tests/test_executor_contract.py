"""CodeExecutor 端口契约测试（M4，P5 Task 5）。

**M4 的定义**（与 `test_llm_contract.py` 同口径）：同一组断言在两个实现上
各跑一遍，确保同签名同语义 —— 防「Fake 只在测试里成立、真适配器不同签名」。
Provider/Executor 专属行为（psutil 采样、四层限制的触发指纹）留在
`test_code_executor.py`，那些不是契约，是实现细节。
"""

import pytest

from app.infrastructure.adapters.execution.subprocess_executor import (
    SubprocessCodeExecutor,
)
from app.infrastructure.ports.code_executor import CodeExecutor, ExecutionResult
from tests.fakes import FakeExecutor

SOURCE_OK = 'print("ok")'
SOURCE_STDIN = 'name = input()\nprint(f"hi {name}")'
SOURCE_ERROR = "raise ValueError(\"boom\")"
SOURCE_BLACKLIST = 'import os\nos.system("echo hi")'


@pytest.fixture(params=["fake", "subprocess"])
def executor(request):
    """两个实现，同一组断言 —— 这是「契约测试」的最低要求（M4）。"""
    if request.param == "fake":
        return FakeExecutor()
    return SubprocessCodeExecutor()


def test_satisfies_code_executor_port(executor):
    assert isinstance(executor, CodeExecutor)


def test_accepts_keyword_signature(executor):
    """端口签名（ports/code_executor.py）：`execute(*, language, source, stdin)`。"""
    result = executor.execute(language="python", source=SOURCE_OK, stdin="")
    assert isinstance(result, ExecutionResult)


def test_normal_run_is_accepted(executor):
    result = executor.execute(language="python", source=SOURCE_OK)
    assert result.status == "accepted"
    assert "ok" in result.stdout
    assert result.exit_code == 0
    assert isinstance(result.duration_ms, int)


def test_stdin_reaches_the_program(executor):
    """判题用例的输入靠 stdin 透传（P4 遗留 5 预留的缝）。"""
    result = executor.execute(language="python", source=SOURCE_STDIN, stdin="世界")
    assert "hi 世界" in result.stdout


def test_runtime_error_reports_exit_code_and_stderr(executor):
    result = executor.execute(language="python", source=SOURCE_ERROR)
    assert result.status == "runtime_error"
    assert result.exit_code is not None and result.exit_code != 0
    assert "ValueError" in result.stderr


def test_blacklist_blocks_without_execution(executor):
    """黑名单命中：不执行任何用户代码，exit_code 为 None。"""
    result = executor.execute(language="python", source=SOURCE_BLACKLIST)
    assert result.status == "blocked"
    assert result.exit_code is None
    assert result.stdout == ""


def test_limit_detail_carries_all_layers(executor):
    result = executor.execute(language="python", source=SOURCE_OK)
    for key in ("wall_clock", "cpu", "memory", "file_size", "output"):
        assert key in result.limit_detail, f"limit_detail 缺 {key}"
