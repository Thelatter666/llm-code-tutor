# 清理批次实施计划（强档：lint 清零 + H-3 分层重构 + spec 漂移收口）

- 日期：2026-09-01
- 分支：`feat/cleanup-batch`（自 main @ 7a38c43 切出）
- 基线（总指挥独立复跑）：后端 pytest **995 passed / 2 skipped**（~197s）；前端 vitest 8 passed / vue-tsc 零错误 / vite build 通过；`make lint` **35 errors**
- 授权：AGENT.md 授权例外表已登记本批（Task 完成且全量测试通过后按 Task 粒度 commit；merge 不在授权内）

---

## 0. 目标与验收总口径

| # | 项 | 验收口径 |
|---|---|---|
| 1 | lint 35 清零 | `make lint` = 0 errors；行为零变化（全量 995/2 每分类修完复跑） |
| 2 | M-3 response_model | `/openapi.json` diff 只增不改（响应体 schema 从自由对象升级为信封声明）；54 个 JSON 端点响应体逐字段比对零漂移 |
| 3 | M-4 死配置 | `Settings.llm_provider` 与 `.env.example` 的 `LLM_PROVIDER` 行删除，全仓 grep 零残留 |
| 4 | M-5 术语改口 | CodeSession 用户可见文案零「草稿」（含锁用例）；Exercise.status 的「草稿」标签**不改**（见 §3 裁定 R3） |
| 5 | H-3 分层重构 | `grep -rn "infrastructure.adapters" app/services/` = 0；B1 回归（`test_embedding_switch.py` 全组过 + 拆 409 门必失败）；embedding 409 流程语义零变化（只换实现位置） |
| 6 | spec 漂移回写 | 漂移 3 标注落正文；漂移 4 五条逐条核对（预计全部已在 P5/P6 期间回写，核对表进完成报告）；漂移 5 随 M-4 消解 |

红线（全程）：测试离线约定、H-1 负载纪律（pytest/vue-tsc/build 严格串行）、UTCDateTime/禁FK/禁硬编码 request_id、端点守卫不回归、禁改检索与 409 语义、新错误码零新增、merge/push 不做。

---

## 1. 现状勘察结论（计划的事实基础，全部实测/实读）

### 1.1 lint 35 的精确分布（本计划逐处核对过源码）

| 规则 | 数量 | 位置 | 修法 |
|---|---|---|---|
| UP017 | 9 | chat_service.py:318、auth_service.py:48、models.py:28、db.py:27/:32、security.py:23、test_kb_models.py:67、test_db.py:55/:63 | `timezone.utc` → `datetime.UTC`（先改 import 为 `from datetime import UTC, ...`，同一对象，零行为变化）。chat_service.py:313-316 有一段注释自称「与 models.py / auth_service.py 一致用 timezone.utc」的 UP017 豁免说明——本次全量改口后该注释一并删除（注释描述的前提消失） |
| B008 | 7 | knowledge.py:22/:39、auth.py:57/:63、admin_model_config.py:99/:129（均 `user: User = Depends(...)`）、admin_knowledge.py:90（`file: UploadFile = File(...)`） | 全部是 FastAPI 依赖惯用法误报。**修法：转 Annotated**（与 deps.py 的 `SessionDep/CurrentRidDep` 及各 admin router 的 `AdminDep` 既有风格一致），零行为变化，不动 ruff 配置 |
| I001 | 7 | main.py:1、registry.py:1、models.py:9、security.py:1、model_config_service.py:7、test_db.py:1、test_static_hosting.py:43 | `ruff check --fix` 后**重新 Read 再 Edit**（行号漂移）。注意 Task 5 会改 model_config_service 的 import 区，顺序无碍 |
| UP035 | 4 | ports/llm.py:10、db.py:3、embedder_runtime.py:16、adapters/llm/openai_compat.py:3 | `typing.AsyncIterator/Callable` → `collections.abc` 同名导入（3.12 下类型标注等价） |
| UP046 | 2 | schemas/common.py:8/:15（`ApiResponse` / `Page` 的 `Generic[T]`） | PEP 695：`class ApiResponse[T](BaseModel)`。pydantic 2.13.5 支持；全仓仅 common.py 定义处用 TypeVar `T`（已 grep 确认无外部 `from app.schemas.common import T`） |
| UP045 | 1 | ports/code_executor.py:35 `Optional[int]` | → `int \| None` |
| UP007 | 1 | ports/llm.py:47 `Union[TextDelta, Usage]` | → `TextDelta \| Usage` |
| SIM117 | 1 | openai_compat.py:72 嵌套 `async with` | 合并为单条 `async with self._client() as client, client.stream(...)`（语义等价） |
| S112 | 1 | chroma_store.py:162 except→continue | **按语义修**：except 内补 `logger.debug` 留痕后再 continue（清理失败不影响主流程的语义不变，但从静默变为可观测；不新增业务行为） |
| PLW1510 | 1 | test_gitignore.py:21 `subprocess.run` 未声明 check | 显式 `check=False`（该用例本来就断言 returncode，语义精确化） |
| F401 | 1 | test_static_hosting.py:43 | 删除未用的 `ApiError` 导入（与该行 I001 一并消解） |

