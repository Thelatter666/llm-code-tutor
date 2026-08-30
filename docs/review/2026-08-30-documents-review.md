# 文档审阅报告（只读）

- 审阅日期：2026-08-30
- 审阅范围：`AGENT.md`、`CONTEXT.md`、`docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md`、`docs/superpowers/plans/2026-08-30-p0-foundation.md`、`docs/adr/0001`–`0006`
- 审阅方式：只读，未修改任何既有文档
- 总体结论：**spec 质量很高（权衡、边界外声明、术语消歧都到位），但 plan 与 spec 之间存在 6 处实质性偏差，其中 4 处会直接导致 P1/P2 返工。建议修订 plan 后再开工 P0。**

判定依据的一句话概括：spec 把「为什么」讲透了，plan 把「怎么做」写细了，但两者在**端口签名、中断机制、Makefile 契约、数据模型字段**四个接缝处对不上。

---

## 一、阻塞级（P0 开工前必须解决）

### B1. `LLMPort` 签名无法承载 SSE `done` 事件契约

`spec §6.1` 的 `done` 事件要求返回 `{message_id, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}`。

```
207:  | `done` | `{message_id, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}` | 生成结束；Mock 模式下 `token_usage` 按 `len(content)//4` 估算并置 `usage_estimated=true` |
```

而 plan Task 4 定义的端口：

```python
class LLMPort(Protocol):
    async def stream(self, messages, params) -> AsyncIterator[str]: ...
    async def complete(self, messages, params) -> str: ...
```

除 `token_usage` 外的字段都可在服务层拼装，但 **`token_usage` 只能来自 provider 本身** —— OpenAI 兼容协议下它藏在流的最后一个 chunk（需 `stream_options: {include_usage: true}`）或 `complete` 的响应体里，纯文本流拿不到。

后果：P2 实现 `done` 事件时必然要改 `LLMPort` 签名，连带 Task 6 的 4 个契约测试全部重写。这是**当前计划中代价最大的一处**。

建议：P0 就把端口改为返回结构化增量，例如 `AsyncIterator[Delta | Usage]`（或 `stream()` 返回 `(iterator, usage_future)` 二元组），并让 `MockLLMProvider` 走同一签名。

---

### B2. 中断机制：plan 用实例级 `cancel()`，spec 用 per-request Event 注册表

spec §8.1 明确：

```
312:  **中断实现**：`asyncio.Event` 存于内存注册表，键为 `(conversation_id, request_id)`；生成循环每次 yield 前检查一次 Event
```

plan Task 5 给出的是实例方法：

```python
class MockLLMProvider:
    def __init__(self) -> None:
        self._cancelled = False
    def cancel(self) -> None:
        self._cancelled = True
```

两个问题叠加，会变成一个真实的并发 bug：

1. `ProviderRegistry` 缓存**单实例**（plan Task 4 `self._cache: LLMPort | None`），所有请求共用；
2. `cancel()` 是**实例级**而非请求级。

→ 多用户并发聊天时，任一学生点「停止」会同时掐断所有进行中的流。

这不只是实现细节分歧：Task 5 的 `test_stream_stops_when_cancelled` 会把这个用不上的接口**用测试锁死**，P2 返工时要连测试一起改。

建议：P0 就按 spec §8.1 落 Event 注册表（或 `stream(..., cancel: asyncio.Event | None = None)` 的 per-call token），删掉 `provider.cancel()`。

---

### B3. `make install` 不装本地 embedding，与 spec/ADR 的核心结论冲突

spec §3.2 权衡 17 用整段论证了「本地 embedding 必须默认安装」：

```
76:  17. **本地 embedding 依赖默认安装** —— 牺牲约 1GB 体积与数分钟安装时间，换取无 API Key 时 RAG 仍有真实语义。若默认不装，无 key 演示将退化为 HashingEmbed 哨兵（检索结果不注入 prompt），知识库功能实际不可用。
```

ADR-0004 的 Consequences 也复述了这条：

```
14:  - 无 API Key 且未装本地 embedding 时，知识库检索实际不可用。为降低影响，本地级 `sentence-transformers` 设为 optional extras 且 `make setup` 默认安装（见 spec §3.2 权衡 17）。
```

但 plan Task 12 的 Makefile：

```makefile
install:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev]"
	cd $(FRONTEND) && npm install

