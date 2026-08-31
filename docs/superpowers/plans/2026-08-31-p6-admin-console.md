# P6 管理后台收口 Implementation Plan

> 本计划已于 2026-08-31 经总指挥审阅**通过**：§4/§8 八项全部裁定（含 2 处修订/补充），并新增
> 裁定 9（KB.owner_id 悬空例外）。各裁定已回填 §3 契约定稿、Task 2/3 用例清单与 §5 回写清单，
> 均标注「已裁定 2026-08-31」。

## 0. 测试基线（本 agent 于 2026-08-31 在 main @ 8264001 独立复跑，非转述）

| 项 | 值 | 备注 |
|---|---|---|
| 后端 pytest | **955 passed / 2 skipped（172.36s）** | 首跑命中 H-1 负载敏感 flake（`test_memory_hog_is_killed_by_memory_layer` 1 failed）；隔离复跑 1 passed（0.22s）；随后干净复跑全量 955/2，与总指挥基线一致。2 条 skip 为 `test_retrieval_quality_realistic.py` 语料条件 skip，与本批无关 |
| 前端 vitest | 8 passed | `npx vitest run`（`npm test` 在本机进 watch 模式） |
| 前端 vue-tsc | 零错误 | `npx vue-tsc --noEmit` |
| 前端 vite build | 通过（26.20s） | 本 agent 首测在**双构建并发**下 Node 堆 OOM；总指挥在 main @ 8264001 两次**串行**单构建均成功（33.45s / 28.30s，未设 NODE_OPTIONS）——OOM 仅发生于并发内存压力，**不是本机常态**。串行纪律采纳（完成报告须如实记录「串行单构建无 OOM」）；`NODE_OPTIONS=--max-old-space-size=4096` 无害可保留 |
| make lint | 35 errors（exit 2） | P0/P1 存量，本批新文件零告警、总数不得上涨，禁顺手修 |
| git | main @ 8264001，工作树 clean | 分支 `feat/p6-admin-console` 已切出 |

## 1. Global Constraints（引用 AGENT.md / spec §4.2 / 决策库，不再重复论证）

1. 分层 routers → services → domain → infrastructure；领域层零 IO；**新代码一律端口注入**。
   `indexing_service.py:30,136`、`model_config_service.py:15-19,223,315` 的 H-3 直连违规
   **原样保留、禁止模仿、禁止顺手修**。
2. models 只用 `UTCDateTime`、全库禁 ForeignKey；级联靠服务层手工序列。禁硬编码 `request_id=""`；
   全部端点挂 `CurrentRidDep`，admin 端点另挂 `AdminDep`（`Annotated[User, Depends(require_admin)]`，
   照 `admin_exercise.py:32` 先例）并写 AuditLog。新错误码须注册 `core/errors.py::CODE_STATUS`
   —— **本批计划零新错误码**（详见 §3）。
3. 术语照 CONTEXT.md；用户可见文案零违禁词（「题目/试题/草稿」不得出现；M-5 既有「未命名草稿」
   本批不动、也不模仿）。
4. 防抄袭统计口径只数 `role=user`（P2 偏离 4）：后端 `anti_plagiarism_stats.py` 不改，前端页面
   说明文案必须写明。
5. 测试离线约定不破坏（conftest 已内置 `HF_HUB_OFFLINE=1`）；H-1 负载纪律：**后端 pytest、
   前端 vue-tsc、vite build 三者串行跑，禁止满负载并行**（并发双构建实测 OOM，串行单构建无 OOM）。
6. 测试门槛：每个后端 Task 完成后全量 `cd backend && . .venv/bin/activate && python -m pytest -q`
   通过；前端 Task 完成门槛 = `npx vitest run` + `npx vue-tsc --noEmit` + vite build 三者全过。
7. merge 与远端操作不在授权内；禁止直接在 main 上提交。

## 2. File Structure

