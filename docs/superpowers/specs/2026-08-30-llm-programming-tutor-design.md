# 基于大语言模型的智能编程教学辅助系统 —— 总体架构设计

- 日期：2026-08-30
- 状态：Grilling 完成（4 轮共 26 项质询全部采纳并写回），结论建议：**有条件通过**
- 规模判定：**重量级**（新系统、架构级、多子系统）

---

## 1. 背景与目标

面向编程教学场景，构建一个以大语言模型为核心的智能教学辅助系统，覆盖学生在编程学习中的"问、查、写、练、纠"全链路，并为教师/管理员提供知识库、模型与用户的管控能力。

**功能范围（12 个功能点）**

| 端 | 功能点 |
|---|---|
| 学生端 | AI 编程答疑对话；RAG 课程知识库增强；代码智能解析与辅导；在线代码编辑器与运行调试；习题练习与 AI 习题辅导 |
| 管理后台 | 用户管理；知识库管理；模型参数配置；系统日志 |
| 增强特性 | 防抄袭约束提示词；RAG 知识库检索；错题驱动学习 |

---

## 2. 定位与已定选型

**交付定位**：毕业设计/课程设计演示原型 —— 功能完整、可端到端演示、本地一键启动；外部依赖允许 Mock；不追求高并发与生产级安全加固。

| 维度 | 选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 业务存储 | SQLite（SQLAlchemy，开 WAL） |
| 向量存储 | Chroma 本地持久化目录 |
| 进程模型 | **单进程单 worker（`--workers 1`）** |
| LLM 接入 | Provider 抽象，OpenAI 兼容协议，内置 Mock 降级 |
| Embedding | Provider 抽象，三级回退：OpenAI 兼容 → sentence-transformers（`paraphrase-multilingual-MiniLM-L12-v2`，384 维）→ HashingEmbed（**哨兵级，不参与检索**，见 §7.3）。本地级走 optional extras `[local-embed]`（含 torch，约 1GB），`make install` 默认安装，`make install-lite` 可跳过，另有 `make setup-local-embed` 供已装精简版后补装 |
| 代码编辑与执行 | Monaco Editor + 后端 subprocess 受限执行器（无 Docker）。资源限制：psutil RSS 采样 + `RLIMIT_CPU` + 墙钟超时 + `RLIMIT_FSIZE`；**不使用 `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_RSS`**（macOS 不支持，见 §8.3） |
| 支持语言 | Python、JavaScript |
| 流式协议 | SSE |
| 鉴权 | 自建账号 + JWT（bcrypt），student / admin 两角色 |
| 启动形态 | Makefile / 一键脚本为主，附可选 Dockerfile。`make dev` 走双端口（Vite 5173 + FastAPI 8000），`make serve` 走单端口（FastAPI 托管 `frontend/dist`，8000） |
| 数据库迁移 | **不做迁移**，`create_all` + seed；README 注明"演示库，升级请重建" |
| 鉴权存储 | JWT 存 `localStorage` + Axios 拦截器（XSS 风险已在 §3.3 显式接受） |
| 日志 | 业务审计日志落库 + 管理后台查询 |
| 前端 UI | 接入 uiuxpromax（`uipro init --ai codebuddy`） |

---

## 3. 核心假设 / 显式权衡 / 边界外声明

### 3.1 核心假设

1. 并发 < 50、注册用户 < 1000、知识库文档 < 500 份、单文档 < 10MB。在此规模下单进程 + SQLite + Chroma 本地目录足够，无需引入消息队列或连接池调优。
2. Chroma 单集合可容纳全部切片，按 `kb_id` 元数据过滤即可，无需 per-KB 拆分集合。
3. 演示环境具备 Python 与 Node 运行时（已核实：Python 3.12.7 / Node v24.14.0）。
4. 课程知识库内容以中文编程教材与讲义为主（PDF / Markdown / TXT / DOCX）。
5. **强制单 worker**：SQLite 与 Chroma 本地目录均不支持多进程并发写（前者会 `database is locked`，后者会损坏索引），因此一键脚本固定 `--workers 1`。并发 <50 时 CPU 不是瓶颈，时间主要消耗在等待 LLM 响应上。

### 3.2 显式权衡

1. **模块化单体而非微服务** —— 牺牲进程级故障隔离，换取一键启动与极低联调成本。已声明的定位下，隔离收益无人买单。
2. **代码执行用 subprocess + psutil 采样限内存，不做 cgroup/seccomp** —— 挡得住学生误操作，挡不住蓄意攻击。**不使用 `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_RSS`**：实测 macOS darwin 下 `resource.setrlimit` 对这三项一律抛 `ValueError: current limit exceeds maximum limit`，仅 `RLIMIT_CPU`、`RLIMIT_FSIZE`、`RLIMIT_NOFILE` 可用。
3. **薄弱知识点画像实时聚合而非冗余表** —— 牺牲查询性能换数据一致性；声明规模下聚合成本可忽略。
4. **Chroma 单集合 + 元数据过滤** —— 简化生命周期管理，代价是每次检索必须带过滤条件。
5. **编程题判题同步执行不排队** —— 牺牲吞吐换实现简洁，单用例超时 5s。
6. **知识库索引用 BackgroundTasks 而非 Celery** —— 省一个 broker 进程；代价是重启丢任务、无重试队列。
7. **引用采用编号内联引用而非生成后脚注对齐** —— 模型边生成边引用，成本远低于事后对齐；代价是引用粒度只到片段级。
8. **`top_k` 开放后台配置但默认值写死**；`score_threshold` 按 embedding 模型分别给出默认值（OpenAI 兼容 0.25 / MiniLM 0.35 / 其他 0.30），并叠加与模型无关的相对截断规则 —— 兼顾可调优、无配置时行为确定，以及跨模型可比性。
9. **前端不引入 E2E 测试** —— 成本高于收益，仅保证类型检查与构建通过。
10. **防抄袭底线硬编码进模板，不开放配置** —— 后台只能选档位，不能绕过底线。
11. **强制单 worker 换取存储层正确性** —— 牺牲多核利用率，换取 SQLite 与 Chroma 不出现并发写损坏。
12. **HashingEmbed 定位为哨兵而非可用降级** —— 宁可少一个功能，不要一个错的功能（见 §7.3）。
13. **删除知识库时 Chroma 删除失败仍继续删 DB** —— 牺牲向量层一致性，换取记录不残留为无法清理的死数据，并落 AuditLog 告警。
14. **单 worker + 阻塞调用卸载到线程池** —— 单事件循环下，代码执行（最长 5s）、判题（累计最长 15s）、知识库索引、embedding 推理若同步执行会冻结整个后端。统一走 `run_in_threadpool`，并以信号量限制并发（代码执行 2、索引 1）。代价是引入线程池并发管理，收益是彻底消除冻结。**（P5 补记）** 编程题判题的**每个用例**都过与 `/code/run` 同一个执行信号量 —— 判题就是代码执行，不该绕过配额；获取超时 `4290` 照常向上传播，该次提交**不落库**（宁可让学生重试，不要留下一条判分不明的提交）。
15. **豁免采用显式入口契约而非语义推断** —— 推断错了泄露的是完整答案，代价不对称。聊天入口一律 `seek_answer`，豁免仅在代码辅导页 / 编辑器页 / 习题页「批改我的作答」按钮等显式入口生效。
16. **检索不持锁、写操作持锁** —— per-`kb_id` 的 `asyncio.Lock` 仅保护索引 / 删除 / 重建 / GC；检索允许读到中间态。让最常演示的检索路径排队得不偿失。
17. **本地 embedding 依赖默认安装** —— 牺牲约 1GB 体积与数分钟安装时间，换取无 API Key 时 RAG 仍有真实语义。若默认不装，无 key 演示将退化为 HashingEmbed 哨兵（检索结果不注入 prompt），知识库功能实际不可用。
18. **不做数据库迁移** —— 演示库的生命周期是"删库重建"，Alembic 的在线升级能力用不上，而每批维护 revision 是纯负担。
19. **不做 OCR** —— 扫描版 PDF 直接判为解析失败并提示，不引入 OCR 依赖。

### 3.3 边界外声明（首版不做）

- 多租户、班级与课程排课体系；**选课关系**（仅保留 `KnowledgeBase.course_code` 轻量维度，见 §5）
- 国际化 i18n（但 AI 回答语言在 prompt 中固定为中文）
- 用户代码的网络隔离与系统调用白名单（仅做危险调用黑名单拦截，**防误触而非防攻击**）
- 水平扩展、负载均衡、分布式锁
- 真实抄袭检测（不做文本相似度比对，仅做提示词层约束 + **拦截率度量**，见 §7.4）
- 生产级安全加固（WAF、密钥托管、审计不可篡改存储）；**XSS 防护**（JWT 存 `localStorage`，被 XSS 读取的风险显式接受）
- OCR（扫描版 PDF 不做文字识别，见 §8.2）

