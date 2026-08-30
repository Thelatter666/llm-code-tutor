# P3 代码解析与辅导（含三项并入任务）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `POST /code/analyze`（静态解析 + AI 讲解，固定 `review_my_code` 意图豁免防抄袭档位），并完成三项 P2 遗留并入任务：Mock 提供方流式延迟、前端 Markdown 渲染（防 XSS）、spec §8.1 歧义表述改写。

**Architecture:** 沿用 P0–P2 的 `routers → services → domain → infrastructure` 分层。静态解析是确定性输出，按本批次裁定**纯领域层实现**（`domain/code/`，零 IO，可脱离数据库单测）；`CodeAnalysis` 表落 `infrastructure/persistence/models.py`；服务层（`CodeService`）负责 source_hash 复用、豁免意图装配、流式收集与降级；路由只做参数校验与序列化。前端新增代码辅导页，AI 回答统一经带消毒的 Markdown 渲染组件。

**Tech Stack:** Python 3.12 · ast（标准库）· FastAPI · SQLAlchemy 2 (async) · Pydantic v2 · pytest · Vue 3 · Vite · TypeScript · markdown-it + DOMPurify + highlight.js（消毒渲染）· vitest + happy-dom（消毒策略单测）

## Global Constraints

以下约束逐字摘自 spec / ADR / AGENT.md / 批次裁定，每个任务默认包含，不再重复说明。

- 单进程单 worker（ADR-0002）；**解析（ast.parse 为 CPU 同步调用）必须经 `run_in_threadpool` 卸载**，AI 流式生成本身是异步端口调用，无需卸载
- 不做数据库迁移，建表用 `create_all`（ADR-0006）；datetime 列用 `app.infrastructure.persistence.db.UTCDateTime`
- 统一响应体 `{code, message, data, request_id}`；端点注入 `CurrentRidDep`，禁止硬编码 `request_id=""`
- 领域层（`backend/app/domain/`）禁止 import 任何基础设施模块，业务规则零 IO 可单测
- 服务层只依赖 `Protocol` 端口，不依赖具体 adapter
- 术语以 `CONTEXT.md` 为唯一来源（静态报告 StaticReport / AI 报告 AIReport / 代码分析 CodeAnalysis / 请求意图 / 评改已写代码 ReviewMyCode / 豁免 Exemption / 文本增量 TextDelta / 用量 Usage / 估算用量 EstimatedUsage）
- **边界：不创建 `CodeSession` 与 `CodeRun` 表，不实现其 CRUD** —— 归 P4；页面代码输入用组件本地状态
- SSE 复用 P2 的 `infrastructure/sse.py`；中断用 per-call `asyncio.Event`，绝不做成 provider 实例方法
- `token_usage` 必须来自流末 `Usage` 元素；Mock 无真实计数按 `len(content)//4` 估算并置 `usage_estimated=true`
- 不配置 CORS（dev / serve 均同源）
- 禁止任何涉及远端的操作（`git push` / `git remote add`）
- 每个任务完成后跑全量后端测试（`cd backend && . .venv/bin/activate && python -m pytest -q`），**基线 476 passed / 2 skipped**（2 条 skip 为 P1 语料型条件跳过，属预期）
- 前端：`npx vue-tsc --noEmit` 零错误；路由组件必须懒加载；`frontend/docs/ui-baseline.md` 是强制约束

### Commit 策略

用户已于 **2026-08-31 预先授权**（`AGENT.md`「授权例外」表）：本计划每个 Task 完成且全量测试通过后，**可直接按 Task 粒度 `git commit`**，无需逐次请示。**`git merge` 与 `git push` 不在授权范围内**，仍需用户单独下令。

### 本批次的七条已拍板决策（不再讨论，直接执行）

1. **豁免是显式契约不是推断** —— `/code/analyze` 固定传 `intent=review_my_code`（ADR-0005）。绝不按「消息是否含代码块」推断意图。
2. 所有阻塞调用经 `run_in_threadpool` 卸载；解析与 AI 推理都不例外。
3. 单进程单 worker；建表用 `create_all`；datetime 用 `UTCDateTime`；端点一律 `CurrentRidDep`。
4. SSE 工具复用 `infrastructure/sse.py`；中断用 per-call `asyncio.Event`。
5. `token_usage` 必须来自流末 `Usage` 元素；Mock 按 `len(content)//4` 估算并置 `usage_estimated=true`。
6. 不配置 CORS。
7. Mock 延迟：`Settings.mock_token_delay_ms` 默认 30，**只影响 Mock 提供方的 `stream()`**，`complete()` 不受影响；绝不触碰 OpenAI 兼容链路；受影响的既有测试显式把该设置调为 0（不改默认值、不删延迟）。

