# 清理批次完成报告

- 日期：2026-09-01
- 分支：`feat/cleanup-batch`（基线 main @ 7a38c43）
- 提交链：37d4968（计划+授权）→ 8ef145d（裁定回填）→ ecac6c2（Task 1 lint）→ 85a1334（Task 2 M-4/M-5）→ 629c1aa（Task 3 M-3）→ e810acf（Task 4 H-3 indexing）→ a596dcd（Task 5 H-3 model_config）→ a20814d（Task 6 spec 回写）→ 本报告 commit（Task 7）
- 性质：强档清理（动既有代码，行为零变化优先）。**merge 不在授权内，未执行。**

## 1. 验收总表（全部本批实跑，非转述）

| 门槛 | 基线（main） | 本批收尾实跑 | 判定 |
|---|---|---|---|
| `make lint` | 35 errors | **All checks passed（0 errors）** | ✅ 清零 |
| 后端 pytest | 995 passed / 2 skipped | **1006 passed / 2 skipped（202.19s）** | ✅ 零回归，+11 条本批新增锁用例 |
| 前端 vitest / vue-tsc / vite build | 8 / 零错误 / 通过 | 8 passed / exit 0 / 37.22s 通过（Task 2 后前端零改动，`git diff --name-only 85a1334..HEAD \| grep frontend` = 0） | ✅ |
| H-3 红线 | services 直连适配器 2 文件 6 处 | `grep -rn "infrastructure.adapters" app/services/ --include="*.py"` = **0** | ✅ |
| B1 回归 | — | `test_embedding_switch.py` 21 条全组过 × 多次；409 门变异实拆击杀（§4 C3） | ✅ |
| 纪律 grep | — | `request_id=""` 0 处；models 裸 DateTime 0 处（15 列全 UTCDateTime）；ForeignKey 仅 2 处 docstring 提及（无实体约束）；`CODE_STATUS` 集合与基线一致（4010/4030/4040/4090/4220/4290/5000/5021/5032），**新错误码零新增**；55 端点守卫未动（仅装饰器加 response_model 参数） | ✅ |
| 真服务冒烟 | — | **25/25 通过**（§5） | ✅ |

## 2. 六项逐条结果

### 2.1 lint 35 清零（ecac6c2）

分布核对与修复方式全部照计划 §1.1 执行：UP017×9（`datetime.UTC`，与 `timezone.utc` 同一对象；chat_service 的过期豁免注释删除）、B008×7（**全部为 FastAPI Depends/File 惯用法误报**，转 Annotated：knowledge/auth 新增 `UserDep` 别名、admin_model_config 复用既有 `AdminDep`、upload `file` 参数 Annotated 化；`user` 参数移位不改变 OpenAPI 可见参数序，diff 已证）、I001×7 + F401×1（`ruff --fix` 后逐文件复核 diff）、UP035×4、UP045×1、UP007×1、UP046×2（PEP 695，**附加要求 A2 先行验证**：最小用例证明 `class ApiResponse[T](BaseModel)` 在 pydantic 2.13.5 + FastAPI 运行时求值正常、字段序与 data 透传不变，未启用 noqa fallback）、SIM117×1（嵌套 async with 合并）、S112×1（chroma_store 空集合清理失败补 `logger.warning` 留痕，不静默）、PLW1510×1（test_gitignore 显式 `check=False`，returncode 即断言对象）。

每分类修完跑全量：4 次分类复跑 + 收尾干净串行全量，均 995/2（当时计数）绿。

### 2.2 M-3 response_model（629c1aa）

- 54 个 JSON 端点（53 router + `/health`）全部 `response_model=ApiResponse[Any]`（裁定 R1：信封四字段定型、data 透传零过滤，兼容 facets/judge_detail/limit_detail 超集惯例）。
- **SSE 豁免（R5）例外清单**：`POST /chat/conversations/{id}/messages`、`POST /exercises/{id}/hint` 两端点不套信封，并显式声明 `text/event-stream` 响应（原 FastAPI 默认误标 `application/json` 空 schema）。
- **响应体零漂移证明**：动手前用 TestClient（seed 临时库 + Fake 运行时）抓 55 项基线（52×200 + 3 条刻意错误路径 401/403/404），改后重抓，归一化（掩 request_id/uuid/时间戳/JWT/peak_bytes/elapsed_s）后 diff **IDENTICAL**。
- **openapi diff 量化（A1）**：`+194 / −58`。删除行全部为占位符替换，无既有契约变化：54×`"schema": {}` → `ApiResponse_Any_` $ref（信封升级本体）+ 2×`"description": "Successful Response"` 与配对行（SSE 媒体类型修正）。既有路径的 operationId/参数/requestBody/状态码零变化。
- 错误路径（409/422/4xx/5xx）经异常处理器返回 `JSONResponse`，不经 response_model，形状零影响（err.401/4030/404 基线比对全等）。