---

## 4. 架构设计

### 4.1 分层

```
┌──────────────────────────────────────────────────────┐
│ 前端  Vue3 + Vite + TS + Element Plus                 │
│   student：答疑对话 / 知识问答 / 代码辅导 / 编辑器 /   │
│            习题练习 / 错题本                           │
│   admin：  用户管理 / 知识库管理 / 模型配置 / 日志      │
└──────────────────────┬───────────────────────────────┘
                       │  REST + SSE
┌──────────────────────▼───────────────────────────────┐
│ 接口层   routers/     参数校验与序列化，无业务逻辑      │
│   auth · chat · knowledge · code · exercise · admin · audit │
├──────────────────────────────────────────────────────┤
│ 应用服务层 services/   用例编排；跨领域调用的唯一入口   │
├──────────────────────────────────────────────────────┤
│ 领域层   domain/       实体 + 纯业务规则，禁止任何 IO   │
├──────────────────────────────────────────────────────┤
│ 基础设施层 infrastructure/                             │
│   ports/       LLMProvider · Embedder · VectorStore · │
│                DocumentParser ·                       │
│                CodeExecutor · CodeParser              │
│   adapters/    OpenAICompat · SentenceTransformer ·   │
│                HashingEmbed · ChromaStore ·          │
│                PdfPlumber · PythonDocx · TextReader · │
│                SubprocessSandbox · AstParser · Mock*  │
│   persistence/ SQLAlchemy(SQLite) · Chroma 客户端      │
└──────────────────────────────────────────────────────┘
```

**端口清单**（P1 补记：原表遗漏了 RAG 链路所需的三个端口，均由
`infrastructure/ports/` 定义 `Protocol`，服务层只依赖协议不依赖实现）：

| 端口 | 职责 | 适配器 |
|---|---|---|
| `LLMProvider` | 对话与流式生成 | OpenAICompat、Mock |
| `Embedder` | 文本 → 向量；暴露 `name` / `model` / `dimension` / `is_sentinel` | SentenceTransformer、OpenAICompat、HashingEmbed |
| `VectorStore` | 向量 upsert / query / 删除；`query` 的 `kb_ids` **必填**（ADR-0007） | ChromaStore |
| `DocumentParser` | 源文件 → 纯文本；无文字层的扫描版 PDF 抛 `EmptyDocumentError` | PdfPlumber、PythonDocx、TextReader |
| `CodeExecutor` | 受控执行学生代码 | SubprocessSandbox |
| `CodeParser` | 静态分析 | AstParser |

### 4.2 四条硬约束

1. **领域层零 IO** —— `domain/` 不 import 任何基础设施模块，业务规则可脱离数据库单测。
2. **服务层依赖注入端口** —— services 只依赖 `Protocol`，不依赖具体 adapter；adapter 由 `ProviderRegistry` 依据后台 `ModelConfig` 解析。
3. **前端永不直连大模型** —— 所有 AI 调用过后端，以便统一施加防抄袭策略、注入 RAG 上下文、落审计日志。
4. **配置热生效** —— `ModelConfig` 带 `revision` 版本号，`ProviderRegistry` 缓存实例并以 revision 为失效键；后台保存即生效，无需重启。

### 4.3 目录结构

```
llm-code-tutor/
├── AGENT.md                      # Agent 工作流约束
├── CONTEXT.md                    # 术语表
├── Makefile                      # make dev / test / seed / setup
├── README.md
├── docs/
│   ├── adr/
│   └── superpowers/{specs,plans}/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py               # FastAPI 入口、全局异常处理、CORS
│   │   ├── core/                 # config · security · logging · deps
│   │   ├── domain/               # 实体与纯业务规则（无 IO）
│   │   ├── services/             # 用例编排
│   │   ├── routers/              # HTTP + SSE
│   │   ├── schemas/              # Pydantic 出入参
│   │   ├── infrastructure/
│   │   │   ├── ports/
│   │   │   ├── adapters/{llm,embedding,vectorstore,executor,parser}/
│   │   │   └── persistence/{db.py, repositories/}
│   │   └── prompts/              # Jinja2 提示词模板
│   ├── seeds/                    # 习题种子数据 + 初始 admin
│   └── tests/
└── frontend/
    ├── package.json · vite.config.ts
    └── src/{api,router,stores,views/{student,admin},components,types}
```

**P5 补记**：`backend/seeds/` 已落地为顶层包（遗留 M2 收口）。`seeds.seed()` 按
**admin → ModelConfig → exercises** 编排，三步全部幂等 —— 已存在即跳过，不覆盖既有
数据（管理员改过的密码与题干必须活过第二次 `make seed`）。`app/seed.py` 保留
`python -m app.seed` CLI 入口并**再导出** `seed` / `DEFAULT_ADMIN_USERNAME`，是薄壳而非
第二份实现（两份会各自漂移）。习题主键按
`uuid5(NAMESPACE_URL, "llm-code-tutor:exercise:<slug>")` 确定性派生 —— Exercise 没有
自然键（题干会被改、题型不是标识），幂等判定落在主键的确定性上，不为此在 §5 之外
新增列。

---

## 5. 数据模型

14 张表，SQLite 落地；向量存 Chroma，业务侧只留 `vector_id` 引用。

| 实体 | 关键字段 |
|---|---|
| **User** | username, email, hashed_password, role(student\|admin), status(active\|disabled), created_at, last_login_at |
| **Conversation** | user_id, title, created_at, updated_at |
| **Message** | conversation_id, role(user\|assistant\|system), content, citations(JSON), token_usage, model, provider, truncated, **anti_plagiarism_mode**, **blocked_by_policy(bool)**, created_at |
| **KnowledgeBase** | name, description, owner_id, **course_code(可空)**, embed_provider, embed_model, **status(ready\|reindexing)**, created_at |
| **Document** | kb_id, title, source_type(pdf\|md\|txt\|docx), source_uri, status(pending\|indexing\|ready\|failed\|reindexing), error_msg, **chunk_indexed**, **chunk_total**, created_at |
| **Chunk** | document_id, kb_id, content, ordinal, char_count, meta(JSON), **embed_model**, vector_id |
| **CodeSession** | user_id, language, source_code, title, created_at, updated_at |
| **CodeAnalysis** | user_id, language, source_hash, static_report(JSON), ai_report(JSON?), created_at —— 唯一约束 `(user_id, language, source_hash)`；`source_hash = sha256(language + NUL + source)` |
| **CodeRun** | user_id, language, source_code, stdin, status(accepted\|runtime_error\|timeout\|memory_exceeded\|blocked), stdout, stderr, exit_code, duration_ms, **limit_detail(JSON)**, created_at |
| **Exercise** | type(choice\|multi\|blank\|short\|coding), stem, options(JSON?), answer(JSON), test_cases(JSON?), explanation, knowledge_tags(JSON), difficulty(1-5), source(seed\|admin\|ai), status(draft\|published), created_by, created_at |
| **Submission** | user_id, exercise_id, answer(JSON), is_correct(bool?), score, judge_detail(JSON), feedback, attempt_no, created_at |
| **MistakeBookEntry** | user_id, exercise_id, wrong_count, consecutive_correct, last_wrong_answer, last_wrong_at, mastered, mastered_at —— 唯一约束 `(user_id, exercise_id)` |
| **ModelConfig** | provider, base_url, **api_key_encrypted**（Fernet 密文，读取接口一律返回掩码）, model, temperature, top_p, max_tokens, embedding_provider, embedding_model, anti_plagiarism_mode(strict\|guided\|loose), score_threshold, top_k, revision, updated_by, updated_at —— 单例记录 |
| **AuditLog** | user_id, action, target_type, target_id, detail(JSON), ip, request_id, created_at |

**P1 补记**：

- `KnowledgeBase.status`：§6.2（未就绪 → `5032`）与 §8.7（重建期间置 `reindexing`）
  都要求知识库级状态，故补此列。**文档索引不改变知识库状态** —— §3.2 权衡 16 明确
  「检索允许读到中间态」，只有全量重建才需要阻断检索。
- `KnowledgeBase.embed_provider` / `embed_model`：记录**最近一次实际用于索引**的模型，
  与 `ModelConfig.embedding_*`（配置的期望值）分列，两者不一致时由
  `GET /admin/model-config/embedding-consistency` 告警（§8.7 步骤 4）。

