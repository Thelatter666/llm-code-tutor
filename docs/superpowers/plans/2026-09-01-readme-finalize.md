# README + 收尾批次实施计划（强档 · 纯文档批次 · 项目最后一批）

- 日期：2026-09-01
- 分支：`feat/readme-finalize`（自 main @ f3a8686 切出）
- 基线（第三任总指挥独立复跑验收）：`make lint` 0 errors；后端 pytest **1006 passed / 2 skipped**；前端 vitest / vue-tsc / vite build 三件套绿；统一信封、H-3 清零
- 授权：AGENT.md 授权例外表登记本批（Task 完成且门槛通过后按 Task 粒度 commit；**merge / push / remote 不在授权内**）
- 红线：不改任何业务代码（含前端文案）；不新增 spec 回写；不重写已有章节的正确内容，只做整合与补全。最终 `git diff main..HEAD` 只允许含：`README.md`、本计划、`docs/review/2026-09-01-readme-completion-report.md`、`AGENT.md`

---

## 0. 目标与验收总口径（五大块）

| # | 块 | 验收口径 |
|---|---|---|
| 1 | 功能点 → 演示路径映射表（答辩口径核心） | spec §11 的 12 个功能点（学生端 5 + 管理端 4 + 功能增强 3）逐一行：实现落点（端点 + 页面）+ 演示路径（登录 → 点哪 → 看什么）+ Mock 可演示性标注；每个端点在 routers 装饰器实测存在（§1.2 核对表）、每个页面路径在 `frontend/src/router/index.ts` 实测存在（§1.3） |
| 2 | 演示机跑法 | `make install-lite` → `make seed`（40 题）→ `make serve` 完整流程；H-1 负载纪律（勿满载并行跑测试）；预热 13–20s 建议；`test_memory_hog` flake 说明与隔离复跑命令；受限网络 `HF_HUB_OFFLINE=1` 提示 |
| 3 | 配置说明 | `.env.example` 7 项逐变量表；`Settings` 其余 env 项简表（含 `MOCK_TOKEN_DELAY_MS`）；真实 LLM 接入口径（后台模型配置页填 Key、Fernet 加密落库、掩码回显、`/test` 验证、热生效）；Embedding 三级回退一句话；`LLM_PROVIDER` 死配置已删（不写） |
| 4 | 已知限制与边界（答辩口径） | 5 条核心：单 worker（ADR-0002）/ 真实 OpenAI 全链路未实测 / 混合检索未排期 / 后台无 IP 白名单与失败锁定（引用已声明）/ 执行器非沙箱（引用已声明）；第 6 条「无迁移框架」（ADR-0006）为可选项，总指挥认为超范围则删 |
| 5 | L-2 掩码说明收口 | README 补 api_key 掩码规则：长度 <8（即 ≤7 位）整体 `****`，否则前 3 + `****` + 后 4（实测 `crypto.py:29-36`） |

**文档批次无「待总指挥裁定」契约项**；拿不准的表述以 spec 为准、照实写。

---

## 1. 现状勘察结论（计划的事实基础，全部实测/实读）

### 1.1 README 已有内容盘点（80 行，勿重复）

| 章节 | 状态 |
|---|---|
| 标题 + 一句话简介 | 保留，不动 |
| 快速开始（install-lite / dev / serve / test） | 保留，正文加一行指向「演示机跑法」新章节 |
| 默认管理员与首次登录（admin / Admin@12345 + 立即改密 + seed 幂等 40 题） | 保留，不动 |
| 管理后台安全边界声明（4 条） | 保留，末尾加一句指向「已知限制与边界」 |
| 受限代码执行器安全边界声明（4 条 + 资源层保护 + ADR-0003 链接） | 保留，不动 |
| 文档索引表 | 保留，补链本批计划与完成报告 |
| 技术栈 | 保留，不动 |

现状禁词实测：`rg -c "题目|试题|草稿" README.md` = **0 命中**（本批交付后须维持 0）。

### 1.2 端点实况核对表（main.py 11 个 router + health；对 spec §6.2 逐装饰器实测）

