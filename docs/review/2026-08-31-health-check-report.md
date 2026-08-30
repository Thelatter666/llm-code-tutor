# P0–P4 全面健康检查报告（独立只读审计）

- 审计日期：2026-08-31
- 审计对象：main @ 9b5187f（P0–P4 全部合入后的现状）
- 审计方式：只读 + 独立复现。除本报告外未创建/修改/删除任何仓库文件；变异测试均为「改坏 → 跑测试 → 字节级还原 → `git status` 验证干净」的方式执行，结束后工作区确认为 clean。
- 环境备注：全量测试与真服务实测均在 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 下进行（P4 已实测受限网络会无限等待）。

---

## 1. 总体健康度：**基本健康**

三句话理由：功能契约与 spec 的一致性、四项编码纪律 grep 专项、安全边界的声明与实测（JWT / 黑名单 / 读权限 / CORS / XSS 消毒）全部经得起独立复现，质量高于同级演示项目；但存在 1 个负载敏感的失败用例使「659 passed」基线不可在任意负载下无条件复现、1 条 spec §9 降级承诺（Chroma 不可用 → 5032）实测不可达、以及 4 处服务层直连适配器的分层违规。以上均无阻塞 P5 开工的返工级缺陷，遗留项绝大多数有明确裁定与归属。

---

## 2. 发现清单

分级：阻塞（P5 开工前必须修）/ 高 / 中 / 低。每条附证据。

### 阻塞级

无。没有发现会阻断 P5 开工或造成既有功能错误结果的缺陷。

### 高

**H-1 全量测试存在负载敏感的失败用例，「659 passed」基线不可无条件复现。**
首次 `make test`（与前端 vue-tsc/vite build 并行跑在同一机器上）实测：
`FAILED tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer`，
`AssertionError: assert 'timeout' == 'memory_exceeded'`，1 failed / 658 passed / 2 skipped（132s）。
隔离复跑同一条用例：**1 passed（0.90s）**。机理：该用例是全套件唯一用真实 256MB 阈值推满内存的用例
（`tests/test_code_executor.py:3-20` 注释自述其唯一性）；机器高负载时子进程的 CPU 秒先于 RSS 攀到
256MB 耗尽，CPU 层（SIGXCPU, exit -24）先杀，状态变 `timeout`，断言即失败。
无并行负载的干净复跑中 pytest 步骤通过（链条走到前端 vitest，详见 §8），且报告交付前的独立全量复跑实测 **659 passed / 2 skipped（120.03s）**，与声称基线一致——即基线本身成立，问题只在负载敏感的 flake。
建议：给该用例标注负载敏感性并在 CI/演示机上避免满载跑测试；不建议放宽断言——它守的正是「内存层先于 CPU 层触发」这个真实承诺。

**H-2 spec §9「Chroma 不可用 → 知识库功能降级（5032）」在代码里不可达，实测返回 5000。**
全仓 5032 的抛出点只有三处：模型未就绪（`embedder_runtime.py:80`）、向量化服务全链失败（`embedder_runtime.py:117`）、KB reindexing（`retrieval_service.py:171`，仅限显式传 `kb_ids` 时）。没有任何路径把 Chroma 客户端/查询异常转换为 5032。
实测（真服务，把 Chroma 持久目录换成普通文件使客户端初始化失败）：
`GET /api/v1/knowledge/search?query=test` → `{"code":5000,"message":"服务器内部错误"}`。
spec §9 同一行还承诺「其余模块不受影响」，按此实现带 RAG 的聊天在 Chroma 宕机时同样会以 5000/流错误收场（该点未实测，见 §8）。
建议：在检索入口把 VectorStore 异常收敛为 5032（约一个 try/except + 两条测试的改动量）。

**H-3 服务层 4 处直接 import 具体适配器，违反 spec §4.2 硬约束 2「services 只依赖 Protocol」。**
AST 全仓 import 分析命中：
- `app/services/indexing_service.py:30` import `app.infrastructure.adapters.document.parsers`，`:136` 直接调用 `parse_document(...)` —— `DocumentParser` 端口（`ports/document.py`）已定义却未注入使用，端口沦为测试摆设；
- `app/services/model_config_service.py:15,16,19` import 三个 embedding 适配器（`HashingEmbed` / `DEFAULT_OPENAI_EMBED_MODEL` / `DEFAULT_LOCAL_EMBED_MODEL`），`:223`、`:315` 直接引用 `HashingEmbed.model` 类属性。
domain / routers / ports / schemas 四层扫描 clean（同一脚本）。
建议：indexing 走 `DocumentParser` 端口注入；两个默认模型常量上移到 `registry` 或端口层，`HashingEmbed.model` 的哨兵判定改由 registry 提供。纯重构，现有测试可保护。