```
backend/
├── app/
│   ├── routers/
│   │   ├── admin_users.py            # 新增：用户 CRUD 三/四端点
│   │   ├── admin_model_config.py     # 扩展：GET/PUT /model-config、POST /model-config/test
│   │   ├── admin_stats.py            # 扩展：GET /admin/logs、GET /admin/overview
│   │   └── （main.py                 # 修改：删除 /admin/ping 占位与 _admin 子路由）
│   ├── services/
│   │   ├── user_service.py           # 新增：用户 CRUD + 硬删除级联
│   │   ├── model_config_service.py   # 扩展：update_llm_config / test_connection（只加方法，不动 H-3 违规行）
│   │   ├── audit_service.py          # 扩展：list_logs 分页查询
│   │   └── overview_service.py       # 新增：仪表盘聚合
│   ├── schemas/
│   │   └── admin.py                  # 新增：UserIn/UserPatch/UserOut、ModelConfigOut/ModelConfigPut、LogOut、OverviewOut
│   └── core/
│       └── crypto.py                 # 修改：mask_api_key 短密钥防护（L-2，约一行）
├── tests/
│   ├── test_admin_users_api.py       # 新增：CRUD/软删 4030/硬删级联/审计保留/顺序专项
│   ├── test_admin_model_config_api.py# 新增：GET 掩码/PUT revision/409 流程不动/test 端点
│   ├── test_admin_logs_overview.py   # 新增：logs 筛选分页、overview 聚合
│   ├── test_auth_deps.py             # 扩展：M-8「token 有效但用户已删 → 4010」
│   ├── test_registry.py              # 扩展：mask_api_key 短密钥用例
│   └── test_auth_api.py              # 修改：test_admin_route_blocks_student 的 /admin/ping 改为真实端点
frontend/
├── public/
│   └── favicon.svg                   # 新增（裁定 6：静态文件）
├── index.html                        # 修改：favicon link
├── src/
│   ├── api/
│   │   └── admin.ts                  # 新增：users / model-config / logs / overview / stats / exercises(admin) 客户端
│   ├── types/
│   │   └── admin.ts                  # 新增：出参 TS 类型
│   ├── router/index.ts               # 修改：六个 admin 路由（requiresAdmin）
│   ├── components/AppShell.vue       # 修改：导航新增五项（adminOnly）
│   └── views/admin/
│       ├── UsersAdminView.vue        # 新增
│       ├── ModelConfigView.vue       # 新增
│       ├── LogsView.vue              # 新增
│       ├── OverviewView.vue          # 新增
│       ├── AntiPlagiarismStatsView.vue # 新增
│       └── ExerciseAdminView.vue     # 新增（P5 遗留：对接既有五端点）
README.md                              # 修改：M-15（默认管理员警示 + 40 题说明 + 后台安全边界声明条）
docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md  # 收尾 Task 回写
docs/review/2026-08-31-p6-completion-report.md                     # 收尾 Task 产出
```

## 3. 契约定稿（八项已于 2026-08-31 全部裁定，见 §8）

统一约定沿用 spec §6.2：前缀 `/api/v1`、统一响应 `{code, message, data, request_id}`、
分页 `page`+`page_size` → `{items, total}`。**零新错误码**：重复账号 4090（注册先例）、
不存在 4040、停用 4030、参数 4220、需要确认 4090，全部已在 `CODE_STATUS`。

### 3.1 用户管理（spec §6.2 admin 行 / §8.9）

- `GET /admin/users?q=&role=&status=&page=&page_size=` → `{items, total}`。
  `q` 对 username/email 前缀模糊匹配（SQLite 演示规模用 `LIKE '%q%'`，Python 层过滤亦可，
  实现取 SQL `contains`）；`role` 取值 `student|admin`，`status` 取值 `active|disabled`，
  非法取值 422（Query pattern）。按 `created_at` 倒序。
- 出参 UserOut（**裁定 4**，已裁定 2026-08-31）：`id, username, email, role, status,
  created_at, last_login_at` —— **包含 email**（管理员互见）；`hashed_password` 永不出参。