---

## File Structure

```
backend/
├── app/
│   ├── domain/code/
│   │   ├── __init__.py
│   │   ├── analysis.py          静态解析（Python ast + JS 轻量解析），零 IO
│   │   └── review.py            Mock 讲解模板（static_report → Markdown）+ prompt 问题串
│   ├── infrastructure/
│   │   ├── adapters/llm/mock_provider.py   追加 mock_token_delay_ms 流式延迟
│   │   └── persistence/models.py           追加 CodeAnalysis
│   ├── prompts/                 （code_review.j2 已有，不改）
│   ├── services/
│   │   └── code_service.py      hash 复用 / 豁免装配 / 流式收集 / Mock 模板化 / 降级
│   ├── routers/
│   │   └── code.py              POST /code/analyze
│   ├── schemas/code.py
│   └── main.py                  （注册 code 路由）
└── tests/
    ├── test_mock_provider.py    （追加延迟用例）
    ├── test_code_analysis.py    静态解析领域层
    ├── test_code_review_template.py  Mock 模板
    ├── test_code_models.py      CodeAnalysis 表
    ├── test_code_service.py     服务层编排
    └── test_code_api.py         HTTP 层

frontend/
├── package.json                 （+ markdown-it dompurify highlight.js；dev + @types/markdown-it vitest happy-dom）
├── vitest.config.ts
├── src/
│   ├── utils/markdown.ts        渲染 + 消毒（html:false + DOMPurify 双层）
│   ├── components/MarkdownView.vue
│   ├── api/code.ts · types/code.ts
│   ├── views/student/CodeReviewView.vue
│   ├── views/student/ChatView.vue        （assistant 气泡改 Markdown 渲染）
│   ├── router/index.ts                   （追加 /code 路由，懒加载）
│   └── components/AppShell.vue           （追加导航项）
└── tests/markdown.spec.ts       消毒策略单测（vitest）
```

---

## Task 0: 实施计划

- [ ] 本文件落盘并 commit（`docs: P3 实施计划`）。

---

## Task 1: Mock 提供方流式延迟（并入任务 1，改 P0 产物代码）

**Files:**
- Modify: `backend/app/core/config.py`（Settings 增项）
- Modify: `backend/app/infrastructure/adapters/llm/mock_provider.py`
- Modify: `backend/tests/conftest.py`（套件级显式置 0）
- Modify: `backend/tests/test_mock_provider.py`（追加延迟用例）

> **问题**：Mock 约 0.1s 生成完毕，浏览器点「停止」几乎总来不及截断，无 API Key 演示看不到流式输出（P2 完成报告 §4.3 / §7.2，8.31 裁定第 2 项）。
> **要求**：每个 `TextDelta` 之间 `await asyncio.sleep(delay/1000)`；`complete()` 非流式**不得**引入延迟；只影响 Mock。构造参数显式给值时优先于 Settings（供延迟用例独立于环境变量）。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| `Settings` 声明 `mock_token_delay_ms` 且默认 30 | 裁定的默认值 |
| 开启延迟（如 5ms）时 `stream()` 总耗时显著大于 0（≥ 0.2s） | 流式延迟真实生效 |
| 同延迟下 `complete()` 耗时 < 0.1s | 非流式不受影响 |
| `cancel` 预先置位时流立即结束、不睡眠 | 中断路径不被延迟拖慢 |

- [ ] **Step 2: 确认失败 → 最小实现**
  - `Settings.mock_token_delay_ms: int = 30`（`ge=0`）
  - `MockLLMProvider(token_delay_ms: float | None = None)`：未显式给值时读 `get_settings()`；`stream()` 逐字符循环把 `asyncio.sleep(0)` 升级为 `asyncio.sleep(delay)`（delay=0 时语义与原先一致）
- [ ] **Step 3: conftest 套件级置 0**（`os.environ.setdefault("MOCK_TOKEN_DELAY_MS", "0")`，与既有 `DATABASE_URL` 等同一模式；不改默认值、不删延迟，延迟用例用构造参数显式开延迟）
- [ ] **Step 4: 全量测试通过 → Commit** `feat(backend): Mock 提供方流式延迟 mock_token_delay_ms，无 Key 演示可观察逐字输出`