install-lite:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev]"
	@echo "已跳过本地 embedding extras（torch 约 1GB）；需要真实语义检索时执行 make setup-local-embed"
	cd $(FRONTEND) && npm install
```

**两个 target 装的完全一样**（都只有 `[dev]`），差别只有一句 echo。`install-lite` 名不副实，`install` 又恰恰漏掉了 spec 论证过的那件事。结果是 P0 一结束，P1 的可用性前提就已经丢了。

修复：把 `install` 改成 `pip install -e ".[dev,local-embed]"`，`install-lite` 保持 `.[dev]`。

---

### B4. Makefile target 命名与 spec / ADR 不一致

| 来源 | 引用的 target |
|---|---|
| `spec §2` 选型表 | `make setup`（默认安装）、`make setup-lite`（跳过） |
| `ADR-0004` Consequences | `make setup` |
| plan Task 12 实际定义 | `install` / `install-lite` / `setup-local-embed` |

`test_makefile_declares_required_targets` 只检查 `install:` `install-lite:` `dev:` `serve:` `test:` `seed:`，**没有检查 `setup:`**，所以测试全绿但文档与实现对不上。这属于测试守护选错了对象 —— 它守护的是 plan 自己的写法，而不是 spec 的契约。

修复：统一到一套命名（建议采用 plan 的 `install` / `install-lite`，回头改 spec §2 与 ADR-0004 两处引用）。

---

### B5. P0 计划完全没有 `.gitignore`

spec §8.8 明确要求：

```
390:  - 主密钥来自环境变量 `APP_SECRET`；缺失时首次启动自动生成并写入 `.secret_key`，该文件加入 `.gitignore`
```

而 plan 的 File Structure（第 30–81 行）里没有任何 `.gitignore`，15 个 Task 也没有一步创建它。会被提交进仓库的包括：`backend/.secret_key`（**加密主密钥**）、`backend/data/app.db`（含用户密码哈希）、`backend/.venv`、`frontend/node_modules`、`frontend/dist`。

演示项目「整个目录极可能被拷贝传播」正是 spec §8.8 的论证前提，这里正好踩中。

修复：Task 1 或 Task 12 增加创建 `.gitignore` 的步骤。

---

### B6. plan 的 15 处 `git commit` 与 `AGENT.md` 铁律冲突

`AGENT.md`：

```
31:  | 7. 提交指令   | **未经用户明确下令，绝不执行 commit / merge / push**，包括不带参数的 `git commit`         |
38:  - 第 7 阶段前，禁止任何形式的 `git commit`、`git merge`、`git push`、`git rebase`。
```

plan 的 Task 1–12、13、14、15 每个都以 `git commit` 收尾，共 15 处；Global Constraints 还写了「每个任务完成后独立 commit」。

若 plan 交由 Agent 执行，会在第一个 Task 就违反仓库强制约束。

修复：在 plan 顶部加一句「所有 commit 步骤须经用户明确下令后执行；未获授权时改为在任务末尾停下并汇报」。（这是在两个约束之间做显式仲裁，不是删掉 commit 步骤。）

---

## 二、高优先级（P1/P2 前解决，否则累积返工）

### H1. Task 2 的 `models.py` 缺两个字段，但注释写的是「全量表定义」

plan 第 62 行注释：

```
62:  │           └── models.py       全量表定义
```

实际只定义了 `User` / `ModelConfig` / `AuditLog` 三张（这是 P0 需要的，合理裁剪）。但 `ModelConfig` 相对 spec §5 **少了两个字段**：

| spec §5 ModelConfig | plan Task 2 ModelConfig |
|---|---|
| `embedding_provider` | ✗ 缺失 |
| `embedding_model` | ✗ 缺失 |

这两个字段是 spec §8.7「embedding 配置变更 → 409 + 强制重建」与 `Chunk.embed_model` 启动校验的前提。叠加 ADR-0006（无迁移、改结构要删库重建），P1 开工第一件事就是删库。

修复二选一：
- P0 就把这两列建出来（推荐，成本近零）；
- 或在 Task 2 明确标注「P0 只落所需字段，P1 追加 embedding_* 两列，届时需删库重建」，并把注释从「全量表定义」改成「P0 所需表定义」。

---

### H2. `ModelConfig` 单例缺乏约束，且 `updated_at` 无 `onupdate`

spec §5 标注 ModelConfig 为「单例记录」，但：

1. 模型层**没有任何单例约束**（无唯一约束、无 CHECK），`seed()` 用 `select(ModelConfig).limit(1)` 判断存在性 —— 一旦出现第二行，就有一行变孤儿；
2. `updated_at` 只有 `default=_now`，**没有 `onupdate=_now`**；
3. `ProviderRegistry` 用 `order_by(ModelConfig.updated_at.desc()).limit(1)` 取配置（plan 第 750 行）。

三者叠加：P6 的 `PUT /admin/model-config` 若实现为「查不到就 insert」，配置更新后 `updated_at` 不变，registry 可能取到旧行且 revision 不变 → **改了配置不生效**，直接违背 spec §4.2 硬约束 4「配置热生效」。

修复：给 `updated_at` 加 `onupdate=_now`；给单例加显式保护（如固定主键 + 注释，或统一走一个 `get_or_create_singleton()`）。

---

### H3. `admin_ping` / `health` 硬编码 `request_id=""`

```python
@_admin.get("/ping")
async def admin_ping(user=Depends(require_admin)):
    return ok({"role": user.role}, request_id="")

