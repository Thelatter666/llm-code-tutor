# P4 在线代码编辑器与受限执行器 —— 完成报告

- 日期：2026-08-31
- 分支：`feat/p4-editor-sandbox`（基点 `7a2cbf2`，**未 merge、未 push**）
- 实施计划：`docs/superpowers/plans/2026-08-30-p4-editor-sandbox.md`
- 直接依据：`docs/adr/0003-code-sandbox-resource-limits.md`、ADR-0002、spec §3.1 / §3.2 / §5 / §6.2 / §8.3 / §9
- 环境：Apple Silicon / macOS（darwin 24.6.0），Python 3.12，Node v24，`.venv` 依赖齐全（含 psutil）
- 测试基线：P0+P1+P2+P3 = `658 passed / 2 skipped`（commit `730222c` 上）；P4 全量 = **`659 passed / 2 skipped / 0 failed`**（129.33s，本批 +1）+ 前端 vitest `8 passed`
- 本文所有「实测」均来自**真服务**（`uvicorn app.main:app --workers 1`，独立库 `backend/data/e2e-p4.db`）+
  真 SQLite + 真子进程 + 真浏览器（Playwright），非推断；无 API Key（Mock 模式）为既定演示路径

> **环境备注（重要）**：本批的全量测试与 uvicorn 均在 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`
> 下运行。原因：sentence-transformers 加载已缓存模型时默认仍会联网查 Hugging Face Hub，
> 在 ZCode 执行环境的受限网络下该请求**无限等待**（进程采样确认主线程停在 kqueue），
> 表现为全量测试卡死在 `test_embedding_switch.py::test_rebuild_uses_the_newly_configured_model`。
> 加离线标志后该用例 9.05s 通过，测试语义零变化（只是跳过对已缓存模型的在线版本检查）。
> 在无网络限制的终端里跑 `make test` 不需要这两个变量。详见 §8 偏离 2。

---

## 1. 任务清单

| # | Task | 状态 | Commit |
|---|---|---|---|
| 0 | P4 实施计划（含基准实测表） | 完成 | `5bd7e68` |
| 1 | 领域层执行策略：黑名单扫描（注释/字符串剥离）+ 受限命令装配，零 IO | 完成 | `0bd6466` |
| 2 | `CodeSession` / `CodeRun` 表 + `limit_detail` JSON 结构 | 完成 | `63a7aee` |
| 3 | `CodeExecutor` 端口（同步 Protocol）+ `SubprocessCodeExecutor`（四层限制真起进程实测） | 完成 | `584957c` |
| 4 | `CodeService.run`：并发 2 + 429 + `run_in_threadpool` 卸载 + 落库 + 审计 | 完成 | `407fabb` |
| 5 | `POST /code/run` + 草稿 CRUD + `GET /code/runs` 路由 | 完成 | `730222c` |
| 6 | 前端 Monaco 编辑器页（路由级懒加载 + worker 配置 + 运行输出面板） | 完成 | `3477f71` |
| 7 | `make test` 全量 + 浏览器实测（本报告 §5） | 完成 | 随 6 |
| — | 内存阈值可注入（负载缓解，2026-08-31 用户确认；默认 256MB 不变） | 完成 | `8ae1f4a` |
| — | 顶层 README + ADR-0003 安全边界声明 | 完成 | `26410ba` |
| — | 12 条限制层实测 + 降级路径 + 变异测试 + 本报告 | 完成 | 本 commit |

**边界遵守**：领域层（`app/domain/`）零基础设施 import（源码级用例守住）；服务层只依赖
`CodeExecutor` Protocol（服务层测试用 `FakeExecutor`，适配器层测试真起子进程，两者不混）；
`subprocess_executor.py` 无 `RLIMIT_AS/DATA/RSS`（M11 变异测试反向验证，见 §12）。

---

## 2. 端点实测：`POST /code/run` 与草稿 / 历史

真服务（端口 8000，独立库 `backend/data/e2e-p4.db`），学生账号 `p4demo`（HTTP 注册创建）。

| 请求 | 实测结果 |
|---|---|
| 未带 Token `POST /code/run` | `HTTP 401 {"code":4010,"message":"未提供登录凭证"}`，`request_id` 非空且与响应头一致 |
| `language=ruby` | `HTTP 422`（`string_pattern_mismatch`，Pydantic 白名单） |
| `source` 超 20000 字 | `HTTP 422`（`string_too_long`） |
| Python `print('hello', sum(range(11)))` | `HTTP 200`，`code=0`，`status=accepted`、`stdout="hello 55"`、`exit_code=0`、`duration_ms=33`、`run_id=7859e376-…` 七字段齐备 |
| 黑名单代码 | `HTTP 200`（**业务结果不是 HTTP 错误**），`status=blocked`，`exit_code=null`，`duration_ms=0` |
| `GET /code/runs?page=1&page_size=20` | `{items, total}`，按 `created_at` 倒序；全部实测结束后该用户共落 15 行 `CodeRun`（覆盖 accepted / runtime_error / timeout / memory_exceeded / blocked 五种状态） |
| 草稿 CRUD | 浏览器实测保存草稿成功（§5）；服务层 pytest 覆盖创建/列表/改名/改源码/删除/跨用户隔离 |

统一响应体 `{code, message, data, request_id}` 全部端点遵守；「blocked / timeout /
memory_exceeded 都是 200」是有意设计 —— 它们是对输入的正常业务结果，不是服务器错误。

---

## 3. 限制层实测表（12 条，逐条数值证据）

**实测口径**：真实 uvicorn（默认配置，`--workers 1`）+ 真实 HTTP `POST /code/run` +
真实子进程。下表为 2026-08-31 实测驱动脚本的一次完整运行（脚本逐条打印 JSON，结果快照存
`/tmp/p4_task7_results.json`）。

| # | 验证项 | 实测结果（真服务 HTTP） | pytest 旁证（`-s` 输出） |
|---|---|---|---|
| 1 | 持续吃内存（真实 256MB 阈值） | `status=memory_exceeded`，**peak=304.8MB**（319,651,840 B），samples=12，exit_code=**-9**，duration=1209ms | peak 292.4MB / 0.90s / 9 samples；本批 279.3MB / 1.09s |
| 2 | 死循环不占内存 → CPU 层 | `status=timeout`，exit_code=**-24（SIGXCPU）**，duration=3110ms，`cpu.applied=true`、`cpu.triggered=true`、`wall_clock.triggered=false`（证明是 CPU 层杀的，不是墙钟兜底） | exit -24 / 3.10s |
| 3 | 纯睡眠 10s → 墙钟层 | `status=timeout`，exit_code=**-9**，duration=**5100ms**，`wall_clock.triggered=true`；`stdout` 无「不应出现」 | 5.05s / -9 |
| 4 | 写 4MB 文件 → `RLIMIT_FSIZE` | Python `stderr="errno 27"`（**EFBIG**）；代码内 `getsize` 输出 **1048576 字节**，HTTP 返回后驱动脚本从沙箱外 `os.stat` 复核同为 **1048576 字节**（= 上限，分毫不差）；`file_size.applied=true` | Python errno 27 / JS EFBIG / 落盘 1,048,576 B |
| 5 | 输出超长 → 8KB 截断 | 截断后 stdout 恰 **8192 字节**，实际产出 **1048581 字节**（`output.stdout_bytes`），`stdout_truncated=true`，尾部 `TAIL` 被截掉；`status=accepted`（进程没被管道卡死） | 同 8192 / 1048581 |
| 6 | 命中黑名单 → 不执行 | `status=blocked`，`blacklist.rule=os_system`，`executed=false`，exit_code=null，**副作用文件未产生**（代码里写了 `os.system('touch …')`，执行即会留痕），duration=0 | rule=os_system，副作用未产生 |
| 7 | 正常代码 | `status=accepted`，`stdout="hello 55"`，exit_code=0，duration=33ms，`run_id` 返回 | 4 组参数化用例全过 |
| 8 | 孙进程逃逸（`os.fork`） | 沙箱 fork 出孙进程 pid=**6296**，父进程 5014ms 被墙钟杀，`process_group.killed=true`，HTTP 返回后 `psutil.pid_exists(6296)=**False**` | pid 37087 存活=False / 5.04s |
| 9 | 事件循环不冻结 | 空闲基线 60 次 `/health`：中位 **0.70ms** / P95 **1.45ms** / 最大 2.48ms；执行 4.5s 睡眠任务期间连打 **200 次**：中位 **0.72ms** / P95 **1.18ms** / 最大 **4.31ms** —— 与空闲基线同量级，无冻结 | — |
| 10 | 并发第 3 个 → 429 | 见 §4：HTTP **429**，`code=4290`，`retry_after=0.5`，且其后 2 并发全部成功（许可不泄漏） | 服务层/API 层 429 用例（超时缩至 0.1s） |
| 11 | 临时目录无泄漏 | 四路径前后计数全为 0 泄漏：成功 0 / 超时 0 / 内存杀 0 / 黑名单（不建目录）0；**异常路径**（坏解释器直连适配器逼 `Popen` 抛 `FileNotFoundError`）泄漏 0 且返回 `runtime_error` | `test_execution_leaks.py` 8 条全过 |
| 12 | 无僵尸进程 | 全部实测跑完后扫描 uvicorn（pid 6236）整棵子树：**zombie = 0 个** | 批量执行后 `psutil` 扫描为空 |

第 8 条用 `os.fork` 而非 `subprocess` 的原因：`subprocess` 在源码层就被黑名单拦截（命中的话
连进程都起不来，验不了进程组 kill）；`os.fork` 同样能派生孙进程且不在黑名单 —— 用它才能
单独验证「杀进程组」这一层本身。黑名单**不是**安全边界（ADR-0003），`os.fork` 正是一例。

---

## 4. 事件循环不冻结与并发上限（专项实测）

### 4.1 阻塞卸载生效：执行期间事件循环延迟与空闲同量级

方法：先测 60 次空闲 `/health` 基线；随后起一个 4.5s 的 `/code/run`（`time.sleep(4.5)`，
整段执行含 psutil 轮询都在线程池里），执行期间主线程连打 `/health` 200 次，逐次计耗时。

| 采样 | n | 中位数 | P95 | 最大 |
|---|---|---|---|---|
| 空闲基线 | 60 | 0.70 ms | 1.45 ms | 2.48 ms |
| 执行期间 | 200 | 0.72 ms | 1.18 ms | 4.31 ms |

执行期间的 P95 与中位数**不高于**空闲基线（最大值 4.31ms 为单次毛刺，仍是毫秒量级）——
`run_in_threadpool`（ADR-0002 BlockingOffload）把阻塞调用挡在事件循环之外，`/health`
这类轻请求完全不受影响。卸载本身另有服务层用例锁住（M10 变异测试，§12）。

### 4.2 并发上限 2 与 429（真实 HTTP）

在第二个真实例（端口 8001）上实测，`EXECUTION_QUOTA_TIMEOUT_S=0.5`（把信号量等待超时从
默认 10s 缩到 0.5s 以便触发）。**为什么必须缩短**：生产默认下墙钟 5s 会先于 10s 等待超时
释放并发位，第 3 个请求总能等到执行位 —— 429 机制真实存在但需要更长的占用才可见；
缩短等待超时只改变「等多久才 429」，不改变上限与释放逻辑。

3 个并发 `time.sleep(2)` 请求同时发出：

| 请求 | 结果 | 耗时 |
|---|---|---|
| #1 | HTTP 200，`accepted` | 2.11s |
| #2 | HTTP 200，`accepted` | 2.11s |
| #3 | **HTTP 429**，`code=4290`，`retry_after=0.5`，「代码执行并发已满，请稍后重试」 | 0.56s（等满超时被拒） |

紧接其后的 2 并发验证（许可不泄漏）：HTTP 200 × 2（2.08s / 2.09s），`accepted` × 2 ——
429 没有泄漏信号量许可，队列空出后立即恢复满速 2 路。

---

## 5. 前端实测：Monaco 路由级懒加载 + 浏览器真实运行

### 5.1 构建产物（`npx vue-tsc --noEmit && npx vite build`，最终验证跑一次）

`vue-tsc` 零错误；`vite build` 成功（2981 modules，40.69s）。关键产物：

| 产物 | 体积 | gzip | 说明 |
|---|---|---|---|
| `CodeEditorView-BiOOahIv.js` | 9.81 kB | 4.26 kB | **路由级懒加载独立 chunk**（hash 与交接记录一致） |
| `CodeEditorView-DWvVoeTd.css` | 3.42 kB | 0.87 kB | 页面样式 |
| `monaco-Df6frexO.js` | 4,002.67 kB | 1,034.43 kB | Monaco 单独成块，仅在访问 /editor 时下载 |
| `ts.worker-DTZAwq0V.js` | 7,043.07 kB | — | TS/JS 语言 worker（`?worker` 产出） |
| `editor.worker-DCKwvLbM.js` | 274.13 kB | — | 基础编辑 worker |
| `index-M_mHYPOr.js` | **56.21 kB** | 21.48 kB | 业务主包 —— hash 与 P4 前基线**完全一致**，零回归 |

dev 模式网络面板旁证：进入 `/#/editor` 后浏览器才开始请求 `monaco-editor` 主模块与
editor.worker / ts.worker（`MonacoEnvironment.getWorker` 配置生效，JS/Python 语言切换时
worker 正常服务）。