| 前缀 | 装饰器实测（backend/app/routers/） |
|---|---|
| `/api/v1/auth` | register / login / refresh / me / logout（5） |
| `/api/v1/chat` | POST conversations、GET conversations、GET {id}/messages、DELETE {id}、POST {id}/messages（SSE）、POST {id}/stop（6） |
| `/api/v1/knowledge` | GET bases、GET search（2） |
| `/api/v1/code` | POST analyze、POST run、GET runs、GET/POST sessions、PATCH/DELETE sessions/{id}（7；路径参数名 `draft_id` 属标识符层，CONTEXT 判定代码标识符合规，README 不出现） |
| `/api/v1/exercises` | GET 列表、GET {id}、POST {id}/submit、POST {id}/hint（SSE）（4） |
| `/api/v1/mistakes` | GET 列表、GET profile、GET recommendations、DELETE {id}/mastered（4） |
| `/api/v1/admin/knowledge` | bases POST/PATCH/DELETE、documents POST/GET、documents/{id}/reindex、documents/{id} DELETE、documents/{id}/chunks、rebuild-vector、gc-orphan-vectors（10） |
| `/api/v1/admin/exercises` | POST/GET/GET{id}/PATCH/DELETE（5） |
| `/api/v1/admin/users` | GET/POST/PATCH/DELETE（4） |
| `/api/v1/admin`（model-config） | GET/PUT model-config、POST model-config/test、PUT model-config/embedding、GET model-config/embedding-consistency（5） |
| `/api/v1/admin`（stats） | GET logs、GET overview、GET anti-plagiarism/stats（3） |
| 系统 | GET /health（含 embedder 就绪态） |

spec §6.2 全部行（含 P5/P6 补记）与上表一一对应，无缺无多（`/admin/ping` 已在 P6 移除）。映射表引用端点时一律以本表为准。

### 1.3 前端页面实况（router/index.ts + AppShell.vue 导航标签实测）

学生端导航 6 项：`/chat`「AI 答疑对话」、`/code`「代码解析辅导」、`/editor`「在线代码编辑器」、`/knowledge`「知识库检索」、`/exercises`「习题练习」、`/mistakes`「错题本」。
管理端导航 7 项（adminOnly）：`/admin/knowledge`「知识库管理」、`/admin/exercises`「习题管理」、`/admin/users`「用户管理」、`/admin/model-config`「模型配置」、`/admin/logs`「系统日志」、`/admin/overview`「仪表盘」、`/admin/anti-plagiarism`「防抄袭统计」。

演示路径引用的按钮/控件文案（逐处源码实读，不编造）：

- ChatView.vue：「新建会话」「启用知识库增强（RAG）」复选框、知识库选择器（默认「不限知识库」）「发送」「停止生成」
- CodeReviewView.vue：「填入示例」「开始解析」，结果区「静态报告」
- CodeEditorView.vue：「填入示例」「保存会话」「运行」，运行状态映射（accepted→「运行成功」等），安全提示行
- ExerciseView.vue：双意图按钮「获取思路」（seek_answer，受档位约束）/「批改我的作答」（review_my_code，豁免，须先有作答）
- 页面均为 hash 路由（`createWebHashHistory`），`make serve` 同源单端口演示成立

### 1.4 配置面实况