**执行顺序（每类修完跑全量）**：① `ruff check --fix`（I001+F401+可自动 UP，约 23 处）→ re-read 复核 diff；② UP017 手工全量；③ UP046/UP045/UP007/UP035；④ B008 Annotated 化（7 处）；⑤ SIM117/S112/PLW1510。

### 1.2 M-3 契约勘察

- 信封由 `core/responses.py:ok()` 手工拼装，`ApiResponse` 目前**全仓零消费者**（正是 M-3 要补的）。
- 55 个 router 端点 + `/health`，其中 **2 个 SSE**（chat.py:69 消息流、exercise.py:109 hint 流）返回 `StreamingResponse`，**不适用信封**——`{code,message,data,request_id}` 无法描述事件流。错误路径全部经 `ApiError` 异常处理器返回 `JSONResponse`，不经过 response_model 序列化，**409/422/4xx/5xx 形状零影响**。
- **契约提案（R1，见 §3）**：全部 JSON 端点统一 `response_model=ApiResponse[Any]`——`data: T | None`（T=Any）对嵌套内容完全透传，零字段过滤，与「实际响应为超集」惯例（facets、judge_detail、limit_detail）天然兼容。逐端点具体类型（`ApiResponse[UserOut]` 等）会在 data 内做字段过滤，与超集惯例直接冲突，**不采**。
- 漂移防护实测法：Task 3 动手**前**用 TestClient（seed 后临时库）对 54 个 JSON 端点逐一抓响应体存 `/tmp`，加 response_model 后重抓，归一化（剥 request_id/id/时间戳）逐字段 diff，要求零差异。
- 新增锁用例（C5 的可击杀前提）：`tests/test_openapi_envelope.py`——断言 openapi.json 中除 2 个 SSE 路径外全部端点的 200 响应 schema 引用 ApiResponse 组件且 required 含 `code/message/data/request_id`。

### 1.3 M-4 / M-5 勘察

- `Settings.llm_provider`（config.py:19）全仓唯一出现即定义处；`.env.example:12` 有 `LLM_PROVIDER=mock` 行；README 无引用。删两处即可，漂移 5 随之消解。
- 「未命名草稿」四处确认：models.py:222、schemas/code.py:60、code_service.py:193、CodeEditorView.vue:133。
- **超出题面四处但属"用户可见文案零草稿"纪律范围的 CodeSession 相关字样**（全量清单）：
  - 用户可见字符串：`code_service.py:246` `"草稿不存在"`（4040 错误 message，走 API 给用户看）；CodeEditorView.vue:191「保存草稿」按钮、:272 侧栏标题「草稿」、:284 空态文案「还没有草稿，写点代码后点「保存草稿」」。
  - 注释/标识符：api/code.ts:53、CodeEditorView.vue:17、CodeEditor.vue:82/:101、CodeReviewView.vue:12、code_service.py:31/:190/:237、routers/code.py 头注释、test 注释等——**注释随手改口（同文件零风险），标识符（`create_draft`/`saveDraft`/`drafts` 等）不动**（题面与 H-3 红线均为改动最小面；标识符层 CONTEXT.md 判定本就合规）。
  - `tests/test_code_run_service.py:304` 现锁 `assert draft.title == "未命名草稿"`——M-5 必须同步改为「未命名会话」（该用例即 C4 的既有击杀者）。