### 5.2 浏览器真实运行验证（Playwright，真服务 + 真后端）

账号 `p4demo` 从登录页真实登录 → 进入 `/#/editor`，全程真实键盘/点击事件：

| 步骤 | 断言结果 |
|---|---|
| 编辑器可编辑 | 点击 Monaco 可视行，用真实键盘事件键入 `print("editor-e2e:", 6 * 7)`，DOM 读回内容**逐字符一致**；语法高亮正常（关键字/字符串/数字分色） |
| 点运行 | 状态条「运行成功 · exit 0 · 174 ms」；**标准输出面板 = `editor-e2e: 42`** |
| 限制层面板 | 「限制层实测」表 4 行全实数：墙钟 5s/175ms、CPU 3s/已设置、内存 256.0MB/峰值 11.9MB、文件写入 1.0MB/已设置 |
| 语言切换 | 切到 JavaScript，重键入 `const xs=[1,2,3]; console.log("js-e2e:", …)`，运行「运行成功 · exit 0 · 326 ms」，**输出 `js-e2e: 6`** |
| 草稿（CodeSession） | 「保存草稿」后草稿列表出现 `const xs = [1, 2, 3]; · javascript` |
| 运行历史 | 面板出现 2 条记录（326ms / 174ms），点击可回填源码 |
| 安全边界声明 | 页面右侧 alert 全程可见：「被执行代码以当前操作系统用户身份运行，对本机文件系统有读权限……**只防误触、不防攻击**」（ADR-0003 要求） |
| 控制台 | 唯一 error 为 `favicon.ico` 404（P4 之前即存在，与编辑器无关） |