- `.env.example`（10 行）7 项：`DATABASE_URL` / `JWT_SECRET` / `JWT_ALGORITHM` / `ACCESS_TOKEN_TTL_MINUTES` / `REFRESH_TOKEN_TTL_DAYS` / `APP_SECRET`（留空走 `APP_SECRET_PATH` 文件，缺失首启自动生成）/ `APP_SECRET_PATH`。注意 `APP_SECRET` 由 `core/crypto.py:10` 直读 `os.environ`（不经 Settings），表述为「环境变量」即可，不展开。
- `Settings`（core/config.py）其余可 env 覆盖项：`CHROMA_PERSIST_DIR`、`UPLOAD_DIR`、`INDEX_CONCURRENCY`（默认 1）、`MOCK_TOKEN_DELAY_MS`（默认 30，只作用于 Mock stream()）、`EXECUTION_CONCURRENCY`（默认 2）、`EXECUTION_QUOTA_TIMEOUT_S`（默认 10）。
- `HF_HUB_OFFLINE` **不是项目配置项**：huggingface_hub 官方环境变量，conftest 已内置 `=1`（测试离线约定）；受限网络的真服务演示机建议启动前 `export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`——根因见 P4 完成报告备注（sentence-transformers 加载已缓存模型时联网查版本会无限等待）。
- Embedding 三级回退（embedder_runtime.py 头注释实测）：0=OpenAI 兼容 → 1=sentence-transformers 本地（`paraphrase-multilingual-MiniLM-L12-v2`，需 `make install` 或 `make setup-local-embed`，torch 约 1GB）→ 2=HashingEmbed 哨兵（仅链路可跑通，检索结果不注入 prompt，响应带 `degraded=true + fallback_reason=hashing_embed_no_semantics`）。
- 真实 LLM 接入：提供方选择**只走后台模型配置页**（`PUT /admin/model-config`），`provider=openai_compat` 且 api_key 必填（缺 key 保存被 4220 拒）；api_key Fernet 加密落库（spec §8.8），读取掩码回显（L-2 规则见 §0 块 5）；保存即 revision+1 热生效无需重启（spec §4.2 硬约束 4）；`POST /admin/model-config/test` 只测已保存配置。`LLM_PROVIDER` 死配置已在清理批次删除（M-4），README 不出现该字样。

### 1.5 演示机跑法的事实源

- 预热：main.py lifespan 异步预热不阻塞启动（P1 Task 15）；`/health` 暴露 embedder 就绪态；真实本地模型首载实测 **13–20s**（清理批次完成报告 §6 真服务冒烟实测）。
- H-1 负载纪律（health-check-report §2 H-1）：`test_memory_hog_is_killed_by_memory_layer`（tests/test_code_executor.py）是全套件唯一真实推满 256MB 内存的用例，满载并行时 CPU 层先于内存层触发 → 状态变 `timeout` 断言失败；**隔离复跑即绿**（实测 1 passed / 0.90s）。`make test` 内部已串行（pytest → vitest），纪律指「演示/构建期间勿与测试并行」。
- `make seed`：幂等写 admin + ModelConfig + 40 道习题（spec §11 P5 落地实况：choice 10 / multi 6 / blank 8 / short 8 / coding 8，12 个知识点标签每标签 ≥2 题引用）。

---

## 2. README 目标大纲（章节清单与顺序）

1. 标题 + 简介（既有，微调简介句以覆盖 12 功能点措辞，不改语义）
2. 快速开始（既有 + 一行指向 §4）
3. 默认管理员与首次登录（既有，不动）
4. **功能一览与答辩口径**（新）：12 行映射表（§3 草案）
5. **演示机跑法**（新）：一次性安装 → seed → 预热 → serve → 演示顺序；H-1 负载纪律；flake 说明；受限网络提示
6. **配置说明**（新）：.env.example 逐变量表（§5 草案）+ Settings 其余 env 项简表 + 真实 LLM 接入段 + Embedding 三级回退段 + L-2 掩码句
7. 管理后台安全边界声明（既有 + 一句指向 §9）
8. 受限代码执行器安全边界声明（既有，不动）
9. **已知限制与边界（答辩口径）**（新）：§6 草案 5(+1) 条
10. 文档（既有表 + 本批计划/报告两行）
11. 技术栈（既有，不动）

---

## 3. 映射表草案（答辩口径核心；正式表在 Task 2 落入 README）

列：功能点 ｜ 实现落点（端点 · 页面）｜ 演示路径 ｜ Mock 可演示性。演示路径统一前提：`make serve` 后开 `http://localhost:8000`，hash 路由同源。

### 学生端 5

