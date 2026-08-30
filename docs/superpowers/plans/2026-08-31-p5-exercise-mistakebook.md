# P5 习题与错题本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 P5 全部内容——三张新表（Exercise / Submission / MistakeBookEntry）、判题四路（choice/multi/blank 即时判分 + coding 受限执行 + short AI 评分）、掌握度状态机（可回滚）、学生端端点（习题列表/详情/提交/hint SSE + 错题本四端点）、admin 习题 CRUD（spec §6.2 缺口补全）、`backend/seeds/` 包迁移 + 约 40 题种子、前端学生端两页（习题练习页 + 错题本页）、遗留项（M2 seeds 目录、M4 端口契约测试补全、M6 死代码删除）与 spec 回写。

**Architecture:** 沿用 P0–P4 的 `routers → services → domain → infrastructure` 分层。判题规则与掌握度状态机是确定性纯规则，按 P3 裁定先例落**领域层**（`domain/exercise/`，零 IO，可脱离数据库单测）；coding 判题的执行编排、15s 累计预算、简答题 AI 评分的 LLM 调用落**服务层**（`ExerciseService` / `MistakeBookService`），执行一律经端口注入的 `CodeExecutor` + `run_in_threadpool` 卸载；hint 复用 chat 的 SSE 全套模式（`infrastructure/sse.py`、`citation` 先行、per-call 中断 Event、`finally` 注销 + 审计）；检索复用 `RetrievalService`（spec §7.2），reindexing 拦截语义自动继承、不改检索服务。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · SQLite (WAL) · Pydantic v2 · pytest · Vue 3 · Vite · TypeScript · Element Plus · Monaco（复用 P4 `CodeEditor`）· SSE

---

## 0. 测试基线（本 agent 于 2026-08-31 独立复跑，非转述）

| 项 | 实测值 |
|---|---|
| 后端 `pytest -q` | **661 passed / 2 skipped，121.34s**（2 条 skip 为 `test_retrieval_quality_realistic.py` 语料条件 skip，与本批无关） |
| 前端 `npm test`（vitest） | **8 passed** |
| `vue-tsc --noEmit` | 零错误 |
| `vite build` | 通过（Monaco 4MB 超限告警为既有已知项） |

**H-1 警示（健康检查）**：`test_code_executor.py::test_memory_hog_is_killed_by_memory_layer` 是负载敏感用例，**禁止满负载并行跑测试**（不要与前端构建同时跑）。本批新增的真子进程契约测试与种子自校验会拉长套件约 25–40s，同理。

## 1. Global Constraints

以下约束逐字来自 spec / AGENT.md / 批次裁定 / P5 提示词，每个任务默认包含，不再重复。

- 分层 `routers → services → domain → infrastructure`；领域层零 IO；**服务层只依赖 Protocol 端口**。`indexing_service.py:30,136` 与 `model_config_service.py:15-19,223,315` 的直连适配器违规属清理批次：**禁止模仿、禁止顺手修复**，新代码一律端口注入
- `CodeExecutor` 端口是**同步签名**（`ports/code_executor.py:47`）：判题执行必须经 `run_in_threadpool` 卸载（ADR-0002）；LLM 阻塞调用同理
- 判题超时（已裁定）：端口无 per-call 超时参数，「单题全部用例累计 15s 上限」由服务层自计——跨用例累计耗时，超预算中止剩余用例并按已通过比例判分，`judge_detail` 体现中止原因
- models 只用 `UTCDateTime`（SQLite 回读 naive datetime）；**禁止 ForeignKey**（照 M-2 现状，级联靠服务层手工序列）；新错误码必须注册进 `core/errors.py` 的 `CODE_STATUS`（本批预计无需新码，见 §3 契约定稿第 10 条）
- 每个端点挂 `CurrentRidDep`；admin CRUD 挂 `AdminDep`（`require_admin`）并写 `AuditLog`，action 命名沿用既有风格（`admin_kb_*` 同族）
- 术语照 CONTEXT.md：Exercise / Submission / MistakeBookEntry / Mastery / WeakKnowledgePoint / RandomFill / Judging；**不使用**「题目」「试题」「错题（作为实体名）」「草稿」——用户可见文案同样遵守（M-5 教训）
- 单 worker 前提（ADR-0002）；不引入消息队列 / 新进程 / 新重依赖
- 测试离线；`conftest.py` 集中管理（`MOCK_TOKEN_DELAY_MS=0`、`HF_HUB_OFFLINE=1` 等既有约定不得破坏）
- 建表 `create_all` 不迁移（ADR-0006）；统一响应 `{code, message, data, request_id}`；禁止硬编码 `request_id=""`
- 禁止任何远端操作（`git push` / `git remote add`）；`merge` 必须用户下令
- 每个后端 Task 完成后跑全量后端测试（`cd backend && . .venv/bin/activate && python -m pytest -q`），基线 661 passed / 2 skipped 随任务递增，以实际为准；前端 Task 完成后跑 `npm test` + `npx vue-tsc --noEmit` + `npx vite build`（三者全过才算完成）

### Commit 策略

用户已于 **2026-08-31 预先授权**（`AGENT.md` 授权例外表 P5 行）：本计划每个 Task 完成且全量测试通过后，**可直接按 Task 粒度 `git commit`**，无需逐次请示。**`merge` 与远端操作不在授权内**。阶段一（本计划文档）仅允许一次 `docs:` commit。

### 本批次的已裁定决策（不再讨论，直接执行）

1. 判题超时：服务层自计「单题全部用例累计 15s」预算（2026-08-31 审计裁定）
2. 习题来源：内置种子约 40 题 + 后台 CRUD（spec §6.2 缺口本批回写）
3. 掌握度：连续 2 次答对即掌握，**错误时必须回滚**（mastered=false、mastered_at=null）——硬要求，专项用例守护
4. 漏选（所选为正确答案的真子集）按错误处理：50 分、`is_correct=false`、计入错题本
5. hint intent 显式传入，不做语义推断；chat 入口一律 `seek_answer`
6. reindexing 检索语义已修复落库（默认作用域静默排除非 ready、显式 kb_ids → 5032、向量库故障 → 5032），**不要动检索服务**
7. SSE 协议；`fallback_reason` 是封闭三值枚举
8. hint 的 `seek_answer` 受防抄袭档位约束；`review_my_code` 豁免档位但 `_floor.j2` 三条底线仍注入——**免的是档位不是底线**（同 spec §8.4 对 `/code/analyze` 的处理）
9. hint 的 RAG query 取 `stem + knowledge_tags`，**不含学生作答**（spec §7.2：防错误答案污染相似度）

---

## 2. File Structure

