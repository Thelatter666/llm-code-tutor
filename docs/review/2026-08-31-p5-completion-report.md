# P5 完成报告（习题与错题本）

- 日期：2026-08-31
- 分支：`feat/p5-exercise-mistakebook`，收尾时 HEAD `f125470`（Task 16），本报告随收尾 commit 一并入库
- 执行依据：`docs/superpowers/plans/2026-08-31-p5-exercise-mistakebook.md`（总指挥 2026-08-31 裁定通过）
- 术语照 `CONTEXT.md`；报告数字全部为本批次执行期间**真实实跑**结果，未验证项显式标注「未验证」

---

## 1. 交付概览

### Task 9–17 commit 表

| Task | 内容 | commit |
|---|---|---|
| 9 | 错题本端点（条目/画像/推荐/重置掌握） | `a703767` |
| 10 | 习题 hint SSE（双意图豁免差异、citation 先行、finally 审计） | `e607e9a` |
| 11 | admin 习题 CRUD 五端点（写入校验/发布流/级联删除与审计） | `c72b85d` |
| 12 | `backend/seeds/` 包迁移（M2 收口） | `5b5f950` |
| 13 | 40 题习题种子（五题型齐备、uuid5 幂等、coding 自校验） | `ff0dfb2` |
| 14 | 删除死代码 `ChatService.count_actions`（M6 收口） | `acc00bc` |
| 15 | 前端习题练习页 | `886dba0` |
| 16 | 前端错题本页 | `f125470` |
| 17 | spec 回写 + 变异测试 + 真服务冒烟 + 完成报告 + 审阅修复 | 本 commit |

### 变更规模（实测）

- 已提交区间 `git diff --shortstat 9c989d5..HEAD`（Task 9–16）：**31 files changed, 6115 insertions(+), 55 deletions(-)**
- 本收尾 commit（spec 回写 + 审阅修复 + 本报告，`git diff --shortstat` 工作区实测）：**16 files changed, 557 insertions(+), 73 deletions(-)**

### 交付物盘点

- **后端 13 个新端点**：学生 exercise 4（列表/详情/submit/hint SSE）+ mistake 4 + admin·exercise 5。全部挂 `CurrentRidDep`；admin 另挂 `AdminDep` 并落审计（`admin_exercise_create/update/delete`）；`mistake_reset_mastered` 也写审计（见偏离 c）
- **40 题种子**：choice 10 / multi 6 / blank 8 / short 8 / coding 8；难度 1×8 / 2×10 / 3×12 / 4×7 / 5×3；12 标签封闭词表每个 ≥2 题；uuid5 确定性主键 + 存在即跳过；coding 参考答案用**真** `SubprocessCodeExecutor` 逐用例实测（26 用例 0 失败）
- **前端两页**：`ExerciseView`（五题型作答/判分结果/hint 双入口/SSE 流式渲染/`focus` 深链）与 `MistakeBookView`（三态筛选/掌握状态/薄弱画像/RandomFill 标注/重置掌握），均懒加载独立 chunk

## 2. 测试基线（全部本次实跑，收尾阶段）

### 后端 pytest

| 项 | 实测值 |
|---|---|
| 全量第 1 次 | **955 passed / 2 skipped，181.94s** |
| 全量第 2 次 | **955 passed / 2 skipped，183.23s** |
| 全树收集 | 957 collected（= 955 passed + 2 skipped，吻合） |
| 2 条 skip | `test_retrieval_quality_realistic.py` 语料条件 skip，与 P5 无关（既有） |
| 基线演进 | 交接前 762 → T9 783 → T10 832 → T11 914 → T12 921 → T13 942 → T14 942（删死代码零新增）→ 收尾后 955 |

新增用例 193 条（762+193=955），各文件 `--collect-only` 实测：

| 文件 | 用例数 |
|---|---|
| `test_mistake_api.py` | 23 |
| `test_exercise_hint.py` | 51 |
| `test_admin_exercise_api.py` | 65 |
| `test_exercise_shapes.py` | 25 |
| `test_seeds_package.py` | 7 |
| `test_seed_exercises.py` | 22 |
| 合计 | **193** |

### H-1 负载敏感用例（Step B 专项）