- **新增术语锁用例（C4 前提）**：`tests/test_terminology.py`——断言 CodeSession 默认标题常量三处一致为「未命名会话」，且 `app/` 与 `frontend/src/` 的用户可见字符串（错误 message / 模板文本）不含「草稿」二字的 CodeSession 文案（实现方式：对改后的四处直接断言 + 对 code_service 4040 message 断言）。

### 1.4 H-3 勘察与重构契约

**indexing（Task 4）**：
- `ports/document.py:23` `DocumentParser.parse(path)` 与 `parsers.py:78` `parse_document(path, source_type)` 签名错位——端口无 source_type，这正是它当初接不进服务的原因。
- **契约**：端口签名定稿为 `parse(self, path: Path, source_type: str) -> ParsedDocument`（服务真实需要的接缝 = spec §4.1「源文件 → 纯文本」的完整语义）。适配器新增 `MultiFormatDocumentParser` 类实现该端口，内部委托现有 `parse_document` 派发函数（`parse_document` 原样保留，test_document_parsers 的 14 处直调不动；`test_parsers_satisfy_port` 的逐格式 isinstance 因 runtime_checkable 只查方法名而仍然通过——保留原断言，另加一条 `MultiFormatDocumentParser` 对端口的 isinstance，不制造假改动）。
- 接线走 `app/infrastructure/runtime.py`：`get_document_parser()/set_document_parser()` 进程单例，与 `get_code_executor()` 完全同构（同一测试注入点惯例）；`IndexingService.__init__` 增 `parser: DocumentParser | None = None`，缺省取 runtime 单例；`_run` 内改为 `run_in_threadpool(self._parser.parse, Path(uri), doc.source_type)`。
- 现有 4 个 IndexingService 构造点（测试）零改动可用（新参缺省）。
- **C1 锁用例**（新增）：注入记录调用的 FakeDocumentParser，断言 `index_document` 走的是注入实例（回退直连即失败）。

**model_config（Task 5）**：
- `default_embedding_model()`（model_config_service.py:410-416，依赖 3 个适配器常量/类属性）**整体移至 registry.py**（registry 本就是 spec §4.2 指定的 adapter 解析层，已 import 这三个适配器；函数全仓无外部调用方，移动零波及）。
- registry 新增公开常量 `HASHING_EMBED_MODEL = HashingEmbed.model`；`model_config_service.py:323` 的 `model == HashingEmbed.model` → `model == HASHING_EMBED_MODEL`。服务层删除全部 3 行适配器 import（:17/:18-20/:21-23）。
- **build_llm（P6 L-3 一并处置，二选一已择）**:选「走 registry 公开入口」——registry 新增 `build_primary_llm(cfg: LLMConfig) -> LLMPort`，封装 `build_llm(cfg, LLM_LEVEL_PRIMARY) or build_llm(cfg, LLM_LEVEL_MOCK)` 的首选级选择与兜底；model_config_service 的 test 端点改用它，并删除对 `llm_runtime.LLM_LEVEL_*` 的直接 import。理由：服务层不该知道降级链的级别编号——那是 registry/runtime 的内部知识；行为完全等价（PRIMARY 级恒返回非 None，or 分支不变）。
- **C2 锁用例**（新增）：① registry `default_embedding_model` 三分支映射断言（openai→`text-embedding-3-small`、hashing→`hashing-256`、其它→MiniLM）——把常量改坏/回退硬编码即死；② 结构守卫（下条）。
- **结构守卫测试（C1+C2 共同的机械化红线）**：新增 `tests/test_architecture.py`——AST 扫描 `app/services/*.py`，断言无任何 `app.infrastructure.adapters` import（把 grep 红线固化为用例）。

