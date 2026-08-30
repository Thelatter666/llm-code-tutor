# P4 在线代码编辑器与受限执行器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `POST /code/run`（四层受限执行器）、`CodeSession` 草稿 CRUD、`CodeRun` 历史 `GET /code/runs`，以及 Monaco 在线编辑器页（路由级懒加载）。**这是全项目唯一一批会真实起子进程、真实杀进程、真实建删临时目录的代码 —— 每一层限制都必须真起进程实测，给出数值证据，不接受「理论上生效」。**

**Architecture:** 沿用 `routers → services → domain → infrastructure`。领域层 `domain/code/execution.py` 只放**纯字符串/规则**逻辑（黑名单扫描、命令装配、状态与阈值常量），零 IO 可脱离数据库单测；`CodeExecutor` 以 `Protocol` 定义在 `infrastructure/ports/code_executor.py`（照 `ports/llm.py` 范式），适配器 `SubprocessCodeExecutor` 真起子进程并实施四层限制；`CodeService` 只依赖端口，服务层测试注入 `FakeExecutor`。整段执行是同步阻塞调用，经 `run_in_threadpool` 卸载（ADR-0002）。

**Tech Stack:** Python 3.12 · subprocess / resource / signal / psutil（新增依赖）· FastAPI · SQLAlchemy 2 (async) · Pydantic v2 · pytest · Vue 3 · Vite · TypeScript · monaco-editor 0.56（新增依赖，路由级懒加载）

## Global Constraints

以下约束逐字摘自 spec / ADR / AGENT.md / 批次裁定，每个任务默认包含，不再重复说明。

- 单进程单 worker（ADR-0002）；**整段执行（含 psutil 轮询）必须经 `run_in_threadpool` 卸载**
- 不做数据库迁移，建表用 `create_all`（ADR-0006）；datetime 列用 `app.infrastructure.persistence.db.UTCDateTime`
- 统一响应体 `{code, message, data, request_id}`；端点注入 `CurrentRidDep`，禁止硬编码 `request_id=""`
- 领域层（`backend/app/domain/`）禁止 import 任何基础设施模块，业务规则零 IO 可单测
- 服务层只依赖 `Protocol` 端口，不依赖具体 adapter
- 术语以 `CONTEXT.md` 为唯一来源（代码运行 CodeRun / 代码会话 CodeSession / 执行队列上限 ExecutionQuota / 阻塞卸载 BlockingOffload / 代码执行器 CodeExecutor）
- 不配置 CORS（dev / serve 均同源）
- 禁止任何涉及远端的操作（`git push` / `git remote add`）
- 每个任务完成后跑 `make test`（后端 pytest + 前端 vitest），**基线后端 538 passed / 2 skipped、前端 8 passed**
- 前端：`npx vue-tsc --noEmit` 零错误；路由组件必须懒加载；`frontend/docs/ui-baseline.md` 是强制约束

### Commit 策略

用户已于 **2026-08-31 预先授权**（`AGENT.md`「授权例外」表）：本计划每个 Task 完成且全量测试通过后，**可直接按 Task 粒度 `git commit`**，无需逐次请示。**`git merge` 与 `git push` 不在授权范围内**，仍需用户单独下令。

### 本批次的十条已拍板决策（不再讨论，直接执行）

1. **四层资源限制**（spec §8.3 / ADR-0003），逐层 `try/except` 包裹，不支持时降级并记入 `limit_detail`：

   | 层 | 手段 | 阈值 |
   |---|---|---|
   | 墙钟超时 | `select` 轮询 + `os.killpg(SIGKILL)` | 5s |
   | CPU 时间 | 子进程内 `resource.setrlimit(RLIMIT_CPU)` | 3 CPU 秒 |
   | 内存 | `psutil` 轮询采样进程树 RSS，超阈值 `killpg(SIGKILL)` | 256MB，采样间隔 100ms |
   | 文件写入 | 子进程内 `resource.setrlimit(RLIMIT_FSIZE)` | 1MB |

   **绝不使用 `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_RSS`** —— 本机实测（见 §基准实测）三项均抛 `ValueError: current limit exceeds maximum limit`。