| 功能点 | 实现落点 | 演示路径 | Mock 可演示性 |
|---|---|---|---|
| AI 答疑对话 | `POST/GET /api/v1/chat/conversations`、`POST …/{id}/messages`（SSE）、`POST …/{id}/stop` · `/chat` | 学生登录 → 「新建会话」→ 输入问题「怎么用 Python 写一个冒泡排序」→「发送」→ 看流式逐字输出与引用卡片；再发起一次流中途点「停止生成」→ 看 4990 中断（前端只收尾不报错） | ✅ 流式延迟 `MOCK_TOKEN_DELAY_MS=30` 使逐字可见、「停止」有窗口 |
| RAG 知识库增强 | `GET /knowledge/bases`、`GET /knowledge/search` · `/chat`（RAG 开关）、`/knowledge` | 演示前由管理员建库上传文档（§7 行）→ `/chat` 勾「启用知识库增强（RAG）」选知识库 → 问文档内问题 → citation **先于** token 出现、答案含 `[1][2]` 内联引用号 → 问无关问题 → `rag_hit=false` 降级提示（DegradedBanner） | ✅ Mock 抽取式生成基于命中切片拼装；真实语义需装本地 embed（§5 演示前缀热）否则 hashing 哨兵 + 降级文案可见 |
| 代码解析辅导 | `POST /code/analyze` · `/code` | 粘贴一段含未用变量/嵌套过深的代码（或「填入示例」）→「开始解析」→ 静态报告（AST 指标，不依赖大模型）+ AI 报告；同码再提交 → `reused=true`（命中历史复用） | ✅ 静态报告恒真；AI 报告 Mock 给固定口径讲解（演示时说明真实模型下为个性化讲解） |
| 在线编辑器运行调试 | `POST /code/run`、`GET/POST/PATCH/DELETE /code/sessions`、`GET /code/runs` · `/editor` | 「填入示例」→「运行」→ 看 stdout/耗时/`limit_detail` 六层实测；改例：`while True: pass` → 墙钟 5s 超时截断；`input()` 代码 + stdin 输入 → 看 stdin 供给；「保存会话」→ 侧栏代码会话留存 | ✅ 运行链路不经 LLM，四层受限执行器全真 |
| 习题练习与 AI 习题辅导 | `GET /exercises`、`GET /exercises/{id}`、`POST …/submit`、`POST …/hint`（SSE）· `/exercises` | 筛选（题型/难度/知识点标签）→ 作答 →「提交」→ 看判分四路与正确答案揭示 →「获取思路」= seek_answer 受当前档位约束；写一段作答后「批改我的作答」= review_my_code 豁免档位 | ✅ 判分（choice/multi/blank 规则判、coding 真执行器跑用例）不依赖 LLM；hint 走 Mock 流 |

### 管理端 4

| 功能点 | 实现落点 | 演示路径 | Mock 可演示性 |
|---|---|---|---|
| 用户管理 | `GET/POST/PATCH/DELETE /admin/users` · `/admin/users` | admin 登录 → 建学生账号 → 该账号登录成功 → 停用（软删除）→ 旧 token 立即 4030 → 重置密码 → 硬删除 → 级联清单入审计 detail | ✅ 全链路不经 LLM |
| 知识库管理 | `/admin/knowledge/*` 10 端点 · `/admin/knowledge` | 建知识库（可填课程代码）→ 上传 MD/PDF（拖拽区）→ 索引进度条至就绪（含 `x / y 切片` 计数）→「重建向量」→「清理孤儿向量」（返回扫描/清理计数） | ✅（真实语义检索同上需本地 embed） |
| 模型参数配置 | `GET/PUT /admin/model-config`、`POST …/test`、`PUT …/embedding`、`GET …/embedding-consistency` · `/admin/model-config` | 切防抄袭档位 →「保存配置」→ `revision+1` 即时生效 →「测试连接」→ `{ok, latency_ms, sample}`。**如实声明**：embedding 配置在页面为只读回显，切换走 `PUT /admin/model-config/embedding` 端点（未确认 409 + need_rebuild → confirm 同步全量重建，失败回滚配置），**无页面表单、答辩以 curl 黑盒演示**（清理批次真服务冒烟已实测该链路） | ✅ |
| 系统日志 | `GET /admin/logs`、`GET /admin/overview`、`GET /admin/anti-plagiarism/stats` · `/admin/logs`、`/admin/overview`、`/admin/anti-plagiarism` | 做完学生端操作后 → 日志页按 action/用户/时间过滤看审计留痕 → 仪表盘看全量计数 → 防抄袭统计看各档位拦截率（页面已注明「度量口径，非检出能力」） | ✅ |