```
backend/
├── app/
│   ├── domain/exercise/               # 新领域包（零 IO）
│   │   ├── __init__.py
│   │   ├── judging.py                 # 判题四路的纯规则 + 题型/来源/状态常量
│   │   ├── mastery.py                 # 掌握度状态机（可回滚）
│   │   ├── short_scoring.py           # 简答评分：prompt 构建 / Mock 启发式 / JSON 解析
│   │   └── hint.py                    # hint 问题串构建 + 模板选择
│   ├── infrastructure/persistence/models.py   # 追加 Exercise / Submission / MistakeBookEntry
│   ├── prompts/                       # （exercise_hint.j2 / mistake_review.j2 已在库，不改）
│   ├── schemas/exercise.py            # 出入参（新建）
│   ├── services/
│   │   ├── exercise_service.py        # 列表/详情/判题提交/hint SSE（新建）
│   │   ├── mistake_service.py         # 错题条目/画像/推荐/重置掌握（新建）
│   │   └── chat_service.py            # 删除死代码 count_actions（M-6，357 行起）
│   ├── routers/
│   │   ├── exercise.py                # 学生端：GET /exercises*、POST submit、POST hint
│   │   ├── mistake.py                 # 学生端：GET /mistakes*、DELETE .../mastered
│   │   └── admin_exercise.py          # 管理端 CRUD（spec §6.2 缺口）
│   ├── main.py                        # 注册 3 个新路由
│   └── seed.py                        # 变薄壳：委托 backend/seeds/（CLI 入口与 Makefile 不变）
├── seeds/                             # 新包（spec §4.3；M2 落地）
│   ├── __init__.py                    # seed(session) 编排：admin + ModelConfig + exercises
│   ├── admin.py                       # 自 app/seed.py 迁入
│   ├── model_config.py                # ModelConfig 单例迁移
│   └── exercises.py                   # 约 40 题数据 + 幂等写入（uuid5 确定性主键）
└── tests/
    ├── fakes.py                       # 追加 FakeExecutor（判题替身，集中管理）
    ├── test_exercise_models.py        # 三表
    ├── test_judging.py                # 判题纯规则
    ├── test_mastery.py                # 掌握度状态机（含回滚专项）
    ├── test_short_scoring.py          # 简答评分
    ├── test_executor_contract.py      # Fake vs 真执行器同组断言（M4）
    ├── test_exercise_service.py       # 判题编排 + 15s 预算
    ├── test_exercise_api.py           # 学生端 HTTP
    ├── test_mistake_service.py        # 错题服务
    ├── test_mistake_api.py            # 错题 HTTP
    ├── test_exercise_hint.py          # hint SSE
    ├── test_admin_exercise_api.py     # admin CRUD
    ├── test_seed.py                   # （回归，迁移后不破坏）
    └── test_seed_exercises.py         # 40 题幂等 + 自校验

frontend/src/
├── api/exercise.ts · api/mistake.ts   # 新 api 模块
├── types/exercise.ts · types/mistake.ts
├── views/student/ExerciseView.vue     # 习题练习页
├── views/student/MistakeBookView.vue  # 错题本页
├── router/index.ts                    # + /exercises、/mistakes（懒加载）
└── components/AppShell.vue            # + 两个导航项
```

---

## 3. 契约定稿（本批新增契约的实现口径；标注【待总指挥裁定】的六项不得先斩后奏）

1. **【待总指挥裁定】admin 习题 CRUD 形态**：新建 `routers/admin_exercise.py`，前缀 `/api/v1/admin/exercises`（照 `admin_knowledge.py` 风格），五端点：
   - `POST /admin/exercises`：body 为 `{type, stem, options?, answer, test_cases?, explanation?, knowledge_tags, difficulty, status?="draft"}`；`source` 服务端固定写 `admin`，`created_by` 取当前管理员 id
   - `GET /admin/exercises?type=&difficulty=&knowledge_tag=&status=&page=&page_size=` → `{items, total}`（spec 分页约定）
   - `GET /admin/exercises/{id}`（含 draft，学生端看不到的这里看得到）
   - `PATCH /admin/exercises/{id}`：全部字段可选更新（含 `status` 发布/下架）
   - `DELETE /admin/exercises/{id}`：**建议**手工级联删除该习题的 Submission 与 MistakeBookEntry（照 M-2 无 FK 现状的服务层手工序列，spec §8.9 用户硬删除同序），AuditLog detail 记录 `{submissions_deleted, mistake_entries_deleted}`；备选是存在 Submission 时 `4090` 拒绝。**计划采级联方案**，待裁定
   - 审计 action：`admin_exercise_create` / `admin_exercise_update` / `admin_exercise_delete`（对齐 `admin_kb_*` 命名族）
   - `source` 语义闭环：`seed`（种子包写入，管理员不可改）、`admin`（CRUD 写入）、`ai`（预留枚举值，本批无写入入口）；CRUD 的 PATCH 不允许改 `source`
2. **【待总指挥裁定】`DELETE /mistakes/{id}/mastered` 语义**：手动重置掌握度——`mastered=false`、`mastered_at=null`；**`consecutive_correct` 保留不清零**。理由：该端点的用途是「把已掌握的习题重新拉回练习」，最小变更原则下只撤销掌握标记；`consecutive_correct` 是学生真实作答的历史事实，清零等于篡改历史，且学生重置后再答对一次即可重新掌握（2 次阈值的计数仍连续），语义自然。`wrong_count` / `last_wrong_*` 同样保留（历史不可篡改）。路径中的 `{id}` 是 MistakeBookEntry.id，非本人条目一律 `4040`（不泄露存在性，照 `chat_service.get_conversation` 先例）。回写 spec §6.2
3. **【待总指挥裁定】hint 请求体扩展**：`POST /exercises/{id}/hint` body = `{intent: "seek_answer"|"review_my_code", answer?}`。`answer` 承载学生当前作答（JSON，与 submit 的 answer 同形），`review_my_code` 时**必填**（Pydantic `model_validator` → FastAPI 422），`seek_answer` 时可缺省；`judging` 不对 HTTP 开放（内部意图）。缺省/非法 intent 由 Pydantic Literal 校验拒绝（422）。回写 spec §6.2
4. **【待总指挥裁定】hint 的 `done` 载荷**（chat §6.1 的同源变体，无 Message 实体故无 `message_id`）：
   `{exercise_id, intent, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}` —— 保留 chat done 的全部降级/用量语义（`degraded` 取检索与提供方的或、`fallback_reason` 检索优先），仅以 `exercise_id + intent` 替代 `message_id`。回写 spec §6.2
5. **【待总指挥裁定】简答题 AI 评分 prompt 形态**：**不走 PromptAssembler**，由领域层 `domain/exercise/short_scoring.py` 构建 `[system, user]` 两条消息。理由：`PromptAssembler.TEMPLATES` 的四套主模板面向学生辅导，经 `_system.j2` 无条件注入防抄袭档位与底线内容，会污染要求严格 JSON 输出的判分调用；判分是内部调用（Judging 意图完全豁免，spec §7.1），不面向学生输出。system 要求模型只输出 JSON `{score: 0-100, is_correct: bool, feedback: string}`；user 含题干 / 参考答案 / 解析 / 学生作答。**Mock 模式判定取配置层（同 P3 §8.4 口径：`cfg.provider` 非真提供方即 Mock）**，不发起 LLM 调用，改用确定性启发式评分（学生作答与参考答案+解析的字符二元组重合度 → 映射 0-100），`judge_detail.judge_mode="mock_heuristic"`、`ai_scored=true` 照记。真提供方 JSON 解析失败 → `ApiError(5021)`：**不落 Submission、不入错题本**（把「模型故障」记成「学生答错」比丢一次提交更糟）。硬规则：模型给出 `is_correct` 但 `score<60` 时强制 `is_correct=false`（spec §5.1「得分 <60 视为错误」）。回写 spec §5.1 / §7
6. **【待总指挥裁定】种子幂等策略**：Exercise 无自然键，采用 **uuid5 确定性主键**——`uuid5(uuid.NAMESPACE_URL, "llm-code-tutor:exercise:<slug>")`，slug 在种子数据中显式给定（如 `py-choice-01`）。写入前按主键查存在即跳过（不覆盖，与 admin/ModelConfig 的「已存在则跳过」语义一致）。不引入 spec §5 之外的新列，幂等判定落在主键确定性上。回写 spec §4.3
7. **answer / test_cases 的 JSON 形态**（spec §5 只写了 JSON，此处定稿并回写 spec §5）：
   - `choice`：`answer="B"`（选项键）；`options={"A": "文本", "B": "文本", ...}`
   - `multi`：`answer=["A","C"]`（键数组，种子内排序存储）；`options` 同上
   - `blank`：`answer="文本"`（比对规则：去首尾空白 + casefold 忽略大小写）
   - `short`：`answer="参考答案文本"`（解析放 `explanation`）
   - `coding`：`answer={"language": "python", "solution": "源码"}`；`test_cases={"language": "python", "cases": [{"stdin": "...", "expected_stdout": "..."}]}`——**执行语言归属 test_cases**（它定义怎么跑），学生提交 `answer={"source": "..."}` 不带语言，杜绝「学生语言与用例语言不一致」。stdout 比对规则：`stdout.strip() == expected_stdout.strip()`
   - 提交的 `answer`（Submission.answer）与学生视图同形：choice=`"B"`、multi=`["A","C"]`、blank=`"文本"`、short=`"文本"`、coding=`{"source": "..."}`