2. **输出截断在父进程读管道时做**（stdout / stderr 各 8KB），解码 `errors="replace"`。不用 `RLIMIT_FSIZE` 截输出 —— stdout 是 pipe 不是 file，该限制对管道无效。
3. **必须杀掉整个进程组**：`start_new_session=True`，终止时 `os.killpg(os.getpgid(pid), SIGKILL)`，并 `wait()` 回收避免僵尸。
4. **stdin 用临时文件重定向**，不走管道写入 —— 学生代码不读 stdin 时父进程写大块数据会死锁。
5. **临时目录在成功 / 超时 / 被杀 / 抛异常四条路径下都必须清理**（`try/finally`）。
6. **黑名单是防误触，不是防攻击**（spec §8.3）：命中即 `status=blocked` 直接返回不执行，并在 README 与后台页面显式声明「被执行代码以当前 OS 用户身份运行，对本机文件系统有读权限」。不做真正的安全边界。
7. 子进程 `env` 清空继承；Python 以 `python -I -S` 启动，JS 用 `node`。
8. **并发上限 2（信号量）；获取信号量超时 10s 即返回 `429` + `retry_after`，不无限排队**（spec §9）。
9. 整段执行（含 psutil 轮询）是同步阻塞调用，必须经 `run_in_threadpool` 卸载（ADR-0002）。
10. 审计落 `AuditLog(action=code_run)`；Monaco 必须**路由级懒加载**；沿用 `frontend/docs/ui-baseline.md` 的配色 / 间距 / 圆角。

### 基准实测（2026-08-31，本机 macOS darwin，作为本计划的事实依据）

| 项 | 实测结果 |
|---|---|
| `setrlimit(RLIMIT_AS\|DATA\|RSS, ...)` | 三项均 `ValueError: current limit exceeds maximum limit` —— **ADR-0003 结论在本机复现** |
| `setrlimit(RLIMIT_CPU\|FSIZE\|NOFILE, ...)` | 全部成功 |
| `setrlimit` 无法再抬高 | `ValueError: not allowed to raise maximum limit`（故只能在子进程内、用户代码之前设置） |
| `while True: a.append(1)` | 3.12s 达 500.4MB RSS → **256MB 约在 1.5s 处触发，早于 3s CPU 限制**，内存层可独立验证 |
| `RLIMIT_CPU=2s` + `while True: pass` | 2.12s 被杀，`returncode=-24`（SIGXCPU） |
| `RLIMIT_FSIZE=1MB` 写 4MB（Python / Node） | Python：`OSError [Errno 27] File too large`；Node：`EFBIG`；文件实际落盘 1048576 字节 |
| `killpg` 杀孙进程 | 先 `subprocess.Popen(['/bin/sh','-c','sleep 60'])` 再被杀：子孙进程 pid 存活检查为 `False`，无僵尸 |
| 打印 1MB 到管道 | 非阻塞 `select` 抽取 19 次读完，耗时 0.04s |
| `sleep 10` | 5.00s 被墙钟杀掉，`returncode=-9` |
| `python -I -S` | 正常工作；`env={}` 亦可正常启动 |

---

## File Structure