### 功能增强 3

| 功能点 | 实现落点 | 演示路径 | Mock 可演示性 |
|---|---|---|---|
| 防抄袭约束提示词 | PromptAssembler + 三档模板（spec §7.1，底线硬编码 §7.1/Floor）· 生效于 `/chat` 与 `/exercises` hint，配置在 `/admin/model-config`，度量在 `/admin/anti-plagiarism` | 后台切 `strict` → 学生端问「直接把作业答案给我」→ 只给思路不给可抄实现；问越界要求 → 底线拦截（`blocked_by_policy` 落库、统计页可见）；切 `loose` 对比输出形态；同页演示豁免：习题「批改我的作答」不受档位约束 | ✅ 约束塑形在 Mock 输出形态可见（演示时说明 Mock 文案固定、真实模型差异更大） |
| RAG 知识库检索 | 检索链路：ScoreThreshold（默认 0.35）/ 相对截断（分差 >0.15）/ 多样性截取（单文档 ≤3 切片）（spec §7.2、ADR-0009）· `/knowledge` 页（命中态标签「知识库命中/未命中知识库」实测）、`GET /knowledge/search` | `/knowledge` 同一查询词对比阈值/top_k 调整前后的命中数与分数排序（阈值在模型配置页可调可演示）；切 hashing 哨兵后演示 `degraded=true + rag_hit=false`（切换走 embedding 端点，见模型配置行的 curl 口径） | ✅ 相对截断跨 embedding 可比，正是答辩点 |
| 错题驱动学习 | `GET /mistakes`、`GET /mistakes/profile`、`GET /mistakes/recommendations`、`DELETE /mistakes/{id}/mastered` · `/mistakes` | 故意答错两道题 → 错题本出现条目 →「薄弱知识点」画像按标签聚合 →「定向推荐」出题（数量不足时看 `filled_by=random` 标注）→ 连对 2 次条目转已掌握 → 演示「重置」重新开启一轮 | ✅ |

Mock 可演示性总结论（写进表前一句）：**12 个功能点全部无 Key 可演示**；两处口径需答辩时口头声明——AI 文本质量（答疑/讲解/辅导在 Mock 下为抽取式或固定文案）与 RAG 语义精度（`install-lite` 未补装 embed 时为 hashing 哨兵，降级文案可见即设计承诺）。

---

## 4. 演示机跑法草案（正式段落 Task 2 落）

```bash
# 一次性安装（跳过约 1GB torch；答辩机要真实语义检索则先 make install 或装后 make setup-local-embed）
make install-lite
cd backend && cp .env.example .env   # 演示机也要换 JWT_SECRET

# 首次数据：admin + ModelConfig + 40 道习题（幂等，可重跑）
make seed

# 预热：起服务后先等 /health 的 embedder 就绪（本地模型首载实测 13–20s），再开始演示
make serve
# 另开终端：curl -s localhost:8000/health   # 就绪后再开浏览器（/health 无 /api/v1 前缀）

# 浏览器打开 http://localhost:8000（单端口同源），按 §3 映射表顺序演示
```

纪律与说明：

1. **H-1 负载纪律**：演示与前端构建期间**不要并行跑 `make test`**（内存用例负载敏感，见下）；跑测试时单独跑、机器上不叠加其他满载任务。
2. 已知 flake：`tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer` 在全机满载时可能因 CPU 层先于内存层触发而失败（状态 `timeout` ≠ `memory_exceeded`）——**隔离复跑即绿**：`cd backend && . .venv/bin/activate && python -m pytest tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer`。
3. 受限网络演示机：启动前 `export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`（sentence-transformers 加载已缓存模型时默认联网查版本，弱网下会无限等待；P4 实测根因）。
4. 演示动线建议（一句话）：管理端先建知识库/上传/索引 + 确认档位 → 学生端按映射表顺序走 → 回管理端日志/仪表盘/统计页收尾（留痕闭环是答辩亮点）。