**语义不变的证明**：Task 4/5 各自完成后跑 B1 回归全套 `test_embedding_switch.py`（21 条），并在 Task 7 真服务冒烟实测 409→confirm→重建流程。

### 1.5 spec 漂移逐条核对结论（Task 6 输入）

| 漂移 | 现状核对（main @ 7a38c43 实读） | 动作 |
|---|---|---|
| 3 CodeParser | spec §4.1 端口表与 ASCII 图仍列 `CodeParser/AstParser`，正文无「落领域层」标注 | 端口表下加「清理批次补记（2026-09-01）」：CodeParser 无 ports 定义，`domain/code/analysis.py` 纯领域实现，属 P3 已裁定的有意偏离（判定依据：ports/ 目录实测无 code_parser.py） |
| 4 P3/P4 五条契约 | **逐条已在**：`reused`（§6.2:313）、`ai_report` 结构（§8.4:591）、`source_hash`+唯一约束（§5:199）、`mock_token_delay_ms`（§7.3:491-499）、`/code/run` 的 stdin 重定向/父进程 8KB 截断/200 语义/`limit_detail` 结构（§8.3 第 4/6/7/8 条:560-578）。健康检查清单基于 9b5187f，P5/P6 期间已回写 | 不补文字；核对表（条目→行号证据）写进完成报告，spec 修订记录注明「清理批次逐条核验，无缺口」 |
| 5 LLM_PROVIDER | spec 正文无该环境变量的引用（grep 零命中），M-4 删除即消解 | 随 Task 2，无 spec 改动 |

另：CONTEXT.md 修订记录补清理批次一行（M-4/M-5/H-3/漂移 3 的文档动作）。

---

## 2. Task 划分与文件清单

> 每 Task 完成判据：`make lint`（如适用）+ 后端全量 995/2（新增用例后计数会增长，如 996+/2）+ 涉前端时 vue-tsc/build/vitest；全量测试严格串行。

### Task 1 · lint 35 清零（行为零变化）
改：§1.1 表列 18 个文件（app 12 + tests 5 + openai_compat）。新增测试：无。
验证：`make lint` 0 errors；全量 995/2。

### Task 2 · M-4 死配置 + M-5 术语改口
改：config.py（删 :19）、backend/.env.example（删 :11-12）、models.py:222、schemas/code.py:60、code_service.py:190/:193/:237/:246（含注释）、CodeEditorView.vue（:17/:133/:191/:272/:284）、api/code.ts:53、CodeEditor.vue:82/:101、CodeReviewView.vue:12（注释）、test_code_run_service.py:304。
新增：`tests/test_terminology.py`（C4 锁）。
验证：grep「未命名草稿」全仓 0；grep「草稿」的 CodeSession 用户可见字符串 0；全量 + 前端三件套。

### Task 3 · M-3 response_model=ApiResponse[?]
改：schemas/common.py（若 Task 1 未消则此处消 UP046 已由 Task 1 完成——本 Task 只增不改）、11 个 router 文件全部 53 个 JSON 端点 + main.py `/health` 加 `response_model=ApiResponse[Any]`；2 个 SSE 端点不加（例外清单写进完成报告）。
新增：`tests/test_openapi_envelope.py`（C5 锁）。
基线动作：动手前抓取 54 端点响应体存 /tmp，完成后归一化 diff 零漂移；`/openapi.json` 前后 diff 审查「只增不改」。
验证：全量 995/2 + openapi 用例。

### Task 4 · H-3：indexing 走 DocumentParser 端口
改：ports/document.py（签名定稿）、adapters/document/parsers.py（+`MultiFormatDocumentParser`）、runtime.py（+get/set_document_parser）、indexing_service.py（删 :30，构造器 +parser，:136 改端口调用）、test_document_parsers.py（+`MultiFormatDocumentParser` 端口 isinstance 断言，原断言不动）。
新增：FakeDocumentParser 注入锁用例（进 test_indexing_service.py）。
验证：grep 红线 services 内 adapters 仅剩 model_config_service（Task 5 清）；全量重点 test_indexing/test_embedding_switch/test_retrieval_quality*。