### 2.3 M-4 死配置（85a1334）

`Settings.llm_provider`（config.py）与 `.env.example` 的 `LLM_PROVIDER=mock` 行删除。删除前全仓 grep 复核：唯一命中即定义处；README 无引用。spec 漂移 5 随之消解（spec 正文从未引用该环境变量，grep 零命中）。

### 2.4 M-5 术语改口（85a1334）

- 题面四处「未命名草稿」→「未命名会话」（models.py / schemas/code.py / code_service.py / CodeEditorView.vue）。
- **超出题面的用户可见字样（R3 全改口）**：`code_service.py` 4040 message「草稿不存在」→「代码会话不存在」（A4 前置 grep：全仓仅此一处抛出点，无测试锁原文）；前端「保存草稿」按钮 / 侧栏「草稿」标题 / 空态「还没有草稿…」三处 → 会话措辞。
- **边界（R3 裁定）**：Exercise.status 管理页「草稿」发布态标签**保留**——CONTEXT.md 禁词限定于 CodeSession 行（术语表结构），习题发布态是另一实体；标识符（`create_draft`/`saveDraft`/`drafts` 等）不动；`models.py` docstring 中作为禁词说明出现的「草稿」保留。
- 同步 `test_code_run_service.py:304` 断言；新增 `tests/test_terminology.py`（默认标题三层一致 + 7 个文案源头文件禁词扫描 + 4040 message 断言）。

### 2.5 H-3 分层重构（e810acf + a596dcd）

**indexing**：`DocumentParser` 端口签名定稿 `parse(path, source_type)`（R4），新增 `MultiFormatDocumentParser`（`parse_document` 的类化外壳，函数原样保留），`runtime.get/set_document_parser()` 与 `get_code_executor` 同构接线，`IndexingService` 构造器 +`parser` 参数。新增 `_RecordingParser` 注入锁 + A5「类与函数行为等价」实测（成功/ValueError/FileNotFoundError 三路径一致）+ 端口 isinstance。

**model_config**：`default_embedding_model` 整体迁入 registry（函数体零改动）、新增 `HASHING_EMBED_MODEL` 常量；服务层删除 3 个 embedding 适配器 import 与 `LLM_LEVEL_*` import。**build_llm（R2）**：新增 `registry.build_primary_llm(cfg)` 公开入口，test 端点改走它——级别编号不再出 registry，行为等价（PRIMARY 级恒非 None，or 兜底分支不变）。

**语义不变承诺兑现**：只换实现位置，未改任何变量名/判定顺序/异常类型/回滚流程；B1 三道闸用例组全过；真服务实测 409→confirm→重建→哨兵降级可见全链路（§5）。

**机械化红线**：新增 `tests/test_architecture.py`（AST 扫描 services 禁 import `infrastructure.adapters`），把 grep 红线固化为用例。

### 2.6 spec 漂移回写（a20814d）

| 漂移 | 处置 |
|---|---|
| 3 CodeParser | spec §4.1 端口表下新增「清理批次补记（2026-09-01）」：CodeParser 行为已裁定的有意偏离（P3 裁定原文理由：纯领域实现、ast 标准库、无第二实现需抽象、将来需要再提炼端口）；同补记定稿 DocumentParser 接缝签名含 source_type |
| 4 P3/P4 五条契约 | **逐条核验已在，无缺口**（健康检查清单基于 9b5187f，P5/P6 期间已回写）：`reused` 超集→§6.2 code 行；`ai_report` 自描述结构→§8.4 首条；`source_hash=sha256(language+NUL+source)`+唯一约束→§5 CodeAnalysis 行；`mock_token_delay_ms`→§7.3 专段；`/code/run` `limit_detail` 结构与 blocked/timeout/memory_exceeded=200 语义、stdin 临时文件重定向、父进程 8KB/流截断→§8.3 第 4/6/7/8 条 |
| 5 LLM_PROVIDER | 随 M-4 消解（§2.3） |

