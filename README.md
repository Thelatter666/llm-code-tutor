# 基于大语言模型的智能编程教学辅助系统

面向编程教学场景的智能辅助系统：学生端提供 AI 答疑对话（RAG 课程知识库增强）、代码智能解析与辅导、
在线代码编辑器与受限运行、习题练习与 AI 习题辅导；管理端提供用户与知识库管理、模型参数配置与系统日志。

## 快速开始

```bash
# 1) 安装（精简版，跳过约 1GB 的 torch；需要真实语义检索再执行 make setup-local-embed）
make install-lite

# 2) 起双端口开发服务：前端 http://localhost:5173 · 后端 http://localhost:8000
make dev

# 3) 单端口演示（先构建前端，再由后端同源伺服 dist）
make serve

# 4) 全量测试（后端 pytest + 前端 vitest）
make test
```

无 API Key 时系统运行在 Mock 提供方模式（`MockProvider`），全链路可跑通，适合演示与开发。
演示机的完整流程见「演示机跑法」，逐功能点的实现落点与演示路径见「功能一览与答辩口径」。

## 默认管理员与首次登录（必读）

首次 `make seed` 会创建默认管理员：

- 用户名：`admin`　密码：`Admin@12345`
- **首次登录后请立即修改密码**（用户管理 → 编辑 → 重置密码）。
  默认口令公开于本 README，任何拿到项目副本的人都能用它登录管理后台。
- `make seed` 为幂等操作：题库将写入 **40 道习题**（五种题型齐备、覆盖 12 个
  Python 基础知识点标签）；重复执行不会覆盖管理员已改的密码与已编辑的题干。

管理后台入口：登录后在左侧导航可见（仅管理员角色显示），包含用户管理、习题管理、
模型配置、系统日志、仪表盘与防抄袭统计。

## 功能一览与答辩口径

以下 12 个功能点与 spec §11 的功能清单逐一对应。端点路径均省略统一前缀 `/api/v1`
（`/health` 除外）；页面路径即左侧导航项，hash 路由，`make serve` 同源可演示。

> **总结论：12 个功能点全部无需 API Key 即可演示（Mock 提供方）。**
> 答辩时需口头声明两处：① **AI 文本质量**——Mock 下答疑 / 讲解 / 辅导为抽取式生成或
> 固定文案，真实模型下为个性化输出；② **RAG 语义精度**——演示机未补装本地嵌入模型时
> 检索运行在 HashingEmbed 哨兵级降级上，降级横幅可见，这是设计承诺而非故障（ADR-0004）。

| 功能点 | 页面（导航项） | 关键端点 |
|---|---|---|
| 1. AI 答疑对话 | `/chat` | `POST /chat/conversations/{id}/messages`（SSE） |
| 2. RAG 知识库增强 | `/chat`、`/knowledge` | `GET /knowledge/bases`、`GET /knowledge/search` |
| 3. 代码解析辅导 | `/code` | `POST /code/analyze` |
| 4. 在线编辑器运行调试 | `/editor` | `POST /code/run` |
| 5. 习题练习与 AI 习题辅导 | `/exercises` | `POST /exercises/{id}/submit`、`POST /exercises/{id}/hint`（SSE） |
| 6. 用户管理 | `/admin/users` | `GET/POST/PATCH/DELETE /admin/users` |
| 7. 知识库管理 | `/admin/knowledge` | `/admin/knowledge/*`（10 端点） |
| 8. 模型参数配置 | `/admin/model-config` | `GET/PUT /admin/model-config`、`POST /admin/model-config/test` |
| 9. 系统日志 | `/admin/logs`、`/admin/overview`、`/admin/anti-plagiarism` | `GET /admin/logs`、`GET /admin/overview`、`GET /admin/anti-plagiarism/stats` |
| 10. 防抄袭约束提示词 | 生效于 `/chat` 与 `/exercises` | `PUT /admin/model-config`（配置）· `GET /admin/anti-plagiarism/stats`（度量） |
| 11. RAG 知识库检索 | `/knowledge` 与答疑链路 | `GET /knowledge/search` |
| 12. 错题驱动学习 | `/mistakes` | `GET /mistakes`、`GET /mistakes/profile`、`GET /mistakes/recommendations` |