---

## Task 2: 静态解析领域层（Python ast + JS 轻量解析）

**Files:**
- Create: `backend/app/domain/code/__init__.py` `backend/app/domain/code/analysis.py`
- Create: `backend/tests/test_code_analysis.py`

> **spec §8.4**：静态解析产出 `static_report`（函数/类清单、圈复杂度、未使用变量、裸 `except`、行数统计）。
> **本批次裁定**：确定性输出，纯领域层实现、零 IO、可脱离数据库单测（ast 是标准库，无网络无磁盘）。
> **`StaticReport` 结构**（spec 未定死字段名，本批次定稿，全语言共用同构）：
> `{language, lines{total,code,blank,comment}, functions[{name,line,args,complexity}], classes[{name,line,methods}], complexity{max,average,worst}, issues{unused_variables[{name,line}], bare_excepts[{line}]}, syntax_error{line,message}|null}`
> Python 的「裸 except」= `ExceptHandler.type is None`；JavaScript 无 except，对应物为**空 catch 块**（`catch (...) {}`），落同一字段并在文档注明。
> **语法错误不抛 500**：返回 `syntax_error` 并给出可用的行数统计 —— 教学工具对写了一半的代码更要给出反馈。

- [ ] **Step 1: 失败测试**（每条规则一个正向 + 一个反向用例）

| 组 | 断言 |
|---|---|
| Python 行数 | 代码 / 空行 / 注释行分类正确；空源码零除不炸 |
| Python 函数/类 | 函数清单含嵌套方法；`args` 计数含默认参；类统计方法数 |
| Python 圈复杂度 | 规则固化：1 + If/For/While/AsyncFor/ExceptHandler/IfExp/Assert/each comprehension(+其 if)/BoolOp 增量/match_case；直线代码=1 |
| Python 未使用变量 | 函数内赋值后未读取 → 报告；`_` 前缀豁免；`self/cls` 豁免；augassign 视为已读；闭包内读取视为已读；`except E as e` 的 `e` 计入 Store |
| Python 裸 except | `except:` 命中；`except ValueError:` 不命中 |
| Python 语法错误 | `syntax_error.line/message` 非空，函数清单为空，行数统计仍产出 |
| JS 函数/类 | `function f(){}`、`const g = () => {}`、`class A{}` 命中 |
| JS 未使用变量 | 声明后零引用 → 报告；有引用不报 |
| JS 空 catch | `catch(e){}` 空体命中；有处理逻辑不命中 |
| JS 行数 | `//` 与 `/* */`（含跨行）注释分类正确 |
| 零 IO | 模块源码不含 `import sqlalchemy` / `open(` / `requests`（源码级断言） |

- [ ] **Step 2–4: 失败 → 实现 `analyze(language, source) -> StaticReport`（dataclass，`asdict()` 序列化）→ 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): 静态解析领域层，Python ast + JS 轻量解析（spec §8.4）`

---

## Task 3: CodeAnalysis 表 + Mock 讲解模板（领域层）

**Files:**
- Modify: `backend/app/infrastructure/persistence/models.py`
- Create: `backend/app/domain/code/review.py`
- Create: `backend/tests/test_code_models.py` `backend/tests/test_code_review_template.py`

> **spec §5**：`CodeAnalysis = user_id, language, source_hash, static_report(JSON), ai_report(JSON?), created_at`。**不建 CodeSession / CodeRun**（归 P4）。
> `ai_report(JSON)` 定为本批次的自描述结构：`{content, provider, model, token_usage, usage_estimated, degraded, fallback_reason}` —— content 是 Markdown，前端用 Task 6 的组件渲染。
> **spec §8.4**：Mock 模式下 `ai_report` 由 `static_report` 模板化生成 —— 纯函数 `render_mock_review(static_report) -> str`，产出 Markdown。
> `source_hash` = sha256(f"{language}\x00{source}")；唯一约束 `(user_id, language, source_hash)` 让「不重复算」在库层也有守卫。

- [ ] **Step 1: 失败测试**

| 文件 | 断言 |
|---|---|
| models | 建表；static_report / ai_report JSON 列可读写；`created_at` 带 UTC 时区；唯一约束生效（重复插入 IntegrityError） |
| review 模板 | 有未使用变量 / 裸 except 时逐条出现在讲解里；无问题时输出「未发现明显问题」段；复杂度过高（>10）时给出拆分建议；语法错误时展示错误信息并跳过问题段；语言措辞区分（Python 裸 except / JS 空 catch） |
| 问题串 | `build_review_question(...)` 含静态摘要、完整源码与语言标注；供 PromptAssembler 装配（Task 4 消费） |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): CodeAnalysis 表与 Mock 讲解模板，static_report 模板化生成 AI 报告（spec §5 §8.4）`