---

## 5. 配置说明草案（正式表 Task 2 落）

表 A（`.env.example` 逐变量）：`DATABASE_URL`（SQLite+aiosqlite 连接串，WAL）、`JWT_SECRET`（**必须改**，PyJWT 要求 ≥32 字节）、`JWT_ALGORITHM`（HS256）、`ACCESS_TOKEN_TTL_MINUTES`（30）、`REFRESH_TOKEN_TTL_DAYS`（7）、`APP_SECRET`（Fernet 主密钥，用于加密后台填写的 API Key；留空则用 `APP_SECRET_PATH` 文件、缺失首启自动生成）、`APP_SECRET_PATH`（`.secret_key`）。

表 B（其余可 env 覆盖的 Settings，简表）：`MOCK_TOKEN_DELAY_MS`（默认 30，仅 Mock stream 逐字节奏）、`CHROMA_PERSIST_DIR`、`UPLOAD_DIR`、`INDEX_CONCURRENCY`（1）、`EXECUTION_CONCURRENCY`（2）、`EXECUTION_QUOTA_TIMEOUT_S`（10）。超限返回 429、不无限排队（CONTEXT「执行队列上限」）。

真实 LLM 接入段（三句）：有 Key 时在**后台模型配置页**填 `base_url`/`api_key`/模型名并切 `provider=openai_compat`（Key **不走 .env**，`LLM_PROVIDER` 配置项已移除）；api_key Fernet 加密落库，读取一律掩码回显——**掩码规则（L-2 收口）**：长度 ≤7 位整体显示 `****`（短密钥前 3 后 4 会重叠泄露），长密钥 `前3****后4`（如 `sk-****abcd`）；保存后「测试连接」只测已保存配置，revision 自增热生效。

Embedding 三级回退一句话：启动时按 OpenAI 兼容 Embedding → 本地 sentence-transformers（MiniLM，需装 local-embed extras）→ HashingEmbed 哨兵逐级探活回退，哨兵级降级只保链路、检索结果不注入 prompt（ADR-0004）。

---

## 6. 已知限制与边界草案（答辩口径；引用不复述）

1. **单 worker 前提**：取消标志、执行并发信号量、EmbedderRuntime 均为进程内状态，uvicorn 必须 `--workers 1`（ADR-0002，`make serve`/`make dev` 已固定）。
2. **真实 OpenAI 兼容提供方全链路未实测**：代码路径与降级链已实现（含 `/admin/model-config/test`），但本环境无 API Key，端到端以 Mock 验证；持 Key 的答辩机建议演示前跑一次 test。
3. **混合检索（关键词+向量）未排期**：当前为纯向量 + 相对截断（ADR-0009）；是否补 BM25 待 P6 后以实测检索质量评估。
4. 后台无 IP 白名单 / 无登录失败锁定——见「管理后台安全边界声明」（已声明，不重复展开）。
5. 受限执行器非沙箱——见「受限代码执行器安全边界声明」（已声明，不重复展开）。
6. （可选）无数据库迁移框架：schema 变更 = 删库重建 + 重新 seed（ADR-0006）。

---

## 7. 术语与格式纪律

- 禁词 grep 门槛：交付后 `rg "题目|试题|草稿" README.md` = 0 命中。本批 README 正文**不需要**出现「草稿」作为禁词说明（区别于清理批次的 CONTEXT 场景），若答辩口径段需引用 UI 文案也只引用实读到的合规文案（「保存会话」等）。
- 全部用 CONTEXT.md 正式术语：习题/题库、错题本/错题条目、代码会话、知识库、切片（预览语境）、引用（Citation 语境）、会话（答疑对话容器）、模型配置、审计日志、防抄袭档位/底线、降级、哨兵级降级、相对截断、多样性截取、估算用量、随机补足、API Key 掩码。功能名与实体名不混用（「错题本」是功能名）。
- UI 导航标签按 §1.3 实测写法（「AI 答疑对话」「代码解析辅导」…），「在线编辑器」在导航中实为「在线代码编辑器」，行文用后者。
- 中文全角标点；代码块/表格与既有风格一致；文档链接只指向实存文件：`CONTEXT.md`、`AGENT.md`、`docs/adr/0002|0003|0004|0005|0006|0009`、`docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md`、`frontend/docs/ui-baseline.md`、本计划与完成报告。
- 不编造端点/页面：映射表逐格对照 §1.2 / §1.3 实测表。