### 学生端

#### 1. AI 答疑对话

- **实现落点**：`/chat` 页；`POST/GET /chat/conversations`、`GET/DELETE /chat/conversations/{id}`（含 messages 列表）、`POST /chat/conversations/{id}/messages`（SSE）、`POST /chat/conversations/{id}/stop`。本链路固定为求答案意图（`seek_answer`），受防抄袭档位约束，不做语义推断（spec §7.1）。
- **演示路径**：学生登录（注册默认学生角色）→「新建会话」→ 输入「怎么用 Python 写一个冒泡排序」→「发送」→ 看流式逐字输出与气泡下方引用卡片；再发起一问、流中途点「停止生成」→ 前端只结束打字机（中断是 `4990`，不弹错误提示）。
- **Mock 可演示性**：✅ 逐字节奏由 `MOCK_TOKEN_DELAY_MS`（默认 30ms）控制，「停止」有可截断窗口。

#### 2. RAG 知识库增强

- **实现落点**：`/chat` 页（RAG 开关 + 知识库选择器）与 `/knowledge` 页（学生侧只读检索）；`GET /knowledge/bases`、`GET /knowledge/search`；答疑 SSE 链路的上下文装配见 spec §7.2 / §8.1。
- **演示路径**：先在管理端建好知识库并等索引「就绪」（见功能点 7）→ `/chat` 勾选「启用知识库增强（RAG）」、选择器选中该库（默认「不限知识库」）→ 问一个答案就在文档里的问题 → 引用卡片先于正文出现、正文含 `[1][2]` 内联引用号；再问一个无关问题 → 明确告知知识库无相关内容（`rag_hit=false` 降级横幅）。
- **Mock 可演示性**：✅ Mock 的抽取式生成基于命中切片拼装回答，引用可溯源。

#### 3. 代码解析辅导

- **实现落点**：`/code` 页；`POST /code/analyze`（请求 `{language, source}`，响应 `{static_report, ai_report, analysis_id, reused}`）。评改意图（`review_my_code`），豁免防抄袭档位（ADR-0005）。
- **演示路径**：粘贴一段含未用变量 / 嵌套过深的代码（或点「填入示例」）→「开始解析」→ 先看「静态报告」（AST 结构指标，不依赖大模型），再看 AI 报告（讲解与改进建议）；同码再次提交 → 出现「与上次分析相同，已复用历史结果」（`reused=true`，按用户命中）。
- **Mock 可演示性**：✅ 静态报告恒为客观结果；AI 报告 Mock 下为固定口径文案。

#### 4. 在线编辑器运行调试

- **实现落点**：`/editor` 页（Monaco 编辑器）；`POST /code/run`（5s 墙钟超时、并发上限 2）、代码会话 CRUD（`/code/sessions`）、`GET /code/runs`。本系统只提供运行与输出观测，不提供断点调试。
- **演示路径**：「填入示例」→「运行」→ 看 stdout、耗时与 `limit_detail`（各限制层实测数据）；把示例改成 `while True: pass` → 墙钟超时截断；演示 `input()` + stdin 供给；「保存会话」→ 代码会话留存于历史。「运行」的安全边界见下文「受限代码执行器」声明（必读）。
- **Mock 可演示性**：✅ 执行链路完全不经过大模型，四层受限执行器全真。

#### 5. 习题练习与 AI 习题辅导

- **实现落点**：`/exercises` 页；`GET /exercises`（支持题型 / 难度 / 知识点标签筛选）、`GET /exercises/{id}`、`POST /exercises/{id}/submit`、`POST /exercises/{id}/hint`（SSE；`intent` 由按钮显式传入，二取一）。
- **演示路径**：筛选后作答 →「提交判分」→ 自动判分（choice / blank 规则比对，multi 按全对 / 漏选 / 错选计分，coding 经真执行器跑用例并留 `judge_detail` 逐用例详情，short 走 AI 参考评分——Mock 下标识为「AI 参考评分（Mock 启发式）」、降级可见）与正确答案、解析揭示，答错自动归集错题本；点「获取思路」= 求答案意图（`seek_answer`），受当前档位约束；在作答区写出内容后点「批改我的作答」= 评改意图（`review_my_code`），豁免档位（无作答时按钮给出提示）。
- **Mock 可演示性**：✅ 规则判分与编程题执行不依赖大模型；short 题在 Mock 下走确定性启发式（不发起 LLM 调用）；hint 走 Mock 流，引用与降级语义与答疑链路同源。