- `POST /admin/users`：`{username, email, password, role?, status?}`，role 默认 `student`、
  status 默认 `active`；密码复用注册校验（8–128 位）与 `hash_password`（bcrypt 经
  `run_in_threadpool`，照 `auth_service.py:32` 先例）；username/email 重复 → 4090。
  审计 `admin_user_create`（detail 不含密码明文与哈希）。
- `PATCH /admin/users/{id}`：`{status?, role?, email?, password?}` 全可选，schema
  `extra=forbid`（照 P5 ExercisePatch 先例，schema 外字段 422 显式拒绝）。
  `status:"disabled"` 即软删除——日常路径，**保留全部数据**；停用后该用户所有
  `get_current_user` 路径 4030（`deps.py:37-38` 既有分支，无需新代码，补用例）。
  传 password 即管理员重置密码（重哈希）。审计 `admin_user_update`（detail 记
  `fields` 列表，不记值——密码与 email 均不进审计）。
  **对自己的 role/status 变更一律 4220**（裁定 1 扩面，已裁定 2026-08-31）：
  自降权 student、自停用 disabled 与自删同样锁死；email/password 自改允许。
- `DELETE /admin/users/{id}` 硬删除级联（spec §8.9）：
  - 按序删除 **会话 → 消息 → 提交 → 错题条目 → 代码会话 → 代码分析 → 代码运行**，
    再删 User 行。实现口径：先取该用户全部 conversation_id，删其 messages，
    再删 conversations；其余六表按 `user_id` 逐表 `delete()` 计数（照
    `exercise_service.delete` 与 `knowledge_service.delete` 手工级联先例）。
    `KnowledgeBase.owner_id` 与 `AuditLog.user_id` **不在级联清单**（spec §8.9 只列七类；
    AuditLog 一律保留）。
  - **审计保留用例**：删除前为该用户造若干审计行，删除后断言 AuditLog 行数不变。
  - `AuditLog(action=admin_user_delete)` 照 `admin_exercise_delete` 先例，detail 带全部
    **级联计数**：`{username, conversations_deleted, messages_deleted, submissions_deleted,
    mistake_entries_deleted, code_sessions_deleted, code_analyses_deleted, code_runs_deleted}`。
  - 目标不存在 → 4040。
  - **管理员自删/互删约束（裁定 1 扩面，已裁定 2026-08-31）**：删除自己 → 4220；
    删除/停用/降权**其他 admin** 时校验「操作后系统至少剩余 1 名 `role=admin 且
    status=active` 的用户」，否则 4220（防锁死：演示系统无 CLI 建号通道，最后一个
    admin 失效即不可恢复）。
  - **KB.owner_id 悬空例外（裁定 9，已裁定 2026-08-31）**：硬删除**不级联知识库**
    （照 spec §8.9 七类清单）。UserService.delete 的 docstring 与 §8.9 回写必须显式
    注明该例外及理由；须确认知识库展示对 owner 缺失容忍——一个删除了建库管理员的
    系统，KB 不能因此 5000 或消失（用例锁定）。
  - **级联执行方式（裁定 5，已裁定 2026-08-31）**：单事务同步删除（演示规模数据量小，
    与 admin_exercise_delete 同口径）。

### 3.2 模型配置（spec §6.2 admin 行 / §4.2 硬约束 4 / §8.7 / §8.8）

- `GET /admin/model-config`：出参 `provider, model, base_url, api_key(掩码), temperature,
  top_p, max_tokens, anti_plagiarism_mode, score_threshold, top_k, embedding_provider,
  embedding_model, revision, updated_by, updated_at`。api_key 走 `decrypt_api_key` →
  `mask_api_key`（CONTEXT.md「API Key 掩码」：`sk-****abcd` 面向展示，Fernet 面向落盘）。
