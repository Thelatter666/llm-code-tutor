"""SubprocessCodeExecutor —— 四层受限执行器（spec §8.3 / ADR-0003）。

### 为什么不用 `preexec_fn` 设 rlimit

教科书写法是在 `Popen(preexec_fn=...)` 里调 `resource.setrlimit`。但本适配器跑在
`run_in_threadpool` 的**线程池**里，而 CPython 文档明确写着 `preexec_fn` 在多线程
进程中使用不安全：fork 时若别的线程正持有 malloc 锁，子进程会在 exec 之前死锁。

于是把 rlimit 的设置挪进**子进程自己**：命令形如
`python -I -S -c <引导脚本> <脚本> <状态文件>`，引导脚本先设限制、再执行用户代码
（Python）或 `os.execv` 让位给 node（JavaScript）。rlimit 是进程属性，跨 `exec`
保留；引导脚本把每层是否设上写进状态文件，父进程读回后并入 `limit_detail`。

### 四层限制各由谁执行

| 层 | 谁执行 | 触发后的指纹 |
|---|---|---|
| 墙钟 5s | 父进程 `select` 轮询到点后 `killpg(SIGKILL)` | `exit_code == -9` |
| CPU 3s | 子进程 `RLIMIT_CPU` | `exit_code == -24`（SIGXCPU） |
| 内存 256MB | 父进程 `psutil` 每 100ms 采样进程树 RSS | `limit_detail.memory.triggered` |
| 文件 1MB | 子进程 `RLIMIT_FSIZE` | 写操作返回 EFBIG |

**绝不使用 `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_RSS`** —— ADR-0003 已实测：
macOS darwin 下 `setrlimit` 对这三项一律抛
`ValueError: current limit exceeds maximum limit`。

### 输出截断为什么在父进程做

`RLIMIT_FSIZE` 只约束**文件**写入，对 pipe 无效。stdout 是 pipe，所以 8KB 截断
只能在父进程读管道时做。超出上限后**继续读但丢弃**，否则子进程会卡在写满的管道
上，一个「打印 1MB 然后退出」的正常程序会白白等到墙钟超时。
"""

import json
import logging
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import psutil

from app.domain.code.execution import (
    CPU_LIMIT_S,
    FILE_SIZE_LIMIT_BYTES,
    MEMORY_LIMIT_BYTES,
    MEMORY_SAMPLE_INTERVAL_S,
    OUTPUT_LIMIT_BYTES,
    STATUS_ACCEPTED,
    STATUS_BLOCKED,
    STATUS_MEMORY_EXCEEDED,
    STATUS_RUNTIME_ERROR,
    STATUS_TIMEOUT,
    STATUS_FILENAME,
    STDIN_FILENAME,
    WALL_TIMEOUT_S,
    build_command,
    build_env,
    scan_blacklist,
    script_filename,
)
from app.infrastructure.ports.code_executor import ExecutionResult

logger = logging.getLogger(__name__)

# 临时目录前缀 —— 泄漏排查与测试计数都靠它
TEMP_PREFIX = "coderun-"
# 单次读取的管道块大小
_READ_CHUNK = 65536
# 杀掉进程组后留给内核回收的时间
_REAP_GRACE_S = 2.0
_SAMPLE_INTERVAL_MS = int(MEMORY_SAMPLE_INTERVAL_S * 1000)


# ---------------------------------------------------------------- 引导脚本

_BOOTSTRAP_PYTHON_TEMPLATE = '''\
import json, os, resource, sys

_status_path = sys.argv[2]
_script_path = sys.argv[1]
_log = {}


def _apply(name, value):
    const = getattr(resource, name, None)
    if const is None:
        return {"applied": False, "error": "platform has no " + name}
    try:
        resource.setrlimit(const, (value, value))
        return {"applied": True, "error": None}
    except Exception as exc:
        return {"applied": False, "error": type(exc).__name__ + ": " + str(exc)}


_log["cpu"] = _apply("RLIMIT_CPU", __CPU_SECONDS__)
_log["file_size"] = _apply("RLIMIT_FSIZE", __FILE_BYTES__)
with open(_status_path, "w") as _fh:
    _fh.write(json.dumps(_log))

_name = os.path.basename(_script_path)
with open(_script_path, "rb") as _fh:
    _raw = _fh.read()
_code = compile(_raw.decode("utf-8", "replace"), _name, "exec")
_globals = {
    "__name__": "__main__",
    "__file__": _script_path,
    "__builtins__": __builtins__,
    "__doc__": None,
    "__package__": None,
}
sys.argv = [_name]
try:
    exec(_code, _globals)
except SystemExit:
    raise
except BaseException:
    import traceback

    _etype, _evalue, _tb = sys.exc_info()
    # 剥掉引导脚本自己那一帧：学生只需要看到 main.py 里的行
    traceback.print_exception(_etype, _evalue, _tb.tb_next)
    sys.exit(1)
'''