### 管理端

#### 6. 用户管理

- **实现落点**：`/admin/users` 页；`GET/POST/PATCH/DELETE /admin/users`。
- **演示路径**：管理员登录 →「用户管理」→ 新建学生用户（注册默认学生角色）→ 该用户可登录 → 编辑为「停用」（软删除，日常路径：数据保留，登录与旧 token 立即 4030）→ 编辑重置密码 → 硬删除：级联清七类数据（会话 → 消息 → 提交 → 错题条目 → 代码会话 → 代码分析 → 代码运行），审计日志一律保留、级联计数写进审计 detail。自停用 / 自降权 / 自删一律 4220，末位活跃管理员受保护。
- **Mock 可演示性**：✅ 全链路不经过大模型。

#### 7. 知识库管理

- **实现落点**：`/admin/knowledge` 页；`/admin/knowledge/*` 共 10 端点（知识库 CRUD、文档 multipart 上传 / 列表、文档重建 / 删除、切片读取、`rebuild-vector`、`gc-orphan-vectors`）。
- **演示路径**：新建知识库（可选填课程代码作为检索作用域）→ 拖拽上传 MD / PDF / DOCX / TXT → 索引进度条（`x / y 切片`）到「就绪」→ 删除文档 →「重建向量」→「清理孤儿向量」（返回扫描 / 清理计数，spec §8.6）。**切片内容核对**：端点 `GET /admin/knowledge/documents/{id}/chunks` 存在但**无页面入口**，以接口（curl 黑盒）演示。
- **Mock 可演示性**：✅ 索引链路（解析 / 切分 / 向量化写入）全真；语义精度取决于嵌入模型级别（见功能点 2 总结论）。

#### 8. 模型参数配置

- **实现落点**：`/admin/model-config` 页；`GET/PUT /admin/model-config`、`POST /admin/model-config/test`、`PUT /admin/model-config/embedding`、`GET /admin/model-config/embedding-consistency`。
- **演示路径**：切换防抄袭档位（严格：只给思路与伪代码 / 引导：默认，允许 ≤10 行片段 / 宽松：允许完整实现、需讲解）→「保存配置」→ revision 自增、热生效无需重启（spec §4.2 硬约束 4）→「测试连接」返回 `{ok, latency_ms, sample}`（只测已保存配置）。**embedding 切换的 409 重建流程与一致性检查无页面入口**（页面该区域为只读回显）：`PUT /admin/model-config/embedding` 未确认且已有切片 → `409 + need_rebuild`，确认后同步全量重建、任一库失败整体回滚配置（spec §8.7）——该链路在清理批次真服务冒烟中已黑盒实测。
- **Mock 可演示性**：✅

#### 9. 系统日志

- **实现落点**：`/admin/logs`、`/admin/overview`、`/admin/anti-plagiarism` 三页；`GET /admin/logs`、`GET /admin/overview`、`GET /admin/anti-plagiarism/stats`。
- **演示路径**：先做一批学生端操作 → 日志页按 action / 用户 / 时间段过滤审计留痕（仅可查询、不可修改或删除）→ 仪表盘看用户 / 会话 / 知识库 / 习题等聚合计数与嵌入模型就绪快照 → 防抄袭统计看各档位拦截率（页面已注明：拦截率是度量口径，不是抄袭检出能力）。
- **Mock 可演示性**：✅

### 功能增强

#### 10. 防抄袭约束提示词