- `PUT /admin/model-config`（**裁定 2**，已裁定 2026-08-31）字段面定稿：
  `{provider(mock|openai_compat), model, base_url?, api_key?, temperature?, top_p?,
  max_tokens?, anti_plagiarism_mode(strict|guided|loose), score_threshold?, top_k?}`，
  `extra=forbid`。校验：model 非空；temperature ∈ [0,2]；top_p ∈ (0,1]；max_tokens ≥ 1；
  top_k ∈ [1,20]；score_threshold ∈ [0,1] 或 null（null=恢复「按模型默认值」语义，
  `models.py:60` M1 约定）；**api_key 语义**：字段缺省/null = 不变更（掩码回显导致前端
  常态回传 null，绝不能把已有密钥清掉），空串 = 4220 拒绝（「清除密钥」不提供——provider
  回 mock 即等效）。**保存时机校验（裁定 2 追加，已裁定 2026-08-31）**：PUT 后
  `provider=openai_compat` 且（本次未提供 api_key 且库中无 key）→ **4220 拒绝保存**
  —— 静默降级会把「配置错误」伪装成「降级运行」，该校验成本为零。
  **mock_token_delay_ms 不入 PUT 字段面（方案 A，已裁定 2026-08-31）**：它是
  `Settings` env 配置（`config.py:29`），`MockProvider.stream()` 直读 settings
  （`mock_provider.py:83`），无 ModelConfig 列、无 revision 链路。裁定不考虑方案 B
  （增列牵动 ADR-0006 的「create_all 不迁移，既有库缺列」问题，超出本批最小改动面）。
  保存即 `revision += 1`（`model_config_service.py:74-75` 既有机制）、`updated_by=管理员`，
  审计 `admin_model_config_update`（detail 记字段清单 + 掩码化 api_key 变更与否）。
  **embedding_provider/embedding_model 不入本 PUT**——仍走既有 `/model-config/embedding`
  409 重建流程（spec §8.7，PR-B1 三道闸），本批不动。
- **热生效（spec §4.2 硬约束 4）**：`refresh_llm_config` / `refresh_embedder_config` 以
  revision 为缓存失效键（`app/infrastructure/registry.py:53-70`，ProviderRegistry 缓存与
  `_revision` 比对），PUT 保存后**下一次调用即用新值**。
  必须有端到端用例：PUT 改 `model`/`anti_plagiarism_mode` → 不重启进程 → 断言
  `get_llm_runtime().snapshot()`（或 chat/hint 链路 `done` 载荷）已用新值；revision 自增断言。
- `POST /admin/model-config/test` → `{ok, latency_ms, sample}`：用**当前已保存配置**
  发起一次真实调用（openai_compat 有 key → 走其 complete；否则 Mock），latency_ms 取
  单次调用实测耗时，sample 取生成文本前 N 字符。**测试失败不抛 5xx**：返回
  `ok:false` + `latency_ms:null` + `sample` 置错误说明（管理页可展示，不打爆全局异常码）。
  请求体缺省为空对象；**裁定 2 附项（已裁定 2026-08-31）**：test 端点只测已保存配置，
  不接受覆盖参数（面最小），前端「先保存再测试」。

### 3.3 日志查询（spec §6.2 admin 行）

- `GET /admin/logs?action=&user_id=&start=&end=&page=&page_size=` → `{items, total}`，
  按 `created_at` 倒序。`start/end` 为 ISO 8601 日期或日期时间（含日期按当日 00:00/23:59:59
  闭合区间解析，非法 422）；`action` 精确匹配（index 列在）；`user_id` 精确匹配。
- LogOut 出参：`id, user_id, action, target_type, target_id, detail, ip, request_id,
  created_at`（审计行全字段回显——管理页就是给管理员看的）。
- 实现落 `AuditService.list_logs()`（审计域的查询归审计服务，不新建路由服务），
  照 `admin_exercise.list` 的 SQL where 拼装风格。
- 日志页说明文案（裁定 8，已裁定 2026-08-31）：页面顶部固定说明「审计日志记录管理操作与关键
  行为留痕，仅可查询、不可修改或删除」。

### 3.4 仪表盘聚合（spec §6.2 admin 行，P2 遗留 7.3）