---

## Task 4: CodeService（hash 复用 / 豁免装配 / 流式收集 / 降级）

**Files:**
- Create: `backend/app/services/code_service.py`
- Modify: `backend/tests/fakes.py`（如需追加替身，沿用 `FakeLLM` / `ExplodingLLM` 模式）
- Create: `backend/tests/test_code_service.py`

> **spec §8.4 / ADR-0005**：固定 `review_my_code` 意图；`source_hash` 命中历史则复用；provider 可用时流式生成 `ai_report`；Mock 模式由 `static_report` 模板化生成。
> **「Mock 模式」判定 = 配置层**（与 P2「无 API Key → Mock 模式，不算降级」同口径）：`cfg.provider != openai_compat` 或无 API Key → 模板化，**不发起 LLM 调用**（顺带避开 Mock 延迟，让无 Key 演示的 /code/analyze 秒回）。
> **降级路径（spec §9）**：配置了真提供方但调用失败（`LLMRuntime` 抛 `5021`）→ 改用模板生成，置 `degraded=true` + `fallback_reason="llm_fallback_to_mock"`（封闭枚举之一）。
> **静态解析阻塞卸载**：`analyze()` 经 `run_in_threadpool`（ADR-0002）。
> **不做 RAG**：spec §7.2 明确该链路只服务答疑对话与习题辅导；`/code/analyze` 无 citation。
> **底线检测不做**：输入是代码而非自然语言请求，关键词误判率高；底线条文仍由模板无条件注入（装配器无跳过开关，spec §3.2 权衡 10）。
> **审计**：写 `AuditLog(action=code_analyze)`（业务关键行为，与 chat 同模式）。

- [ ] **Step 1: 失败测试**

| 断言 | 锁住什么 |
|---|---|
| 首次分析：落库一行，`static_report` 与领域层产出一致 | 主路径 |
| 相同 `(user_id, language, source)` 二次分析：返回同一 `analysis_id`，静态解析只执行一次（monkeypatch 计数）、不发起 LLM 调用 | source_hash 复用 |
| 不同 user 相同源码：不复用（按 user 隔离） | 越权隔离 |
| 装配时 `intent=review_my_code`：捕获到的 system prompt 含豁免标记、**不含**档位标记，即使后台配置为 strict | ADR-0005（豁免是显式契约） |
| Mock 模式：`ai_report.content == render_mock_review(...)`，provider=mock，`usage_estimated=true`，FakeLLM 零调用 | spec §8.4 Mock 模板化 |
| 真提供方（FakeLLM）：`ai_report.content` 为流式收集文本；`token_usage` **逐字取自流末 Usage**（`FixedUsageLLM` 给与长度无关的 1111/2222/3333） | 拍板决策 5 |
| FakeLLM(fail=True)：不抛 5021，改模板生成 + `degraded=true` + `fallback_reason="llm_fallback_to_mock"` | spec §9 降级可见 |
| 静态解析经 `run_in_threadpool`（monkeypatch 计数断言） | ADR-0002 |
| `AuditLog(action=code_analyze)` 落库 | 审计 |