**P5 补记 —— `answer` / `test_cases` 的各题型形态**（§5 只写了「JSON」，此处定稿；
判题、admin 写入校验与种子共用同一份规则）：

| 题型 | `Exercise.answer` | `Exercise.options` / `test_cases` | 比对规则 |
|---|---|---|---|
| choice | 选项键字符串，如 `"B"` | `options = {"A": 文本, "B": 文本, …}`（键值对象，非数组） | 键全等 |
| multi | 选项键数组，如 `["A","C"]`（种子内按字母序存储） | `options` 同上 | 集合比较，乱序选择等价 |
| blank | 参考答案文本 | 无 | 去首尾空白 + `casefold` 忽略大小写 |
| short | 参考答案文本（解析放 `explanation`） | 无 | 转 AI 评分（§5.1 路 4） |
| coding | `{"language", "solution"}` | `test_cases = {"language", "cases":[{"stdin","expected_stdout"}]}` | `stdout.strip() == expected_stdout.strip()` |

- **执行语言归属 `test_cases`**（它决定用什么跑）；学生只交 `{"source": 源码}`，不带
  语言 —— 杜绝「学生语言与用例语言不一致」。
- `Submission.answer` 与学生视图同形（即上表的作答侧）。
- `attempt_no`：同一 `(user, exercise)` 现有提交数 + 1，从 1 递增。同用户并发提交的
  竞态在单 worker 演示规模下显式接受（无唯一约束）—— 重号只影响"第几次作答"的显示。
- `judge_detail` 各题型形态：choice/blank `{"method":"direct","passed"}`；
  multi `{"method":"direct","missing":[],"wrong":[]}`；
  coding `{"method":"executed","language","budget_exceeded","budget_limit_s","cases":[…]}`；
  short `{"ai_scored":true,"judge_mode":"model"|"mock_heuristic","model","provider","token_usage","feedback"}`。

### 5.1 判题三路

- **单选题、填空题**（choice / blank）：后端比对 `answer` 即时判分，`is_correct` 直接落定，得分 0 或 100。
- **多选题**（multi）：全对得 100 分且 `is_correct=true`；漏选（所选为正确答案的真子集）得 50 分且 **`is_correct=false`**；含错选得 0 分且 `is_correct=false`。**漏选按错误处理**，计入错题本。
- **编程题**（coding）：调用 `CodeExecutor` 执行 `test_cases`；全部通过得 100 分且 `is_correct=true`，否则按通过比例给分且 `is_correct=false`。`judge_detail` 记录每个用例的输入、期望输出、实际输出与耗时。**单题全部用例累计耗时上限 15s**，超出即中止剩余用例并按已通过比例判分。
- **简答题**（short）：转 AI 评分，`is_correct` 与 `score` 由大模型给出并标记 `judge_detail.ai_scored=true`；**得分 < 60 视为错误**，计入错题本。所有简答题判定均为参考分，前端必须展示"AI 参考评分"标识。

四种题型的错题归集判定统一为：`is_correct == false` 即入错题本。

**P5 补记 —— 判题落地口径**：

- **多选题空作答**（提交空数组、或缺少作答键）判 **0 分且 `is_correct=false`，但不算
  「漏选」**：`∅` 虽然是数学意义上的真子集，「漏选」的语义是「选了部分」—— 若按子集
  判定，"交白卷得 50" 就成了规则漏洞。`judge_detail.missing` 此时填全部正确键、
  `wrong` 为空，供前端区分「没答」与「答漏」。
- **编程题 15s 预算**由服务层跨用例自计（`CodeExecutor` 端口无 per-call 超时参数）：
  每个用例执行**前**先查预算，超预算即中止剩余用例（`judge_detail.cases[]` 里标
  `skipped:true, skip_reason:"budget_exceeded"`），按 `已通过 / 全部用例数` 取比例分，
  未全部通过一律 `is_correct=false`。`budget_limit_s` 随详情回传，前端可解释扣分。
- **简答题的评分调用不走 `PromptAssembler`**：装配器的四套主模板经 `_system.j2`
  无条件注入防抄袭档位与底线内容，会污染要求严格 JSON 输出的判分调用。system / user
  两条消息由领域层 `domain/exercise/short_scoring.py` 构建（判分是内部调用，§7.1
  完全豁免，不面向学生输出）。system 要求只输出
  `{"score": 0-100, "is_correct": bool, "feedback": string}`。
- **Mock 模式不发起 LLM 调用**：判定取配置层（`ModelConfig.provider`，同 §8.4 口径），
  改用确定性启发式（学生作答与参考答案的字符二元组重合度 → 0-100），
  `judge_detail.judge_mode="mock_heuristic"`、`ai_scored=true` 照记。**前端标识必须
  区分 judge_mode**：`model` → 「AI 参考评分」，`mock_heuristic` →
  「AI 参考评分（Mock 启发式）」—— Mock 可接受，但降级必须可见（§9 红线）。
- **真提供方输出解析失败 → `5021`，且不落 `Submission`、不入错题本**：把「模型故障」
  记成「学生答错」比丢一次提交更糟（学生无辜背一个错题条目，画像也被污染）。
- **硬规则**：模型给出 `score < 60` 时强制 `is_correct=false`，不采信模型自报的
  `is_correct`（§5.1「得分 <60 视为错误」）。

---

## 6. 接口契约

统一约定：前缀 `/api/v1`；Bearer JWT（白名单仅 `/auth/register`、`/auth/login`、`/health`）；admin 路由统一挂 `require_admin`；统一响应 `{code, message, data, request_id}`；分页一律 `page` + `page_size`，返回 `{items, total}`。

### 6.1 SSE 事件契约

`Content-Type: text/event-stream`

| 事件 | 载荷 | 时机 |
|---|---|---|
| `citation` | `{chunk_id, document_id, doc_title, kb_id, snippet, score, number}` | 检索完成后、生成开始前，可多次 |
| `token` | `{delta: string}` | 逐字增量 |
| `done` | `{message_id, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}` | 生成结束；Mock 模式下 `token_usage` 按 `len(content)//4` 估算并置 `usage_estimated=true` |
| `error` | `{code, message}` | 流中异常；学生主动中断为 `4990`，服务端故障沿用 `5021` |

`citation` 先于 `token` 发出，前端得以在答案出现前展示"引用了哪几段"。

`citation` 载荷在 P2 落地时比上表多出 `document_id` / `kb_id` / `number` 三个字段：
`number` 与 §7.2 步骤 5 注入 prompt 的片段编号 `[1][2][3]` 对齐，前端据此把模型正文里的
内联引用号映射到具体切片；`kb_id` 供管理端溯源。**上表是最小集，实际响应为其超集。**

**中断不是服务端故障**：学生点「停止」时发 `error` 事件且 `code=4990`，前端只结束打字机、
不弹红色错误提示；真正的调用失败才用 `5021`。两者混用会让一次正常的用户操作显示成故障。

**P5 附注 —— 习题辅导 `hint` 的 `done` 是同源变体**：该链路没有 Message 实体，故以
`exercise_id` + `intent` 两个字段替代 `message_id`，其余语义一个不减：
`{exercise_id, intent, token_usage, usage_estimated, model, provider, rag_hit, degraded,
fallback_reason}`（九字段）。`degraded` 取检索与提供方的或、`fallback_reason` 优先报
检索的；`citation` 仍先于 `token`；中断仍是 `4990`。

### 6.2 端点清单

