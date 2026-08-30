"""资源泄漏专项：临时目录（四条路径）与僵尸进程。

这是本批次「做错可能伤到机器」的那一面 —— 泄漏的临时目录会一直堆在 `/tmp`，
未回收的子进程会一直是僵尸。故每条断言都是**前后计数对比**，不是「看起来没报错」。
"""

import os
import tempfile
import time

import psutil
import pytest

from app.domain.code.execution import (
    STATUS_ACCEPTED,
    STATUS_BLOCKED,
    STATUS_MEMORY_EXCEEDED,
    STATUS_RUNTIME_ERROR,
    STATUS_TIMEOUT,
)
from app.infrastructure.adapters.execution.subprocess_executor import (
    TEMP_PREFIX,
    SubprocessCodeExecutor,
)

PY = "python"


def _temp_dirs() -> list[str]:
    root = tempfile.gettempdir()
    try:
        return [n for n in os.listdir(root) if n.startswith(TEMP_PREFIX)]
    except FileNotFoundError:
        return []


@pytest.fixture(autouse=True)
def _clean_slate():
    """跑之前先把历史残留清掉，避免其他用例的残留干扰计数。"""
    for name in _temp_dirs():
        import shutil

        shutil.rmtree(os.path.join(tempfile.gettempdir(), name), ignore_errors=True)
    yield
    for name in _temp_dirs():
        import shutil

        shutil.rmtree(os.path.join(tempfile.gettempdir(), name), ignore_errors=True)


@pytest.fixture(scope="module")
def executor():
    return SubprocessCodeExecutor()


# ---------------------------------------------------------------- 四条路径

def test_temp_dir_is_cleaned_after_success(executor):
    before = len(_temp_dirs())
    result = executor.execute(language=PY, source="print('ok')\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_ACCEPTED
    assert after == before, f"成功路径泄漏了 {after - before} 个临时目录"


def test_temp_dir_is_cleaned_after_wall_clock_timeout(executor):
    before = len(_temp_dirs())
    result = executor.execute(language=PY, source="import time\ntime.sleep(10)\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_TIMEOUT
    assert after == before, f"墙钟超时路径泄漏了 {after - before} 个临时目录"


def test_temp_dir_is_cleaned_after_memory_kill(executor):
    before = len(_temp_dirs())
    result = executor.execute(language=PY, source="a = []\nwhile True:\n    a.append(1)\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_MEMORY_EXCEEDED
    assert after == before, f"内存 kill 路径泄漏了 {after - before} 个临时目录"


def test_temp_dir_is_cleaned_after_blacklist(executor):
    before = len(_temp_dirs())
    result = executor.execute(language=PY, source="import os\nos.system('ls')\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_BLOCKED
    assert after == before, f"黑名单路径泄漏了 {after - before} 个临时目录"


def test_temp_dir_is_cleaned_when_spawn_itself_raises():
    """第四条路径：`Popen` 就抛异常时，`try/finally` 仍必须清理。

    用一个不存在的解释器路径逼出 `FileNotFoundError`。
    """
    broken = SubprocessCodeExecutor(python_executable="/nonexistent/python-for-tests")
    before = len(_temp_dirs())
    result = broken.execute(language=PY, source="print('ok')\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_RUNTIME_ERROR
    assert "执行器" in result.stderr or "Nonexistent" in result.stderr or result.stderr
    assert after == before, f"异常路径泄漏了 {after - before} 个临时目录"


def test_temp_dir_is_cleaned_when_node_is_missing():
    """JS 侧同源：node 不在时引导脚本 execv 失败，目录照样要清掉。"""
    broken = SubprocessCodeExecutor(node_executable="/nonexistent/node-for-tests")
    before = len(_temp_dirs())
    result = broken.execute(language="javascript", source="console.log('ok');\n")
    after = len(_temp_dirs())
    assert result.status == STATUS_RUNTIME_ERROR
    assert after == before, f"node 缺失路径泄漏了 {after - before} 个临时目录"


# ---------------------------------------------------------------- 僵尸进程

def _zombies_owned_by_us() -> list[int]:
    me = os.getpid()
    found = []
    for proc in psutil.process_iter(["pid", "ppid", "status"]):
        info = proc.info
        if info.get("ppid") == me and info.get("status") == psutil.STATUS_ZOMBIE:
            found.append(info["pid"])
    return found


def test_no_zombie_children_after_a_batch_of_runs(executor):
    """批量执行（含被杀与派生孙进程的用例）后，不得留下已终止未回收的子进程。"""
    sources = [
        "print(1)\n",
        "import time\ntime.sleep(10)\n",
        "a = []\nwhile True:\n    a.append(1)\n",
        "raise ValueError('x')\n",
        "import os, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "while True:\n"
        "    time.sleep(0.1)\n",
    ]
    for src in sources:
        executor.execute(language=PY, source=src)

    # 给内核回收留一个节拍
    time.sleep(0.5)
    zombies = _zombies_owned_by_us()
    print(f"\n[僵尸检查] 批量执行后本进程僵尸子进程 = {zombies}")
    assert zombies == []


def test_no_zombie_children_in_the_whole_batch_run(executor):
    """上一批跑完后，这一批再跑一遍 —— 回收是每次都成立，不是碰巧。"""
    statuses = []
    for src in ("print(1)\n", "import time\ntime.sleep(10)\n", "while True:\n    pass\n"):
        statuses.append(executor.execute(language=PY, source=src).status)
    assert set(statuses) == {STATUS_ACCEPTED, STATUS_TIMEOUT}
    time.sleep(0.5)
    assert _zombies_owned_by_us() == []