**H-4 不传 `kb_ids` 的检索不拦截 `reindexing` 状态的知识库，spec §8.7 步骤 3「期间检索返回 5032」只覆盖了一半。**
`retrieval_service.py:161-177`：仅当显式传 `kb_ids` 时逐个校验状态（`167-171`）；不传时 `174-177` 直接 `select(KnowledgeBase.id)` 把 reindexing 的库一并纳入作用域照常查询。学生端 `GET /knowledge/search` 不带 `kb_ids`、或聊天请求不带 `kb_ids` 时，reindexing 期间的检索不会得到 5032。
P5 的习题辅导复用同一条检索链路（spec §7.2），此缺口会被带进 P5。
建议：`_resolve_scope` 的无 `kb_ids` 分支同样过滤/拒绝非 `ready` 状态（按 spec 语义应拒绝而非静默过滤，需用户拍板）。

### 中

**M-1 `make lint` 实测 35 errors（22 处可 `--fix`），分布：** UP017×9、B008×8、I001×6、UP035×4、UP046×2、SIM117/UP045/UP007/PLW1510/S112/F401×1。与 agent-assignment 登记的「34 处」基本一致（+1）。已裁定 P6 之后单开批次清理，现状与裁定相符。

**M-2 全库没有 ForeignKey 约束，`PRAGMA foreign_keys=ON` 形同虚设。**
`db.py:39-44` 确实设置了该 pragma，但 `models.py` 全部关联列（如 `Chunk.kb_id`、`Message.conversation_id`）都是普通 `String` 列——没有任何 `ForeignKey`，唯一约束仅有 `code_analyses` 的 `(user_id, language, source_hash)`（`models.py:196`）与 users 的 username/email。级联正确性完全依赖服务层手工删除（`knowledge_service.py:139-198` 经审计确认顺序正确）。P6 的用户硬删除级联（spec §8.9）也将同样依赖手工序列。是否补 FK 牵连 `create_all` 删库重建（ADR-0006），属架构决策，建议 P6 评估。

**M-3 README 无默认管理员账号与密码警示，照 README 无法完成首次登录。**
`grep -n "Admin@12345|默认密码|管理员" README.md` 0 命中。实测 `admin / Admin@12345` 可正常登录（隔离服务验证）。documents-review M15 要求 README 写明默认密码并提示首次登录后修改，至今未做（README 是 P4 新建的，P6 还会收口一次）。

**M-4 `.env.example` 的 `LLM_PROVIDER` 是死配置。**
`Settings.llm_provider`（`config.py:19`）在 app 内除定义外零引用；`registry.py` 的 `build_llm` 只认 `ModelConfig` 行。照 `.env.example` 改 `LLM_PROVIDER=openai_compat` 不会有任何效果，会误导部署者。建议删除该行或在 Settings 里删字段，或真正接上。

**M-5 术语「草稿」用于 CodeSession 的默认 title 与 UI 文案，与 CONTEXT.md「不使用『草稿』」冲突。**
`models.py:221` 与 `schemas/code.py:60` 默认值 `"未命名草稿"`、`code_service.py:193` 同、`frontend/src/views/student/CodeEditorView.vue:133` 同。代码标识符层全部合规（一律 `CodeSession`），违规只在用户可见字符串与注释。低风险，建议改「未命名会话」。

**M-6 死代码：`ChatService.count_actions`（`chat_service.py:357`）无任何调用方**（app 与 tests 均 0 引用），docstring 自称「仅供测试与统计」但测试也不用它。

**M-7 索引期间 `/health` 出现 p95 ≈ 500ms 毛刺。**
定频采样（100ms 间隔、独立线程、n=90）：中位 2.4ms、P95 498ms、最大 589ms。P1 §5.3 的记录是中位 7.2ms / P95 108ms / max 243ms。中位毫秒级的承诺成立（ADR-0002），毛刺属 GIL 与批量推理调度，量级未失控，记录观察。