| 域 | 端点 | 说明 |
|---|---|---|
| auth | `POST /auth/register` `POST /auth/login` `POST /auth/refresh` `GET /auth/me` `POST /auth/logout` | 注册默认 student 角色 |
| chat | `POST /chat/conversations` `GET /chat/conversations` `GET /chat/conversations/{id}/messages` `DELETE /chat/conversations/{id}` | |
| chat | `POST /chat/conversations/{id}/messages` `{content, use_rag, kb_ids?, course_code?}` → **SSE** | 主答疑链路；**固定 `seek_answer` 意图，不做语义推断**（见 §7.1） |
| chat | `POST /chat/conversations/{id}/stop` `{request_id?}` | 服务端置 cancel flag；**幂等**，流已结束返回 `{cancelled: false}` 而非报错。`request_id` 缺省时取消该会话全部进行中的流 |
| knowledge | `GET /knowledge/bases?course_code=` `GET /knowledge/search?query=&kb_ids=&course_code=&top_k=` | 学生侧只读；`course_code` 为空表示不限课程；**后端校验 kb 存在且 `status=ready`**（不存在 `404`，未就绪 `5032`） |
| admin·kb | `POST/PATCH/DELETE /admin/knowledge/bases` `POST /admin/knowledge/bases/{id}/documents`（multipart） `GET /admin/knowledge/bases/{id}/documents?status=` `POST /admin/knowledge/documents/{id}/reindex` `DELETE /admin/knowledge/documents/{id}` `GET /admin/knowledge/documents/{id}/chunks` `POST /admin/knowledge/bases/{id}/rebuild-vector` `POST /admin/knowledge/bases/{id}/gc-orphan-vectors` | 切片预览服务答辩演示；gc 清理孤儿向量 |
| code | `POST /code/analyze` `{language, source}` → `{static_report, ai_report, analysis_id, reused}` | 评改意图，豁免防抄袭约束；`reused=true` 表示命中历史、按用户复用了既有 `CodeAnalysis` |
| code | `POST /code/run` `{language, source, stdin}` → `{status, stdout, stderr, exit_code, duration_ms, limit_detail, run_id}` | 5s 墙钟超时；经线程池卸载，并发上限 2，超出返回 `429` |
| code | `GET/POST/PATCH/DELETE /code/sessions` `GET /code/runs` | 编辑器草稿与历史 |
| exercise | `GET /exercises?type=&difficulty=&knowledge_tag=&page=&page_size=` `GET /exercises/{id}` `POST /exercises/{id}/submit` `POST /exercises/{id}/hint` `{intent, answer?}` → SSE | intent **必填**，由前端入口按钮显式传入；`seek_answer` 受防抄袭档位约束，`review_my_code` 豁免。**P5 落地口径见下方「exercise / mistake / admin·exercise 端点补记」** |
| mistake | `GET /mistakes?mastered=` `DELETE /mistakes/{id}/mastered` `GET /mistakes/profile` `GET /mistakes/recommendations?limit=` | 同上 |
| admin·exercise（P5 补记） | `POST /admin/exercises` `GET /admin/exercises?type=&difficulty=&knowledge_tag=&status=&page=&page_size=` `GET /admin/exercises/{id}` `PATCH /admin/exercises/{id}` `DELETE /admin/exercises/{id}` | 补齐 §6.2 原先缺失的出题入口（习题来源之二：内置种子 + 后台 CRUD）。审计 action `admin_exercise_create/update/delete` |
| admin | `GET /admin/users?q=&role=&status=` `POST /admin/users` `PATCH /admin/users/{id}` `DELETE /admin/users/{id}` | |
| admin | `GET/PUT /admin/model-config` `POST /admin/model-config/test` | test 返回 `{ok, latency_ms, sample}`；PUT 改 embedding 配置时可能返回 409 |
| admin·embedding（P1 补记） | `PUT /admin/model-config/embedding` `{provider, model, confirm}` | §8.7 的入口。已有切片且 `confirm=false` → `409` + `{need_rebuild:true, knowledge_base_ids, from, to}`；确认后保存配置并**同步**触发全量重建，返回 `{rebuilt:[...], failed:[...]}`。**任一知识库重建失败即回滚配置**并抛 `5000` + `{rolled_back_to}` —— 否则会出现「新配置 + 旧维度向量」的静默零命中 |
| admin·embedding（P1 补记） | `GET /admin/model-config/embedding-consistency` | §8.7 步骤 4：比对配置的模型与切片上记的模型，返回不一致清单。**只告警不自动修复**（自动重建可能在无人值守时吃掉几分钟 CPU） |
| admin | `GET /admin/logs?action=&user_id=&start=&end=` `GET /admin/overview` `GET /admin/anti-plagiarism/stats` | overview 为仪表盘聚合；stats 返回各档位拦截率 |
| system | `GET /health` | |

**admin 端点补记（P6，管理后台收口）**：

- **`GET /admin/users` 出参 UserOut（裁定 4）**：`id, username, email, role, status,
  created_at, last_login_at` —— 含 email（管理员互见），`hashed_password` 永不出参。
  分页 `{items, total}` 按创建时间倒序；`q` 对 username/email 模糊匹配，`role`/`status`
  精确匹配（非法取值 422）。
- **`POST /admin/users`**：`{username, email, password, role?, status?}`（role 默认
  student、status 默认 active）；密码口径与注册一致（8–128 位，bcrypt 落库）；
  username/email 重复 → 4090。审计 `admin_user_create`。
- **`PATCH /admin/users/{id}`**：全字段可选、`extra=forbid`（schema 外字段 422 显式
  拒绝）；`status:"disabled"` 即**软删除**（日常路径，保留全部数据，登录与旧 token
  立即 4030）；传 password 即管理员重置密码。审计 `admin_user_update`。
  **自操作禁令（裁定 1）**：对自己的 role/status 变更一律 4220（自降权/自停用与自删
  同样锁死系统）；email/password 自改允许。
- **`DELETE /admin/users/{id}` 硬删除 + 级联（裁定 5：单事务同步）**：按序删
  会话 → 消息 → 提交 → 错题条目 → 代码会话 → 代码分析 → 代码运行，再删 User 行；
  `AuditLog` 一律保留（§8.9）。审计 `admin_user_delete`，detail 带全部级联计数。
  **末位 active admin 约束（裁定 1）**：删/停/降权其他 admin 后须剩余 ≥1 名
  `role=admin 且 status=active`，否则 4220；自删 4220。
  **KB.owner_id 悬空例外（裁定 9）**：硬删除**不级联知识库**（§8.9 七类清单之外），
  知识库功能对 owner 缺失必须容忍（不得 5000 或消失）。
- **`GET /admin/model-config`**：全字段回显；`api_key` 走掩码 `sk-****abcd`
  （§8.8；≤7 位短密钥整体 `****`，不泄露片段）。含 `revision / updated_by / updated_at`。
- **`PUT /admin/model-config`（裁定 2）**：字段面
  `{provider(mock|openai_compat), model, base_url?, api_key?, temperature?, top_p?,
  max_tokens?, anti_plagiarism_mode(strict|guided|loose), score_threshold?, top_k?}`，
  `extra=forbid`。**api_key 缺省/null = 不变更**（掩码回显下前端常态回传 null，
  绝不能清掉已有密钥）；空串 4220；`provider=openai_compat` 且（本次未提供且库中无）
  key → 4220 拒绝保存（静默降级会把「配置错误」伪装成「降级运行」）。
  保存即 `revision += 1`、`updated_by=管理员`（§4.2 硬约束 4 热生效，无需重启）；
  审计 `admin_model_config_update`。**embedding 两字段不入本 PUT** —— 仍走
  `/admin/model-config/embedding` 的 409 重建流程（§8.7）。`mock_token_delay_ms`
  保持 env 配置（`Settings`），不提供写入入口。
- **`POST /admin/model-config/test`（裁定 2 附项）**：**只测已保存配置**，不接受覆盖
  参数；返回 `{ok, latency_ms, sample}`。只测首选级提供方（不经降级链 —— 否则坏配置
  被 Mock 伪装成 ok=true）；失败返回 `ok:false` 且不抛 5xx（配置测试的失败是业务结果）。
- **`GET /admin/logs`（裁定 8 文案）**：`action` / `user_id` 精确匹配（两列有索引）、
  `start` / `end` 为 ISO 日期或日期时间（纯日期按当日闭合区间，无时区输入按 UTC，
  非法 422），按 `created_at` 倒序分页 `{items, total}`。出参为审计行全字段回显
  （含 detail JSON / ip / request_id）。页面说明：审计日志仅可查询、不可修改或删除。
- **`GET /admin/overview`（裁定 3）**：**最小集，实际响应为超集** ——
  `users{total,active,admin}`、conversations、messages、knowledge_bases、documents、
  code_sessions、code_analyses、code_runs、`exercises{published,draft}`、submissions、
  `mistake_entries{total,unmastered}`、audit_logs、`model_config{provider,model,
  anti_plagiarism_mode,revision}`、`embedder`（与 /health 同源快照）。
- **`GET /admin/anti-plagiarism/stats` 口径（P2 偏离 4）**：只数 `role=user` 的请求；
  页面文案必须写明「拦截率是度量口径，不是抄袭检出能力」。
- **`/admin/ping` 占位端点已移除**（P6）：spec §6.2 从未收录，OpenAPI 已同步消失。

**exercise / mistake / admin·exercise 端点补记（P5）**：

- **学生端只暴露 `status=published`**：列表与详情对 draft 与不存在一律 `4040`
  （不泄露「存在但未发布」）。`POST /exercises/{id}/submit` 同口径先校验再判分。
- **`GET /exercises` 响应为 `{items, total, facets.knowledge_tags}`**：分页按 §6.2 统一
  约定；`facets.knowledge_tags` 是 published 习题的标签去重清单，**不受 `knowledge_tag`
  筛选影响** —— 前端筛选下拉需要闭环的数据源，否则选完一个标签就没法换标签。
  spec 原本无此字段，按「实际响应为最小集超集」的既有惯例收录。