```
backend/
├── app/
│   ├── domain/code/
│   │   └── execution.py                运行状态 / 阈值常量、黑名单扫描、命令装配（零 IO）
│   ├── infrastructure/
│   │   ├── ports/code_executor.py      ExecutionResult + CodeExecutor Protocol
│   │   ├── adapters/execution/
│   │   │   ├── __init__.py
│   │   │   └── subprocess_executor.py  SubprocessCodeExecutor（四层限制 + 进程组 kill）
│   │   ├── persistence/models.py       + CodeSession / CodeRun
│   │   ├── concurrency.py              + execution_slot()（并发上限 2 + 等待超时 10s）
│   │   └── runtime.py                  + get/set_code_executor（测试注入点）
│   ├── core/config.py                  + execution_concurrency / execution_quota_timeout_s
│   ├── services/code_service.py        + run() / 草稿 CRUD / 运行历史
│   ├── schemas/code.py                 + 运行与草稿出入参
│   └── routers/code.py                 + POST /code/run、sessions CRUD、GET /code/runs
├── pyproject.toml                      + psutil
└── tests/
    ├── test_execution_policy.py        领域层：黑名单 + 命令装配（纯字符串）
    ├── test_code_executor.py           适配器层：真实子进程，12 条限制实测
    ├── test_execution_leaks.py         临时目录 / 僵尸进程 / 孙进程逃逸
    ├── test_code_run_models.py         CodeSession / CodeRun 表
    ├── test_code_run_service.py        服务层（FakeExecutor）
    └── test_code_run_api.py            HTTP 层（鉴权 / 429 / request_id）

frontend/
├── package.json                        + monaco-editor
├── vite.config.ts                      + monaco 单独分包
├── src/
│   ├── api/code.ts                     + runCode / sessions CRUD / runs
│   ├── types/code.ts                   + CodeRun / CodeSession
│   ├── components/CodeEditor.vue       Monaco 懒加载包装（含 worker 配置）
│   ├── views/student/CodeEditorView.vue
│   ├── router/index.ts                 + /editor（懒加载）
│   └── components/AppShell.vue         + 导航项
└── docs/ui-baseline.md                 （只读，不改）
```

---

## Task 0: 实施计划

- [x] 本文件落盘并 commit（`docs: P4 实施计划（在线编辑器与受限执行器）`）。

---

## Task 1: 领域层执行策略（零 IO）

**Files:**
- Create: `backend/app/domain/code/execution.py`
- Create: `backend/tests/test_execution_policy.py`

> **spec §8.3 步骤 1**：黑名单扫描命中即 `status=blocked` 直接返回，不执行。
> **本批次裁定**：扫描前先**剥离注释与字符串字面量**（Python 用标准库 `tokenize`，JS 用正则）。理由：教学代码里常见「不要用 `os.system`」这类注释，不剥离会产生令人困惑的误报；剥离是纯字符串工作，零 IO、确定性、可单测。`tokenize` 抛错时（源码写了一半）回退到原始源码 —— 宁可误报也不漏报。
> **黑名单是防误触，不是防攻击** —— 不做编码绕过对抗（`__import__('o'+'s')` 一笔带过），此点写入完成报告与 README 声明。

- [ ] **Step 1: 失败测试**

| 组 | 断言 |
|---|---|
| 常量 | `RUN_LANGUAGES=('python','javascript')`；五种 status 常量取值与 spec §5 一字不差；四个阈值常量 = 5s / 3 / 256MB / 1MB / 8KB |
| Python 黑名单 | `os.system(...)`、`import subprocess`、`socket.socket()`、`shutil.rmtree('/')`、`__import__('os')` 各自命中并给出规则名 |
| eval+exec | `eval(x)` 单独**不**命中；`exec(y)` 单独**不**命中；两者同时出现才命中 `eval_exec` |
| JS 黑名单 | `child_process`、`new Function(`、`fs.rmSync` 命中；普通 `console.log` 不命中 |
| 注释剥离 | `# 不要使用 os.system` 注释**不**命中；`"""os.system"""` 文档字符串**不**命中 |
| 剥离失败回退 | 未闭合的括号（`tokenize` 抛错）→ 回退原始源码，`os.system` 仍命中 |
| 命令装配 | Python → `[sys.executable, '-I', '-S', '-c', <bootstrap>, script]`；JS → `[sys.executable, '-c', <bootstrap>, node, script]`；脚本文件名 `main.py` / `main.js` |
| 环境装配 | `build_env()` 不含 `PATH` 之外的任何宿主环境变量，且不含 `HOME` / `PYTHONPATH` |
| 零 IO | 模块源码不含 `import sqlalchemy` / `open(` / `subprocess` / `requests`（源码级断言） |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: `make test` 通过 → Commit** `feat(backend): 执行策略领域层，黑名单扫描与受限命令装配（spec §8.3 ADR-0003）`