- `GET /admin/overview`（**裁定 3**，已裁定 2026-08-31）字段面定稿（最小集；回写 §6.2
  时标注「最小集，实际响应为超集」）：
  ```json
  {
    "users": {"total": 0, "active": 0, "admin": 0},
    "conversations": 0,
    "messages": 0,
    "knowledge_bases": 0,
    "documents": 0,
    "exercises": {"published": 0, "draft": 0},
    "submissions": 0,
    "mistake_entries": {"total": 0, "unmastered": 0},
    "audit_logs": 0,
    "model_config": {"provider": "mock", "model": "mock-1",
                     "anti_plagiarism_mode": "guided", "revision": 1},
    "embedder": {"ready": true, "level": 0, "model": "..."}
  }
  ```
  计数全部 `select(func.count())`，演示规模单事务聚合；`embedder` 直接复用
  `get_embedder_runtime().snapshot()`（/health 同源）。实现落新 `OverviewService`。

### 3.5 删除 `/admin/ping`（L-1）

- 已 grep 全仓：`/admin/ping` 仅两处——`main.py:89-92`（端点本体）与
  `backend/tests/test_auth_api.py:111`（`test_admin_route_blocks_student`）。
  spec §6.2 从未收录（健康检查漂移 1），**删除不破坏任何契约测试**。
  处置：删 `main.py` 的 `_admin` 子路由整体；`test_admin_route_blocks_student` 改打
  `GET /api/v1/admin/users`（Task 1 落地后存在，语义不变：学生 4030）。
  spec 无需回写。

### 3.6 前端

- 六个路由全部懒加载独立 chunk + `meta: { requiresAdmin: true }`（照既有
  `admin/knowledge` 先例）；AppShell 导航新增五项 `adminOnly: true`（用户管理/模型配置/
  系统日志/仪表盘/防抄袭统计；admin·exercise 管理页归入「习题管理」第 6 项——或并入
  习题练习入口旁，实现时按导航宽度取舍，均为 adminOnly）。
- api/admin.ts 照 `api/mistake.ts` 风格薄封装；types/admin.ts 出参类型与 §3 出参一一对应。
- 样式复用既有 CSS 变量体系与 Element Plus 组件，零硬编码色值（ui-baseline §7）。
- 防抄袭统计页说明文案（裁定 8，已裁定 2026-08-31）：**「统计口径：仅统计学生（role=user）
  发起的答疑请求；拦截率 = 触发底线次数 / 总请求数，是度量口径，不是抄袭检出能力」**
  （`anti_plagiarism_stats.py` docstring 的页面化，CONTEXT.md「拦截率」消歧说明）。
- 模型配置页：api_key 输入框留空 = 不变更（对应 §3.2 语义），旁注「仅在实际调用时解密，
  读取接口一律掩码显示」。
- 用户管理页：硬删除按钮二次确认（ElMessageBox，照 MistakeBookView 重置掌握度先例），
  确认文案写明「硬删除将级联清除该用户全部数据且不可恢复，审计日志保留」。

## 4. Tasks

每个后端 Task 完成且全量 pytest 通过后按 Task 粒度 commit（授权见 §7/AGENT.md P6 行）；
前端 Task 以三件套通过为门槛。

- **Task 0 实施计划**：本文件 + AGENT.md P6 授权行登记，一次 docs commit。✅（本次）
- **Task 1 用户 CRUD（软路径）+ L-2 + M-8**：schemas/admin.py（UserOut/UserIn/UserPatch）
  + UserService（list/create/update）+ routers/admin_users.py（GET/POST/PATCH）+
  `mask_api_key` 短密钥防护与用例 + `test_auth_deps.py` 补「token 有效但用户已删 → 4010」
  （M-8/M11 收口）。用例：列表分页与 q/role/status 筛选、4090 重复、PATCH extra=forbid 422、
  停用后登录/访问 4030、掩码用例。审计 `admin_user_create/update`。