- **学生详情不泄题**：不含 `answer` / `explanation` / `test_cases`；coding 题附
  `language`（取 `test_cases.language`）。正确答案与解析只在提交后的响应里揭示。
- **`POST /exercises/{id}/hint` 请求体 `{intent, answer?}`**：`intent` 取
  `seek_answer` / `review_my_code` 两值，`judging` 是内部判分意图、**不对 HTTP 开放**
  （不在取值内 → 422）。`answer` 与 submit 同形，`review_my_code` **必填**（缺失 → 422），
  `seek_answer` 可缺省。本端点**没有配套的 `/stop`**：中断由前端 `AbortController`
  断连承担（§8.1 的第二重保险），per-call 取消 Event 与 `4990` 语义保留与 chat 同构。
- **`GET /mistakes?mastered=`** 三态（不传=全部、`true`=已掌握、`false`=未掌握），
  返回裸数组、每条附学生视图的习题摘要（单学生条目上限即题库规模，不分页）。
  **`GET /mistakes/recommendations?limit=`** 默认 5、取值范围 1–20（越界 422）。
  **`DELETE /mistakes/{id}/mastered`** 的 `{id}` 是 MistakeBookEntry.id，非本人条目与
  不存在一律 `4040`。
- **admin CRUD**：`source` 与 `created_by` 都不由请求体决定 —— 创建时服务端写死
  `source=admin`、`created_by=当前管理员`，`status` 缺省 `draft`。`PATCH` 的 schema 不含
  `source` 且 **`extra=forbid`**：传 `source` 或任何 schema 外字段一律 **422 显式拒绝**，
  不静默忽略（静默忽略属「看起来成功、实际没生效」的静默型失败）。跨题型一致性
  （choice/multi 必带 options 且答案键 ⊆ options、coding 必带 `test_cases.language` +
  非空 cases）在 PATCH **合并后**重新校验，失败 422 且不落半截改动。
  `DELETE` **手工级联**删该习题的 Submission 与 MistakeBookEntry（§5 无 ForeignKey，
  级联靠服务层序列，同 §8.9 用户硬删除口径），删除计数写进 `AuditLog.detail`。
  `source` 语义闭环：`seed`（种子写入，管理员不可改）· `admin`（CRUD 写入）·
  `ai`（预留枚举值，本批无写入入口）。
- **`POST /exercises/{id}/submit` 的编程题作答形态错误 → `4220`**（HTTP 422）：
  `answer` 必须是 `{"source": 非空源码}`。本批只新增这一个错误码并注册进 `CODE_STATUS`；
  其余沿用既有码（`4040` 越权、`5021` 评分/生成失败、`5032` 检索链路继承、`4290` 执行配额、
  `4990` 只进 SSE 载荷）。参数校验沿用 FastAPI 的 422。
- **`DELETE /mistakes/{id}/mastered` 落 `AuditLog(action=mistake_reset_mastered)`**：
  它改变学习状态（重新开启一轮），留痕口径与 `chat_conversation_delete` 同例。
- **错题本的三个出口都只认 published 习题**：条目列表、画像聚合与重置回显一律过滤
  `status != published` 的习题 —— 管理员把某道习题下架后，它的题干与选项不得再从错题本
  泄出（否则绕过上面那条不变量）；这类条目按「无主条目」同口径丢弃，重置返回 `4040`。

---

## 7. 提示词策略

模板落 `app/prompts/*.j2`，四套主模板 + 一个 `PromptAssembler`：`rag_qa` / `code_review` / `exercise_hint` / `mistake_review`。

### 7.1 防抄袭三档

由后台 `anti_plagiarism_mode` 切换，注入 system prompt。

| 档位 | 约束 |
|---|---|
| `strict` 严格 | 禁止输出完整可运行代码；只给思路拆解、关键概念、伪代码骨架（函数签名 + 注释占位）；学生追问时继续细化思路，不补代码 |
| `guided` 引导（默认） | 允许 ≤10 行最小片段解释单个概念；禁止给出完整实现；必须先讲思路再给片段 |
| `loose` 宽松 | 允许完整实现，但必须附逐段讲解并前置"请先自行尝试"提醒 |

**三档共有的不可覆盖底线**（硬编码进模板，后台配置无法绕过）：

1. 代做作业式请求一律转为引导。
2. 考试 / 竞赛在线作答场景拒绝直接给答案。
3. 输出中的任何代码必须配讲解。

**豁免项（不受档位约束）**

| 意图 | 端点 / 调用 | 是否受档位约束 | 理由 |
|---|---|---|---|
| 求答案 / 求实现 | chat、`/exercises/{id}/hint` 且 `intent=seek_answer` | **受约束** | 直接产出可提交的实现，构成抄袭风险 |
| 评改学生已写代码 | `/code/analyze`、`/exercises/{id}/hint` 且 `intent=review_my_code` | **豁免** | 学生已写出代码，给出改进版本不构成抄袭 |
| 判分与评分 | 简答题 AI 评分（内部调用） | **豁免** | 不向学生输出实现 |

`intent` 由前端**显式传入**，是契约而非推断：习题辅导界面提供「获取思路」（`seek_answer`）与「批改我的作答」（`review_my_code`）两个入口按钮，`/code/analyze` 固定传 `review_my_code`。

**聊天入口一律固定 `seek_answer`，不做任何语义推断。** 学生提问时经常会顺手贴上题目给出的示例代码；若按"消息含代码块即判为评改"来推断，就会误判为豁免并直接给出完整答案 —— **防抄袭将在最常用的入口被绕过**。推断错误的代价（泄露完整答案）与收益不对称，因此豁免只在显式入口生效。

**P5 补记 —— 习题辅导的两种意图如何落地**：

| 入口 | 模板 | 档位 | 问题串内容 |
|---|---|---|---|
| 学生点「获取思路」 | `exercise_hint.j2` | **受约束**（`resolve_mode` 施加配置档位） | 题型 + 题干 + 选项 + 知识点标签；**不含参考答案与解析** |
| 学生点「批改我的作答」 | `mistake_review.j2` | **豁免**（`mode=None`） | 上述内容 + 参考答案 + 解析 + 学生作答 |

- `seek_answer` 的问题串刻意不含答案：档位是提示词层的**软**约束，一旦模型不听话把
  实现吐出来，泄题的就是这条串本身；不给它答案，是最便宜的硬保证。
- `review_my_code` 豁免的是**档位，不是底线**：`_floor.j2` 三条底线仍由 `_system.j2`
  无条件注入（同 §8.4 对 `/code/analyze` 的处理）。
- **底线检测的输入是题干**（`floor_hit = detect_floor_violation(stem)`）：题干充当学生
  的请求文本；学生作答是**答案不是请求**，不做检测 —— 与 §8.4「不对代码做检测」同口径，
  否则关键词规则在代码/答案文本上误判率极高。
- 判分（`judging`）完全豁免且**不走装配器**：简答题评分的 prompt 由领域层构建，见 §5.1
  的 P5 补记。`judging` 作为 HTTP 入参不被接受（内部意图）。

### 7.2 RAG 增强装配链路

1. `Embedder.embed(query)` → `VectorStore.query(top_k=5, filter={kb_id ∈ ...})`
2. 相关度低于 `score_threshold` 的命中直接丢弃。默认值**按 embedding 模型分别取**：OpenAI 兼容 0.25 / MiniLM 0.35 / 其他 0.30
3. **相对截断兜底**：与最佳命中分差 > 0.15 的命中一律丢弃 —— 余弦相似度的绝对值分布随模型而异，相对分差跨模型可比
4. 按 `document_id` 聚合做**多样性截取**（单文档最多 3 片段），防止长文档霸占上下文
5. 片段编号 `[1][2][3]` 注入 prompt，要求模型**内联引用编号**
6. 命中的 `chunk_id` 写入 `Message.citations`，前端点击可溯源
7. **零命中或命中被全部截断时明确降级**：告知"知识库无相关内容"，改走通用回答，响应标记 `rag_hit=false` —— 防止模型幻觉冒充知识库答案

**该链路同时服务于答疑对话与习题辅导**。`/exercises/{id}/hint` 的检索 query 取 `stem + knowledge_tags`，**不含学生作答** —— 把错误答案带进检索会污染相似度。若不做此处理，同一知识点在「答疑」与「习题辅导」两个入口的答案质量会相差一档。

### 7.3 Mock Provider 与 HashingEmbed 的行为