**M-8 `get_current_user` 的「用户不存在 → 4010」分支无直接测试。**
`deps.py:34-36` 分支存在；`test_auth_deps.py` 4 条只覆盖无效 token/refresh 语义，「token 有效但用户已删」无用例。「已停用 → 4030」有 API 层覆盖（`test_auth_api.py:140`）。

**M-9 前端除 8 条消毒测试外没有任何其他测试。**
路由守卫（`router/index.ts:44-58` 的 requiresAuth/requiresAdmin/fetchMe 失败分支）、`api/client.ts` 的 401 拦截与错误分支均零测试。这是 spec §10「前端保证类型检查与构建」之外的自设缺口，可在 P5/P6 页面开发时顺带补守卫用例。

### 低

**L-1 `GET /api/v1/admin/ping` 占位端点未列入 spec §6.2**（`main.py:85-88`，P0 占位、注释写明 P6 取代）。
**L-2 `mask_api_key` 对短密钥会泄露全文**：`crypto.py:29-32` 对长度 ≤7 的 key 输出重叠掩码（如 6 位 key → 前 3 后 4 全量暴露）。真实 API Key 足够长，实际风险趋零。
**L-3 favicon 404 仍未修**：`frontend/public/` 不存在、`index.html` 无 favicon 引用（P4 遗留 2 原样开放）。
**L-4 Mock 输出文案用「片段」而非「切片」**（`mock_provider.py:103` 等）——属 AI 输出自然语言，非实体命名，仅记录。

### 查过且干净的维度（列出查了什么）

- **维度 4 编码约定四项全绿**：`request_id=""` 硬编码 0 处；`models.py` 无裸 `DateTime`（全部 `UTCDateTime`）；`ApiError` 抛出的 9 个码（4010×7/4030×2/4040×9/4090×1/4130×1/4150×1/5000×2/5021×5/5032×3）全部在 `CODE_STATUS` 注册表内，4290 由 `concurrency.py:90` 抛出且已注册，4990 只出现在 SSE 载荷不入 HTTP 映射（与 spec §6.1 一致）；bcrypt（`auth_service.py:32,45`）、ast 解析（`code_service.py:117`）、文件 IO（`indexing_service.py:136-137`）、AI/向量推理（`chroma_store.py`、`embedder_runtime.py:105`）全部经 `run_in_threadpool` 卸载；**33 个端点逐一核对全部挂 `CurrentRidDep`**（脚本 AST 核对，非抽查），管理端守卫经 `AdminDep` 全覆盖。
- **维度 6 安全边界声明与实现一致**：`os.system` 黑名单命中 `status=blocked` 且金丝雀文件未产生（无副作用）；`getattr(os,"system")` 链实测绕过并产生文件——与 README「只防误触不防攻击」声明一致（诚实声明，非缺陷）；读 `/etc/passwd` 与仓库内 `AGENT.md` 均 accepted——README 第 3 条「读权限不受限」声明准确；JWT 篡改/过期均 401、学生访问管理端点 4030、跨用户会话读写删均 404 不泄露存在性；CORS 未配置（无 `Access-Control-Allow-Origin` 头、OPTIONS 405）；XSS 对抗实测：对真实 `renderMarkdown`（esbuild 打包原码 + happy-dom DOM 级判定）投喂 17 个载荷（含 mXSS math/mglyph、实体编码 scheme、`data:text/html`、`srcdoc` iframe、`<object>/<embed>`）**全部 DOM 级 clean**；`v-html` 全前端仅 `MarkdownView.vue:13` 一处；`.secret_key` 在 `.gitignore`。
- **维度 8 其余项干净**：知识库删除三步顺序（向量→Chunk→Document/KB）在 `knowledge_service.py:147-154` 逐行确认；Chroma 失败返回 `"failed"` 仍删 DB 并写 `AuditLog(detail.vector_cleanup)`（`:241-256`）；GC 经 `_existing()` 遍历**全部维度分区集合**（`chroma_store.py:143-148`），ADR-0007 多集合情况覆盖；ModelConfig 单例用固定主键（`models.py:19,46`）+ `updated_at onupdate`（`:64`）。
- **维度 9 其余项干净**：7 个路由组件全部 `() => import` 懒加载（构建产物逐视图独立 chunk 印证）；DegradedBanner 覆盖 `fallback_reason` 封闭枚举三值 + 未知原因兜底文案（`DegradedBanner.vue:17-40`），三个使用方（Chat/KnowledgeSearch/CodeReview）；ui-baseline §7 清单可代码核对的项全部通过（CSS 变量 39 处、cursor:pointer、focus-visible、prefers-reduced-motion、transition 200ms、视图/组件零硬编码色值）。