- **Task 2 用户硬删除级联**：UserService.delete（§3.1 七级联顺序；docstring 逐项列出
  七类级联清单 + 两项不级联例外 AuditLog / KB.owner_id——裁定 V7 附带要求）+
  `admin_user_delete` 审计含级联计数 + 裁定 1 全量约束落地。专项用例：①级联（造全七类
  数据 → 删除 → 七表计数归零、AuditLog 不动）②审计保留 ③级联计数进 detail ④4040
  ⑤自删 4220 ⑥自停用/自降权 4220（PATCH 路径）⑦删/停/降权末位 admin 4220
  ⑧KB.owner_id 例外：删除建库 admin 后知识库列表/详情仍可读、不 5000 不消失。
- **Task 3 model-config GET/PUT**：ModelConfigService 扩展（`update_llm_config`：
  字段面按裁定 2 定稿、api_key 缺省=null=不变更 / 空串 4220、openai_compat 无 key
  4220 拒绝保存、revision+=1、`admin_model_config_update` 审计）
  + admin_model_config.py 扩展两端点 + schemas。用例：GET 掩码/不出明文、PUT 各字段校验
  422 面、api_key 缺省不清除、openai_compat 且库中无 key → 4220、**revision 热生效
  端到端**（PUT → snapshot 断言新值）、embedding 两字段不在 PUT 面、审计行。
- **Task 4 model-config/test**：POST /admin/model-config/test（§3.2）。用例：mock 配置
  ok=true 且 sample 非空、故意坏 base_url（openai_compat + 假地址）→ ok=false 不 5xx。
- **Task 5 logs 查询**：AuditService.list_logs + GET /admin/logs（挂 admin_stats.py）。
  用例：action/user_id/start/end 四筛选、分页 {items,total}、倒序、start>end 422 或空集
  （取 422，见用例落地时与 FastAPI Query 校验一致性）。
- **Task 6 overview 聚合**：OverviewService + GET /admin/overview（挂 admin_stats.py）。
  用例：空库全零不出错、造数后各计数正确、embedder snapshot 字段存在。
- **Task 7 删除 /admin/ping**：main.py 移除 `_admin` 子路由 + `test_auth_api.py:111`
  改打 `/admin/users` + OpenAPI 路径数回归（test_smoke 若断言路径数则同步）。用例：
  GET /admin/ping → 4040（SPA fallback 前 API 404 语义）。
- **Task 8 前端基建**：api/admin.ts、types/admin.ts、router 六路由、AppShell 导航五项
  （adminOnly）。门槛三件套。
- **Task 9 用户管理页**：列表（q/role/status 筛选 + 分页）、新建、编辑（含重置密码）、
  停用/启用、硬删除二次确认（文案见 §3.6）。门槛三件套。
- **Task 10 模型配置页**：表单全字段 + api_key 留空不变更语义 + 保存/测试按钮 +
  revision 回显 + 防抄袭档位三选一 + embedding 区只读提示「embedding 配置请在知识库
  管理页切换（触发重建流程）」。门槛三件套。
- **Task 11 日志页 + 仪表盘页 + 防抄袭统计页**：日志筛选表 + 分页；仪表盘指标卡 +
  embedder 就绪状态；统计页三档表格 + overall + 口径文案（裁定 8）。门槛三件套。
- **Task 12 admin·exercise 管理页**（P5 遗留）：列表（五端点对接：type/difficulty/
  knowledge_tag/status 筛选）、新建/编辑表单（含 shapes 422 错误展示）、发布/下架、
  删除二次确认。门槛三件套。
- **Task 13 顺带收口**：M-15 README（默认管理员 admin / Admin@12345 + 首次登录立即修改
  警示 + 「make seed 后题库含 40 道习题」说明 + 后台安全边界声明条：admin 路由有 JWT 与
  require_admin 拦截，但默认口令公开于本 README、无 IP 白名单/失败锁定/审计防篡改，
  演示项目请勿真实部署）；L-3 favicon（裁定 6：`frontend/public/favicon.svg` 静态文件 +
  index.html link）。后端门槛 pytest，前端门槛含 build。