- **实现落点**：提示词装配器（PromptAssembler）组合三档模板与检索上下文（spec §7.1 / §7.2）；防抄袭底线硬编码进模板、后台配置无法绕过；生效于答疑对话与习题辅导两条链路，档位配置见功能点 8，效果度量见功能点 9。
- **演示路径**：管理端切 `strict` → 学生端问「直接把作业完整答案给我」→ 只给思路与伪代码、不产出可抄实现 → 提出越过底线的要求 → 底线拦截（`Message.blocked_by_policy` 落库、统计页拦截率 +1）→ 切 `loose` 对比输出形态 → 演示豁免通道：习题「批改我的作答」（`review_my_code`）不受档位约束。意图判定为入口按钮显式声明，非模型语义推断（ADR-0005）。
- **Mock 可演示性**：✅ 约束形态可见；注意 Mock 文案固定，**Mock 输出形态 ≠ 真实模型遵循度**。

#### 11. RAG 知识库检索

- **实现落点**：检索链三级纪律：相关度阈值（默认 0.35）→ 相对截断（与最佳命中分差 > 0.15 即丢弃，ADR-0009）→ 多样性截取（单文档最多 3 切片）；入口 `/knowledge` 页与 `GET /knowledge/search`，答疑链路内部复用同一检索。
- **演示路径**：`/knowledge` 输入同一查询词 → 看命中分数排序与「知识库命中 / 未命中知识库」标签 → 在模型配置页调 `top_k` / 阈值后重查、对比命中数变化 →（接口级可选）切 HashingEmbed 后看 `degraded=true + fallback_reason=hashing_embed_no_semantics + rag_hit=false`，验证哨兵级降级「保链路、不保语义」的设计承诺。
- **Mock 可演示性**：✅ 相对截断跨嵌入模型可比，正是答辩点（绝对阈值绑定模型，相对分差不绑定）。

#### 12. 错题驱动学习

- **实现落点**：`/mistakes` 页（错题本）；`GET /mistakes`（mastered 三态筛选）、`GET /mistakes/profile`（薄弱知识点实时聚合）、`GET /mistakes/recommendations`、`DELETE /mistakes/{id}/mastered`。
- **演示路径**：故意答错两道习题（自动归集错题条目）→ 错题本页看「薄弱知识点」按标签聚合的错误次数条形图 →「推荐练习」看定向推荐（数量不足时从全部已发布习题中按难度递增补足并标注「随机补足」，防止误读为个性化推荐——习题无课程维度，见 spec §8.5 P5 补记）→ 同一题连对 2 次条目转「已掌握」→ 点「重置掌握度」重新开启一轮（错误次数与上次错误记录保留）。
- **Mock 可演示性**：✅ 完全不依赖大模型。

## 演示机跑法（答辩环境）

```bash
# 一次性安装（跳过约 1GB torch；答辩机需要真实语义检索则改用 make install，
# 或装后补执行 make setup-local-embed）
make install-lite
cd backend && cp .env.example .env   # 演示机也必须换 JWT_SECRET

# 首次数据：默认管理员 + 模型配置 + 40 道习题（幂等，可安全重跑）
make seed

# 演示前预热：起服务后先轮询 /health，等 embedder.ready 为 true 再开始演示
# （本地模型首次加载实测约 13–20 秒；未就绪期间检索返回 5032，前端有提示）
make serve
# 另开终端：curl -s localhost:8000/health

# 浏览器打开 http://localhost:8000（单端口同源，hash 路由）
```

- **演示动线建议**：管理端先建知识库 / 上传 / 等索引就绪 + 确认防抄袭档位 → 学生端按上文功能点 1–5 顺序走 → 回到管理端日志 / 仪表盘 / 防抄袭统计收尾（留痕闭环是答辩亮点）。
- **负载纪律（必读）**：演示与前端构建期间**不要并行跑 `make test`**；跑测试时单独跑，机器上不叠加其他满载任务。
- **已知 flake**：`tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer` 是全套件唯一真实推满 256MB 内存的用例，全机满载时 CPU 层可能先于内存层触发导致断言失败（状态 `timeout` ≠ `memory_exceeded`）——**隔离复跑即绿**：
  `cd backend && . .venv/bin/activate && python -m pytest tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer`
