"""代码执行器端口（CONTEXT.md「代码执行器 CodeExecutor」）。

范式照 `ports/llm.py`：`@runtime_checkable` 的 `Protocol` + `frozen` dataclass 结果
对象，让契约测试能用 `isinstance` 断言端口符合性。

### 为什么端口是同步的

整段执行（起进程、抽管道、psutil 轮询、杀进程组）**是同步阻塞调用**，由服务层
经 `run_in_threadpool` 卸载（ADR-0002）。若把端口定义成 `async def`，会掩盖
「它其实会阻塞事件循环」这一事实 —— 后来者会以为可以直接 `await` 而忘记卸载，
那正是 ADR-0002 要防的事。同步签名让「必须卸载」这一个约束在类型上就可见。

### limit_detail 的契约

`limit_detail` 不是配置回显，而是**每次运行的实测留痕**：每层记录 `applied`
（这一层在当前平台是否真的设上了）、`triggered`（这次是不是被它杀掉的）与实测
值。平台不支持某层时 `applied=false` 并附 `error` —— 降级必须可见（spec §9）。
"""

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecutionResult:
    """一次代码执行的完整结果（spec §6.2 的 `/code/run` 响应骨架）。

    `exit_code` 为负表示被信号杀死（-9 SIGKILL / -24 SIGXCPU）；
    命中黑名单时为 `None` —— 代码根本没有启动过，谈不到退出码。
    """

    status: str
    stdout: str
    stderr: str
    exit_code: Optional[int]
    duration_ms: int
    limit_detail: dict


@runtime_checkable
class CodeExecutor(Protocol):
    """代码执行器端口。

    实现必须满足：命中黑名单时**不执行**任何用户代码，直接返回 `status=blocked`。
    """

    def execute(self, *, language: str, source: str, stdin: str = "") -> ExecutionResult: ...