8. **judge_detail 形态**：
   - choice / blank：`{"method": "direct", "passed": bool}`
   - multi：`{"method": "direct", "missing": [...], "wrong": [...]}`
   - coding：`{"method": "executed", "language", "budget_exceeded": bool, "budget_limit_s": 15, "cases": [{"index", "stdin", "expected_stdout", "actual_stdout|null", "passed", "duration_ms", "status", "skipped"(仅被中止的用例, reason="budget_exceeded")}]}`
   - short：`{"ai_scored": true, "judge_mode": "model"|"mock_heuristic", "model", "provider", "token_usage", "feedback"}`
9. **边界定稿**：multi 空作答（空数组/缺提交键）→ 0 分、`is_correct=false`，**不视为漏选**（空集按未作答处理，防止「不答得 50」）。coding 预算中止后按 `已通过 / 全部用例数` 取比例分，未全部通过即 `is_correct=false`。`attempt_no` = 该 (user, exercise) 现有 Submission 数 + 1，从 1 递增；同用户并发提交的 attempt_no 竞态在单 worker 演示规模下接受（无 await 点竞争窗口的业务影响为零，不做唯一约束）
10. **错误码**：本批预计**无需新码**——不存在 `4040`、参数校验沿用 FastAPI 422 现状（全仓未注册 4220，保持「无消费者的码不入表」）、LLM 失败 `5021`、向量库 `5032`（检索链路继承）、内部 `5000`。hint 流内异常走 `error` 事件（chat 同款）
11. **GET /exercises 响应附 `facets.knowledge_tags`**（published 习题的标签去重清单，不受 knowledge_tag 筛选影响）：前端筛选下拉需要闭环的标签来源，spec 无此端点，按「实际响应为最小集超集」惯例回写 spec §6.2
12. **RandomFill 的「同课程」口径**：Exercise 无课程维度（spec §5 无 course_code 列），随机补足从**全部 published 习题**中按难度递增选取（排除已在推荐清单中的、排除该生已掌握的）；每项标注 `filled_by: "profile"|"random"`。回写 spec §8.5
13. **hint 的底线检测口径**：`floor_hit = detect_floor_violation(stem)`——题干视作学生的请求文本；学生作答内容不做检测（它是答案不是请求，与 `/code/analyze` 不对代码做检测同口径）。底线由模板无条件注入，不受 intent 影响
14. **判题经执行并发配额**：coding 每个用例的执行都过 `execution_slot()`（与 `/code/run` 共享全局并发 2，spec §3.2 权衡 14）——判题就是代码执行，不该绕过配额；获取超时 `4290` 照常向上传播、该次提交不落库

---

## 4. Tasks

### Task 0: 实施计划

- [x] 本文件落盘并 commit（`docs: P5 习题与错题本实施计划`）。**阶段一到此停下，待总指挥裁定通过后才进入 Task 1。**

---

### Task 1: 数据模型三表 + schemas 骨架

**Files:** Modify `backend/app/infrastructure/persistence/models.py`、`backend/app/domain/exercise/__init__.py`（常量先落 `domain/exercise/judging.py`，models 反向引用它与 `domain/knowledge/status.py` 同模式）；Create `backend/app/schemas/exercise.py`、`backend/tests/test_exercise_models.py`

> **spec §5**：Exercise（type/stem/options?/answer/test_cases?/explanation/knowledge_tags/difficulty 1-5/source/status/created_by/created_at）、Submission（user_id/exercise_id/answer/is_correct(bool?)/score/judge_detail/feedback/attempt_no/created_at）、MistakeBookEntry（wrong_count/consecutive_correct/last_wrong_answer/last_wrong_at/mastered/mastered_at，**唯一约束 (user_id, exercise_id)**）。无 ForeignKey（M-2 现状）。全部 datetime 用 `UTCDateTime`。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| 三表建表；JSON 列（options/answer/test_cases/knowledge_tags/judge_detail/last_wrong_answer）可读写往返 | spec §5 字段落地 |
| `created_at` 等时间列回读带 UTC 时区（UTCDateTime） | 已知陷阱 6 |
| MistakeBookEntry 重复 (user_id, exercise_id) 插入抛 IntegrityError | 唯一约束 |
| `difficulty` 超界不设防于 DB 层但 Pydantic 入参 `ge=1 le=5` 拒绝（422） | 入参校验 |
| `is_correct` 可为 None（spec bool?） | spec 原样 |
| 三表全库无 ForeignKey（`__table__.columns` 无 FK，全表断言） | M-2 现状不破坏 |

- [ ] **Step 2–4: 失败 → 实现 models + 常量 + schemas 骨架（ExerciseIn/ExerciseOut/SubmissionOut/HintIn 占位）→ 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): Exercise/Submission/MistakeBookEntry 三表与 schemas 骨架（spec §5）`

---

### Task 2: 领域层判题规则（choice / multi / blank / coding 比例判分）

**Files:** Create `backend/app/domain/exercise/judging.py`、`backend/tests/test_judging.py`

> **spec §5.1 逐条照写死**：choice/blank 比对 answer 即时判分 0 或 100；multi 全对 100/true、真子集 50/**false**、含错选 0/false；coding 按通过比例给分（比例判分是纯函数，执行编排归 Task 6）。blank 比对去首尾空白 + casefold；stdout 比对 strip 后全等。统一规则 `is_correct == false` 即入错题本（该归集在服务层，本任务只出判定）。边界：multi 空作答 → 0/false（契约定稿 9）。

- [ ] **Step 1: 失败测试**

| 组 | 断言 | spec 条款 |
|---|---|---|
| choice | 对 → (100, True)；错 → (0, False) | §5.1 路 1 |
| blank | 精确相等 (100, True)；首尾空白/大小写差异仍 (100, True)；不同 (0, False) | §5.1 路 1 |
| multi | 全对 (100, True)；真子集（漏选）(50, **False**)；含错选 (0, False)；空作答 (0, False)；乱序选择等价全对 | §5.1 路 2 + 边界 |
| coding 判分 | 3/4 通过 → 75/False；4/4 → 100/True；0/4 → 0/False；`budget_exceeded=True` 时未跑用例不计入通过但计入分母 | §5.1 路 3 |
| judge_detail | multi 产出 missing/wrong 键；direct 详情结构契约定稿 8 | §5.1 |
| 零 IO | 模块源码不 import sqlalchemy / open / requests（源码级断言） | §4.2 硬约束 1 |

- [ ] **Step 2–4: 失败 → 实现（纯函数 + 常量 EXERCISE_TYPES / 源与状态枚举）→ 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 判题纯规则——choice/multi/blank 即时判分与 coding 比例判分（spec §5.1）`