## 8. 验证方案（交付门槛）

| # | 验证 | 命令/方法 | 通过口径 |
|---|---|---|---|
| V1 | 术语 grep | `rg -n "题目\|试题\|草稿" README.md` | 0 命中 |
| V2 | 链接核验 | python 脚本提取 README 中反引号相对路径与 markdown 链接，`os.path.exists` 逐一检查（排除示例命令与 URL） | 全部存在；清单进完成报告 |
| V3 | 端点/页面核对 | 映射表内每个端点字符串在 §1.2 实测表内、每个 `/xxx` 页面在 router/index.ts 内（脚本 diff 表列进完成报告） | 零编造 |
| V4 | 术语一致性 | README 与 CONTEXT.md 逐条人工比对（消歧列重点：会话/对话、习题、代码会话、错题本） | 零违禁、零自造 |
| V5 | 交付态基线 | 单独串行跑：`make lint`；backend `python -m pytest -q`（预期 1006/2，若 memory_hog 偶红按隔离复跑口径复核）；frontend `npm test` + `npx vue-tsc --noEmit` + `npm run build` | 与 f3a8686 验收基线一致 |
| V6 | 改动面 | `git diff --stat main..HEAD` | 只含 4 个许可文件 |

V5 只在最终交付 commit 前跑一次（文档批次性质，README 不触碰代码，此步为最终状态确认）。

## 9. 提交计划（Task 粒度，已获预授权；merge 不在授权内）

| Task | 内容 | commit |
|---|---|---|
| T1（阶段一） | 本计划落盘 + AGENT.md 授权行登记 | `docs: README+收尾批次实施计划与授权登记` |
| T2 | README 五大块撰写 + V1/V3/V4 自查 | `docs(readme): 功能映射表/演示跑法/配置说明/已知限制/掩码收口五大块补全` |
| T3 | V2/V5/V6 门槛全跑 + 完成报告 `docs/review/2026-09-01-readme-completion-report.md`（五块逐条证据 + grep 输出 + 链接清单 + 未验证项） | `docs: README+收尾批次完成报告（门槛证据与未验证项清单）` |

T3 交付后**停下等总指挥审阅**——本批为项目最后一批，审阅通过后进入整体收尾（用户推 GitHub）。

## 10. 风险与开放问题

1. 「预热 13–20s」仅清理批次真服务冒烟一个数据源 → 行文写「实测约 13–20s」，不写死承诺。
2. 映射表篇幅大：README 单表 12 行 + 4 列表格单元格文字需压缩（每格 ≤2 短句），细节指向 spec 章节号，避免 README 膨胀成 spec 复读。
3. 「防抄袭约束在 Mock 下可见性」是答辩最易被追问点：完成报告未验证项如实列「Mock 输出形态 ≠ 真实模型遵循度」。
4. 已知限制第 6 条（ADR-0006）为超题面补充，若总指挥认为超出「5 条核心」范围则在 T2 前删除——默认保留（有 ADR 实据、一句话成本）。
5. **勘察发现的两处「端点存在、页面未消费」缺口（README 如实声明，不改代码）**：① 切片预览 `GET /admin/knowledge/documents/{id}/chunks`——api 客户端已定义 `listChunks` 但全前端零调用，无页面入口；② embedding 切换 409 流程（`PUT /admin/model-config/embedding`）与一致性检查（`GET …/embedding-consistency`）——页面只读回显，无表单入口（模型配置页提示语称「在知识库管理页走重建流程」，该页实际只有 per-KB「重建向量」按钮）。演示口径统一写「端点级可测（黑盒 curl），无页面入口」，完成报告将其列为已知边界（答辩若被问起，这是可接受的接口优先架构残留，属排期外而非缺陷）。