截图证据（已入库）：

- `docs/review/assets/p4-editor-python-run.png` —— Python 运行成功 + 输出 + 限制层表
- `docs/review/assets/p4-editor-js-run.png` —— JavaScript 切换后运行成功

### 5.3 ui-baseline 合规核对（交接文档遗留核对项）

对照 `frontend/docs/ui-baseline.md` 逐条：配色/间距/圆角全部走 CSS 变量
（`--color-card` / `--space-*` / `--radius-card` 等，两个新组件源码**零硬编码色值**）；
可点击元素均有 `cursor: pointer`；hover 过渡 200ms（150–300ms 区间内）；键盘 focus 态用
`--color-ring`（`.list__main:focus-visible`）；图标用 Element Plus Icons（无 emoji）；
路由组件懒加载 ✅；`@media (max-width: 1023px)` 纵向堆叠；SFC 单文件 + PascalCase ✅。
「prefers-reduced-motion」条款：本页无流式/打字动画类交互，未触发该条款。

---

## 6. 降级路径与 `limit_detail` 实录

`limit_detail` 是本批次的证据载体：四层各自记录 `applied` / `triggered` / 实测值，
由**实测留痕**填充而非配置回显。本机（darwin）逐路径的真实内容：

**① 全层可用（正常路径）** —— `degraded_layers=[]`，四层全部生效：