---

## Task 2: CodeSession / CodeRun 表

**Files:**
- Modify: `backend/app/infrastructure/persistence/models.py`
- Create: `backend/tests/test_code_run_models.py`

> **spec §5**：
> - `CodeSession` = user_id, language, source_code, title, created_at, updated_at
> - `CodeRun` = user_id, language, source_code, stdin, status(accepted\|runtime_error\|timeout\|memory_exceeded\|blocked), stdout, stderr, exit_code, duration_ms, **limit_detail(JSON)**, created_at
> `limit_detail` 是本批次的证据载体，结构由本批次定稿（见下），四层各自记录 `applied` / `triggered` / 实测值。

- [ ] **Step 1: 失败测试**

| 断言 |
|---|
| 建表成功，`code_sessions` / `code_runs` 两表存在 |
| `CodeSession` 的 `source_code` 可读写长文本；`updated_at` 有 `onupdate`（改草稿会推进） |
| `CodeRun.limit_detail` 是 JSON 列，写入嵌套 dict 后原样读回 |
| `CodeRun.status` 五种取值均可落库（参数化） |
| `exit_code` 可为 `None`（blocked 时未执行） |
| 两表的 `created_at` 均带 UTC 时区 |
| `CodeRun` 按 `user_id` 建索引（历史查询按用户过滤） |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: `make test` 通过 → Commit** `feat(backend): CodeSession 与 CodeRun 表，limit_detail 记录四层限制生效情况（spec §5 §8.3）`

---

## Task 3: CodeExecutor 端口 + SubprocessCodeExecutor 适配器

**Files:**
- Create: `backend/app/infrastructure/ports/code_executor.py`
- Create: `backend/app/infrastructure/adapters/execution/__init__.py` `subprocess_executor.py`
- Create: `backend/tests/test_code_executor.py` `backend/tests/test_execution_leaks.py`
- Modify: `backend/pyproject.toml`（+ `psutil`）
- Modify: `backend/app/infrastructure/runtime.py`（注入点）

> **端口范式照 `infrastructure/ports/llm.py`**：`@runtime_checkable` 的 `Protocol` + `@dataclass(frozen=True)` 的结果对象。
> **端口是同步的**（`def execute(...) -> ExecutionResult`）—— 因为整段执行是阻塞调用，服务层用 `run_in_threadpool` 卸载；把端口定义成 `async` 会掩盖「它其实阻塞」这一事实（ADR-0002）。
>
> **`preexec_fn` 禁用**：适配器跑在线程池里，`subprocess` 的 `preexec_fn` 在多线程进程中存在 fork 后持锁死锁的已知风险。改为**在子进程内用引导脚本自设 rlimit**：
> - Python：`[sys.executable, '-I', '-S', '-c', BOOTSTRAP, script, status_path]` —— bootstrap 设 rlimit、`exec(compile(...))` 执行用户代码
> - Node：`[sys.executable, '-c', BOOTSTRAP_EXEC, node, script, status_path]` —— bootstrap 设 rlimit 后 `os.execv` 让位给 node
> rlimit 跨 `exec` 保留；bootstrap 把各层是否设置成功写入 `status.json`，父进程读回后并入 `limit_detail`。
> **不用 `runpy`**：它的内部帧会出现在学生看到的 traceback 里。用 `exec(compile(src, 'main.py', 'exec'), globals)` 并在 bootstrap 里剥掉自身帧，学生只看到 `File "main.py", line N`。
>
> **读取管道用非阻塞 `select` 循环**，与 psutil 内存采样共用同一个 100ms 节拍：醒来先抽管道（保证子进程不会因管道满而阻塞），再采内存，再看墙钟。**超出 8KB 后继续读但丢弃**，只置 `truncated=true`。

- [ ] **Step 1: 失败测试**（`tests/test_code_executor.py`，全部真起子进程）