- 隔离复跑 5 次（无并行负载）：**5/5 通过**，单次 0.21–0.24s
- 两次全量（与前端构建**串行**执行）H-1 均未触发
- 同批次审阅修复阶段曾实测 3 次里 2 次 failed、1 次 passed；failed 的两次均为 5.2s 左右——5s 墙钟层先于 256MB 内存层杀掉子进程 → `status=timeout`，断言 `timeout == memory_exceeded` 失败
- 机理：该用例（`test_code_executor.py::test_memory_hog_is_killed_by_memory_layer`，P4 交付）是全套件唯一用真实 256MB 阈值推满内存的用例；负载高时子进程 RSS 攀升速度慢于墙钟累计，墙钟层先触发。**不是 P5 引入的缺陷**，但 P5 新增真子进程用例把套件从 133s 拉到约 182s，客观上提高了撞上它的概率
- 处置：未放宽断言（它守的是「内存层先于 CPU 层触发」的真实承诺，健康检查明确不建议放宽）；详见 §7 已知限制

### 前端三门槛（收尾阶段实跑）

| 门槛 | 实测值 |
|---|---|
| `npm test`（vitest） | **8 passed**（零新增，与计划预估一致） |
| `vue-tsc --noEmit` | **零错误**（exit 0） |
| `vite build` | **通过**（1m07s） |

chunk 体积（构建日志实测）：`ExerciseView` 14.62 kB JS + 4.17 kB CSS；`MistakeBookView` 7.86 kB JS + 2.99 kB CSS。Monaco 4MB 超限告警为**既有已知项**，与本批无关。

### lint

`make lint` 实测 **35 errors**（22 fixable），与 M-1 基线分布逐项一致——**P5 新文件零告警，lint 总数未涨**。存量归属 P6 后清理批次，按裁定未顺手修。

## 3. 真服务冒烟实测摘录

`uvicorn --workers 1` + 独立临时库（脚本 `/tmp/p5gen/smoke.py`，全部走 HTTP 不碰测试替身；档位经直接改库设置为 strict——`PUT /admin/model-config` 的 LLM/档位部分归 P6）。**收尾重跑（审阅修复之后）：44/44 通过**。审阅修复前为 41/41，收尾新增 3 条断言（见下）。

覆盖链路（全部通过）：

- **种子**：`python -m app.seed` 连跑两次幂等（1 用户 / 1 配置 / 40 习题）
- **列表**：published 共 40；facets 覆盖 12 标签；type=coding → 8、difficulty=3 → 12、knowledge_tag=推导式 → 7 且 facets 不受影响；分页 page=2/page_size=15 → 15 条 total 40；学生详情不含 answer/explanation/test_cases
- **判题**：choice 答错 0 分并揭示答案解析、答对 100 分 attempt_no 递增；multi 漏选 50/False（judge_detail `missing:["B","D"], wrong:[]`）；coding 真子进程正确 100 / 部分 33 / 黑名单逐用例 blocked / 非 `{source}` 形态 → 4220
- **short**：Mock 启发式 `judge_mode="mock_heuristic"`、ai_scored=true
- **hint 双意图 SSE**（strict 档实测话术原文）：
  - `seek_answer`：`[Mock 模式]我不能给出完整可运行代码，只给思路拆解：1) 先明确输入与输出；2) 拆解为最小可验证步骤；3) 逐步实现并测试。关键概念讲清楚之后，下面只给伪代码骨架：…`
  - `review_my_code`：`[Mock 模式]本次为评改已写代码 / 判分请求，豁免防抄袭档位约束，下面给出改进版本与讲解。`（strict 档下不受档位约束，豁免话术可见）
  - done 九字段齐全；无知识库时 `degraded=true` + `fallback_reason="no_relevant_chunk"`
- **错题本**：画像降序聚合；推荐 5 条标注封闭（本例全 profile，RandomFill 路径由零错题新学生 4 条全 random 验证）；推荐不泄题；limit=21 → 422；连对两次转已掌握；重置掌握 mastered=false / 连对归零 / 错误历史保留
- **admin**：创建 source=admin/status=draft；学生访问 → 4030；PATCH 传 source → 422；发布后学生可见；DELETE 级联删并回计数 `{submissions_deleted:1, mistake_entries_deleted:1}`
- **审计**：六类 action 全部落库（exercise_submit/exercise_hint/mistake_reset_mastered/admin_exercise_create·update·delete）

**收尾新增 3 条断言（对应审阅修复②③，全部通过）**：

1. draft 习题发布后学生提交答错入错题本 → 下架后 `/mistakes` 条目丢弃（列表为空）且 `DELETE /mistakes/{id}/mastered` 返回 **4040**
2. hint `review_my_code` 传参考答案形态 `{"solution":"print(1)"}` → **422**（门禁收紧为学生形态）
3. hint 对不存在习题仍是**流前 404**（非 200 + 流内 error；此断言脚本中已有，随重跑复验通过）

## 4. 变异测试记录（8 项逐条实跑）