---

### Task 3: 领域层掌握度状态机（可回滚专项）

**Files:** Create `backend/app/domain/exercise/mastery.py`、`backend/tests/test_mastery.py`

> **spec §8.5**：正确 → `consecutive_correct += 1`，达 2 次（MASTERY_THRESHOLD）置 `mastered=true`、`mastered_at=now`；错误 → `wrong_count += 1`、`consecutive_correct=0`、**`mastered=false`、`mastered_at=null`**、写 `last_wrong_answer/last_wrong_at`；无条目则创建。**掌握度回滚是硬要求**（总指挥交接 §7 陷阱 4），专项用例必须覆盖「已掌握后再答错 → 回到未掌握」。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| 无条目 + 答错 → 创建态：wrong_count=1、consecutive_correct=0、mastered=False、last_wrong_answer/at 已写 | §8.5 错误分支 |
| 无条目 + 答对 → consecutive_correct=1、mastered=False | §8.5 正确分支 |
| 连续答对 2 次 → mastered=True、mastered_at 非 null | Mastery 阈值 2 |
| 连续答对 1 次后答错 → consecutive_correct=0、mastered 仍 False | 连续性 |
| **已掌握（mastered=True）后答错 → mastered=False、mastered_at=None、wrong_count+1**（回滚专项，变异测试目标） | §8.5 可回滚 |
| 已掌握后答对 → mastered 保持 True、mastered_at 不变 | 幂等不抖动 |
| last_wrong_answer 每次错误覆盖为新答案 | §8.5 字段语义 |

- [ ] **Step 2–4: 失败 → 实现 `MasteryState`（dataclass）+ `apply_answer(state, *, is_correct, wrong_answer, now)` → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 掌握度状态机——连续 2 次答对即掌握、错误硬回滚（spec §8.5）`

---

### Task 4: 领域层简答评分（prompt 构建 / Mock 启发式 / JSON 解析）

**Files:** Create `backend/app/domain/exercise/short_scoring.py`、`backend/tests/test_short_scoring.py`

> **spec §5.1 路 4 + 契约定稿 5**：内部判分调用（Judging 意图完全豁免），prompt 不走 PromptAssembler（四套主模板面向学生辅导，会注入无关的防抄袭内容污染 JSON 输出）。system 要求严格 JSON `{score, is_correct, feedback}`；user 含题干/参考答案/解析/学生作答。Mock 启发式：学生作答与「参考答案+解析」的字符二元组重合度映射 0-100，确定性可单测。解析：剥代码围栏 → 取首个 `{...}` → json.loads → score 钳制 0-100；失败抛专用异常由服务层转 5021。硬规则：score<60 时 is_correct 强制 False。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| system prompt 含「只输出 JSON」与评分字段说明；user prompt 含题干/参考答案/解析/学生作答四要素 | 契约定稿 5 |
| Mock 启发式：作答含参考答案大部分内容 → 高分（≥60）；空作答/完全无关 → 低分（<60）；同输入两次调用结果完全一致 | Mock 确定性 |
| `parse_judge_json`：裸 JSON / ```json 围栏 / 前后带说明文字三种形态都能解析 | 真模型输出的健壮性 |
| score=30 + is_correct=True → 强制 (30, False)；score=85 + is_correct=True → (85, True) | §5.1「<60 视为错误」 |
| score 超界（150 / -5）钳制到 0-100 | 健壮性 |
| 非法输出（无 JSON）抛解析异常 | 服务层 5021 的前置 |
| 零 IO 源码级断言 | §4.2 硬约束 1 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 简答题 AI 评分领域层——JSON 输出契约、Mock 启发式与 <60 硬规则（spec §5.1）`

---

### Task 5: FakeExecutor 与 CodeExecutor 端口契约测试（遗留 M4）

**Files:** Modify `backend/tests/fakes.py`；Create `backend/tests/test_executor_contract.py`

> **健康检查 M4 + P5 提示词**：新增判题用 FakeExecutor（进 fakes.py 集中管理），与真实 `SubprocessSandbox` 跑**同组签名/语义断言**，风格照 `test_llm_contract.py` 的 `provider` fixture 参数化（`pytest.fixture(params=["fake", "subprocess"])`），防「Fake 只在测试里成立、真适配器不同签名」。FakeExecutor 还要支撑 Task 6：**可控结果序列（每用例通过/失败/状态）与可控延迟**（`time.sleep`，供 15s 预算测试）。

- [ ] **Step 1: FakeExecutor 设计 + 契约失败测试**

| 断言（两组参数各跑一遍） | 锁住什么 |
|---|---|
| `isinstance(executor, CodeExecutor)`（runtime_checkable） | 端口符合性 |
| `execute(*, language, source, stdin="")` 关键字签名调用成功 | 端口签名（`ports/code_executor.py:47`） |
| 正常打印 → `status="accepted"`、stdout 含输出、`exit_code=0`、`duration_ms` 为 int | 语义：成功路径 |
| stdin 传入 → stdout 回显（`input()` 读入） | 语义：stdin 透传（判题用例输入依赖它，P4 遗留 5 的缝） |
| 抛异常代码 → `status="runtime_error"`、exit_code≠0 | 语义：失败路径 |
| 黑名单代码（`os.system`）→ `status="blocked"`、exit_code=None | 语义：黑名单先于执行 |
| `limit_detail` 含 wall_clock/cpu/memory/file_size/output 键 | limit_detail 契约 |

- [ ] **Step 2: 实现 FakeExecutor（构造参数：`results` 序列或按 source 内容判定通过、`delay_s=0.0`、记录 `calls`）与参数化测试 → 通过**

  真执行器组会真起子进程（约 7 例 × 2 参数 ≈ +8s），注意 H-1：不要满负载并行跑。
- [ ] **Step 3: 全量测试 → Commit** `test(backend): CodeExecutor 端口契约测试——FakeExecutor 与 SubprocessSandbox 同组断言（遗留 M4）`

---

### Task 6: ExerciseService——判题提交编排（含 15s 累计预算）

**Files:** Create `backend/app/services/exercise_service.py`（本任务先落 submit 编排，hint 归 Task 10）；Modify `backend/tests/fakes.py`（如需补短评分用 LLM 替身复用 `FakeLLM`）；Create `backend/tests/test_exercise_service.py`

> **spec §5.1 / §8.5**：submit 链路——取 published 习题（不存在或未发布 `4040`）→ 按题型判分 → `attempt_no` 递增 → 落 Submission → `is_correct==false` 即经 MistakeBookService 记错（`record_result`，Task 8 提供本任务先注入最小实现或桩）→ 写 `AuditLog(action="exercise_submit")`。
> **15s 预算（已裁定）**：服务层 `time.monotonic()` 跨用例累计；每个用例执行前检查预算，超了就中止剩余用例（标记 skipped + reason），按已通过比例判分。预算秒数为构造参数 `budget_seconds`（默认 `domain` 常量 15.0），测试注入小值配 FakeExecutor 延迟验证，不 monkeypatch。每个用例执行：`execution_slot()` + `run_in_threadpool(executor.execute, ...)`。
> **short 判分**：Mock 判定取配置层（P3 口径）；真提供方经 `LLMRuntime.complete()`（**非流式**，判分不流式）；5021 向上传播、不落库。
> **判分意图**：服务内部调用以 `JUDGING` 意图豁免档位（判分不走 PromptAssembler，此意图语义用于审计 detail 与未来扩展，不改变判分行为）。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 | spec 条款 |
|---|---|---|
| choice 对/错各一例：score 100/0、is_correct、Submission 落库、judge_detail.method="direct" | 即时判分主路径 | §5.1 路 1 |
| blank 大小写/空白容错 | 判分口径 | §5.1 路 1 |
| multi 三分支：全对 100/True；漏选 50/**False**（变异测试目标）；含错选 0/False | 多选语义 | §5.1 路 2 |
| **漏选判 50 且 is_correct=False → 入错题本**（mock 错题服务记录调用断言） | 漏选按错误处理 | §5.1 + §8.5 |
| coding 全过 100/True；部分过按比例 + is_correct=False；judge_detail.cases 每用例含 stdin/期望/实际/耗时 | §5.1 路 3 | §5.1 |
| **15s 预算**：`budget_seconds=0.3` + FakeExecutor(delay=0.15) × 5 用例 → 执行在预算处中止、`budget_exceeded=True`、剩余用例 skipped、分数=已通过/5×100、is_correct=False | 已裁定超时语义 | §5.1 路 3 |
| coding 执行经 `run_in_threadpool`（monkeypatch 计数）与 `execution_slot` | ADR-0002 / 权衡 14 | — |
| 黑名单代码提交 coding → 每用例 blocked、0 分、is_correct=False | 执行器语义继承 | §8.3 |
| short 真提供方：FakeLLM 返回合法 JSON → score/is_correct 落定、judge_detail.ai_scored=True、judge_mode="model" | §5.1 路 4 | §5.1 |
| short Mock 配置（provider=mock）：**零 LLM 调用**（FakeLLM 计数=0）、judge_mode="mock_heuristic"、ai_scored=True | Mock 判定配置层 | §8.4 同口径 |
| short LLM 输出非法 JSON → 抛 `ApiError(5021)`、**无 Submission 落库、错题服务未被调用** | 故障不记成答错 | §9 |
| short score=45 → is_correct 强制 False → 入错题本；score=80 → 不入 | <60 硬规则 | §5.1 |
| attempt_no：同 (user, exercise) 连续提交 1、2、3 | §5 字段 | — |
| 错误提交写 MistakeBookEntry（经 Task 8 的 record_result；本任务用注入替身断言参数） | 统一规则 is_correct==False 即入错题本 | §8.5 |
| 不存在 / 未发布（draft）习题提交 → 4040 | 学生端只暴露 published | §6.2 |
| AuditLog(action="exercise_submit") 落库 | 审计 | §8.1 同模式 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**（MistakeBookService 若未就绪，本任务内先落 `record_result` 最小实现，Task 8 扩展查询侧）
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): ExerciseService 判题编排——四路判分、15s 累计预算、错题归集（spec §5.1 §8.5）`