- **Task 14 收尾**：spec 回写（§5 清单）→ 变异测试逐条实拆（§6）→ 真服务冒烟
  （uvicorn 单 worker + 临时库：软删 4030、硬删级联计数、配置热生效、logs/overview/stats
  真数据）→ `docs/review/2026-08-31-p6-completion-report.md` → **停下等总指挥审阅，
  不做任何 merge**。

## 5. spec 回写项清单（Task 14 执行，逐条标注「P6 补记」）

1. §6.2 admin 行（users）：出参字段面（含 email）、POST/PATCH 校验面（extra=forbid、
   4090 重复、禁自降权/自停用）、软删/硬删双路径、级联计数入审计 detail、
   自删禁令 + 末位 active admin 约束（裁定 1）。
2. §6.2 admin 行（model-config）：GET/PUT 字段面与 api_key「缺省=不变更」语义、
   embedding 字段不入 PUT（仍走 409 流程）、test 端点返回 `{ok, latency_ms, sample}`
   与 ok=false 不抛 5xx。
3. §6.2 admin 行（logs）：筛选参数与出参字段面、倒序分页。
4. §6.2 admin 行（overview）：指标集（按「实际响应为超集」惯例收录，标注最小集）。
5. §8.9 补 P6 实记：七类级联与计数审计落地、管理员自删禁令与末位 active admin 约束
   （裁定 1）、**KB.owner_id 悬空例外及理由**（裁定 9——硬删除不级联知识库，
   知识库功能对 owner 缺失必须容忍）。
6. 健康检查漂移 1（/admin/ping OpenAPI 存在、spec 未列）随删除自然消解——回写处注明
   「占位端点已移除」。
7. 零新错误码：不加 §9 条目；如有偏离再补。

## 6. 变异测试指引（Task 14 逐条实拆：改坏 → 目标测试必须失败 → 字节级还原 → `git status` 干净）

| # | 变异点 | 预期失败用例 |
|---|---|---|
| V1 | 硬删除级联里把 AuditLog 一并按 user_id 删除 | 审计保留用例 |
| V2 | `admin_user_delete` 审计 detail 漏掉任一级联计数（或计数写死 0） | 级联计数用例 |
| V3 | PUT /admin/model-config 去掉 `revision += 1` | revision 热生效端到端用例 |
| V4 | PATCH status=disabled 不生效（或 `can_login` 判定反转） | 停用用户 4030 用例 |
| V5 | logs 查询丢掉任一筛选参数的 where 条件 | logs 筛选用例 |
| V6 | `mask_api_key` 还原短密钥泄露（≤7 位全文返回） | L-2 掩码用例 |
| V7 | UserService.delete 打乱级联顺序（消息先于会话删除的计数归并不影响正确性——顺序变异以「漏删某表」替代：注释掉 code_runs 删除行） | 顺序专项用例 |

> V7 说明（已裁定 2026-08-31）：无 FK 下七表删除彼此独立，「顺序」只有配合漏删才可观测；
> 顺序专项用例的实际守卫是**逐表计数归零**，故以漏删作变异体。真顺序断言不做——任意删除
> 次序在 DB 层等价，顺序只是代码注释约定，审计顺序号属过度设计。**附带要求**：七类级联
> 清单 + 两项不级联例外（AuditLog / KB.owner_id）在 UserService.delete docstring **逐项
> 列出**——防后续批次新增表时有人忘了更新级联清单，这是无 FK 架构的真正长期风险。

## 7. Commit 授权

用户已于 2026-08-31 预先授权（AGENT.md 授权例外表 P6 行，随本次 docs commit 登记）：
每个 Task 完成且全量测试通过后，按 Task 粒度 `git commit`，无需逐次请示。
merge / push / remote 不在授权内。

## 8. 问题清单（**已裁定 2026-08-31**，总指挥逐条批复；#1/#2 含修订/补充，新增 #9）