全部按「改坏 → 跑目标测试必须失败 → 字节级还原 → `git status` 验证干净」执行，复现脚本 `/tmp/p5gen/mutate.py`、结果 `/tmp/p5gen/mutation-report.json`。8 项全部被具名用例击杀，结束后工作区干净：

| # | 突变 | 击杀用例（实测失败清单） |
|---|---|---|
| M1 | `mastery.py` 错误分支删掉 `mastered=false` 回滚 | `test_mastery.py::test_mastered_rolls_back_on_wrong`、`test_mistake_service.py::test_record_result_full_cycle_with_rollback`（2 failed） |
| M2 | `judging.py` 删 multi 真子集 50 分分支 | `test_judging.py::test_multi_subset_scores_50_and_is_wrong`、`test_multi_detail_reports_missing_and_wrong`、`test_exercise_service.py::test_multi_subset_scores_50_and_is_wrong`（3 failed） |
| M3 | `exercise_service.py` 删 15s 预算时间比较 | `test_exercise_service.py::test_coding_budget_abort_marks_skipped_and_scores_by_ratio`（1 failed） |
| M4 | `mistake_service.py` 随机补足标注改标 profile | 服务层 `test_recommendations_random_fill_is_marked`、`test_recommendations_without_mistakes_all_random` + HTTP `test_recommendations_marks_profile_and_random`、`test_recommendations_default_limit_is_five`（4 failed） |
| M5 | hint 装配 intent 强制 seek_answer | `test_exercise_hint.py::test_review_my_code_is_exempt_from_mode_but_not_from_floor`（1 failed） |
| M6 | `seeds/exercises.py` 删主键存在性检查 | `test_seed_exercises_is_idempotent`、`test_seed_exercises_does_not_overwrite_edits`（IntegrityError，2 failed） |
| M7 | 学生端列表去 published 过滤 | `test_exercise_api.py::test_list_exposes_only_published`（1 failed）。**诚实记录**：submit 路径的 draft 4040 由 `get_published` 单独守住，该突变未使其失败——列表过滤与提交校验是两道独立防线，各自有专项用例 |
| M8 | reset_mastered 保留 consecutive_correct | 裁定 2 服务层 `test_reset_mastered_clears_streak_keeps_history` + HTTP `test_reset_mastered_returns_reset_state`（2 failed） |

## 5. 偏离与自主决策清单（请总指挥逐条复核）

| # | 决策 | 理由 |
|---|---|---|
| a | hint 中断注册表作用域键取 `f"{user_id}:{exercise_id}"` 而非计划写的 `(exercise_id, request_id)` | 习题是**共享实体**，裸 `exercise_id` 会让 B 同学发起辅导掐断 A 同学进行中的流（跨用户干扰）；chat 安全是因为会话属于单个用户。已写进 spec §8.1 P5 补记，并有专项用例 |
| b | `GET /mistakes` 返回裸数组不分页 | 与学生端会话/知识库/文档列表同构；spec 分页约定只约束分页端点。单学生条目上限即题库规模（40），分页无收益 |
| c | 手动重置掌握度写 `AuditLog(mistake_reset_mastered)` | 计划只要求 admin 端点写审计；但改变学习状态的用户关键行为应留痕，同 `chat_conversation_delete` 先例。已回写 §6.2 |
| d | 新增 `backend/app/domain/exercise/shapes.py`（计划文件表之外） | 跨题型形状规则（choice/multi 必带 options、answer 键 ⊆ options、coding 必带 test_cases）独立成模块，admin CRUD 写入校验与种子自校验**共用一份**，避免两套口径漂移 |
| e | PATCH 显式 null 到非空列 → 422（计划未列） | 否则 `{"difficulty": null}` 落库时 NOT NULL 违约变 5000；入口就该拒绝。`options`/`test_cases` 是真可空列除外 |
| f | `ExerciseView` 支持 `/exercises?focus=<id>` 深链 | 错题本「去做这道习题」需要跳转定位，无深链则推荐区闭环断裂 |
| g | `test_exercise_models.py` 的 difficulty 用例补 options | Task 11 收紧跨题型契约后，不补会让该用例因「缺 options」失败而锁不住 difficulty 边界——必要适配，非放宽 |
| h | **未改**：submit 路由 commit 后再查一次习题的 TOCTOU 双查询 | 属 Task 7 已合入代码；单 worker 下窗口极小，改它需动服务层签名（约束 9 禁止重做已合入实现）。留请总指挥裁定 |

## 6. 六路对抗审阅的处置

共 24 条发现：**采纳修复 20 条**，明确不采纳 4 条。

### 采纳修复（20 条，含举要）