| # | 用例 | 断言（数值证据） |
|---|---|---|
| 1 | 吃内存 `a=[]` + `while True: a.append(1)` | `status=memory_exceeded`；`limit_detail.memory.peak_bytes > 256MB`；`duration_ms < 5000`（证明是内存层而非墙钟杀的）；`triggered=true` |
| 2 | 死循环 `while True: pass` | `status=timeout`；`limit_detail.cpu.triggered=true` 或 `exit_code=-24`（SIGXCPU）；实测 wall ≈3s |
| 3 | `time.sleep(10)` | `status=timeout`；`exit_code=-9`；`duration_ms` 落在 5000–6500ms |
| 4 | 写 4MB 文件 | Python：`OSError [Errno 27] File too large`；Node：`EFBIG`；`limit_detail.file_size.applied=true`；落盘文件 ≤1MB |
| 5 | 打印 1MB 字符 | `len(stdout) == 8192`（截断后），`limit_detail.output.stdout_truncated=true`，`status=accepted` 且进程正常退出（不因管道满而卡到超时） |
| 6 | 命中黑名单（写文件做副作用） | `status=blocked`；`stdout`/`stderr` 为空；**副作用文件不存在**（用独立目录验证真的没跑） |
| 7 | 正常代码 | `status=accepted`；`stdout` 正确；`exit_code=0`；`duration_ms` 有值 |
| 8 | 孙进程逃逸 | 代码内 `subprocess.Popen(sleep 60)` 后父进程被杀 → 孙进程 pid 存活检查为 `False` |
| 9 | stdin | `input()` 能读到 stdin；不读 stdin 的代码不被阻塞 |
| 10 | Python 异常 | `status=runtime_error`，`exit_code=1`，stderr 含 `File "main.py"` 且**不含 `runpy`** |
| 11 | JS 正常 / 死循环 / 写大文件 | 三例均按预期；JS 死循环被 CPU 或墙钟杀掉 |
| 12 | 二进制输出 | 输出 `\xff\xfe` 不触发 `UnicodeDecodeError`，`errors="replace"` 生效 |
| 13 | `limit_detail` 结构 | 四层各有 `applied`；本机 `cpu.applied=true` / `file_size.applied=true` / `memory.sampled=true` |
| 14 | 端口符合性 | `isinstance(SubprocessCodeExecutor(), CodeExecutor)`（`@runtime_checkable`） |

- [ ] **Step 2: 失败测试**（`tests/test_execution_leaks.py`）

| 断言 |
|---|
| 成功 / 超时 / 被杀 / 抛异常四条路径各跑一次后，`tempfile.gettempdir()` 下 `coderun-` 前缀目录数量归零 |
| 批量执行（含第 8 条孙进程逃逸）后，`psutil` 扫描不到 status 为 zombie 且 ppid 为本进程的子进程 |
| 抛异常路径：注入一个会让 `Popen` 抛错的解释器路径 → 仍然清理临时目录，且返回 `runtime_error` 而非抛出 |

- [ ] **Step 3–5: 失败 → 实现 → 通过**
- [ ] **Step 6: `make test` 通过 → Commit** `feat(backend): CodeExecutor 端口与 SubprocessCodeExecutor 适配器，四层限制真起进程实测（spec §8.3 ADR-0003）`

---

## Task 4: CodeService.run（并发上限 / 阻塞卸载 / 落库 / 审计）

**Files:**
- Modify: `backend/app/core/config.py`（+ `execution_concurrency` / `execution_quota_timeout_s`）
- Modify: `backend/app/infrastructure/concurrency.py`（+ `execution_slot()`）
- Modify: `backend/app/services/code_service.py`
- Create: `backend/tests/test_code_run_service.py`