_BOOTSTRAP_EXEC_TEMPLATE = '''\
import json, os, resource, sys

_status_path = sys.argv[3]
_node = sys.argv[1]
_script = sys.argv[2]
_log = {}


def _apply(name, value):
    const = getattr(resource, name, None)
    if const is None:
        return {"applied": False, "error": "platform has no " + name}
    try:
        resource.setrlimit(const, (value, value))
        return {"applied": True, "error": None}
    except Exception as exc:
        return {"applied": False, "error": type(exc).__name__ + ": " + str(exc)}


_log["cpu"] = _apply("RLIMIT_CPU", __CPU_SECONDS__)
_log["file_size"] = _apply("RLIMIT_FSIZE", __FILE_BYTES__)
with open(_status_path, "w") as _fh:
    _fh.write(json.dumps(_log))

# rlimit 是进程属性，跨 exec 保留 —— 这是 JS 侧能吃到限制的唯一途径
os.execv(_node, [_node, _script])
'''


def _render_bootstrap(template: str) -> str:
    return (
        template.replace("__CPU_SECONDS__", str(CPU_LIMIT_S)).replace(
            "__FILE_BYTES__", str(FILE_SIZE_LIMIT_BYTES)
        )
    )


# ---------------------------------------------------------------- 工具函数