```json
{"executed": true, "error": null, "blacklist": null,
 "wall_clock": {"limit_s": 5.0, "elapsed_s": 0.033, "triggered": false},
 "cpu":  {"limit_s": 3, "applied": true, "error": null, "triggered": false},
 "memory": {"limit_bytes": 268435456, "sampled": true, "interval_ms": 100,
            "peak_bytes": 770048, "samples": 1, "triggered": false},
 "file_size": {"limit_bytes": 1048576, "applied": true, "error": null},
 "output": {"limit_bytes": 8192, "stdout_bytes": 9, "stderr_bytes": 0,
            "stdout_truncated": false, "stderr_truncated": false},
 "process_group": {"killed": false}, "degraded_layers": [], "platform": "darwin"}
```

**② 黑名单路径（未执行）** —— 各层 `applied=false`、`error="blocked"`，规则名入档：
`blacklist={"rule": "os_system", "executed": false}`，`degraded_layers=["cpu","file_size","memory"]`。

**③ 执行器内部异常路径（坏解释器逼 `Popen` 抛错）** —— `executed=false`、
`error="FileNotFoundError: … '/nonexistent/python-for-tests'"`，各层 `error="failed"`，
仍返回 `runtime_error` 而非抛出，且临时目录照常清理（泄漏 0）。