CONTEXT.md 修订记录登记本批全部文档动作。

## 3. 与既有「超集」惯例的兼容说明

`ApiResponse[Any]` 的 `data: T | None`（T=Any）在 pydantic 序列化中对 data 内容完全透传：不裁剪、不重排、不改型。冒烟中 13 端点抽查断言顶层键集**严等** `{code, message, data, request_id}`，嵌套结构（facets、judge_detail、limit_detail、rebuilt/failed）原样存活。

## 4. 变异实拆记录（Task 7，全部「先验证改坏→击杀→git checkout 字节级还原→git status clean」）

| # | 变异 | 实拆 | 击杀结果 |
|---|---|---|---|
| C1 | indexing 回退直连（重新 import `parse_document` 并绕过注入） | indexing_service.py 两处替换 | **2 failed**：`test_parse_goes_through_injected_document_parser`（功能锁）+ `test_services_never_import_adapters`（结构锁） |
| C2a | registry 常量回退（`HASHING_EMBED_MODEL = "hashing-255"` 错值） | registry.py 一处替换 | **1 failed**：`test_default_embedding_model_maps_each_provider` |
| C2b | 服务层恢复直引 `HashingEmbed.model` | model_config_service.py 两处替换 | **1 failed**：`test_services_never_import_adapters` |
| C3 | 拆 409 门（`if kb_ids and not confirm:` → `if kb_ids and False:`，合法语法） | model_config_service.py 一处替换 | **2 failed**（A6 要求双用例）：`test_switching_with_existing_chunks_returns_409` + `test_unconfirmed_switch_does_not_persist`；其余 20 条仍绿（证明击杀精确非连坐） |
| C4 | models.py 默认标题改回「未命名草稿」 | models.py 一处替换 | **1 failed**：`test_default_title_is_named_conversation`（三层一致性锁精确击杀：服务层参数默认未改，比对失配即死） |
| C5 | 撤 /auth/me 的 response_model | auth.py 一处替换 | **1 failed**：`test_all_json_endpoints_declare_envelope` |

变异结束后工作区 `git status` clean（5 处变异全部还原）。

## 5. 真服务冒烟（uvicorn --workers 1 + 临时库/临时 Chroma 目录 + seed，全程 HTTP 黑盒，25/25）

预热就绪（真实本地模型 13–20s 加载）→ seed admin 登录 → 建库/上传/索引 ready（**端口注入后的真实解析链路**）→ 切片预览非空 → **409 门实测**：未确认切换 openai_compat → 409 + `need_rebuild/knowledge_base_ids/from/to` 契约字段 + request_id 非空 → confirm=true 切 hashing → 200 + `rebuilt` 含本库（**H-3 重构后全量重建真跑**）→ 检索 `degraded=true + fallback_reason=hashing_embed_no_semantics + rag_hit=false`（哨兵降级可见）→ `/code/analyze` 字段面 + 二次调用 `reused=true` → `/code/run` accepted + `limit_detail` 六层结构 → model-config GET 掩码/PUT revision 自增/test ok=true → 习题 facets/错题判分/错题本/推荐 → 13 端点信封四字段严等抽查 → 404 错误信封 +「代码会话不存在」新词实测。

冒烟临时目录与进程已清理。

## 6. 未验证项（如实）

- 真实 OpenAI 兼容提供方全链路（无 Key，与本批无关的既有边界）。
- 前端四断点视觉回归（本批前端仅动文案字符串与注释，vue-tsc/build/vitest 全绿即本批口径；视觉项归 README+收尾批次）。
- 高负载下 `test_memory_hog_is_killed_by_memory_layer` flake（H-1 既有负载敏感项，本批全程按串行纪律执行未复现）。

## 7. 移交清单（README+收尾批次，不在本批范围）

README 统一撰写（含默认管理员密码警示 M-3/旧编号 M15）、答辩口径、混合检索、真实 LLM Key 全链路、L-2 短密钥掩码已修但 README 说明待写。

## 8. 结论

六项全部落地：lint 35→0、M-3 54 端点信封（响应体 IDENTICAL + openapi 只增量化证明）、M-4/M-5 消解、H-3 红线 grep=0 且 B1 回归与 409 门变异击杀双保险、spec 漂移 3/4/5 收口。全量 1006/2、冒烟 25/25、变异 6 组全部精确击杀并字节级还原。**停下等总指挥审阅，未做任何 merge。**