spec 两处表格被劈断并修复、§8.5 失效交叉引用、「题目」禁词、reset 审计未回写、错题本不过滤 status 泄题、HintIn 门禁与 submit 分裂、hint 前置量挪进 try、`py-blank-01` 题干泄露答案、`py-choice-02` 解析与 Unicode 标识符不符、multi-02/blank-06 难度倒挂对调、前端用例表把 status 原样投给学生、hint 收尾用 intent 判定归属与切题误弹提示、错题本三面板 Promise.all 绑死、ElMessageBox 取消未 catch、budget_limit_s 前端写死 15、「还没有错题记录，以下为随机题」判据错误 + 术语、`JudgeCase.status` 收紧为 RunStatus、`routers/mistake.py` 直接 `session.get` 改走服务层 `published_exercise` 等。

其中三处行为级修复对应 §3 冒烟新增断言已实测：

- ① `stream_hint` 前置量（get_published/resolve_mode/floor_hit/params）挪进 try，流内取不到 published 改发 error 事件 + 落审计，不再裸抛
- ② 错题本三个出口（条目/画像/重置回显）只认 `status=published`
- ③ `HintIn.answer` 门禁收紧为学生形态（`is_student_answer`）：`{"solution":...}`、标量、`True` 一律 422

### 明确不采纳（4 条，含理由）

1. **域常量替换 Task 6/7 已合入代码里的 `"published"`/`"draft"` 字面量**：约束 11 禁止重做已合入实现；只替换了自己新增处，并把 pattern 三处重复收敛到 schemas（`TYPE_PATTERN`/`STATUS_PATTERN`）
2. **submit 服务层返回 `(submission, exercise)`**：同上，动已合入签名，收益（省一次查询）不值签名变更
3. **hint 断连时 finally 里 `await` 提交可能被 anyio 取消域掐掉**：与 `chat_service` 逐行同构（P2 已交付并审阅过），修它需引 shield/独立会话，属**跨批次一致性改造**，登记为遗留项（§8）请总指挥裁定是否单开批次统一处理；P5 已用 `aclose()` 专项用例守住「正常断连路径审计与注销」
4. **环境观察**：某审阅 subagent 报告运行期间收到插入式指令要求它「停止并改用日语作答」，它按提示注入处理、未遵从，工作不受影响。此处仅如实记录

## 7. 已知限制与未验证项

- **hint 中断依赖客户端断连（无 /stop 端点，裁定 10）**：服务端无显式停止入口；断连后的审计写入受上述 anyio 取消域影响（**未验证**：真浏览器 AbortController 下的审计落库情况，仅有 `aclose()` 模拟用例）
- **H-1 负载敏感性**：本机隔离复跑通过率 5/5；负载下曾出现 2/3 失败（失败形态 `timeout` 而非 `memory_exceeded`，5s 墙钟层先触发）。**禁止满负载并行跑测试**（勿与 vite build 同时跑）。该用例非 P5 引入（P4 执行器用例），但 P5 真子进程用例把套件从 133s 拉到约 182s，客观上提高撞上概率
- **真实 OpenAI 兼容提供方全链路未验证**（无 API Key，与 P3 遗留 2 同因）；简答 AI 评分与 hint 的 model 路径只经 FakeLLM 契约测覆盖
- **前端两页无 vitest 用例**（M-9 自设缺口；spec §10 只要求类型检查与构建）
- **浏览器视觉项未验证**：对比度、375/768/1024/1440 四断点无溢出
- **seed 的 coding 自校验在满载下未单独计时**；本机实测该文件 1.5–1.9s（空闲）
- 变异测试的 M7 突变未波及 submit 路径（见 §4 诚实记录）——两道防线各自有专项用例，但「列表过滤」这一突变本身只被列表用例击杀

## 8. 遗留项归属建议

| 条目 | 建议归属 |
|---|---|
| H-1 负载敏感 flake（标注/CI 编排/演示机跑法） | 清理批次或 CI 引入时处理；先在文档口径固定「勿满载并行」 |
| hint/chat 的 finally 审计 anyio 取消域（审阅不采纳第 3 条） | 请总指挥裁定是否单开跨批次一致性改造（涉及 chat_service + exercise_service 两处同构代码） |
| submit 路由 TOCTOU 双查询（偏离 h） | 请总指挥裁定；改动牵服务层签名 |
| README 默认密码警示 + 「make seed 后含 40 道习题」的文档说明（M-15 延伸） | P6（README 收口） |
| admin·exercise 的前端管理页 | P6（管理后台收口） |
| `PUT /admin/model-config` 的 LLM/档位部分（本批档位只能改库） | P6 |
| lint 存量 35 errors（M-1） | P6 之后清理批次（既有裁定） |
