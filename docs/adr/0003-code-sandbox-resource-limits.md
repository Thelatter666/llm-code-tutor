# 代码执行器不使用 rlimit 限制内存

受限执行器的内存上限由 `psutil` 轮询采样子进程 RSS 实现（256MB / 100ms），而非 `resource.setrlimit`。**原因已实测确认：macOS darwin 下 `setrlimit` 对 `RLIMIT_AS`、`RLIMIT_DATA`、`RLIMIT_RSS` 一律抛 `ValueError: current limit exceeds maximum limit`**，仅 `RLIMIT_CPU`、`RLIMIT_FSIZE`、`RLIMIT_NOFILE` 可用。演示机正是 macOS，原设计会当场崩溃。

同理，输出截断在父进程读取管道时按 8KB/流截断，不用 `RLIMIT_FSIZE` —— stdout 是 pipe 而非 file，该限制对管道无效。

## Considered Options

- **仅用 rlimit**：零依赖。但在演示平台上内存限制完全不生效，死循环吃内存只能等 CPU 秒耗尽。
- **Docker 沙箱**：隔离最彻底、支持多语言。要求演示环境预装 Docker，与「一键启动」冲突。
- **仅 Linux 生效、macOS 自动降级**：分支多，且演示机恰好走降级路径，等于没有保护。

## Consequences

- 引入 `psutil` 依赖；100ms 采样窗口内可能出现瞬时内存冲高，在演示规模下可接受。
- 最终为四层限制：墙钟 5s 超时 + `RLIMIT_CPU` 3 秒 + psutil 内存 256MB + `RLIMIT_FSIZE` 1MB。每层用 `try/except` 包裹，不支持时降级并记入 `CodeRun.limit_detail`。
- **安全边界必须显式声明**：黑名单（`os.system`、`subprocess` 等）在 Python 下可用 `__import__('o'+'s')`、`getattr` 链轻易绕过，它防的是学生误操作，不是蓄意攻击。此点写入 README 与后台页面。