---

## 3. 遗留项台账

状态判定：已解决（有代码/文档证据）/ 仍开放 / 证据缺失。来源缩写：DR=documents-review（M1-M17/L1-L5）、PR=p1-review、PC=p1-completion、P2/P3/P4=各完成报告、AA=agent-assignment。

| 条目 | 来源 | 当时裁定 | 当前实际状态（证据） | 结论 |
|---|---|---|---|---|
| B1 LLMPort 承载不了 done 契约 | DR | 改结构化增量 | `ports/llm.py` 定义 `LLMChunk/Usage`，`llm_runtime.py:22-28` 在用 | 已解决 |
| B2 实例级 cancel 并发 bug | DR | per-request Event | `cancellation.py:39` 键 `(conversation_id, request_id)`；本次变异复现退化为会话级时 9 条测试失败 | 已解决 |
| B3 `make install` 漏 local-embed | DR | install 装 | `Makefile:11` `".[dev,local-embed]"` | 已解决 |
| B4 make 命名不一致 | DR | 统一 install/install-lite | spec §2、ADR-0004 均已是新命名 | 已解决 |
| B5 无 .gitignore | DR | 补 | `.secret_key`/`data/`/`*.db` 均在 | 已解决 |
| B6 plan commit vs AGENT.md | DR | 书面预授权 | `AGENT.md:49-55` 授权例外表 | 已解决 |
| H1 ModelConfig 缺 embedding_* | DR | P0 就建 | `models.py:55-56` | 已解决 |
| H2 单例无约束/无 onupdate | DR | 修 | 固定主键 singleton（`models.py:19,46`）、onupdate（`:64`） | 已解决 |
| H3 request_id 硬编码 | DR | CurrentRidDep | 0 处硬编码、33/33 端点覆盖 | 已解决 |
| H4 CONTEXT 缺两条术语 | DR | 补 | `CONTEXT.md:88-89` 估算用量/随机补足 | 已解决 |
| M1 score_threshold 单一默认 | DR | nullable | `models.py:59` nullable + `resolve_score_threshold` | 已解决 |
| M2 backend/seeds/ 目录 | DR | P0 建 | 目录不存在，`seed.py` 单文件 | **仍开放（P5 必须接）** |
| M3 response_model=ApiResponse[T] | DR | 后续批次 | routers 0 处 | **仍开放（P6）** |
| M4 契约测试名不副实 | DR | 参数化同组断言 | `test_llm_contract.py` 26 用例（P2 报告 §3） | 已解决 |
| M5 conftest 密钥文件污染 | DR | env 注入 | `conftest.py:9-12` | 已解决 |
| M6 bcrypt 未卸载 | DR | 卸载 | `auth_service.py:32,45` `run_in_threadpool` —— **P2 报告说法与代码一致** | 已解决 |
| M7 StaticPool | DR | 显式声明 | `conftest.py:28-31` | 已解决 |
| M8 uipro 无 fallback | DR | 加 fallback | `ui-baseline.md` 在库；fallback 过程无记录 | 证据缺失（产物在） |
| M9 CORS 说明缺口 | DR | 文字写明 | 实现侧无 CORS 中间件且实测无 AC 头；spec/plan 的文字说明未见 | 已解决（实现）/ 文字缺 |
| M10 LLM fallback 无落点 | DR | 预留链 | `llm_runtime.py` 完整降级链 | 已解决 |
| M11 用户不存在/停用分支测试 | DR | 补两条 | 停用 4030 有（`test_auth_api.py:140`）；用户不存在无 | 部分解决 |
| M12 SPA fallback 死分支 | DR | 补真触发用例 | `test_static_hosting.py:42` 真触发用例 | 已解决 |
| M13 make serve 无 dist 检查 | DR | 加检查 | `Makefile:30` `test -d` | 已解决 |
| M14 .env.example 缺 APP_SECRET | DR | 补 | 已有 APP_SECRET/APP_SECRET_PATH | 已解决 |
| M15 README 默认密码警示 | DR | README 必须写 | README 0 命中 | **仍开放（P6）** |
| M16 分支策略 | DR | feat/* | 各批 feat/p1–p4（报告记载） | 已解决 |
| M17 httpx read timeout | DR | 放宽 | `Timeout(10, read=300)` / embed `read=120` | 已解决 |
| L1 缺 ADR | DR | 补 0007-0010 | 四篇在库 | 已解决 |
| L2 功能点语义重叠口径 | DR | 备口径 | 文档未动 | 仍开放（答辩口径） |
| L3 执行队列上限术语 | DR | 含索引 1 | `CONTEXT.md:87` | 已解决 |
| L4 core/logging.py | DR | 补最小实现 | 在库 + 6 测试 | 已解决 |
| L5 依赖批次标注 | DR | 标注 | `pyproject.toml:18-22` | 已解决 |
| PR-B1 重建失败静默不一致 | PR | 三道闸+3 测 | `switch_embedding_with_rebuild` 三道闸；`test_embedding_switch.py` 5 条失败路径用例 | 已解决 |
| PR-H1 重建同步执行 | PR | 裁定不改 | P1 §8.5 有裁定与重评条件 | 已解决（裁定） |
| PR-H2 spec 漂移 3 处 | PR | 回写 | spec §4.3/§5/§6.2/§9 已含（本次通读确认） | 已解决 |
| PR-H3 语料非代表性 | PR | 真实粒度回归 | `test_retrieval_quality_realistic.py`（2 条条件 skip） | 已解决 |
| PR-M1/M2/M3 | PR | 随批处理 | rebuilt/failed 清单；logging；conftest 注释（`conftest.py:59-72`） | 已解决 |
| P2 遗留 7.1 召回弱点 | P2 | 裁定推迟 | 无代码改动；AA §6 第 1 项「P6 后实测再定」 | 仍开放（按裁定） |
| P2 遗留 7.2 Mock 中断窗口窄 | P2 | P3 做 | `mock_token_delay_ms=30`；本次实测 165 增量/5.28s | 已解决 |
| P2 遗留 7.3 overview 未实现 | P2 | P6 | OpenAPI 无该端点 | 仍开放（P6） |
| P2 遗留 7.4 Markdown 渲染 | P2 | P3 做 | MarkdownView + 8 vitest | 已解决 |
| P2 遗留 7.5 哨兵端到端未验证 | P2 | 补验 | P1 报告 §6.2 真服务已验 hashing `rag_hit=false` | 已解决 |
| P3 遗留 1 spec 回写 5 条契约 | P3 | 收尾批次 | spec 无 reused/ai_report 结构/source_hash/mock_token_delay_ms 条目 | **仍开放** |
| P3 遗留 2 真提供方流式未实测 | P3 | 无 Key 标未验证 | 无变化 | 仍开放（无法验） |
| P3 遗留 3 JS 轻量解析限制 | P3 | 声明即可 | 报告与代码 docstring 已声明 | 已解决（声明） |
| P3 遗留 4 lint 存量 | P3/AA | P6 后单开批次 | 实测 35 errors | 仍开放（按裁定） |
| P3 偏离 1 CodeParser 端口未建 | P3/AA | 按裁定落领域层 | **与代码一致**：`ports/` 无 code_parser.py，`domain/code/analysis.py` 纯领域实现（import 分析零违规） | 已解决（一致） |
| P4 遗留 1 spec 回写 /code/run 契约 | P4 | 收尾批次 | spec §8.3 未含 stdin 重定向/父进程截断 | 仍开放 |
| P4 遗留 2 favicon | P4 | 收尾补 | frontend/public 不存在 | 仍开放 |
| P4 遗留 3 网络隔离 | P4 | 边界外声明 | README 第 4 条已声明 | 已解决（声明） |
| P4 遗留 4 P6 后台安全声明条 | P4 | P6 | 无后台页面 | 仍开放（P6） |
| P4 遗留 5 判题复用执行器 | P4 | 预留缝 | 端口含 `stdin` + `memory_limit_bytes` 构造注入 | 已解决（预留） |
| P4 遗留 6 HF offline 根治 | P4 | 文档化/根治 | conftest 测试侧已固化（`conftest.py:20-21`）；生产启动脚本未设、`sentence_transformer.py` 无 `local_files_only` | 部分解决 |
| P4 偏离 1 内存阈值注入 | P4 | 用户确认 | `8ae1f4a`，默认 256MB 不变，`test_code_executor.py` 唯一真实阈值用例 | 已解决 |

---

## 4. spec 漂移清单（第四轮回写之后）

1. **`GET /api/v1/admin/ping` 在 OpenAPI 存在、spec §6.2 未列**（`main.py:85-88`）。P0 占位端点，spec 从未收录。
2. **检索的 reindexing 拦截实现窄于 spec**：§6.2 knowledge 行与 §8.7 步骤 3 要求「未就绪/重建期间检索 → 5032」；实现只在显式传 `kb_ids` 时校验（见 H-4）。
3. **spec §4.3 端口清单列有 `CodeParser`（AstParser），实现无此端口**（按裁定落领域层）。属已文档化的有意偏离，但 spec 正文未加任何标注，后续读者无从知晓。
4. **P3/P4 报告登记待回写的 5 条契约尚未进 spec**：`/code/analyze` 响应超集 `reused`；`ai_report` 自描述 JSON 结构；`source_hash=sha256(language+NUL+source)` 与唯一约束；`mock_token_delay_ms`；`/code/run` 的 `limit_detail` 结构与「blocked/timeout/memory_exceeded 为 200」语义、§8.3 的 stdin 重定向与父进程截断。
5. **`.env.example` 的 `LLM_PROVIDER` 无消费者**（见 M-4）——配置面与实现漂移。
6. **数据模型无隐性漂移**：11/14 表落地（Exercise/Submission/MistakeBookEntry 属 P5），已建 11 表字段与 §5 逐项一致（含 P1 补记的 `KB.status`/`embed_*`），无多出的表；`Message.token_usage` 内多存一个 `estimated` 布尔属 P2 偏离 8 已登记项。

---

## 5. 性能回归对比表

| 指标 | 历史报告值 | 本次实测（同机隔离服务） | 判定 |
|---|---|---|---|
| 索引吞吐 | 71 切片/s（P1 §5.2，778KB→700 片） | **55.5 切片/s**（778KB→1017 片，重建 18.31s） | -22%，未超 2 倍阈值；本次语料切片数多 45%（标题结构不同），单见记录为观察 |
| 索引期间 /health 中位 | 7.2ms（P1 §5.3） | **2.4ms**（定频采样 n=90） | 成立，无劣化 |
| 索引期间 /health p95/max | P95 108ms / max 243ms | P95 498ms / max 589ms | 毛刺变大，记录观察（见 M-7） |
| Mock 流式（30ms 延迟） | 165 增量 / 5.211s（P3 §4.1） | **165 增量 / 5.28s** | 无劣化 |
| 空闲 /health 中位 | — | 2.52ms（n=60） | — |

---

## 6. P5 / P6 前置就绪度

### P5（习题与错题本）
- **CodeExecutor 端口够用**：`execute(*, language, source, stdin="")` 已含 stdin（`ports/code_executor.py`），判题用例输入可直接传；墙钟 5s（`domain/code/execution.py:56`）与 spec §5.1 单用例上限一致；内存阈值已可构造注入（P4 预留）。**缺口**：端口无 per-call 超时参数，「单题 15s 累计预算」需 P5 服务层自行计费（可接受，但要写进计划）。
- **提示词就绪**：`exercise_hint.j2` / `mistake_review.j2` 在库，`PromptAssembler.TEMPLATES` 已注册两者（`prompt_assembler.py:40`）。
- **开工前建议处理**：H-4（P5 习题辅导复用检索链路，会继承 reindexing 拦截缺口）；建 `backend/seeds/`（M2 已悬三批，约 40 题塞进 `seed.py` 会失控）；无其他阻塞。

### P6（管理后台收口）
- **已有基础**：AuditLog 表与各 action 常量、审计服务、`/admin/anti-plagiarism/stats`（注意口径只数 `role=user`，页面说明需写明，P2 偏离 4）、ModelConfig 单例 + revision 热生效机制、`score_threshold` 列已建但**无写入入口**（等 P6 `PUT /admin/model-config`）、`AuditLog.user_id` nullable（`models.py:71`）满足硬删除保留审计的库层前提。
- **P6 要新建**：用户 CRUD（含硬删除级联，spec §8.9 目前零实现）、model-config 全量 GET/PUT/test、logs、overview、`/admin/ping` 占位替换、后台安全边界声明条（P4 遗留 4）。
- **P6 顺带清单**：M3 response_model、M15 README 密码警示、favicon、lint 清理批次（在其后）、H-2 的 5032 收敛可评估是否同批。

---

## 7. 建议处理顺序

1. **P5 开工前必修（小改动）**：H-4（检索状态拦截补全）；顺手删 M-6 死代码；对 H-1 的用例做负载敏感性标注（或演示机跑测试时避免满载），不建议放宽断言。
2. **可与 P5 并行**：H-3 分层违规重构（走端口/registry，现有测试可保护）；M-4 死配置处理；M-5 术语改口；M-8 补一条「用户不存在」用例。M-2（是否补 FK）是架构决策，建议 P6 评估，牵连删库重建。
3. **P6 范围内一并**：M-3（README 密码警示）、M-1（lint 清理批次，P6 之后）、response_model、overview、model-config 全量、后台声明条、favicon（L-3）。
4. **收尾/答辩前**：spec 回写（漂移 1/3/4 共 7 条）；有真实 Key 时补验 P3 遗留 2 与真实 LLM 下的流式讲解。

---

## 8. 验过什么、没验过什么

**已独立验证**（命令/脚本/实测，非转述报告）：
- `make test` 两次：负载下 1 failed（H-1）/ 无并行负载复跑链条通过；`vue-tsc --noEmit` 零错误；`vite build` 成功（Monaco 4MB 超限告警为既有已知项）；`npm test` 8 passed；`make lint` 35 errors 含分布。
- 后端 pytest 精确计数：无并行负载独立复跑 659 passed / 2 skipped（120.03s），基线成立（H-1 为负载敏感 flake）。
- AST 全仓 import 分层分析；33 端点 `CurrentRidDep`/admin 守卫逐一核对；OpenAPI 30 条路径全量比对；11 张已建表逐字段比对。
- 编码约定 grep 四项专项；4290/4990 抛出点追溯。
- 变异测试复现 2 条（P3-M4 hash 复用关闭 → 3 failed，与报告逐条一致；P2-B 会话级 cancel 退化 → 9 failed，含报告点名用例），改坏-还原后 `git status` clean。
- 真服务黑盒：登录/注册、跨角色 4030、JWT 篡改/过期 401、黑名单拦截 + 金丝雀无副作用、`getattr` 链绕过成功（验证声明诚实性）、项目外/内文件可读、CORS 无头 + OPTIONS 405、跨用户对象 404、`seed` 两次幂等（1 用户）。
- XSS：真实 `renderMarkdown` 打包后 17 个对抗载荷 DOM 级判定全 clean。
- 维度 7：5032 全部抛出点追溯 + Chroma 宕机实测返回 5000（H-2）；检索降级链、done 事件 `degraded` 或语义与 `fallback_reason` 检索优先（`chat_service.py:304-305`）代码级确认。
- 性能三项复测（§5）；测试盲区脚本扫描（192 个公共定义中 32 个测试零引用，逐一人工排除间接覆盖后剩 M-6/M-8 等真缺口）。
- 2 条 skip 的条件与原因（`test_retrieval_quality_realistic.py` A 型语料参数）。

**未验证**（如实列出，不以报告自证代替）：
- 亮色对比度 ≥4.5:1 与 375/768/1024/1440 四断点无溢出（浏览器视觉项；P2/P4 报告用 Playwright 验过，本次未复现）。
- 真实 OpenAI 兼容提供方全链路（无 Key，P3 遗留 2 同因）。
- Chroma 宕机时**聊天流**的行为（只实测了 `/knowledge/search` 返回 5000；带 RAG 的 SSE 是否同样 5000 未验）。
- 256MB 真实内存杀在本机与历史报告数值（peak 292–305MB）的对照复测（隔离单跑只验证了判定路径）。
- 有网络环境下 sentence-transformers 的联网校验行为（全程离线标志）。
- 多 worker 反例（单 worker 为声明前提，未实测违反后果）。
- 10MB/415 上传边界与 723 切片重建等历史实测项（本次未重复，信任其为可复现口径）。
- `.codebuddy/` 技能目录内容（gitignore 范围，非交付物）。

> 补充记录：本报告交付前最后一次独立复跑 `cd backend && .venv/bin/python -m pytest -q`（无并行负载）实测：**659 passed, 2 skipped, 1 warning in 120.03s** —— 与各批次报告声称的基线一致。结论：H-1 的失败是负载敏感的 flake（高负载下 CPU 层先于内存层触发），正常条件下基线成立，但「659 passed」不可在任意负载下无条件复现。