@app.get("/health")
async def health():
    return ok({"status": "ok"}, request_id="")
```

而 `install_request_id` 中间件会把真实 id 写进响应头 `x-request-id`。结果是**响应体与响应头的 request_id 不一致**，排查日志时无法用 body 里的 id 去 grep。同一个 Task 10 里，auth 路由都规规矩矩用了 `current_request_id(request)`，唯独这两个没有。

而且 `ok()` 把 `request_id` 设成**必需关键字参数**，等于逼每个端点手写一遍 —— P6 的管理端点若照抄这个 pattern 会全面扩散。

建议：提供 `CurrentRidDep`（`Annotated[str, Depends(current_request_id)]`）并全量改用；或让 `ok()` 从 ContextVar 取默认值。

---

### H4. `CONTEXT.md` 术语表缺两条已在使用的术语

修订记录：

```
103:  - 2026-08-30 · Grilling 第 3 轮：新增「估算用量」「随机补足」；同步 spec §2 / §3.2 / §3.3 / §6.1 / §8.2 / §8.5 / §10 / §11。
```

但术语表正文（领域实体 / 端口 / 请求意图 / 行为与策略四张表）中**查无「估算用量」「随机补足」两条**。而这两个概念在 spec 里已经落地成字段：`§6.1` 的 `usage_estimated`、`§8.5` 的 `filled_by=random`。

`CONTEXT.md` 开篇声明「所有设计文档、计划文档、代码标识符、接口字段必须使用本表中的正式术语，不得混用或自造」—— 现在是被自己的修订记录打破了。P2/P5 会持续踩。

修复：补两条术语（`估算用量 EstimatedUsage`、`随机补足 RandomFill`），并与 spec §6.1 / §8.5 的字段名对齐英文名。

---

## 三、中优先级

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| M1 | `score_threshold` 固化单一默认值 0.35，与 spec §3.2 权衡 8「按 embedding 模型分别给默认（0.25 / 0.35 / 0.30）」矛盾 | plan 第 379 行 vs spec 第 67 行 | 改为 nullable，`null` = 用模型默认值；P1 加解析函数 |
| M2 | 种子数据目录不一致：spec §4.3 是 `backend/seeds/`，plan 是 `backend/app/seed.py` | spec 第 154 行 vs plan 第 36 行 | P0 就建 `backend/seeds/` 包；P5 加约 40 题后单文件会膨胀到几千行 |
| M3 | 路由未声明 `response_model=ApiResponse[T]`，OpenAPI 里看不到统一信封 | plan Task 3 定义了 `ApiResponse` 但 Task 10 未使用 | 挂 `response_model`，前端类型生成才能对上 |
| M4 | 「契约测试」名不副实：`test_contract_providers_expose_llm_port_surface` 只断言 `name` 是 str、`stream`/`complete` 可调用，未跑同组断言 | plan 第 949–956 行 | spec §10 要求两个 provider 跑同一组断言；把 mock 的 4 条断言参数化到两个 provider |
| M5 | conftest 用文件 `.secret_key.test` 而非固定 env，会污染工作区，且 `APP_SECRET_PATH` 未纳入 `.gitignore` | plan 第 235 行 | 改 `os.environ.setdefault("APP_SECRET", Fernet.generate_key().decode())`，去掉文件 IO |
| M6 | Global Constraints 声明「所有同步阻塞调用须经 `run_in_threadpool` 卸载」，但 bcrypt（~100ms/次）未卸载 | plan 第 22 行 vs Task 7 | 注册/登录走线程池，否则自相矛盾 |
| M7 | 内存 SQLite 未指定 `poolclass=StaticPool` | plan 第 233、242、1466 行 | 依赖 SingletonThreadPool 在单线程下碰巧成立，是脆弱前提；显式声明更稳 |
| M8 | `uipro init --ai codebuddy` 是外部 CLI，plan 无前置可用性检查；不可用时直接卡住 Task 13 → 卡住 `make serve` 验收 | plan 第 2175 行 | 加 fallback：命令不存在时人工落一份基线文件并告警 |
| M9 | spec §4.3 要求 `main.py` 负责 CORS，plan 全程未配置也未说明 | spec 第 143 行 | `dev`/`serve` 均同源，实际不需要；建议在 plan 显式写明「因同源故不配 CORS」，否则是需求追溯缺口 |
| M10 | spec §9「LLM 调用失败/超时 → 降级到下一 Provider」无落点：`LLMPort` 无 `health_check`，registry 是单槽无 fallback 链 | spec 第 408 行 vs plan Task 4 | P0 至少预留 `get_llm()` 内部的 provider 链结构 |
| M11 | `get_current_user` 的「用户不存在 → 4010」「已停用 → 4030」两条分支无直接测试 | plan Task 8 | 安全关键路径，建议补两条 |
| M12 | `install_spa_fallback` 里 `full_path.startswith(("api/", "health"))` 是死分支 —— 真实 API 路由已先注册，永远走不到 | plan 第 2580 行 | `test_api_path_is_not_swallowed` 实际测的是注册顺序而非这段逻辑；要么补一个真能触发的用例，要么删掉死分支 |
| M13 | `make serve` 无 `frontend/dist` 存在性检查；dist 不存在时 fallback 静默不挂载，访问 8000 得到 404 且无任何提示 | plan 第 1994–1997 行 | 加一行存在性检查与明确报错 |
| M14 | `.env.example` 缺 `APP_SECRET`（spec §8.8 的主密钥来源） | plan 第 2009–2018 行 | 补一行注释说明留空即自动生成 |
| M15 | 默认管理员密码 `Admin@12345` 明文进源码，README 未要求说明 | plan 第 1864 行 | 演示可接受，但 README 必须写明并提示首次登录后修改 |
| M16 | plan 未提分支策略；AGENT.md 阶段 4 要求从 `main` 切功能分支 | AGENT.md 第 28 行 | P0 应落在 `feat/p0-foundation`（当前在 `docs/architecture-design`） |
| M17 | httpx `Timeout(60.0)` 对 read 也生效；SSE 流式下推理模型思考超 60s 无 token 会误判超时 | plan 第 1024 行 | read timeout 单独放宽（如 `Timeout(10, read=300)`） |

---

## 四、低优先级 / 流程完整性

- **L1 · 缺 ADR**：以下决策影响数据模型或跨批次引用，建议补 ADR：Chroma 单集合 + 元数据过滤（spec §3.2 权衡 4）、薄弱知识点实时聚合而非冗余表（权衡 3）、按字符切分而非 token（§8.2）、相对截断 vs 绝对阈值（§7.2 步骤 3）。已有 6 篇 ADR 结构统一（决策陈述 / Considered Options / Consequences），补齐成本很低。
- **L2 · 功能点语义重叠**：`AGENT.md` 与 spec §1 的 12 个功能点中，「学生端·RAG 课程知识库增强」与「功能增强·RAG 知识库检索」高度重叠，答辩时易被质疑「一个能力拆两点凑数」。建议提前准备口径。
- **L3 · 术语覆盖不全**：`CONTEXT.md` 的「执行队列上限」只记了代码执行并发 2，未含 spec §3.2 权衡 14 的「索引 1」。另外 P0 未建任何信号量基础设施，P4 才引入 —— 可考虑 P0 先落一个通用 `Limiter`。
- **L4 · `core/logging.py` 缺失**：spec §4.3 的 `core/` 列了 `logging`，plan 的 core 未包含。审计日志落库已覆盖，但应用运行日志（结构化 / uvicorn 配置）无着落。
- **L5 · 依赖引入批次未标注**：`psutil` / `chromadb` / `pdfplumber` / `python-docx` 未进 P0 依赖（分批次引入合理），但 ADR-0003 已声明「引入 psutil 依赖」，建议在 plan 的依赖说明里标注各依赖的引入批次。

---

## 五、一致性核对：通过项

以下项逐一核对后**未发现问题**，记录在此以示覆盖范围：

- **表数量**：spec §5 声明 14 张表，实际列出 14 个实体，一致。
- **功能点数量**：`AGENT.md` 与 spec §1 均为 12 个（学生端 5 + 管理后台 4 + 增强 3），一致。
- **错误码映射**：plan 的 `CODE_STATUS` 覆盖 spec §9 全部码位（4010/4030/4040/4090/4290/5000/5021/5032），无遗漏。
- **ADR 引用有效性**：plan 引用的 ADR-0001 / 0002 / 0006 均存在且内容匹配。
- **单 worker 有测试守护**：`test_makefile_pins_single_worker` 断言 `--workers 1` 出现 ≥2 次（dev + serve），且 uvicorn 允许 `--reload --workers 1` 共存，技术上成立。
- **spec §8.9 有测试守护**：`test_audit_log_survives_without_user` 验证 `AuditLog.user_id` 可空（审计不随用户删除），与 spec 一致。
- **SPA fallback 不吞 API**：注册顺序有测试守护，且 `DIST_DIR` 路径 `parents[2]` 计算正确。
- **`dependency_overrides` 陷阱已加注释**：plan 第 1476 行明确提醒「覆盖键必须是路由注册时使用的同一个函数对象」，这是一处高质量的防坑注释。
- **测试总量**：2+2+4+3+4+4+3+4+2+8+2+3+3 = 44 项，与 Task 15 的「约 40 项」吻合。
- **ADR 体例**：6 篇均为「决策陈述 → Considered Options → Consequences」，且每篇都写清了被否决方案的具体代价，而非泛泛而谈。
- **CONTEXT.md 消歧质量**：「会话 vs 对话」「提交 vs 答案」「底线拦截 vs 档位约束」「豁免 vs 绕过」「阻塞卸载 vs 异步化」等消歧条目准确且有区分度，是这批文档中质量最高的部分。

---

## 六、建议的处理顺序

1. **先仲裁 B6**（AGENT.md vs plan 的 commit 冲突）—— 不解决则无法开始执行。
2. **修订 plan 的 4 处接缝**（B1 端口签名、B2 中断机制、B3/B4 Makefile 契约、H1 数据模型字段）—— 这四处都指向 P1/P2 返工。
3. **补基础设施**（B5 `.gitignore`、M5 conftest 密钥、M7 StaticPool）—— 成本极低，越晚补代价越大。
4. **术语表回填**（H4）—— P2/P5 会持续依赖。
5. **其余中低优先级**在对应批次开工前处理即可。

一句话：**不需要重做 spec，只需要让 plan 重新对齐 spec 的四个接缝，并补上 P0 缺失的基础设施步骤。**