---

### Task 7: 学生端 exercise 路由（list / detail / submit）

**Files:** Create `backend/app/routers/exercise.py`；Modify `backend/app/main.py`、`backend/app/schemas/exercise.py`（补 Out 模型）；Create `backend/tests/test_exercise_api.py`

> **spec §6.2 exercise 行**：`GET /exercises?type=&difficulty=&knowledge_tag=`（**只暴露 published**；分页 page/page_size → `{items, total}`；响应附 `facets.knowledge_tags`，契约定稿 11）；`GET /exercises/{id}`（未发布 → 4040）；`POST /exercises/{id}/submit`。路由不含业务逻辑。提交结果暴露 `correct_answer` / `explanation` / `ai_scored`（前端「AI 参考评分」标识的数据源）。

- [ ] **Step 1: 失败测试**（照 `test_code_api.py` 脚手架）

| 断言 | 锁住什么 |
|---|---|
| 未鉴权 → 4010；学生可访问（非 admin 限定） | 鉴权 |
| 列表只含 published（种一条 draft 一条 published） | spec §6.2 学生端可见性 |
| type/difficulty/knowledge_tag 三过滤器各自生效 | §6.2 查询参数 |
| 响应 `{items, total, facets.knowledge_tags}`；facets 不受 knowledge_tag 过滤影响 | 契约定稿 11 |
| 详情：published 返回完整字段；draft → 4040；不存在 → 4040 | §6.2 |
| 提交返回 submission + correct_answer + explanation + ai_scored；`request_id` 与响应头一致 | CurrentRidDep |
| body 非法（type 不存在 / 缺 answer）→ 422 | 参数校验 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 学生端习题端点——列表筛选/详情/提交判分（spec §6.2）`

---

### Task 8: MistakeBookService——条目 / 薄弱画像 / 推荐（RandomFill）/ 重置掌握

**Files:** Create `backend/app/services/mistake_service.py`、`backend/tests/test_mistake_service.py`

> **spec §8.5 / §6.2**：`list_entries(user_id, mastered?)`；`profile(user_id)` 按 knowledge_tags 聚合 `SUM(wrong_count)`、**排除已掌握**（WeakKnowledgePoint 实时聚合，无独立表；JSON 列无法 SQL 聚合，Python 层聚合，声明规模下成本可忽略——spec §3.2 权衡 3）；`recommendations(user_id, limit=5)`：top-3 薄弱 tag → 选题（排除已掌握）→ 难度升序 → 不足 limit 按难度递增补随机并标 `filled_by="random"`（CONTEXT.md「随机补足」，标注必须可见）；`reset_mastered(user_id, entry_id)` 按契约定稿 2；`record_result` 由 Task 6 已落，本任务收口。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 | spec 条款 |
|---|---|---|
| record_result 集成真实 session：错一次建条目、再对一次 consecutive=1、连对两次 mastered、再错回滚（服务层端到端状态机） | §8.5 落库路径 | §8.5 |
| list_entries 按 mastered 过滤三态（不传/True/False）；条目带习题摘要（type/stem/difficulty/tags） | §6.2 `?mastered=` | §6.2 |
| profile：两题同 tag 聚合 SUM(wrong_count)；已掌握条目排除；按 wrong_count 降序 | WeakKnowledgePoint | §8.5 |
| recommendations：薄弱 tag 命中的题在前、难度升序；不足 limit 补随机且 **filled_by="random" 标注**（变异测试目标）、画像题 filled_by="profile" | RandomFill | §8.5 |
| recommendations 排除已掌握习题；无错题时全随机补足且全部标 random | 边界 | §8.5 |
| reset_mastered：mastered=True → 重置 False/null，consecutive_correct 与 wrong_count 保留（变异测试目标）；他人条目 → 4040 | 契约定稿 2 | §6.2 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): MistakeBookService——错题条目/薄弱画像/定向推荐与 RandomFill/手动重置掌握（spec §8.5）`

---

### Task 9: mistake 路由

**Files:** Create `backend/app/routers/mistake.py`；Modify `backend/app/main.py`、`backend/app/schemas/exercise.py`；Create `backend/tests/test_mistake_api.py`