- **受限网络演示机**：启动前 `export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`——sentence-transformers 加载已缓存模型时默认联网查版本，弱网下会无限等待（P4 批次实测根因；测试链路的 conftest 已内置该约定）。

## 配置说明

### `backend/.env.example` 逐变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | SQLite 连接串（启用 WAL；无迁移框架，见「已知限制」） |
| `JWT_SECRET` | `change-me-in-production` | **必须替换**为随机值（PyJWT 要求 HMAC-SHA256 密钥 ≥32 字节） |
| `JWT_ALGORITHM` | `HS256` | 令牌签名算法 |
| `ACCESS_TOKEN_TTL_MINUTES` | `30` | 访问令牌有效期 |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | 刷新令牌有效期 |
| `APP_SECRET` | （空） | Fernet 主密钥，用于加密后台填写的 API Key（spec §8.8）；留空则使用下方路径的文件，缺失时首次启动自动生成 |
| `APP_SECRET_PATH` | `.secret_key` | Fernet 主密钥文件路径 |

### 其余可环境变量覆盖项（`Settings`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MOCK_TOKEN_DELAY_MS` | `30` | Mock 提供方流式逐字延迟（毫秒），仅作用于 Mock 的流式输出；`0` 不限速 |
| `CHROMA_PERSIST_DIR` | `data/chroma` | 向量库持久化目录（相对 `backend/`） |
| `UPLOAD_DIR` | `data/uploads` | 上传文件落盘目录（相对 `backend/`） |
| `INDEX_CONCURRENCY` | `1` | 知识库索引并发上限 |
| `EXECUTION_CONCURRENCY` | `2` | 代码执行全局并发上限（执行队列上限） |
| `EXECUTION_QUOTA_TIMEOUT_S` | `10` | 拿不到执行位的等待超时；超限返回 `429`，不无限排队 |

### 真实 LLM 接入

提供方选择只走**管理端「模型配置」页**（`.env` 无提供方开关）：`provider` 选
`openai_compat`，填 `base_url` / 模型名 / `api_key` 后保存——选了该提供方但库里无
Key 时保存被拒（`4220`），避免「配置错误」被静默降级伪装成「降级运行」。API Key 经
Fernet **加密落库**，读取接口一律掩码回显：长度 ≤7 位的短密钥整体显示 `****`
（前 3 后 4 会重叠泄露片段），长密钥显示为 `前3****后4`（如 `sk-****abcd`）。
保存即 `revision` 自增、热生效无需重启；「测试连接」只测已保存配置并返回
`{ok, latency_ms, sample}`。无 Key 环境走 Mock 提供方即可全链路演示（见上节）。

### Embedding 三级回退

启动时按 **OpenAI 兼容 Embedding → 本地 sentence-transformers（`paraphrase-multilingual-MiniLM-L12-v2`，需 `make install` 或 `make setup-local-embed` 补装）→ HashingEmbed 哨兵**逐级探活回退；后台更换嵌入配置走独立的 409 重建流程（见功能点 8）。哨兵级降级只保证调用链路可跑通：向量照常写入，但检索结果一律不注入 prompt，响应带 `degraded=true` 与 `fallback_reason` 明示（ADR-0004，spec §9）。

## 管理后台安全边界声明（必读）

管理端点（`/api/v1/admin/*`）具备 JWT 鉴权与 `require_admin` 角色拦截（学生访问
一律 4030），写操作均落审计日志；但本系统是**教学演示项目**，后台边界如实声明如下：

1. **默认口令公开**：见上文「默认管理员」，不修改等于不设防。
2. **无 IP 白名单 / 登录失败锁定**：管理端点不限制来源 IP，密码错误也不触发锁定。
3. **审计日志仅可查询、不可防篡改**：写库即留痕，但删库/改库的人不在此列。
4. **不适用真实生产**：请勿在公网以默认配置部署。

其余运行边界（单 worker 前提、真实提供方未实测等）见「已知限制与边界」。

## 受限代码执行器 —— 安全边界声明（必读）

在线编辑器的「运行」会把学生代码在本机以**受限子进程**方式执行（`POST /code/run`）。
该项能力**不是沙箱**，其安全边界如下（设计依据见 `docs/adr/0003-code-sandbox-resource-limits.md`）：