**HashingEmbed 是哨兵，不是可用降级**。它产生的向量无语义，检索结果近似随机。若仍注入 prompt，模型会基于完全无关的片段理直气壮地作答 —— 这比功能不可用更糟。因此：

- 当实际生效的 Embedder 为 `HashingEmbed` 时，**检索结果一律不注入 prompt**
- 强制 `rag_hit=false` + `degraded=true` + `fallback_reason=hashing_embed_no_semantics`
- 前端提示条文案："当前为无语义向量模式，已停用知识库增强"

**Mock LLM Provider**（`MockProvider`）输出策略：

- 对命中片段做**抽取式生成**：取片段首句 + 模板话术拼装，同样逐字流式吐出
- 同样遵守防抄袭三档（strict 档输出固定引导话术）
- 响应标记 `provider=mock`，前端角标提示"Mock 模式"
- **`mock_token_delay_ms`（默认 30）**：每个 `TextDelta` 之间的间隔毫秒数，**只作用于 `MockLLMProvider.stream()`**，绝不触碰 OpenAI 兼容链路。

  存在的理由：Mock 无网络往返，约 0.1s 即生成完毕，浏览器点「停止」几乎总是来不及截断，
  无 API Key 演示时看不到任何流式效果，`/chat` 与 `/code/analyze` 的演示形同失效。
  实测对照：同一答疑请求 165 个增量，默认 30ms 总耗时 5.21s，置 0 后 0.11s。

  约束：`complete()` 是非流式调用，**不受该设置影响**。延迟会拖慢既有用例，
  测试应在 conftest 中集中把该设置置 0，不得为提速而改动默认值。
  Mock 判定的 `/code/analyze`（§8.4）不发起 LLM 调用，故也不叠加此延迟。

### 7.4 防抄袭效果度量

不做抄袭检测，但做拦截率度量，使该功能点可量化：

- `Message` 落库时写入当次生效的 `anti_plagiarism_mode` 与 `blocked_by_policy`（本次请求是否触发底线拦截）
- `GET /admin/anti-plagiarism/stats` 返回各档位下的「触发底线次数 / 总请求数」
- README 提供固定对照用例（如"直接帮我写冒泡排序"）在三档下的预期输出，供答辩现场对比

---

## 8. 关键流程

### 8.1 答疑对话（含 RAG）

`ChatService.stream_reply()`：落 user message → 装配 RAG 并发 `citation` → 渲染 prompt（防抄袭档位 + 底线 + 上下文 + 历史）→ 流式转发 token，每 token 检查 cancel flag → 落 assistant message（citations / token_usage / model / provider / anti_plagiarism_mode / blocked_by_policy）→ 发 `done` → 写 `AuditLog(action=chat)`。

**历史截断规则**（固定值，不开放配置）：按时间倒序累加最近轮次，累计 token 超过 **4000**，或轮数超过 **10 轮**（一问一答计一轮）即停止累加；若累加后一轮都未纳入（即最近一轮本身已超出预算），则强制纳入最近一轮，保证上下文不断裂。

流中断发 `error`，已生成内容仍落库并标记 `truncated=true`。无论正常结束还是异常中断，`AuditLog(action=chat)` 均在 `finally` 中写入。

**中断实现**：`asyncio.Event` 存于内存注册表，键为 `(conversation_id, request_id)`；生成循环每次 yield 前检查一次 Event；`/stop` 端点与「同一会话发起新请求」两种情形均置位；流结束或异常时在 `finally` 中注销。前端 `AbortController` 断开时 FastAPI 的 `request.is_disconnected()` 亦能感知，作为第二重保险。**该内存注册表依赖单 worker，是 §3.1 假设 5 的又一理由。**

**P5 补记 —— 习题辅导复用同一注册表，但作用域键必须是 per-user**：hint 没有会话可当
作用域，若直接用 `exercise_id` 建键，`create()` 的「同作用域旧流置位」语义就会让
**B 同学发起辅导掐断 A 同学在同一习题上进行中的流**（A 收到 `4990`）—— 会话属于单个
用户所以 chat 安全，而**习题是共享实体**。故 hint 的作用域键取
`f"{user_id}:{exercise_id}"`，保留「同一学生同一习题再发起一次辅导 → 取消自己上一条」
的原意。hint 亦无 `/stop` 端点（§6.2 补记），`finally` 注销与审计留痕
（`AuditLog(action=exercise_hint)`）与 chat 同构。

### 8.2 知识库索引

上传存盘（`status=pending`）→ `BackgroundTasks` 异步执行：解析（pdfplumber / python-docx / 直读）→ 递归标题切分 + 固定窗口重叠 → 批量 embed → Chroma upsert 取 `vector_id` → Chunk 落库 → `status=ready`。失败置 `failed` + `error_msg`，管理端可见并可 reindex。

**切分按字符数计量，不用 token**：默认 **1200 字符 / 150 字符重叠**。中文场景下 token 密度与英文相差 2–3 倍，用 tokenizer 计量会导致切片粒度不可预测；按字符计量可预测且免引入 tiktoken 依赖。`Chunk` 表记录 `char_count`。

**进度可见**：`Document` 暴露 `chunk_indexed / chunk_total`，管理端轮询展示索引进度。

**上传校验**：单文件上限 **10MB**，超出直接拒绝（`413`）；扩展名不在白名单（`.pdf` `.md` `.txt` `.docx`）内直接拒绝（`415`）。

**无文字层文档**：扫描版 PDF（纯图片、无文字层）经 pdfplumber 解析后文本为空或极短。此时判定为解析失败，置 `status=failed` + `error_msg="未提取到文本，可能是扫描版 PDF，请先做 OCR"`。**不做 OCR**（见 §3.3），该限制在管理端上传页显式提示。

**降级路径**：若 Embedder 实际为 `HashingEmbed`，索引仍照常写入（保证链路可跑通），但检索阶段不采纳其结果（见 §7.3）。

**并发与阻塞**：索引任务（解析 + embedding 推理，CPU 密集）经 `run_in_threadpool` 卸载到线程池，并以 per-`kb_id` 的 `asyncio.Lock` 串行化，全局索引并发上限 1。锁仅保护写操作，**检索不持锁**（允许读到中间态）。锁对象由注册表按 `kb_id` 懒创建并定期清理，防止内存泄漏。

### 8.3 代码运行

1. **黑名单扫描**：命中即 `status=blocked` 直接返回，不执行。覆盖 `os.system`、`subprocess`、`socket`、`shutil.rmtree`、`__import__`、`eval` + `exec` 组合等。**黑名单是防误触，不是防攻击** —— Python 下 `__import__('o'+'s')`、`getattr` 链、编码绕过均可轻易绕过，此点必须在 README 与后台页面显式声明。
2. **落临时目录**，`env` 清空继承，以 `python -I -S` / `node` 启动子进程。
3. **四层资源限制**（逐层用 `try/except` 包裹，不支持时降级并记入 `limit_detail`）：

| 层 | 手段 | 阈值 | 跨平台性 |
|---|---|---|---|
| 墙钟超时 | `subprocess` 超时 + SIGKILL | 5s | 全平台 |
| CPU 时间 | `RLIMIT_CPU` | 3 CPU 秒 | macOS / Linux 均可设（已实测） |
| 内存 | **`psutil` 轮询采样子进程 RSS**，超阈值 SIGKILL | 256MB，采样间隔 100ms | 全平台；采样窗口内可能瞬时冲高 |
| 文件写入 | `RLIMIT_FSIZE` | 1MB | macOS / Linux 均可设（已实测） |

4. **输出截断**：父进程读取管道时按 **8KB/流** 截断（`stdout`、`stderr` 各 8KB）。**不使用 `RLIMIT_FSIZE` 截断输出** —— stdout 是 pipe 不是 file，该限制对管道无效。
5. 清理临时目录 → 落 `CodeRun`（含 `limit_detail`，记录各限制层是否生效）→ 写 `AuditLog`。
6. **`stdin` 走临时文件重定向，不走管道写入** —— 学生代码若不读 `stdin`，父进程写大块数据会死锁。
7. **响应语义**：`/code/run` 无论 `status` 是 `accepted` / `runtime_error` / `timeout` / `memory_exceeded` / `blocked`，HTTP 状态一律 **200** —— 执行结果是领域结果而非传输层故障，前端按 `status` 分支渲染（timeout / memory_exceeded 不应弹红色错误条）。
8. **`limit_detail` 是实测留痕，不是配置回显**，结构固定如下（未执行时各层 `applied=false` 并注明原因，字段形状与执行路径保持一致）：