def _write_bytes(path: str, payload: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(payload)


def _drain(fd: int, sink: bytearray) -> tuple[int, bool]:
    """把管道里现有的数据抽干。返回 `(读到字节数, 是否 EOF)`。

    超出 8KB 之后**继续读但不再留存** —— 否则子进程会卡在写满的管道上。
    """
    received = 0
    while True:
        try:
            chunk = os.read(fd, _READ_CHUNK)
        except BlockingIOError:
            return received, False
        except OSError:
            return received, True
        if not chunk:
            return received, True
        received += len(chunk)
        room = OUTPUT_LIMIT_BYTES - len(sink)
        if room > 0:
            sink.extend(chunk[:room])


def _sample_rss(pid: int) -> int:
    """采样进程树 RSS —— 只测直接子进程会让 `os.fork` 出来的孙进程吃内存不被发现。"""
    total = 0
    try:
        proc = psutil.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return total
    return total


def _kill_group(proc: subprocess.Popen) -> None:
    """杀掉整个进程组 —— 只 kill 直接子进程会留下 `os.fork` 出来的逃逸进程。"""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        _kill_single(proc)
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        _kill_single(proc)


def _kill_single(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _reap(proc: subprocess.Popen) -> int | None:
    """回收子进程，避免僵尸。必要时再杀一次。"""
    try:
        return proc.wait(timeout=_REAP_GRACE_S)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            return proc.wait(timeout=_REAP_GRACE_S)
        except subprocess.TimeoutExpired:
            logger.error("进程 %s 在 SIGKILL 后仍未退出", proc.pid)
            return None


# ---------------------------------------------------------------- 执行器


class SubprocessCodeExecutor:
    """受限代码执行器：真起子进程，四层限制 + 进程组回收 + 临时目录清理。"""

    BOOTSTRAP_PYTHON = _render_bootstrap(_BOOTSTRAP_PYTHON_TEMPLATE)
    BOOTSTRAP_EXEC = _render_bootstrap(_BOOTSTRAP_EXEC_TEMPLATE)

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        node_executable: str | None = None,
    ) -> None:
        self._python = python_executable or sys.executable
        self._node = node_executable or (shutil.which("node") or "node")

    # ------------------------------------------------------------ 端口实现

    def execute(self, *, language: str, source: str, stdin: str = "") -> ExecutionResult:
        rule = scan_blacklist(language, source)
        if rule is not None:
            # spec §8.3 步骤 1：命中即返回，不落临时目录、不起进程
            return self._blocked(rule)

        started = time.monotonic()
        workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
        try:
            return self._spawn_and_wait(workdir, language, source, stdin, started)
        except Exception as exc:  # 第四条清理路径：抛异常也要清目录
            logger.exception("代码执行器内部错误")
            return ExecutionResult(
                status=STATUS_RUNTIME_ERROR,
                stdout="",
                stderr=f"执行器内部错误：{type(exc).__name__}: {exc}",
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                limit_detail=self._detail(executed=False, error=f"{type(exc).__name__}: {exc}"),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------ 内部实现

    def _spawn_and_wait(
        self,
        workdir: str,
        language: str,
        source: str,
        stdin: str,
        started: float,
    ) -> ExecutionResult:
        script_path = os.path.join(workdir, script_filename(language))
        _write_bytes(script_path, source.encode("utf-8"))
        status_path = os.path.join(workdir, STATUS_FILENAME)

        stdin_arg: object = subprocess.DEVNULL
        if stdin:
            stdin_path = os.path.join(workdir, STDIN_FILENAME)
            _write_bytes(stdin_path, stdin.encode("utf-8"))
            stdin_arg = open(stdin_path, "rb")

        cmd = build_command(
            language=language,
            python_executable=self._python,
            node_executable=self._node,
            bootstrap=self.BOOTSTRAP_PYTHON
            if language == "python"
            else self.BOOTSTRAP_EXEC,
            script_path=script_path,
            status_path=status_path,
        )
        proc = subprocess.Popen(  # noqa: S603 — 命令由领域层装配，非用户拼接
            cmd,
            cwd=workdir,
            stdin=stdin_arg,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=build_env(),
            # 新会话：子进程自成一个进程组，终止时才能连孙进程一起带走
            start_new_session=True,
            close_fds=True,
        )
        try:
            return self._pump(proc, status_path, started)
        finally:
            if stdin_arg is not subprocess.DEVNULL:
                stdin_arg.close()
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def _pump(self, proc: subprocess.Popen, status_path: str, started: float) -> ExecutionResult:
        """抽管道 + 采内存 + 看墙钟，三件事共用一个 100ms 节拍。"""
        out_fd = proc.stdout.fileno()
        err_fd = proc.stderr.fileno()
        # 非阻塞：父进程不被子进程的输出节奏牵着走
        os.set_blocking(out_fd, False)
        os.set_blocking(err_fd, False)

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        out_total = err_total = 0
        out_eof = err_eof = False
        peak = 0
        samples = 0
        next_sample_at = 0.0
        timed_out = False
        memory_hit = False

        while True:
            # 1) 先抽管道 —— 不抽的话子进程会卡在写满的管道上
            got, eof = _drain(out_fd, stdout_buf)
            out_total += got
            out_eof = out_eof or eof
            got, eof = _drain(err_fd, stderr_buf)
            err_total += got
            err_eof = err_eof or eof

            # 2) 采内存（严格按 100ms 间隔，输出再密也不会超采）
            elapsed = time.monotonic() - started
            if elapsed >= next_sample_at:
                peak = max(peak, _sample_rss(proc.pid))
                samples += 1
                next_sample_at = samples * MEMORY_SAMPLE_INTERVAL_S
            if peak > MEMORY_LIMIT_BYTES:
                memory_hit = True
                break

            # 3) 结束判定
            if out_eof and err_eof:
                break
            if elapsed >= WALL_TIMEOUT_S:
                timed_out = True
                break

            # 4) 等下一个事件：有数据就早醒，没数据最多等一个采样间隔
            pending = [fd for fd, done in ((out_fd, out_eof), (err_fd, err_eof)) if not done]
            if pending:
                select.select(pending, [], [], MEMORY_SAMPLE_INTERVAL_S)
            else:
                time.sleep(MEMORY_SAMPLE_INTERVAL_S)

        if timed_out or memory_hit:
            _kill_group(proc)

        # 收尾再抽一次：被杀之前已经写进管道缓冲区的输出要拿回来（spec §9）
        out_total += _drain(out_fd, stdout_buf)[0]
        err_total += _drain(err_fd, stderr_buf)[0]
        exit_code = _reap(proc)

        log = self._read_status(status_path)
        return ExecutionResult(
            status=self._status(exit_code, timed_out, memory_hit),
            stdout=bytes(stdout_buf).decode("utf-8", errors="replace"),
            stderr=bytes(stderr_buf).decode("utf-8", errors="replace"),
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            limit_detail=self._detail(
                executed=True,
                error=None,
                wall_elapsed_s=round(time.monotonic() - started, 3),
                wall_triggered=timed_out,
                cpu=log.get("cpu"),
                # CPU 秒耗尽的唯一指纹是内核发的 SIGXCPU（见 _status 的注释）
                cpu_triggered=exit_code == -signal.SIGXCPU,
                file_size=log.get("file_size"),
                memory_peak=peak,
                memory_samples=samples,
                memory_triggered=memory_hit,
                out_total=out_total,
                err_total=err_total,
            ),
        )

    # ------------------------------------------------------------ 结果装配

    def _read_status(self, status_path: str) -> dict:
        """读子进程写回的「各层 rlimit 是否设上」。缺失即视为该层未生效。"""
        try:
            with open(status_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            logger.warning("读取限制状态文件失败：%s", status_path)
            return {}

    @staticmethod
    def _status(exit_code: int | None, timed_out: bool, memory_hit: bool) -> str:
        if memory_hit:
            return STATUS_MEMORY_EXCEEDED
        if timed_out:
            return STATUS_TIMEOUT
        if exit_code == 0:
            return STATUS_ACCEPTED
        if exit_code == -signal.SIGXCPU:
            # CPU 秒耗尽：进程在墙钟到点之前就被内核干掉了（spec §9「代码执行超时」）
            return STATUS_TIMEOUT
        return STATUS_RUNTIME_ERROR

    def _blocked(self, rule: str) -> ExecutionResult:
        return ExecutionResult(
            status=STATUS_BLOCKED,
            stdout="",
            stderr=f"命中黑名单规则：{rule}；代码未执行。",
            exit_code=None,
            duration_ms=0,
            limit_detail=self._detail(
                executed=False,
                error=None,
                blacklist_rule=rule,
            ),
        )

    def _detail(self, *, executed: bool, error: str | None, **measured) -> dict:
        """四层限制的统一记录结构。

        未执行（黑名单 / 内部异常）时各层 `applied=False` 并注明原因 —— 字段结构
        保持一致，前端与测试不必区分两套形状。**这里是实测留痕，不是配置回显。**
        """
        skipped = None if executed else ("blocked" if "blacklist_rule" in measured else "failed")
        cpu = measured.get("cpu") or {"applied": False, "error": skipped}
        file_size = measured.get("file_size") or {"applied": False, "error": skipped}
        degraded = [
            name for name, layer in (("cpu", cpu), ("file_size", file_size)) if not layer.get("applied")
        ]
        if not executed:
            degraded.append("memory")
        return {
            "executed": executed,
            "error": error,
            "blacklist": {"rule": measured.get("blacklist_rule"), "executed": False}
            if measured.get("blacklist_rule")
            else None,
            "wall_clock": {
                "limit_s": WALL_TIMEOUT_S,
                "elapsed_s": measured.get("wall_elapsed_s", 0.0),
                "triggered": measured.get("wall_triggered", False),
            },
            "cpu": {
                "limit_s": CPU_LIMIT_S,
                "applied": bool(cpu.get("applied")),
                "error": cpu.get("error"),
                "triggered": measured.get("cpu_triggered", False),
            },
            "memory": {
                "limit_bytes": MEMORY_LIMIT_BYTES,
                "sampled": executed,
                "interval_ms": _SAMPLE_INTERVAL_MS,
                "peak_bytes": measured.get("memory_peak", 0),
                "samples": measured.get("memory_samples", 0),
                "triggered": measured.get("memory_triggered", False),
            },
            "file_size": {
                "limit_bytes": FILE_SIZE_LIMIT_BYTES,
                "applied": bool(file_size.get("applied")),
                "error": file_size.get("error"),
            },
            "output": {
                "limit_bytes": OUTPUT_LIMIT_BYTES,
                "stdout_bytes": measured.get("out_total", 0),
                "stderr_bytes": measured.get("err_total", 0),
                "stdout_truncated": measured.get("out_total", 0) > OUTPUT_LIMIT_BYTES,
                "stderr_truncated": measured.get("err_total", 0) > OUTPUT_LIMIT_BYTES,
            },
            "process_group": {"killed": measured.get("wall_triggered", False) or measured.get("memory_triggered", False)},
            "degraded_layers": degraded,
            "platform": sys.platform,
        }