> **spec §6.2 mistake 行**：`GET /mistakes?mastered=`、`DELETE /mistakes/{id}/mastered`、`GET /mistakes/profile`、`GET /mistakes/recommendations?limit=`（limit 默认 5，ge=1 le=20）。全部挂 `CurrentRidDep` + 登录用户。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| 四端点未鉴权 → 4010 | 鉴权 |
| GET /mistakes 三态过滤与条目结构（HTTP 层） | §6.2 |
| DELETE mastered：本人成功返回重置后状态；他人条目 4040 | 契约定稿 2 |
| profile / recommendations 结构与 limit 校验（0 / 21 → 422） | §6.2 |
| 跨用户隔离：B 看不到 A 的条目 | 归属 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 错题本端点——条目/画像/推荐/手动重置掌握（spec §6.2）`

---

### Task 10: hint 的 AI 辅导链路（SSE）

**Files:** Create `backend/app/domain/exercise/hint.py`、`backend/app/services/exercise_service.py`（追加 `stream_hint`）、`backend/app/routers/exercise.py`（追加 hint 端点）、`backend/tests/test_exercise_hint.py`

> **spec §6.2 / §7.1 / §7.2 / §6.1 + P5 提示词**：hint 复用 chat SSE 全套模式。要点：
> - intent 必填（Literal），`judging` 不对 HTTP 开放；`review_my_code` 必带 `answer`（契约定稿 3）
> - **档位差异**：`seek_answer` → `resolve_mode` 施加配置档位；`review_my_code` → 豁免（mode=None）——变异测试目标。底线仍由模板无条件注入；`floor_hit = detect_floor_violation(stem)`（契约定稿 13）
> - **模板选择**：`seek_answer` → `exercise_hint.j2`（引导式提示）；`review_my_code` → `mistake_review.j2`（定位错误根因 → 补知识点 → 同类小题）。两模板已在 `PromptAssembler.TEMPLATES` 注册（`prompt_assembler.py:40`），不改模板文件
> - **问题串**（`domain/exercise/hint.py`）：seek_answer 含题干+选项+知识点标签，**不含参考答案与解析**（防档位被绕过时直接泄题）；review_my_code 额外含参考答案/解析/学生作答（豁免意图，给出改进不构成抄袭）
> - **RAG**：query = `stem + knowledge_tags`，**不含学生作答**（§7.2）；复用 `RetrievalService.search()` 默认作用域；citation 事件先行；rag_hit/degraded/fallback_reason 三态与 chat 完全一致（含 sentinel 与零命中）
> - **中断**：per-call `asyncio.Event` 注册表（键 `(exercise_id, request_id)`），finally 注销；spec 未定义 hint 的 /stop 端点，中断由前端 AbortController 断连承担，4990 机制保持与 chat 同构（cancel 检查逻辑在流循环中保留）
> - **审计**：`AuditLog(action="exercise_hint")` 在 `finally` 中写（含 intent/mode/rag_hit/chars/error_code），自身不得抛出
> - **不落 Message / Submission**（spec 无此实体）

- [ ] **Step 1: 失败测试**（注入 `FakeLLM` / `FakeRetrieval`，解析产出的 `StreamEvent` 序列断言）

| 断言 | 锁住什么 | spec 条款 |
|---|---|---|
| 事件序列：`citation* → token* → done`；无命中时无 citation 直接 token | §6.1 顺序契约 | §6.1 |
| **citation 先于 token**（首 citation 索引 < 首 token 索引，有命中时） | §6.1 | §6.1 |
| done 载荷九字段：exercise_id/intent/token_usage/usage_estimated/model/provider/rag_hit/degraded/fallback_reason；token_usage 逐字取自流末 Usage | 契约定稿 4 | §6.1 变体 |
| `seek_answer` + 配置 strict → 捕获的 system prompt **含**档位标记 | seek_answer 受档位约束 | §7.1 |
| **`review_my_code` + 配置 strict → system prompt 含豁免标记、不含档位标记**（变异测试目标）；且问题串含学生作答与参考答案 | 豁免是显式契约 | §7.1 / §8.4 |
| seek_answer 问题串**不含**参考答案/解析 | 防泄题 | §7.1 |
| RAG query == stem+tags，**不含学生作答**（FakeRetrieval.queries 断言） | §7.2 | §7.2 |
| FakeRetrieval(miss no_relevant_chunk) → done.degraded=True、fallback_reason="no_relevant_chunk" | 降级可见 | §9 |
| SentinelEmbedder 注入链路 → fallback_reason="hashing_embed_no_semantics"（或 FakeRetrieval 直给定） | 封闭枚举 | §7.3 |
| FakeLLM(fail=True) → LLMRuntime 降级/5021 error 事件（照 chat 语义）；流内异常发 error 事件 | §9 / §6.1 | §6.1 |
| cancel Event 预置位 → 无 token、error 4990 语义与 chat 一致；finally 注销注册表 | 中断同构 | §6.1 |
| 习题不存在 / draft → 4040（HTTP 层，先于 StreamingResponse） | 越权前置校验 | §6.2 |
| `review_my_code` 缺 answer → 422；intent 非法/缺省 → 422 | 契约定稿 3 | §6.2 |
| AuditLog(action="exercise_hint") 在失败路径也落库 | finally 审计 | §8.1 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 习题 hint SSE——双意图豁免差异、citation 先行、降级可见与 finally 审计（spec §6.1 §7.1 §7.2）`

---

### Task 11: admin 习题 CRUD（spec §6.2 缺口补全）

**Files:** Create `backend/app/routers/admin_exercise.py`；Modify `backend/app/services/exercise_service.py`（create/update/delete/list 全量）、`backend/app/schemas/exercise.py`、`backend/app/main.py`；Create `backend/tests/test_admin_exercise_api.py`