1. **黑名单只防误触，不防攻击。** 内置黑名单（`os.system`、`subprocess`、`socket` 等）用于拦截
   学生无意的危险调用；它**可以被轻易绕过**，例如 `__import__('o'+'s')`、`getattr` 链、
   编码变形等。请勿把它当作安全边界，也不要运行来源不明的代码。
2. **被执行代码以当前操作系统用户身份运行。** 系统不做用户切换、不做容器隔离，
   子进程拥有当前用户在本机上的全部权限。
3. **被执行代码对本机文件系统有读权限。** 写入有 1MB 上限（`RLIMIT_FSIZE`），读取不受限 ——
   当前用户能读的文件，被执行代码都能读。
4. **网络访问未隔离。** 当前执行器不限制子进程的网络访问（规划边界外，见 spec §3.3）。

已有的保护是**资源层**而非安全层，用于防失控而非防恶意：墙钟 5s、CPU 3s、内存 256MB
（psutil 采样进程树 RSS，macOS 下不可用 `RLIMIT_AS/DATA/RSS`，见 ADR-0003）、单流输出截断 8KB、
并发上限 2。执行结束后在 `CodeRun.limit_detail` 留存各层实测数据。

## 已知限制与边界（答辩口径）

1. **单 worker 前提**：流取消标志、执行并发信号量、嵌入模型运行时均为进程内状态，
   uvicorn 必须以 `--workers 1` 运行（ADR-0002）；`make serve` / `make dev` 已固定。
2. **真实 OpenAI 兼容提供方全链路未实测**：开发环境无 API Key，提供方与降级链经
   代码实现和 Mock 端到端验证；持 Key 的答辩机建议演示前先跑一次「测试连接」。
   同理，防抄袭约束在 Mock 下的可见性有限——**Mock 输出形态 ≠ 真实模型遵循度**。
3. **混合检索（关键词 + 向量）未排期**：现为纯向量检索 + 相对截断（ADR-0009）；
   是否补关键词通道，待以实测检索质量评估后决定。
4. **后台无 IP 白名单 / 登录失败锁定**：见「管理后台安全边界声明」，不重复展开。
5. **受限执行器非沙箱**：见「受限代码执行器 —— 安全边界声明」，不重复展开。
6. **无数据库迁移框架**：schema 变更即删库重建 + 重新 `make seed`（ADR-0006），
   演示数据均可由 seed 再生。
7. **前端处于双设计系统共存期**（ADR-0011）：全部页面与登录页已迁到自建 `src/ui/`
   适配层 + Tailwind v4，模板层已无 `el-*` 组件；但 Element Plus 仍在适配层内部
   （Select/Dialog/DatePicker 等）与 `v-loading` 指令中服役，完整退场待后续批次
   （ADR-0012）。应用外壳 chunk 因其引用 el-* 而偏大，`manualChunks` 优化随
   shadcn-vue 正式接入一并处理。

## 文档

| 文档 | 说明 |
|---|---|
| `AGENT.md` | AI 编码助手工作约束（强制） |
| `CONTEXT.md` | 术语表（Ubiquitous Language，唯一术语来源） |
| `docs/adr/` | 架构决策记录 0001–0012（含 0011 前端技术栈、0012 Tailwind 共存与视觉回归） |
| `docs/superpowers/specs/` | 设计 spec |
| `docs/superpowers/plans/` | 各批次实施计划 |
| `docs/review/` | 各批次完成报告与评审 |
| `frontend/docs/ui-baseline.md` | 前端 UI 基线 v2（色彩 / 字阶 / 阴影 / 动效 / 外壳 / 适配层，强制） |

## 技术栈

Python 3.12 · FastAPI · SQLAlchemy 2 (async) · SQLite (aiosqlite) · Chroma · pytest ·
Vue 3 · TypeScript · Vite · Tailwind CSS v4 · shadcn-vue（deferred）· Element Plus（共存期，逐步退场）· Monaco Editor · vitest · Playwright（视觉回归截图基线）