- [ ] **Step 2–4: 失败 → 实现 → 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): CodeService —— source_hash 复用、review_my_code 豁免、Mock 模板化与流式降级（spec §8.4 §9 ADR-0005）`

---

## Task 5: code 路由（POST /code/analyze）

**Files:**
- Create: `backend/app/schemas/code.py` `backend/app/routers/code.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_code_api.py`

> **spec §6.2 code 行**：`POST /code/analyze {language, source}` → `{static_report, ai_report, analysis_id}`。响应为其超集：`analysis_id` / `language` / `static_report` / `ai_report` / `reused`（前端可提示「与上次分析相同」）。

- [ ] **Step 1: 失败测试**（照 `test_chat_api.py` 脚手架）

| 断言 | 锁住什么 |
|---|---|
| 未鉴权 → `4010` | 鉴权 |
| 学生可调用（无 admin 限制） | spec 未限角色 |
| Python / JavaScript 各一例：`code=0`，`data.analysis_id` 非空，`static_report` 结构完整 | 主路径 |
| `language=ruby` → 422 | 参数校验 |
| `source` 空 / 超 20000 字 → 422 | 参数校验 |
| 响应体 `request_id` 与响应头一致且非空 | CurrentRidDep（H3） |
| 同一学生重复提交 → `reused=true` 且 `analysis_id` 相同 | 复用语义（HTTP 层） |

- [ ] **Step 2–4: 失败 → 实现（router 不含业务逻辑）→ 通过**
- [ ] **Step 5: 全量测试 → Commit** `feat(backend): POST /code/analyze 端点，统一响应与鉴权接入（spec §6.2）`

---

## Task 6: 前端 Markdown 渲染（并入任务 2，防 XSS）

**Files:**
- Modify: `frontend/package.json`（+ `markdown-it` `dompurify` `highlight.js`；dev + `@types/markdown-it` `vitest` `happy-dom`）
- Create: `frontend/vitest.config.ts` `frontend/src/utils/markdown.ts` `frontend/src/components/MarkdownView.vue` `frontend/tests/markdown.spec.ts`
- Modify: `frontend/src/views/student/ChatView.vue`（assistant 气泡）、`frontend/src/main.ts`（highlight.js 主题样式）

> **消毒策略（双层）**：① `markdown-it` 以 `html:false` 渲染 —— 源里的原生 HTML 一律转义为文本；② 渲染产物再过 `DOMPurify.sanitize` 兜底 —— 即使上游配置被改错，脚本类载荷也进不了 DOM。高亮用 highlight.js（注册 python / javascript / typescript / json / bash，控制体积）。
> **`v-html` 的使用边界**：只允许渲染 `renderMarkdown()` 的**已消毒**产物，组件注释写明该契约；用户气泡保持纯文本渲染。
> 前端此前无单测设施；消毒策略必须有自动化测试，故引入 vitest + happy-dom（dev 依赖，不影响构建产物），在完成报告中说明。

- [ ] **Step 1: 依赖安装（本机实测网络可用性）→ 失败测试 `frontend/tests/markdown.spec.ts`**

| 断言 | 锁住什么 |
|---|---|
| `` `**粗体**` `` 与代码块渲染为 `<strong>` / `<pre><code>` | Markdown 基本能力 |
| 源含 `<script>alert(1)</script>` → 输出不含 `<script` | 第一层（html:false 转义） |
| 源含 `<img src=x onerror=alert(1)>` → 输出不含 `onerror` / 不含 `<img` | 消毒 |
| `[x](javascript:alert(1))` → 输出不含 `javascript:` | 链型 XSS |
| ```` ```python ```` 围栏 → 输出含 `hljs` class | 高亮生效 |
| `renderMarkdown` 对空串 / 纯文本不炸 | 边界 |

- [ ] **Step 2: 实现 `utils/markdown.ts` + `MarkdownView.vue` → 测试通过**
- [ ] **Step 3: ChatView assistant 气泡接入 `MarkdownView`**（用户气泡保持纯文本；打字机行为不变）
- [ ] **Step 4: `npx vue-tsc --noEmit && npx vite build` 零错，记录体积变化**
- [ ] **Step 5: Commit** `feat(frontend): AI 回答 Markdown 渲染，html:false + DOMPurify 双层消毒与代码高亮`

---

## Task 7: 代码辅导页（CodeReviewView）

**Files:**
- Create: `frontend/src/api/code.ts` `frontend/src/types/code.ts` `frontend/src/views/student/CodeReviewView.vue`
- Modify: `frontend/src/router/index.ts`（`/code`，懒加载）、`frontend/src/components/AppShell.vue`（导航项）

> **边界（本批次裁定）**：代码输入用组件本地状态，**不做草稿持久化** —— CodeSession 归 P4。
> 语言下拉（python / javascript）+ 源码文本域 + 「开始解析」；结果区 = 静态报告面板（行数 / 函数 / 类 / 圈复杂度 / 问题清单 / 语法错误提示）+ AI 讲解面板（`MarkdownView` + provider / 估算用量角标 + `DegradedBanner` 复用）+ `reused` 提示。
> 页面提示文案注明「固定为评改已写代码意图，豁免防抄袭档位约束」（ADR-0005 的用户可见面）。