**④ 平台不支持某层时的降级**：引导脚本的 `_apply()` 对不存在的 rlimit 常量返回
`{"applied": false, "error": "platform has no <名>"}`，该层进 `degraded_layers`，
前端显示「以下限制层在当前平台未生效」。**本机 darwin 上四层全部可设（cpu / file_size
rlimit 实测 applied=true），该分支未在本机真实触发 —— 此条如实标注「未验证（本机无此场景）」**，
仅③的 `applied=false` 形状是真实触发过的。内存层无平台分支（psutil 全平台可用），
`RLIMIT_AS/DATA/RSS` 三项按 ADR-0003 禁止使用（M11 反向验证）。

---

## 7. 测试统计

| 项 | 数量 |
|---|---|
| P0–P3 基线（`730222c`） | 658 passed / 2 skipped |
| P4 净增（后端） | **+65**（658 → **659 passed / 2 skipped**，本批阈值注入 +1，见下） |
| 前端 vitest | 8 passed（416ms） |
| 最后一次全量 | `659 passed, 2 skipped` in 129.33s（`HF_HUB_OFFLINE=1` + `nice -n 10`） |

新增用例分布（P4 批次累计）：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_execution_policy.py` | 34 | 五种 status 常量、阈值常量、Python/JS 黑名单、注释与文档字符串不误报、剥离失败回退、eval+exec 组合判定、命令/环境装配、零 IO 源码级断言 |
| `test_code_run_models.py` | 7 | 建表、`limit_detail` JSON 往返、五种状态参数化落库、`exit_code=None`、UTC 时区、user_id 索引 |
| `test_code_executor.py` | **64**（含本批 +1） | 12 类真实子进程实测 + 本批新增「阈值注入被遵守」；`test_implementation_never_sets_rlimit_as_data_or_rss` 守 ADR-0003 硬约束 |
| `test_execution_leaks.py` | 8 | 临时目录四路径 + node 缺失路径 + 僵尸两轮扫描 |
| `test_code_run_service.py` | 15 | 落库/审计/卸载计数/429/许可不泄漏/草稿 CRUD/跨用户隔离/分页历史 |
| `test_code_run_api.py` | 21 | 鉴权 4010、七字段、422、request_id、真死循环 HTTP、草稿五端点、越权 404、HTTP 429 |

**skip 逐条说明**（2 条，与 P1–P3 相同，均为 P1 语料型条件跳过，非本批新增）：
`test_retrieval_quality_realistic.py` 的两条 `[小标题讲义]` 参数 —— 断言只适用于 B 型语料。

**阈值注入对本批测试负载的影响**（用户 2026-08-31 确认的缓解）：全量中把子进程推到
真实 256MB 阈值的用例从 3 处降为 **1 处**（`test_memory_hog_is_killed_by_memory_layer`，
注释中写明其唯一性）；其余内存行为用例用注入的 16/64MB 验证同一行为（peak ~36–100MB）。

---

## 8. 偏离清单

| # | 偏离了什么 | 为什么 | 影响 |
|---|---|---|---|
| 1 | **内存阈值可注入**（`SubprocessCodeExecutor(memory_limit_bytes=…)`，commit `8ae1f4a`）：新增 1 条 16MB 注入行为用例；`test_execution_leaks.py` 的内存杀/僵尸批量 2 处改用 64MB 注入 | 用户 2026-08-31 确认的负载缓解：此前每个吃内存用例把子进程推到 ~292MB，全量约 7–8 次，机器卡顿 | **生产行为零变化**：缺省值仍是领域层常量 256MB，`_pump` 比较与 `_detail` 记录同源；真实 256MB 行为由 1 条保留用例 + 真 HTTP 实测（§3 第 1 条 peak=304.8MB）双重守住。报告如实记录该偏离 |
| 2 | 全量测试与真服务在 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 下运行 | sentence-transformers 加载已缓存模型时默认联网查 HF Hub，在 ZCode 受限网络下**无限等待**（进程采样定位到 kqueue 挂起），全量测试曾三次卡死 | 零代码改动、测试语义零变化（仅跳过对已缓存模型的在线版本检查）；无网络限制的终端不需要。根因属 P1 的 local-embed 依赖，非 P4 引入 |
| 3 | 顶层 `README.md` 创建（commit `26410ba`） | ADR-0003 明确要求把安全边界声明写入 README；交接文档确认此前缺失（页面侧已有，README 侧未做） | 纯文档新增 |
| 4 | `make test` 频率（每 Task 一次）与 `vite build`（最终一次），测试用 `nice -n 10` 降优先级 | 同缓解裁定 | 无影响；每次 commit 前仍有全量门槛 |
| 5 | 429 实测用 `EXECUTION_QUOTA_TIMEOUT_S=0.5` 的第二实例（生产默认 10s） | 默认 10s 下墙钟 5s 先释放并发位，真实流量永远到不了等待超时；缩短只改变触发时机，不改机制 | 机制本身（上限 2、超时 429、许可不泄漏）在真实 HTTP 上验证；生产默认值未动 |

其余：无。实现严格遵循分层（routers → services → domain）、`CurrentRidDep`、`UTCDateTime`、
`create_all`、无 CORS、无远端操作（未 push / 未 remote add / 未 merge）。

---

## 9. 遗留问题

1. **spec 回写建议**（收尾批次处理）：§6.2 code 行补 `POST /code/run` 响应字段全集
   （含 `limit_detail` 与 `run_id`）与「blocked/timeout/memory_exceeded 为 200」语义；
   §5 `CodeRun` 补 `limit_detail` 结构定义（建议直接引用本报告 §6）；§8.3 补「stdout
   截断在父进程读管道时做」与「stdin 走临时文件重定向」两条实现契约。
2. **`ui-baseline` 的 favicon 缺失**：控制台唯一 404，P4 之前即存在，建议收尾批次补一个图标。
3. **网络隔离未做**（spec §3.3 边界外）：被执行代码可访问网络 —— 已在 README 与页面声明。
   若未来需要，Docker 沙箱路线见 ADR-0003 的备选项论证。
4. **黑名单可绕过性是声明过的设计取舍**：`__import__('o'+'s')`、`getattr` 链可绕过
   （`test_blacklist_is_a_guardrail_not_a_security_boundary` 已把「可绕过」写成断言）。
   P6 后台页面还需加同款安全边界声明条（ADR-0003 要求「后台页面」也要有）。
5. **P5 判题复用**：`CodeExecutor` 端口与四层限制可直接复用；判题场景需要把 `limit_detail`
   的阈值常量做成可配置（本批的构造器注入正是为此预留的缝）。
6. **HF Hub 离线等待**的根治（属于 P1 范畴）：`SentenceTransformer` 加载时可传
   `local_files_only=True` 或在文档化启动脚本中固定 `HF_HUB_OFFLINE=1`，避免每个新执行
   环境都踩一次。

---

## 10. 关键决策记录（指令未覆盖处）

1. **`preexec_fn` 改为子进程内引导脚本自设 rlimit**。适配器跑在线程池里，`preexec_fn`
   在多线程进程中有 fork 后持锁死锁的已知风险；引导脚本把各层设置结果写 `status.json`
   供父进程读回并入 `limit_detail`，这才让「每层是否真的设上」成为实测值而非假设。
2. **端口是同步的**（`def execute(...) -> ExecutionResult`）：整段执行本就是阻塞调用，
   定义成 async 会掩盖这一事实；服务层用 `run_in_threadpool` 卸载（ADR-0002）。
3. **黑名单扫描前剥离注释与字符串**（Python `tokenize`，JS 正则）：教学代码里「不要用
   `os.system`」这类注释极常见，不剥离会误报；剥离失败回退原始源码，宁可误报不漏报。
   模块引入类规则（JS `child_process`）改扫「仅剥注释」的面，因为其危险性恰在字符串里。
4. **先抢执行位再卸载**（`execution_slot` 包住 `run_in_threadpool`）：反过来会让超限请求
   先白占一个线程池线程再被退回。
5. **被杀前的管道收尾再抽一次**：墙钟/内存杀掉子进程后，已写进管道缓冲区的输出仍要拿回
   （§3 第 3 条「超时后 stdout 无『不应出现』」同时验证了杀得干净与不误吞合法输出）。
6. **`limit_detail` 未执行时保持同一形状**（各层 `applied=false` + 原因），前端与测试
   不必区分两套结构。
7. **负反馈路径全部 200**：blocked / timeout / memory_exceeded / runtime_error 是对输入的
   正常业务结果；只有并发满（429）与参数非法（422）才是 HTTP 层错误。
8. **内存阈值注入只动比较与记录两处**：不触碰引导脚本、墙钟、CPU、文件层 —— 缓解措施
   的改动面刻意收窄到可被 M3 变异测试覆盖的程度。

---

## 11. 安全边界声明落地（ADR-0003 强制项）

| 落点 | 内容 | 证据 |
|---|---|---|
| 顶层 `README.md`（`26410ba`） | 四条声明：黑名单只防误触不防攻击（点名 `__import__('o'+'s')`、`getattr` 链）；以当前 OS 用户身份运行；对本机文件系统有读权限；网络未隔离 | `README.md`「受限代码执行器 —— 安全边界声明（必读）」节 |
| 学生端编辑器页 | `el-alert` 常驻：「被执行代码以当前操作系统用户身份运行，对本机文件系统有读权限。内置的危险调用黑名单**只防误触、不防攻击**，可被轻易绕过」 | §5.2 浏览器断言 + 截图 |
| 领域层文档 | `domain/code/execution.py` 模块 docstring 写明「可预测而非不可绕过」的取舍 | 源码 |
| 测试断言 | `test_blacklist_is_a_guardrail_not_a_security_boundary`：`getattr(__builtins__, 'ev'+'al')` 真实绕过黑名单并输出 `2` —— 把「可绕过」固化成回归用例 | pytest 通过 |
| P6 待办 | 后台页面同款声明条（ADR-0003 要求），见 §9 遗留 4 | — |

---

## 12. 变异测试指引（12 条，全部实际跑过）

方法：逐条「改坏代码 → 跑受影响测试 → 记录失败 → `git checkout -- <file>` 还原」，
每条都真实执行，非推断。还原后 `git diff` 为空，并回归了受影响文件（87 passed）。

| # | 拆掉哪层 | 怎么改坏 | 会失败的测试（实测） |
|---|---|---|---|
| M1 | 墙钟 5s | `_pump` 的墙钟判定加 `and False` | `test_code_executor.py::test_sleep_is_killed_by_wall_clock`、`test_execution_leaks.py::test_temp_dir_is_cleaned_after_wall_clock_timeout`（**2 failed** in 20.28s；睡眠进程活到自然退出，`status` 变 `accepted`） |
| M2 | CPU rlimit | Python 引导模板 `_log["cpu"] = {"applied": false}`（不再 `_apply`） | `test_infinite_loop_is_killed_by_cpu_seconds`、`test_limit_detail_records_every_layer`（**2 failed** in 5.24s；死循环改由墙钟 -9 收走，`-24` 指纹消失） |
| M3 | 内存采样 kill | `if peak > self._memory_limit:` 加 `and False` | `test_memory_hog_is_killed_by_memory_layer`、`test_memory_threshold_is_injectable_and_honored`（**2 failed** in 5.43s；吃内存进程改被 CPU 层杀，`memory_exceeded` 消失 —— 注入阈值用例同样抓住） |
| M4 | 文件写入 1MB | Python 引导模板不再 `_apply("RLIMIT_FSIZE", …)` | `test_oversized_file_write_is_rejected[python]`、`test_file_on_disk_never_exceeds_one_megabyte`（**2 failed**，1 passed；**落盘实测涨到 4,194,304 字节**，EFBIG 消失；JS 参数用例不受影响 —— 变异隔离性旁证） |
| M5 | 输出 8KB 截断 | `_drain` 无条件 `sink.extend(chunk)` | `test_huge_stdout_is_truncated_to_eight_kilobytes`（**1 failed** in 0.18s；stdout 变 1MB） |
| M6 | 黑名单拦截 | `execute()` 的 `if rule is not None:` → `if False:` | `test_blacklisted_source_is_blocked_without_running`（**1 failed** in 0.18s；**副作用文件被真实创建** —— 该用例用文件存在性证明「没执行」） |
| M7 | 进程组 kill | `_kill_group` 整体退化为 `_kill_single` | `test_grandchild_is_killed_along_with_the_parent`（**1 failed** in 8.19s；孙进程逃逸存活） |
| M8 | 临时目录清理 | `execute()` 的 `finally: shutil.rmtree(...)` → `pass` | `test_temp_dir_is_cleaned_after_success`（**1 failed** in 0.17s；前后计数差 1） |
| M9 | 并发上限 | `_execution_slot()` 容量改 1000 | `test_code_run_service.py::test_third_concurrent_run_gets_429`、`::test_quota_permits_are_not_leaked_after_a_timeout`、`test_code_run_api.py::test_third_concurrent_run_returns_429`（**3 failed** in 17.19s） |
| M10 | 阻塞卸载 | `run()` 改为直接同步调用 executor | `test_code_run_service.py::test_execution_is_offloaded_to_threadpool`（**1 failed** in 0.87s；monkeypatch 计数器为 0） |
| M11 | ADR-0003 硬约束 | 引导模板植入 `_apply("RLIMIT_AS", …)` | `test_implementation_never_sets_rlimit_as_data_or_rss`（**1 failed** in 0.13s；模板字符串断言抓住 —— 该项在 macOS 一旦真用会当场 `ValueError`） |
| M12 | 黑名单注释剥离（领域层） | `strip_noise` 直接 `return source` | `test_python_comment_mentioning_os_system_is_not_blocked`、`::test_python_docstring_mentioning_subprocess_is_not_blocked`、`::test_python_string_literal_mentioning_shutil_rmtree_is_not_blocked`（**3 failed** in 0.23s） |

**已知的单测盲区**（只能端到端验，拆掉后单测仍绿）：§3 第 9 条事件循环延迟（依赖真实
uvicorn + 真实并发打点）与 §4.2 真实 HTTP 429 的时序形态 —— 已由本报告实测覆盖；这两条
没有对应的 pytest 用例，属预期内（它们验证的是部署形态行为）。

复现命令：

```bash
cd backend && . .venv/bin/activate
python -m pytest tests/test_code_executor.py tests/test_execution_leaks.py \
                 tests/test_code_run_service.py tests/test_code_run_api.py \
                 tests/test_execution_policy.py -q