| # | 问题 | 裁定 |
|---|---|---|
| 1 | 管理员能否硬删除自己？能否硬删除其他 admin？ | **采纳推荐并扩面**：禁自删（4220）；同时禁对自己的 role/status 变更（自降权/自停用与自删同锁死，4220）；删/停/降权其他 admin 须剩余 ≥1 名 `role=admin 且 status=active`，否则 4220。email/password 自改允许 |
| 2 | PUT /admin/model-config 字段面与校验；api_key 语义；test 输入面 | **采纳方案 A**（mock_token_delay_ms 不入 PUT）+ api_key 缺省/null=不变更、空串 4220 + test 只测已保存配置。**追加**：PUT 后 openai_compat 且（本次未提供且库中无）key → 4220 拒绝保存 |
| 3 | /admin/overview 指标集 | **采纳**最小集（11 组计数 + 配置摘要 + embedder 快照），回写 §6.2 标注「最小集，实际响应为超集」 |
| 4 | 用户列表出参是否含 email | **采纳**含 email（管理员互见）；hashed_password 永不出参 |
| 5 | 硬删除级联执行方式 | **采纳**单事务同步删除 |
| 6 | favicon 形态 | **采纳** `frontend/public/favicon.svg` + index.html link |
| 7 | 删除 /admin/ping 是否破坏测试 | **采纳**删除；test_auth_api.py:111 改打 /admin/users |
| 8 | 统计页与日志页文案口径 | **采纳**两段文案（统计口径只数 role=user；审计仅查询不可改） |
| 9 | KB.owner_id 悬空例外（计划遗漏，总指挥补） | 硬删除不级联知识库（照 §8.9 七类清单），但 ① UserService.delete docstring 与 §8.9 回写显式注明例外及理由 ② 确认知识库展示对 owner 缺失容忍——KB 不能因此 5000 或消失 |

**V7 附带裁定**：采纳「漏删为变异体 + 逐表计数归零」；真顺序断言不做；七类级联清单 +
两项不级联例外（AuditLog / KB.owner_id）在 docstring 逐项列出（见 §6 V7）。

**OOM 事项更正**：总指挥在 main @ 8264001 两次串行 `npx vite build` 均成功（33.45s /
28.30s，未设 NODE_OPTIONS），无 OOM；本 agent 的 OOM 发生于与 pytest 并行或双构建并发的
内存压力下。裁定：串行纪律采纳；NODE_OPTIONS=4096 无害可保留；**完成报告必须如实记录
「串行单构建无 OOM」，不得把 OOM 写成本机常态**。

**文件引用更正**：本计划 §3.2 原引 `runtime.py:126-144` 不准，实为
`app/infrastructure/registry.py:53-70`（已改）。

## 9. 风险清单

1. **vite build 并发 OOM**（双构建并发下实测；串行单构建无 OOM，见 §8 更正）：
   严禁并行双构建、与后端 pytest 串行；`NODE_OPTIONS=--max-old-space-size=4096` 无害可保留。
2. **H-1 负载敏感**：pytest 全量 ~173s 期间不做任何重活；flake 复现时先隔离复跑再下结论。
3. **级联顺序**：无 FK，漏删即孤儿——V7 漏删变异 + 顺序专项用例守卫。
4. **api_key 误清除**：掩码回显 + 前端回传 null 的组合最容易把密钥清掉，用例显式锁死
   「缺省=不变更」。
5. **overview 聚合面**：字段集未经 spec 定义，回写前以裁定结果为准，避免过度设计。
6. **禁改清单**：H-3 两处直连、M-5「未命名草稿」、检索服务、embedding 409 流程、
   lint 35 存量——本批新代码零模仿。

## 10. 验收清单（P6 完成标准）

- [ ] 后端全量 pytest 通过（基线 955/2 随 Task 递增，以实跑为准）
- [ ] 前端 vitest + vue-tsc + vite build 三件套通过
- [ ] make lint 总数不上涨（35 存量不变），新文件零告警
- [ ] §6 变异测试逐条实拆记录在完成报告
- [ ] 真服务冒烟四项通过（软删 4030 / 硬删级联计数 / 配置热生效 / logs·overview·stats 真数据）
- [ ] spec 回写七条落地并标注 P6 补记
- [ ] 完成报告 `docs/review/2026-08-31-p6-completion-report.md` 交付，停下等审阅