- [ ] **Step 1: 类型 + API 层 → 页面组件 → 路由与导航**
- [ ] **Step 2: `npx vue-tsc --noEmit && npx vite build` 零错；路由懒加载（独立 chunk）**
- [ ] **Step 3: Commit** `feat(frontend): 代码解析辅导页，静态报告与 AI 讲解展示（spec §8.4）`

---

## Task 8: spec §8.1 歧义表述改写（并入任务 3）

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md`

> 原文：「截断后若首轮被丢弃，改为保留最后一轮以保证上下文连贯。」
> 改为：「若累加后一轮都未纳入（即最近一轮本身已超出预算），则强制纳入最近一轮，保证上下文不断裂。」
> 语义与 P2 已实现行为（`test_history_truncation.py::test_oversized_last_round_is_kept_as_a_fallback`）完全一致，**只改文字，不改任何代码**。

- [ ] **Step 1: 改写并前后对照留档（进完成报告）→ Commit** `docs(spec): 改写 §8.1 历史截断兜底句，消除「首轮被丢弃」歧义`

---

## Task 9: 端到端实测、变异测试与完成报告

**Files:**
- Create: `docs/review/2026-08-30-p3-completion-report.md`

- [ ] **Step 1: 真服务实测**（`uvicorn app.main:app --workers 1`）：
  - `POST /code/analyze` Python / JavaScript 各一例，含完整 `static_report`
  - source_hash 复用实测（二次请求 `reused=true`）
  - Mock 延迟对照：同一答疑请求在 `MOCK_TOKEN_DELAY_MS=30`（默认）与 `=0` 下的总耗时
  - Mock 模式下 `ai_report` 由模板生成、`usage_estimated=true`；未配置 API Key 时端点秒回
- [ ] **Step 2: 前端实测**：类型检查 / 构建产物体积对照 / 路由懒加载 chunk / Markdown 高亮与消毒（真浏览器）
- [ ] **Step 3: 变异测试** —— 拆掉关键修复，记录哪些测试失败（每条都实际跑过）：
  1. mock_provider 删 `asyncio.sleep(delay)` → 延迟用例失败
  2. mock 的 `complete()` 也加延迟 → `complete()` 不受影响用例失败
  3. analyzer 跳过裸 except / 未使用变量 / 复杂度 If 计数 → 对应领域层用例失败
  4. service 恒新建行（去复用）→ 复用用例失败
  5. service `intent` 改 `seek_answer` → 豁免用例失败
  6. service 提供方失败时改为直接抛 5021 → 降级用例失败
  7. service 用量改按文本长度现算 → FixedUsage 用例失败
  8. `renderMarkdown` 去掉 DOMPurify → 消毒测试失败
- [ ] **Step 4: 写完成报告并 commit** `docs: P3 完成报告（含端点实测、Mock 延迟对照与变异测试指引）`

---

## 验收清单（P3 完成标准）

- [ ] `python -m pytest -q` 全绿（基线 476 passed / 2 skipped，2 条 skip 与 P3 无关）
- [ ] `POST /code/analyze`：Python 与 JavaScript 均返回完整 `static_report`；语法错误不 500
- [ ] `source_hash` 命中复用（同 user 同源码同语言 → 同 `analysis_id`，不重复解析）
- [ ] `/code/analyze` 固定 `review_my_code`，strict 档下 system prompt 仍为豁免标记（ADR-0005）
- [ ] Mock 模式 `ai_report` 由 `static_report` 模板化生成且不发起 LLM 调用；真提供方走流式收集、用量取流末 `Usage`
- [ ] 真提供方失败 → 模板兜底 + `degraded=true` + `fallback_reason=llm_fallback_to_mock`
- [ ] 静态解析经 `run_in_threadpool`；`AuditLog(action=code_analyze)` 落库
- [ ] Mock 流式延迟默认 30ms 生效、`complete()` 不受影响、套件显式置 0 不拖慢既有用例
- [ ] 前端：Markdown 渲染 + 代码高亮上线；`html:false + DOMPurify` 双层消毒有自动化测试；路由懒加载
- [ ] 未创建 `CodeSession` / `CodeRun`，无草稿持久化（P4 边界）
- [ ] spec §8.1 歧义句已改写，代码零改动

## 待处理项（留到后续批次）

- `CodeSession` / `CodeRun` 与受限执行器（P4）
- 管理端统计页、`/admin/overview`（P6）
- lint 存量清理（P6 后独立批次，含本批新增文件的复核）