### Task 5 · H-3：model_config 常量上移 + build_llm 收口
改：registry.py（+`default_embedding_model`、`HASHING_EMBED_MODEL`、`build_primary_llm`）、model_config_service.py（删 3 适配器 import 与 :410-416 函数，:219/:323/:375 改引用，test_llm_connection 改 `build_primary_llm`，删 `llm_runtime.LLM_LEVEL_*` import）。
新增：`tests/test_architecture.py`（结构守卫）+ registry `default_embedding_model` 映射用例。
验证：**`grep -rn "infrastructure.adapters" app/services/` = 0（红线）**；`test_embedding_switch.py` 21 条全过；全量。

### Task 6 · spec/CONTEXT 回写（docs）
改：spec §4.1 端口表 CodeParser 补记；CONTEXT.md 修订记录；完成报告挂核对表（Task 7 写）。
验证：文档 diff 自查。

### Task 7 · 变异实拆 + 真服务冒烟 + 完成报告
变异 C1–C5（见 §4），逐条「改坏→验证改坏（先跑一次确认失败而非语法错）→字节级还原→git status clean」→ 全量 995+/2 收口；真服务冒烟（见 §5）；写 `docs/review/2026-09-01-cleanup-completion-report.md`；**停下等总指挥审阅，不做 merge**。

---

## 3. 契约定稿与【待总指挥裁定】

| # | 契约 | 本计划定稿 | 状态 |
|---|---|---|---|
| R1 | M-3 的 data 类型 | 统一 `ApiResponse[Any]`（信封定型、data 透传，兼容超集惯例）；**不**逐端点具体模型 | 【待总指挥裁定】若裁定要具体模型，需接受逐端点核对全部超集字段的工作量与漂移风险，请明示 |
| R2 | build_llm 处置 | 走 registry 公开入口 `build_primary_llm`（非加注释保留） | 已择一写入计划，留裁定 |
| R3 | 「草稿」改口边界 | CodeSession 的全部用户可见字符串（含 `"草稿不存在"` 错误 message 与前端 3 处按钮/标题/空态）改口；Exercise.status 管理页「草稿」标签**保留**（习题发布态用语，非 CodeSession 实体，CONTEXT.md 禁词限定于 CodeSession）；标识符不动 | 【待总指挥裁定】「草稿不存在」message 改「代码会话不存在」属响应体 message 文本变化（有测试锁），确认在批准范围内 |
| R4 | DocumentParser 端口签名 | `parse(path, source_type)`；逐格式类不再直接充当端口实现（端口的消费者接缝唯一化） | 计划定稿，留裁定 |
| R5 | SSE 端点 | 2 个流式端点豁免 response_model（信封无法描述事件流），例外清单入完成报告 | 计划定稿，留裁定 |
| R6 | 信封 message 默认 | 沿用 `ok()` 现行为（code=0/message="ok"），response_model 不引入新默认值 | 定稿 |

零新错误码；不触碰 retrieval_service / embedder_runtime / concurrency 的任何语义。

---

## 4. 变异实拆指引（Task 7 逐条执行）

| # | 变异点 | 预期击杀用例 | 说明 |
|---|---|---|---|
| C1 | indexing_service 回退直连 `parse_document` | 新增 Fake 注入锁用例 + `test_architecture.py` | 回退需重新 import 适配器→结构守卫死；仅把注入改回直调→Fake 死 |
| C2 | registry 常量/函数回退（`default_embedding_model` 硬编码错值 / 服务层恢复 `HashingEmbed.model` 直引） | registry 映射用例 + 结构守卫 + embedding-consistency 组用例 | |
| C3 | 拆 409 门：`update_embedding` 的 `if kb_ids and not confirm: raise` 条件破坏 | `test_embedding_switch.py::test_switching_with_existing_chunks_returns_409` | B1 回归红线，另跑 unconfirmed 不落库用例 |
| C4 | 「未命名会话」改回「未命名草稿」（models.py 默认值处） | `test_code_run_service.py:304` + 新增 test_terminology | 先验证术语用例存在再施加 |
| C5 | 撤掉某端点 `response_model` | `test_openapi_envelope.py` | 端点选定 /auth/me（最小面） |