```json
{
  "executed": true,
  "error": null,
  "blacklist": {"rule": null, "executed": false},
  "wall_clock": {"limit_s": 5, "elapsed_s": 0.31, "triggered": false},
  "cpu": {"limit_s": 3, "applied": true, "error": null, "triggered": false},
  "memory": {"limit_bytes": 268435456, "sampled": true, "interval_ms": 100,
             "peak_bytes": 134217728, "samples": 4, "triggered": false},
  "file_size": {"limit_bytes": 1048576, "applied": true, "error": null},
  "output": {"limit_bytes": 8192, "stdout_bytes": 45, "stderr_bytes": 0,
             "stdout_truncated": false, "stderr_truncated": false}
}
```

> 它是事后回答「这次运行到底哪层限制生效了」的唯一依据（P4 审阅明确要求），也是前端限制层展示表格的数据源。

**并发与阻塞**：整段执行（含 psutil 轮询）为同步阻塞调用，经 `run_in_threadpool` 卸载到线程池；全局并发上限 **2**（信号量）。获取信号量超时（默认 10s）即返回 `429` + `retry_after`，**不无限排队**。

**不使用** `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_RSS`：实测 macOS darwin 下 `resource.setrlimit` 对这三项一律抛 `ValueError: current limit exceeds maximum limit`。

### 8.4 代码解析与辅导

静态解析产出 `static_report`（函数/类清单、圈复杂度、未使用变量、裸 `except`、行数统计）→ `source_hash` 命中历史则复用 → provider 可用时流式生成 `ai_report`；Mock 模式下 `ai_report` 由 `static_report` 模板化生成。

- **`ai_report` 为自描述 JSON**：`{content(Markdown), provider, model, token_usage, usage_estimated, degraded, fallback_reason}`。
- **Mock 模式不发起 LLM 调用**：判定取配置层（`ModelConfig.provider`）而非运行时快照 —— 运行时快照在首次调用前为 `None` 不能作判定源；按配置判定可让 Mock 路径完全不走网络，因此也不叠加 §7.3 的 `mock_token_delay_ms` 延迟。
- **复用按 user 隔离**：`ai_report` 可能因档位或模型不同而异，跨账号共享会让 B 学生看到 A 学生的历史讲解。唯一约束 `(user_id, language, source_hash)` 把「不重复算」落到库层。
- **语法错误返回报告而非 4xx/500**：教学工具对写了一半的代码更要给反馈，行号 + 消息 + 行数统计照常产出，前端用 alert 呈现。
- **JS 解析为轻量近似**（正则 + 花括号配对）：不识别字符串/正则字面量、方法清单靠行首模式匹配、不做语法校验。Python 走 `ast` 为精确实现。教学演示够用，**不可当 lint 工具宣传**。

**该流程固定为 `review_my_code` 意图，豁免防抄袭档位约束**（见 §7.1）。但它**不做 RAG、不做底线检测**：RAG 按 §7.2 只服务答疑与习题辅导；底线检测的关键词规则在代码注释里误判率高。不过 `_floor.j2` 三条底线仍由 `code_review.j2` 无条件注入 —— 免的是档位，不是底线（§3.2 权衡 10）。

### 8.5 判题与错题归集

三路判定 → 落 `Submission` → 更新 `MistakeBookEntry`：

- 正确：`consecutive_correct += 1`；达到 2 次置 `mastered=true`、`mastered_at=now`
- 错误：`wrong_count += 1`，`consecutive_correct = 0`，**`mastered=false`、`mastered_at=null`**，写入 `last_wrong_answer` 与 `last_wrong_at`；无条目则创建

**已掌握必须可回滚**。若错误时不重置 `mastered`，学生把某题练到「已掌握」后再答错，该条目将永久停留在 `mastered=true` 并被错题本默认过滤排除，「错题驱动学习」退化为单向门。语义取最直白的一档：掌握了又做错，就是没掌握。

`GET /mistakes/profile`：按 `knowledge_tags` 聚合 `SUM(wrong_count)`，排除已掌握条目。
`GET /mistakes/recommendations`：取 top-3 薄弱 tag → 选题（排除已掌握）→ 按难度升序返回。**不足 `limit` 时按难度递增补足同课程随机题**，并在响应中标注 `filled_by=random`，避免把随机题误当个性化推荐。

**P5 补记 —— 判题与错题归集的落地口径**：

- **错题条目只收错误**：`is_correct=false` 才建条目（「无条目则创建」说的是错误分支）；
  从未答错的正确提交**不建条目**。但已存在的条目在答对时**必须推进**
  `consecutive_correct`，否则永远到不了「连续 2 次」。
- **画像聚合在 Python 层**：`knowledge_tags` 是 JSON 列，无法直接 SQL 聚合；
  声明规模（错题条目 < 千）下成本可忽略（§3.2 权衡 3）。已掌握条目排除在聚合之外。
- **RandomFill 的「同课程」口径**：Exercise 无课程维度（§5 未给 `course_code` 列），
  故随机补足从**全部 published 习题**中选取（排除已在推荐清单中的、排除该生已掌握的）。
  补足项按 `(difficulty, created_at, id)` **确定性**升序选取 —— 演示规模下「可复现」比
  「真随机」更有价值（答辩时同一学生刷新两次不该看到两套推荐）。
- **手动重置掌握度**（`DELETE /mistakes/{entryId}/mastered`）的语义是**开启新一轮练习
  周期**：`mastered=false`、`mastered_at=null`、**`consecutive_correct=0`**；
  `wrong_count` 与 `last_wrong_answer/last_wrong_at` **保留**。理由：(a) 掌握度的定义是
  「连续 2 次答对」，跨周期的旧连对不应计入新一轮的「连续」；(b) 若保留计数，重置后
  答对 1 次即重新掌握，「重置掌握度」按钮形同虚设 —— 静默型语义失效，违反本特性初衷；
  (c) 不可篡改的历史是 `wrong_count` 与 `last_wrong_*`（都保留），`consecutive_correct`
  是状态机状态而非历史，清零不是篡改。非本人条目与不存在一律 `4040`（不泄露存在性）。
- 判题链路另见 §5.1 的 P5 补记（四路落地口径、15s 预算、Mock 启发式与 `5021` 不落库）、
  §5 的 P5 补记（各题型 `answer` / `test_cases` 形态与 `judge_detail` 结构表）与 §6.2 的
  exercise 端点补记（提交后揭示正确答案与解析、`4220` 编程题作答形态错误）。

### 8.6 知识库删除与孤儿向量清理

删除顺序**固定为三步、不可颠倒**：先删 Chroma 向量 → 再删 `Chunk` 行 → 再删 `Document` / `KnowledgeBase` 行。Chroma 删除失败时**仍继续删 DB**，但写 `AuditLog(action=admin_kb_delete, detail={vector_cleanup: "failed"})` 告警，避免残留无法清理的记录。

`POST /admin/knowledge/bases/{id}/gc-orphan-vectors`：扫描 Chroma 中不属于任何 `Chunk.vector_id` 的向量并删除，用于修复历史残留。

**并发控制**：删除、重建、GC 三类写操作与索引共用 per-`kb_id` 的 `asyncio.Lock`（见 §8.2），避免"重建"与"删除"同时发生时的竞态。三类操作均经线程池卸载，不阻塞事件循环。

### 8.7 Embedding 配置变更

**切换即强制全量重建，不允许边用边切**。不同 embedding 模型维度不同（OpenAI 1536 / MiniLM 384 / Hash N），混合会导致 Chroma 查询直接抛错。

1. 后台保存 embedding 配置时，后端检查该 KB 是否已存在 `Chunk` 行
2. 若存在 → 返回 **409 + `need_rebuild: true`**，前端弹二次确认
3. 确认后自动触发 `rebuild-vector`，KB 置 `reindexing`，期间检索返回 `5032`
4. `Chunk.embed_model` 字段记录实际索引所用模型，启动时校验「配置与索引不一致」并告警，防止手动改库或改 `.env` 绕过
5. **切换与重建是一个「要么全成、要么回滚」的单元**：任一 KB 重建失败即把
   `embedding_provider` / `embedding_model` 回滚到切换前，再自增一次 `revision`
   让运行时缓存失效，并抛 `5000` + `{failed, rolled_back_to}`。

   不回滚的后果是**静默零命中**：配置已指向新模型，查询于是拿新维度的向量去查
   `course_chunks_d{新维度}` 集合，而该集合是空的（维度分区见 ADR-0007）——
   学生端拿到空结果，既无错误码也无提示，降级完全不可见，违反 §9。

6. 判定「重建是否成功」不能只看有没有抛异常：逐份文档的索引失败会被
   `IndexingService` 各自吞掉并置 `status=failed`，于是**全部失败也会走成功分支**。
   故按结果复核：仍残留旧模型切片、或重建后切片数为 0，都判为失败。