# 12 条实测驱动（需 uvicorn app.main:app --port 8000 + e2e-p4.db + p4demo 账号）
python /tmp/p4_task7_measure.py   # 脚本见报告附 B 要点，逐条打印 JSON
```

---

## 附 A：本次交付的文件（收尾批次）

```
README.md                                                  （新增：安全边界声明等）
docs/review/2026-08-30-p4-handoff.md                       （交接文档入库）
docs/review/2026-08-30-p4-completion-report.md             （本报告）
docs/review/assets/p4-editor-python-run.png                （浏览器实测截图）
docs/review/assets/p4-editor-js-run.png                    （浏览器实测截图）

backend/app/infrastructure/adapters/execution/subprocess_executor.py  （+ 阈值注入，默认 256MB 不变）
backend/tests/test_code_executor.py                        （+ 阈值注入用例，标注唯一真实 256MB 用例）
backend/tests/test_execution_leaks.py                      （内存相关 2 处改用 64MB 注入）
```

P4 批次累计（此前 7 个 commit 的文件清单见实施计划的 File Structure 节，此处不重复）。

## 附 B：12 条实测复现要点

1. 起服务：`cd backend && DATABASE_URL=sqlite+aiosqlite:///./data/e2e-p4.db uvicorn app.main:app --workers 1 --port 8000`（无网络限制环境可不加 `HF_HUB_OFFLINE=1`）
2. 注册/登录 `p4demo`，`POST /api/v1/code/run` 逐条发送 §3 表中的源码
3. 第 10 条：第二实例 `EXECUTION_QUOTA_TIMEOUT_S=0.5 --port 8001`，3 并发同时发 `time.sleep(2)`
4. 第 11 条异常路径：直连适配器 `SubprocessCodeExecutor(python_executable="/nonexistent/…")`
5. 第 12 条：`psutil` 扫描 uvicorn pid 的整棵子树找 `STATUS_ZOMBIE`