> **契约定稿 1【待总指挥裁定】**：五端点形态、`source=admin` 固定、PATCH 不允许改 source、DELETE 手工级联 Submission + MistakeBookEntry 并在 AuditLog detail 记删除数。校验：choice/multi 必须有 options 且 answer 键 ⊆ options 键；coding 必须有 test_cases（language + 至少一个 case）；difficulty 1-5；type 枚举。这些校验放 Pydantic（422）。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| 学生访问任一 admin 端点 → 4030 | AdminDep |
| POST 创建：source 强制 admin（body 传 seed/ai 也落 admin）、created_by=管理员 id、status 缺省 draft | 契约定稿 1 |
| POST 校验：multi 缺 options → 422；answer 键不在 options → 422；coding 缺 test_cases → 422；difficulty=6 → 422 | 写入校验 |
| GET 分页 `{items, total}` 与 status/type 过滤 | §6.2 分页约定 |
| PATCH：改 status draft→published 后学生端可见（联动 Task 7 语义）；PATCH 传 source → 422 或忽略（以实现为准，测试锁定行为） | 发布流 |
| DELETE：级联删 Submission 与 MistakeBookEntry；AuditLog detail 计数；习题不存在 → 4040 | 手工级联（M-2 口径） |
| 三个审计 action 落库 | 命名族 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): admin 习题 CRUD 五端点——写入校验/发布流/级联删除与审计（spec §6.2 缺口回写）`

---

### Task 12: backend/seeds 包迁移（遗留 M2）

**Files:** Create `backend/seeds/__init__.py`、`backend/seeds/admin.py`、`backend/seeds/model_config.py`、`backend/seeds/exercises.py`（本任务先空实现 `seed_exercises` 为 no-op，Task 13 填数据）；Modify `backend/app/seed.py`（薄壳）、`Makefile`（lint 目标加 `seeds`）；回归 `backend/tests/test_seed.py`

> **spec §4.3**：`backend/seeds/` 是顶层包（习题种子 + 初始 admin）。`app/seed.py` 保持 `python -m app.seed` CLI 入口与 `seed()` / `DEFAULT_ADMIN_USERNAME` 导出（test_seed.py 不改），内部委托 seeds 包。`make seed` 幂等行为不得改变（现状实测：seed 两次仍 1 用户）。`make lint` 增加 seeds 目录。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| `from app.seed import seed, DEFAULT_ADMIN_USERNAME` 仍可用；`seed()` 跑完 admin + ModelConfig 各一行（既有 test_seed 语义不变） | 迁移不破坏 CLI 与测试 |
| `seeds.seed(session)` 直接调用等价可用 | 包边界 |
| Makefile lint 覆盖 seeds（`ruff check app seeds tests` 通过，seeds 零告警） | 工具链 |

- [ ] **Step 2: 迁移实现（admin.py / model_config.py 从 app/seed.py 平移，逻辑零改动）→ 通过**
- [ ] **Step 3: `python -m app.seed` 真跑两次，第二次输出幂等（1 用户 / 1 配置）**
- [ ] **Step 4: 全量测试 → Commit** `refactor(backend): 种子迁移 backend/seeds 包——admin 与 ModelConfig 迁入，app.seed 变薄壳（遗留 M2，spec §4.3）`

---

### Task 13: 约 40 题习题种子 + 幂等 + 自校验

**Files:** Modify `backend/seeds/exercises.py`（填数据）；Create `backend/tests/test_seed_exercises.py`

> **spec §11 P5 行 + 契约定稿 6【待总指挥裁定】**：40 题覆盖 Python 基础知识点，题型配比 choice 10 / multi 6 / blank 8 / short 8 / coding 8；难度分布 1×8 / 2×10 / 3×12 / 4×7 / 5×3；知识点标签封闭词表（变量与赋值/数据类型/运算符/控制流/循环/函数/列表/字典/字符串/切片/推导式/异常处理），每题 1–2 个标签且词表全覆盖（画像/推荐闭环）。coding 题 `answer.solution` 必须对其 `test_cases` 全部通过（**种子自校验**——总指挥交接 §9 审阅重点）。幂等按 uuid5 确定性主键（契约定稿 6）。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 | spec 条款 |
|---|---|---|
| seed_exercises 后恰 40 条；source=seed、status=published 全部成立 | §11 题量与可见性 | §11 |
| **幂等**：连跑两次仍 40 条、id 集合不变（变异测试目标——去掉存在性检查即翻倍） | 契约定稿 6 | §4.3 |
| 五种题型齐备且配比符合设计；难度 1-5 每档非空 | 五题型齐备 | §11 |
| 标签封闭词表：每题 tags ⊆ 词表；词表每个 tag 至少被 2 题引用 | 画像/推荐闭环 | §8.5 |
| choice/multi：answer 键 ⊆ options 键；multi 正确答案 ≥2 键 | answer 形态 | §5 |
| **coding 自校验**：对每道 coding 题用真 `SubprocessCodeExecutor` 跑 `answer.solution` × 全部 cases → 全 passed（参数化 8 例，+10s 左右） | 种子可解性 | §5.1 |
| make seed 语义不变：`app.seed.seed()` 一次调用后 User=1、ModelConfig=1、Exercise=40 | 迁移后总入口 | §4.3 |

- [ ] **Step 2: 填充 40 题数据（每题含 stem/options?/answer/explanation/knowledge_tags/difficulty/slug）→ 通过**
- [ ] **Step 3: 全量测试 → Commit** `feat(backend): 40 题 Python 基础习题种子——五题型齐备、uuid5 幂等与 coding 自校验（spec §11）`

---

### Task 14: 删除死代码 chat_service.count_actions（遗留 M6）

**Files:** Modify `backend/app/services/chat_service.py`（删 357 行起的 `count_actions`）

> 总指挥已核实 app 与 tests 零引用（健康检查 M-6）。删除后全量回归即为本任务的验证。

- [ ] **Step 1: `grep -rn "count_actions" backend/` 确认零引用 → 删除**
- [ ] **Step 2: 全量测试 → Commit** `chore(backend): 删除死代码 ChatService.count_actions（遗留 M6）`

---

### Task 15: 前端习题练习页

**Files:** Create `frontend/src/api/exercise.ts`、`frontend/src/types/exercise.ts`、`frontend/src/views/student/ExerciseView.vue`；Modify `frontend/src/router/index.ts`（`/exercises` 懒加载）、`frontend/src/components/AppShell.vue`（导航项「习题练习」）

> **spec §6.2 / §5.1 / §9 + design baseline**：列表（筛选 type/difficulty/knowledge_tag，tag 下拉数据来自 `facets.knowledge_tags`）→ 作答面板（choice 单选 / multi 多选 / blank 输入 / short 文本域 / coding 复用 `CodeEditor` 组件）→ 提交 → 判分结果（分数、正确/错误、judge_detail 用例表格、正确答案/解析折叠面板）→ **hint 双入口按钮**（「获取思路」=seek_answer /「批改我的作答」=review_my_code，后者有作答内容才可用）→ SSE 流式渲染（复用 `readSseStream` + `MarkdownView` + `CitationList` + `DegradedBanner`）→ 简答题结果带「AI 参考评分」标识（`ai_scored` 驱动）。SSE 中断用 `AbortController`（无 stop 端点，仅前端停止渲染）。沿用 CSS 变量/间距/圆角，路由懒加载。

- [ ] **Step 1: types + api 模块（listExercises / getExercise / submitExercise / streamHint）**
- [ ] **Step 2: 页面组件 → 路由与导航**
- [ ] **Step 3: `npm test` + `npx vue-tsc --noEmit` 零错误 + `npx vite build` 通过；路由独立 chunk**
- [ ] **Step 4: Commit** `feat(frontend): 习题练习页——五题型作答/判分结果/hint 双入口与 SSE 流式辅导`

---

### Task 16: 前端错题本页

**Files:** Create `frontend/src/api/mistake.ts`、`frontend/src/types/mistake.ts`、`frontend/src/views/student/MistakeBookView.vue`；Modify `frontend/src/router/index.ts`（`/mistakes` 懒加载）、`frontend/src/components/AppShell.vue`（导航项「错题本」）

> **spec §8.5 / §6.2**：条目列表（mastered 三态筛选）、掌握状态标签、wrong_count / consecutive_correct、last_wrong_answer / last_wrong_at 展示、薄弱知识点画像区（tag + wrong_count 降序）、推荐区（`filled_by="random"` 的条目带「随机补足」标注，CONTEXT.md 要求标注可见）、已掌握条目的「重置掌握度」入口（确认后 DELETE mastered 并刷新）。降级/降级提示条复用 `DegradedBanner`。文案零违禁词（「错题本」是功能名可用；不出现「题目/试题/草稿」）。

- [ ] **Step 1: types + api 模块（listMistakes / getProfile / getRecommendations / resetMastery）**
- [ ] **Step 2: 页面组件 → 路由与导航**
- [ ] **Step 3: `npm test` + `vue-tsc` 零错误 + `vite build` 通过**
- [ ] **Step 4: Commit** `feat(frontend): 错题本页——掌握状态/薄弱画像/RandomFill 推荐与手动重置掌握`

---

### Task 17: spec 回写、变异测试执行与完成报告

**Files:** Modify `docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md`；Create `docs/review/2026-08-31-p5-completion-report.md`

- [ ] **Step 1: spec 回写（清单见 §5）——逐条落进对应章节，标注（P5 补记）**
- [ ] **Step 2: 变异测试逐条实际执行**（拆实现 → 跑目标测试必须失败 → 还原 → `git status` 干净），记录进完成报告：
  1. `mastery.py` 错误分支删掉 `mastered=false` 回滚 → `test_mastery.py` 回滚专项 + `test_mistake_service.py` 端到端用例失败
  2. `judging.py` multi 删掉真子集 50 分分支 → `test_judging.py` + `test_exercise_service.py` 漏选用例失败
  3. `exercise_service.py` 删掉预算检查 → 15s 预算用例失败
  4. `mistake_service.py` 推荐删掉 `filled_by` 标注 → RandomFill 用例失败
  5. `exercise_service.py` stream_hint 把 review_my_code 的 resolve_mode 强制按 seek_answer 处理 → 豁免差异用例失败
  6. `seeds/exercises.py` 删掉主键存在性检查 → 幂等用例失败
  7. 附带：学生端列表去掉 published 过滤 → 可见性用例失败；reset_mastered 保留行为改成清零 consecutive_correct → 对应用例失败
- [ ] **Step 3: 真服务冒烟实测**（`uvicorn --workers 1`）：种子 40 题、列表筛选、choice 提交判分、coding 提交判分（含 judge_detail 用例表）、short Mock 评分、hint 双入口 SSE（seek_answer 档位话术 vs review_my_code 豁免）、错题本画像/推荐/重置掌握
- [ ] **Step 4: 完成报告（含端到端实测结果、变异测试记录、测试基线增量、未验证项）→ Commit** `docs: P5 完成报告（含判题实测、变异测试记录与 spec 回写）`

---

## 5. spec 回写项清单（Task 17 执行）

| # | 回写内容 | spec 位置 |
|---|---|---|
| 1 | admin 习题 CRUD 五端点（契约定稿 1） | §6.2 新增 admin·exercise 行 |
| 2 | hint 请求体 `{intent, answer?}`（契约定稿 3） | §6.2 exercise 行 |
| 3 | hint 的 `done` 载荷字段集（契约定稿 4） | §6.2 exercise 行（或 §6.1 附注） |
| 4 | `DELETE /mistakes/{id}/mastered` 语义（契约定稿 2） | §6.2 mistake 行 + §8.5 |
| 5 | 简答评分 prompt 形态（领域层构建、Mock 启发式、5021 不落库；契约定稿 5） | §5.1 + §7 |
| 6 | `backend/seeds/` 目录已落地（admin + ModelConfig + 习题种子，uuid5 幂等） | §4.3 + §11 |
| 7 | answer / test_cases 各题型 JSON 形态与比对规则（契约定稿 7） | §5 Exercise 行附注 |
| 8 | `GET /exercises` 分页 + `facets.knowledge_tags` 超集（契约定稿 11） | §6.2 |
| 9 | RandomFill 无课程维度口径（契约定稿 12） | §8.5 |
| 10 | multi 空作答 0 分边界；attempt_no 语义（契约定稿 9） | §5.1 / §5 |
| 11 | hint 底线检测口径（契约定稿 13）；判题过 execution_slot（契约定稿 14） | §7.1 / §3.2 权衡 14 附注 |

## 6. 预估测试增量（最终以实际执行为准）

| 域 | 预估新增 |
|---|---|
| 后端 pytest | Task 1–14 合计 **约 +130~140 条**（661 → 约 790–800），其中真子进程用例约 15 条（契约 7×2 参数 + 种子自校验 8） |
| 套件耗时 | +25~40s（契约 + 自校验；基线 121s → 约 150–160s） |
| 前端 vitest | 0 新增（基线 8 保持；前端硬门槛是 vue-tsc 零错误 + vite build） |

## 7. 风险清单

1. **H-1 负载敏感 flake**：本批新增真子进程用例，报告与完成报告必须注明「避免满负载并行跑测试」
2. **短答评分 JSON 健壮性**：真模型输出可能带围栏/前言——解析器按 Task 4 用例覆盖三种形态；解析失败 5021 不落库是诚实降级
3. **profile 的 JSON 聚合在 Python 层**：声明规模（错题条目 < 千）成本可忽略（spec §3.2 权衡 3 已声明），不做 SQL JSON 聚合
4. **判题占用执行并发**：coding 判题每用例占 execution_slot，一道 4 用例编程题最长可占 15s 预算——与 `/code/run` 共享配额 2，演示场景可接受；已写入契约定稿 14
5. **种子自校验耗时**：8 道 coding × 3-4 用例真起子进程 ≈ +10s，若超预期可在测试内加 `@pytest.mark.timeout` 式保护（不引入新依赖，用现有手段）
6. **attempt_no 并发竞态**：单 worker 下同用户并发提交理论可重号，演示规模接受（契约定稿 9 已声明）
7. **hint 无 /stop 端点**：spec 未定义，中断靠前端断连；4990 机制保留同构，如总指挥认为需要 stop 端点可作为追加项裁定
8. **conftest 既有约定**：所有新测试走既有 fixtures（engine/session），禁止引入联网依赖

## 8. 待总指挥裁定的问题清单（六项正式 + 四项随回写确认）

| # | 问题 | 本计划方案 | 备选 |
|---|---|---|---|
| 1 | admin CRUD 形态 | `/api/v1/admin/exercises` 五端点；DELETE 级联删 Submission + 错题条目并留审计 | DELETE 遇 Submission 时 4090 拒绝 |
| 2 | DELETE mastered 语义 | 重置 mastered/mastered_at；consecutive_correct 保留（最小变更、不篡改历史） | 连 consecutive_correct 一并清零（重置后需再连对 2 次） |
| 3 | hint 请求体 | `{intent, answer?}`；review_my_code 必填 answer（422）；answer 与 submit 同形 | 独立字段拆分（answer/code 两字段） |
| 4 | hint done 载荷 | `{exercise_id, intent, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}` | 另加 submission_id（若要求 hint 关联最近一次提交） |
| 5 | 简答评分 prompt | 领域层构建不走 PromptAssembler；Mock 启发式评分；解析失败 5021 不落库 | 注册新模板进 TEMPLATES；或 Mock 也走 LLM 链路 |
| 6 | 种子幂等 | uuid5 确定性主键 + 存在即跳过 | stem+type 内容哈希查询判定；或新增 slug 列（需改 spec §5） |
| 7 | coding 执行语言归属 | `test_cases.language`（学生只交 source） | Exercise 加 language 列（需改 spec §5） |
| 8 | multi 空作答 | 0 分 / is_correct=false，不算漏选 | 视为漏选给 50（不建议：不答得 50） |
| 9 | GET /exercises 分页 | page/page_size → `{items, total}` + facets | 不分页返回全量 |
| 10 | hint 是否需要 /stop 端点 | 本批不加，断连即中断 | 追加 `POST /exercises/{id}/hint/stop` |

## 9. 验收清单（P5 完成标准）

- [ ] 后端 pytest 全绿（661 基线 + 新增，实际数字以完成为准）；2 条 skip 与 P5 无关
- [ ] 判题四路语义与 spec §5.1 逐条一致；漏选 50/False 入错题本；coding judge_detail 含每用例四要素；15s 累计中止有专项用例
- [ ] 掌握度状态机：连对 2 次掌握、错误硬回滚，均有专项用例且变异测试验证有效
- [ ] 学生端 8 端点 + admin 5 端点全部挂 CurrentRidDep（admin 另挂 AdminDep + 审计）；学生端只暴露 published
- [ ] hint SSE：citation 先行、done 九字段、封闭三值 fallback_reason、finally 审计；seek_answer/review_my_code 档位差异可测
- [ ] 错题本：画像聚合排除已掌握；推荐 top-3 薄弱 tag → 难度升序 → RandomFill 标注可见；手动重置掌握可用
- [ ] `backend/seeds/` 落地；`make seed` 幂等行为不变；40 题五题型齐备；coding 种子自校验通过
- [ ] `count_actions` 死代码删除；FakeExecutor 契约测试与真执行器同组断言通过（M4 收口）
- [ ] 前端两页上线：`npm test` 通过、`vue-tsc --noEmit` 零错误、`vite build` 通过、路由懒加载、DegradedBanner/MarkdownView 复用、「AI 参考评分」与「随机补足」标注可见
- [ ] spec 回写 11 条全部落档；完成报告含真实实测数字、变异测试记录与未验证项
- [ ] 全程零远端操作、零 merge；commit 按 Task 粒度、全部在 `feat/p5-exercise-mistakebook`