### 8.8 API Key 的加密存储

后台「模型参数配置」允许管理员填写 API Key。明文落 SQLite 意味着任何能读取数据库文件的人都能拿到密钥，而演示场景下整个项目目录极可能被拷贝传播。

- 使用 `cryptography.fernet` 对称加密后存入 `ModelConfig.api_key_encrypted`
- 主密钥来自环境变量 `APP_SECRET`；缺失时首次启动自动生成并写入 `.secret_key`，该文件加入 `.gitignore`
- 所有读取接口返回**掩码** `sk-****abcd`；仅在实际调用 Provider 时于内存中解密
- `.secret_key` 丢失即无法解密已存密钥，此时后台提示重新录入（README 明确说明）

### 8.9 用户删除语义

管理员停用用户走 `PATCH /admin/users/{id} {status: "disabled"}`（软删除，保留全部数据），这是日常操作路径。

`DELETE /admin/users/{id}` 为**硬删除 + 级联清理**，按序删除：会话 → 消息 → 提交 → 错题条目 → 代码会话 → 代码分析 → 代码运行。

**`AuditLog` 一律保留，不随用户删除** —— 审计记录的可追溯性优先于数据清理。硬删除操作本身写入 `AuditLog(action=admin_user_delete)`，即使执行者自身后续被删除，该记录仍然存在。

**P6 实记（2026-08-31）**：
- 级联为**单事务同步**执行（裁定 5），`admin_user_delete` 审计的 `detail` 带全部七类
  级联计数（conversations / messages / submissions / mistake_entries / code_sessions /
  code_analyses / code_runs），硬删除不可回滚，计数是唯一事后依据。
- **管理员自删禁令与末位 active admin 约束（裁定 1）**：自删、自降权、自停用一律 4220；
  删/停/降权其他 admin 后须剩余 ≥1 名 `role=admin 且 status=active`，否则 4220。
- **KB.owner_id 悬空例外（裁定 9）**：硬删除**不级联知识库** —— 知识库归属者被删除后，
  其 `owner_id` 悬空但知识库照常可读可管理（不得 5000 或消失）；该例外与 AuditLog 保留
  并列写入 `UserService.delete` docstring，防止后续新增表时漏更级联清单。
- 七类级联清单 + 两项不级联例外（AuditLog / KB.owner_id）在实现 docstring 逐项列出。

---

## 9. 错误处理与降级

| 场景 | 处理 |
|---|---|
| LLM 调用失败 / 超时 | 降级到下一 Provider，并置 `degraded=true` + `fallback_reason="llm_fallback_to_mock"`；全部失败返回 `5021`，前端提示"模型不可用"，已得 citation 仍展示 |
| 无 API Key | 解析为 `MockProvider`，全链路可用 + 前端角标 |
| Embedding 失败 | 三级回退：OpenAI 兼容 → sentence-transformers → HashingEmbed；**落到 HashingEmbed 时不注入 prompt**，强制 `rag_hit=false` |
| Chroma 不可用 | 知识库功能降级（`5032`），其余模块不受影响 |
| 代码执行超时 | kill 进程，`status=timeout`，返回已捕获的部分输出 |
| 执行并发已满 / 获取信号量超时 | 返回 `429` + `retry_after`，不无限排队 |
| 代码内存超阈值 | psutil 采样触发 SIGKILL，`status=memory_exceeded` |
| 代码命中黑名单 | `status=blocked`，返回命中规则名，不执行 |
| 文档解析失败 | `status=failed` + `error_msg`，其余文档不受影响 |
| 切换 embedding 且 KB 已有切片 | 返回 `409` + `need_rebuild: true`，二次确认后强制全量重建 |
| 切换 embedding 后重建失败 | 回滚配置并抛 `5000` + `{failed, rolled_back_to}`。**不回滚则会静默零命中** —— 新模型的新维度向量去查空集合，学生端看不到任何异常 |
| KB 处于 `reindexing` 期间检索 | 返回 `5032`，提示索引重建中 |
| 检索指定 `kb_ids` 不存在 / 未就绪 | 不存在返回 `404`；未就绪返回 `5032` |
| 未捕获异常 | 全局 handler → `{code:5000}` + request_id，隐藏堆栈 |

**降级必须可见**：所有降级在响应中带 `degraded: true` 与 `fallback_reason`，前端展示提示条。

**零命中亦属降级**：§7.2 步骤 7 的「零命中或命中被全部截断」同样置
`degraded=true`，`fallback_reason="no_relevant_chunk"`。它与哨兵降级靠
`fallback_reason` 区分 —— 前者是正常的「知识库里没有相关内容」，后者是
`hashing_embed_no_semantics`，意味着检索结果无语义、不可信。两者都不可注入 prompt。

**`fallback_reason` 是封闭枚举，共三值**，前端必须逐个给文案，不能只做一个泛化的
「已降级」提示条：

| 取值 | 含义 | 前端文案要点 |
|---|---|---|
| `no_relevant_chunk` | 知识库里没有相关内容（正常未命中） | 「知识库无相关内容，以下为通用回答」 |
| `hashing_embed_no_semantics` | 检索结果无语义、不可信（ADR-0004） | 「已停用知识库增强」 |
| `llm_fallback_to_mock` | 首选提供方不可用，已降级到 Mock（§9 首行） | 「模型服务不可用，用量按字符数估算」 |

检索降级与提供方降级可能同时发生，此时 `degraded` 取二者的或，`fallback_reason`
**优先报检索的** —— 它是学生更可感知的那个（P2 约定）。

---

## 10. 测试策略

- **领域层**：纯单测（判题规则、掌握度状态机、防抄袭档位选择、意图豁免判定），无 IO
- **服务层**：注入 Fake adapter 测编排逻辑
- **端口适配**：契约测试 —— `MockProvider` 与 `OpenAICompatProvider` 跑同一组断言，确保同签名同语义
- **执行器**：真起子进程，测墙钟超时 / CPU 秒限制 / psutil 内存 kill / 黑名单 / 管道输出截断 / `limit_detail` 记录正确性
- **API**：`httpx.AsyncClient` + 内存 SQLite（`create_all` 建表），覆盖鉴权与角色拦截
- **前端**：不引入 E2E；保证 `vue-tsc` 类型检查与 `vite build` 通过

---

## 11. 实施批次

| 批次 | 内容 | 依赖 |
|---|---|---|
| P0 | 骨架、单 worker 启动脚本、SQLite WAL、用户鉴权、审计日志、统一响应、Provider 抽象 + Mock、`make seed`（幂等写入初始 admin + 默认 ModelConfig 行）、**执行 `uipro init --ai codebuddy` 建立前端设计基线** | — |
| P1 | RAG 知识库：文档接入 / 切分 / 向量化 / 检索 + 管理端（含删除顺序与孤儿向量 GC、embedding 切换 409 流程） | P0 |
| P2 | AI 答疑对话：SSE + RAG 增强 + 防抄袭三档 + 意图豁免 + 拦截率统计 | P1 |
| P3 | 代码解析与辅导：静态解析 + AI 讲解（豁免档位） | P0 |
| P4 | 在线编辑器与运行调试：Monaco + 四层受限执行器 | P0 |
| P5 | 习题与错题本：题库种子（约 40 题，覆盖 Python 基础知识点，五种题型齐备，编程题配 `test_cases`。**若提供课程大纲则按大纲出题**）+ 判题 + 错题归集 + 薄弱画像 + 定向推荐 + AI 辅导 | P1、P2 |
| P6 | 管理后台收口：用户管理（软删除为默认路径，硬删除级联清理但保留审计）、模型配置页、日志页、防抄袭统计、仪表盘 + 种子数据与 README | P0 |

P0 之后每批均可独立演示。

**P5 落地实况**：题库种子为 **40 道**（choice 10 / multi 6 / blank 8 / short 8 / coding 8；
难度 1×8 / 2×10 / 3×12 / 4×7 / 5×3），知识点标签取 12 项封闭词表（变量与赋值、数据类型、
运算符、控制流、循环、函数、列表、字典、字符串、切片、推导式、异常处理），**每个标签至少
被 2 道习题引用**，使薄弱画像与定向推荐可闭环。未提供课程大纲，故按 §11 的默认口径
（Python 基础知识点）出题。coding 题的参考答案由 `tests/test_seed_exercises.py` 用
**真** `SubprocessCodeExecutor` 逐用例实测通过（Fake 执行器只能证明接线，证明不了习题
可做）。管理后台 CRUD 见 §6.2 的 admin·exercise 行。

---

## 12. 术语

正式术语表见 `CONTEXT.md`。本 spec 全文使用其中定义，不得混用或自造。