> **spec §8.3 末尾 / §9**：并发上限 2，获取信号量超时 10s 返回 `429` + `retry_after`，不无限排队。
> **`asyncio.Semaphore` + `wait_for` 的已知隐患**：等待者被取消时可能丢失许可。因此除了「第 3 个请求 429」之外，**必须再测一次「429 之后仍能跑满 2 路」**，用行为证明许可没有泄漏。若该用例失败则改为自实现配额计数。
> **阻塞卸载**（ADR-0002）：`await run_in_threadpool(self._executor.execute, ...)`，服务层测试用 monkeypatch 计数断言。
> **服务层只依赖端口**：注入 `FakeExecutor`（同签名，可脚本化返回 `ExecutionResult`）。

- [ ] **Step 1: 失败测试**

| 断言 |
|---|
| 正常执行：落一行 `CodeRun`，字段与 executor 返回值一致；`AuditLog(action=code_run)` 落库 |
| 执行经 `run_in_threadpool`（monkeypatch 计数 +1） |
| 命中黑名单：仍落 `CodeRun`（status=blocked）与审计，但 **executor 的 `execute` 被调用**（拦截在适配器内） |
| 第 3 个并发请求 → `ApiError(4290)`，`data.retry_after` 为正数；前两个不受影响 |
| 429 之后队列空出，再并发 2 个 → 全部成功（**许可未泄漏**） |
| 除 2 路并发外，等待超时用 `execution_quota_timeout_s=0.1` 缩短，测试不真等 10s |
| `limit_detail` 原样落库（嵌套 dict 往返一致） |
| 草稿 CRUD：创建 / 列表 / 改名 / 改源码 / 删除；**跨用户隔离**（A 只能看到自己的） |
| 运行历史：按 `created_at` 倒序，按用户过滤，`page` + `page_size` 返回 `{items, total}` |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: `make test` 通过 → Commit** `feat(backend): CodeService.run —— 并发上限 2 与 429、阻塞卸载、CodeRun 落库与审计（spec §8.3 §9 ADR-0002）`

---

## Task 5: code 路由

**Files:**
- Modify: `backend/app/schemas/code.py` `backend/app/routers/code.py` `backend/app/main.py`

> **spec §6.2 code 行**：
> - `POST /code/run {language, source, stdin}` → `{status, stdout, stderr, exit_code, duration_ms, limit_detail, run_id}`
> - `GET/POST/PATCH/DELETE /code/sessions`、`GET /code/runs`（编辑器草稿与历史）
> 「编辑器页」按 §3.2 权衡 15 属**豁免入口**（`review_my_code`），但本批次的 `/code/run` **不发起 LLM 调用**，故不涉及意图装配 —— 豁免声明落在页面文案上（P3 已在同一导航页做过）。

- [ ] **Step 1: 失败测试**

| 断言 |
|---|
| 未鉴权 → `4010` |
| Python 正常代码 → `code=0`，七个响应字段齐备，`run_id` 非空 |
| `language=ruby` → 422；`source` 空 / 超 20000 字 → 422；`stdin` 超长度 → 422 |
| 响应体 `request_id` 与响应头一致且非空 |
| 死循环真实请求 → `status=timeout`（HTTP 层也真跑，证明卸载没冻住路由） |
| 草稿 CRUD 五个端点：创建 / 列表 / 更新 / 删除 / 越权 404 |
| `GET /code/runs` 分页返回 `{items, total}`，按时间倒序 |
| 并发第 3 个请求 → HTTP 429 且 body 含 `retry_after` |

- [ ] **Step 2–4: 失败 → 实现（router 不含业务逻辑）→ 通过**
- [ ] **Step 5: `make test` 通过 → Commit** `feat(backend): POST /code/run 与草稿 / 历史端点，统一响应与鉴权接入（spec §6.2）`

---

## Task 6: 前端 Monaco 编辑器页

**Files:**
- Modify: `frontend/package.json`（+ `monaco-editor`）
- Create: `frontend/src/components/CodeEditor.vue` `frontend/src/views/student/CodeEditorView.vue`
- Modify: `frontend/src/api/code.ts` `frontend/src/types/code.ts` `frontend/src/router/index.ts` `frontend/src/components/AppShell.vue` `frontend/vite.config.ts`