纪律：每次变异先跑目标用例证明「改坏了」（防 P6 S1 式存活/语法错假击杀），还原后 `git diff` 空 + `git status` clean。

## 5. 真服务冒烟方案（Task 7）

单 worker uvicorn + 临时 `DATABASE_URL`/`chroma_persist_dir`/`upload_dir`（tmp 目录），`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，seed 后黑盒：
1. **embedding 切换 409 全流程实测**：建 KB→上传小 txt→轮询 ready→PUT embedding（不带 confirm）→ 断 409 + need_rebuild/knowledge_base_ids/from/to 字段→confirm=true 切 hashing（显式哨兵路径，秒级完成免模型加载）→ rebuilt 清单→检索 5032/degraded 行为抽查；
2. `/code/analyze` 与 `/code/run` 响应形状与重构前基线（Task 3 抓的 /tmp 存档）逐字段比对（归一化动态字段）；
3. 模型配置 GET/PUT：掩码、revision 自增、test 端点 ok=true（mock）；
4. 错题/习题链路防横切回归：列表(facets)→提交判分→错题本→recommendations→hint 非流式前置校验；
5. 结束杀进程、清 tmp，`git status` clean。

## 6. 完成报告结构（docs/review/2026-09-01-cleanup-completion-report.md）

基线复跑表（lint/pytest/前端）→ 六项逐条结果与证据（含 grep 红线输出、openapi diff 结论、54 端点 diff 零漂移证明）→ 变异 C1–C5 实拆记录（含「先改坏验证」证据）→ 真服务冒烟清单 → spec 漂移核对表（§1.5）→ 未验证项如实列出 → 遗留移交（README/答辩口径/混合检索/真实 Key 全链路，不在本批）。

## 7. 提交计划

- 阶段一：本文件 + AGENT.md 授权行 → 1 个 docs commit（Task 0），**停下等审阅**。
- 阶段二：Task 1–7 各 1 commit（`chore(lint):`/`fix(m4,m5):`/`feat(m3):`/`refactor(h3):`/`docs(spec):`/`test: + docs(report)` 粒度，信息按仓库中文惯例）。

---

## 8. 阶段一总指挥裁定（2026-09-01，全部定稿并放行）

R1–R6 全部采纳本计划提案，附加要求如下（执行时不可省）：

| # | 附加要求 | 落点 |
|---|---|---|
| A1 | Task 3 量化口径：`/openapi.json` 前后 diff 必须**只增**——新增 response schema 组件可以，既有路径的 operation/参数/description 零变化；diff 统计（+N/−M）贴进完成报告 | Task 3 / 完成报告 |
| A2 | Task 1 UP046（PEP 695）留 fallback：先写最小用例验证 `class ApiResponse[T](BaseModel)` 在 pydantic 2.13.5 运行时求值无恙，再全量改；若 class body 求值时 `T` 可见性出问题，退回 `TypeVar` + `# noqa: UP046`，不许卡死 | Task 1 ③ |
| A3 | 全量测试计数不写死 995——新增用例后计数增长，以实跑为准；收尾必须一次干净串行全量 | 各 Task 验证门 |
| A4 | R3 追加：改 message 前 `grep -rn "草稿不存在"` 全仓，断言该原文的测试一并同步（计划原只锁 test_code_run_service.py:304） | Task 2 |
| A5 | R4 追加：`MultiFormatDocumentParser` 补一条「与 `parse_document` 行为等价」实测用例（同一文件走新类 vs 直调函数结果一致），不能只过 isinstance | Task 4 |
| A6 | C3 变异：定位 `if kb_ids and not confirm: raise` 破坏条件；除目标用例外另跑 `test_unconfirmed_switch_does_not_persist` | Task 7 |

R3 边界确认：Exercise.status「草稿」标签保留（CONTEXT.md 禁词限定于 CodeSession 行），该边界写进完成报告。
硬门槛：H-3 红线 `grep infrastructure.adapters app/services/ = 0` + B1 回归（test_embedding_switch 全组 + 拆 409 门变异击杀）。