> **Monaco 体积大 → 路由级懒加载**（ui-baseline §6，Medium 严重度）。`CodeEditor.vue` 内部再对 `monaco-editor` 做动态 `import()`，使 Monaco 只在该路由被访问时才下载。
> **Worker 配置照官方文档**（`monaco-editor/docs/integrate-esm.md` 的 Vite 段，配合 Vite 内建 `?worker` 支持）：实现 `self.MonacoEnvironment.getWorker`（**不是 `getWorkerUrl`**），`javascript`/`typescript` 标签给 ts.worker，其余给 editor.worker。
> 页面：语言切换（Python / JavaScript）+ 运行按钮 + 输出面板（stdout / stderr / exit_code / duration_ms）+ 限制层明细（读 `limit_detail`）+ 运行历史 + 安全边界声明条（ADR-0003 要求显式声明）。

- [ ] **Step 1: 依赖安装 + `CodeEditor.vue`（Monaco 懒加载与 worker）**
- [ ] **Step 2: 页面 / API / 类型 / 路由 / 导航**
- [ ] **Step 3: `npx vue-tsc --noEmit && npx vite build` 零错；记录产物体积变化与 monaco chunk 名字**
- [ ] **Step 4: `make test` 通过 → Commit** `feat(frontend): 在线代码编辑器页，Monaco 路由级懒加载与运行输出面板（spec §6.2 §8.3）`

---

## Task 7: 12 条限制层实测 + 变异测试 + 完成报告

**Files:**
- Create: `docs/review/2026-08-30-p4-completion-report.md`

- [ ] **Step 1: 12 条实测**（起真服务 `uvicorn app.main:app --workers 1`，逐条给数值）：
  1. 吃内存 → 被杀 + RSS 峰值
  2. 死循环 → wall / CPU 实测
  3. `sleep 10` → 墙钟实测
  4. 写大文件 → 实测写入量与失败方式
  5. 输出超长 → 实测 stdout 长度
  6. 黑名单 → `blocked` + 副作用文件不存在
  7. 正常代码 → `accepted`
  8. 孙进程逃逸 → 前后进程存活对比
  9. **事件循环不被冻结**：执行期间高频打 `/health`（≥50 次采样），给出中位数 / P95 / 最大值，并与空闲基线对比
  10. 并发第 3 个 → 429 + `retry_after`
  11. 临时目录无泄漏（四路径各一次）
  12. 无僵尸进程
- [ ] **Step 2: 前端实测** —— Monaco 懒加载证据（chunk 名 + 体积）、构建产物体积变化、编辑器在浏览器中实际可编辑并运行（截图或 DOM 断言）
- [ ] **Step 3: 变异测试**（每条都实际跑过，记录失败的测试名）
- [ ] **Step 4: 写完成报告并 commit** `docs: P4 完成报告（含 12 条限制层实测与变异测试指引）`

---

## 验收清单（P4 完成标准）

- [ ] `make test` 全绿（后端 538 + 新增、前端 8 + 新增）
- [ ] `POST /code/run` 七字段齐备；四类终止状态（`accepted` / `runtime_error` / `timeout` / `memory_exceeded`）与 `blocked` 均可复现
- [ ] 四层限制逐层实测有效，且 `limit_detail` 如实记录各层 `applied` / `triggered`
- [ ] 进程组 kill 覆盖孙进程；无僵尸进程；临时目录四条路径均无泄漏
- [ ] 并发上限 2 生效，第 3 个返回 429 且许可不泄漏
- [ ] 事件循环不被冻结（`/health` P95 与空闲基线对比）
- [ ] 前端 Monaco 路由级懒加载；编辑器实际可编辑并运行
- [ ] 安全边界声明在页面与 README 显式可见

## 待处理项（留到后续批次）

- P5 编程题判题将复用 `CodeExecutor` 端口（spec §11）
- 网络隔离（spec §3.3 边界外）：当前执行器不限制网络访问
- P6 后台页面的安全边界声明条（ADR-0003 要求「后台页面」也要有，本批次先落学生端编辑器页）
