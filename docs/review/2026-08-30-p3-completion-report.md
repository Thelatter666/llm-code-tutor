# P3 代码解析与辅导（含三项并入任务）—— 完成报告

- 日期：2026-08-31
- 分支：`feat/p3-code-review`（自 `main` 同基点 `db2d8e1` 切出，P0 / P1 / P2 均已合入）
- 实施计划：`docs/superpowers/plans/2026-08-30-p3-code-review.md`
- 环境：Apple Silicon / macOS 15，Python 3.12.7，Node v24.14.0，`.venv` 依赖齐全
- 测试基线：P0+P1+P2 = `476 passed / 2 skipped`；P3 全量 = **`538 passed / 2 skipped / 0 failed`**
- 本文所有「实测」均来自真服务（`uvicorn app.main:app --workers 1 --port 8001`）+ 真 SQLite +
  真浏览器（Playwright），非推断；无 API Key（Mock 模式）为既定演示路径

---

## 1. 任务清单

| # | Task | 状态 | Commit |
|---|---|---|---|
| 0 | 编写 P3 实施计划 | 完成 | `1265c4a` |
| 1 | **并入 1** Mock 提供方流式延迟 `mock_token_delay_ms`（默认 30，仅 stream、complete 不变） | 完成 | `0c2b3aa` |
| 2 | 静态解析领域层：Python ast + JS 轻量解析，零 IO（spec §8.4） | 完成 | `f070ec4` |
| 3 | `CodeAnalysis` 表 + Mock 讲解模板（static_report → Markdown）（spec §5 §8.4） | 完成 | `589e44e` |
| 4 | `CodeService`：source_hash 复用 / `review_my_code` 豁免 / 流式收集 / 失败降级（§8.4 §9 ADR-0005） | 完成 | `e1c4dbf` |
| 5 | `POST /code/analyze` 路由 + schema（spec §6.2 code 行） | 完成 | `b937f28` |
| 6 | **并入 2** 前端 Markdown 渲染：`html:false + DOMPurify` 双层消毒 + 代码高亮 + 8 条消毒测试 | 完成 | `95058f1` |
| 7 | 前端代码辅导页 `CodeReviewView`（静态报告 + AI 讲解 + 复用提示） | 完成 | `26ac359` |
| 8 | **并入 3** spec §8.1 歧义表述改写（只改文字，零代码改动） | 完成 | `87dfc2c` |
| — | 清理 P3 新增文件的 lint 告警（7 处，全部机械修复） | 完成 | `c72670b` |

**边界遵守**：未创建 `CodeSession` / `CodeRun` 表、未实现其 CRUD，并有反向用例
`test_code_models.py::test_code_session_and_code_run_tables_are_not_created` 锁住该边界；代码辅导页
的代码输入用组件本地状态，无草稿持久化（归 P4）。

---

## 2. 端点实测：`POST /code/analyze`

真服务（端口 8001，独立库 `backend/data/e2e-p3.db`），学生账号 `p3demo`。

### 2.1 Python 例（含裸 except 与多分支函数）

请求体（240 字符源码，`grade()` 带负数分支、`main()` 带裸 except）：

```json
{"language": "python", "source": "def grade(scores):\n    total = 0\n    for s in scores:\n ..."}
```

响应：`HTTP 200`，**总耗时 0.142s**（此时 Mock 延迟已开启，见 §4.1 —— 不受影响）。
`data.static_report` 完整结构：

```json
{
  "language": "python",
  "lines":       {"total": 15, "code": 13, "blank": 2, "comment": 0},
  "functions": [
    {"name": "grade", "line": 1,  "args": 1, "complexity": 3},
    {"name": "main",  "line": 9,  "args": 0, "complexity": 2}
  ],
  "classes": [],
  "complexity":  {"max": 3, "average": 2.5, "worst": "grade"},
  "issues": {
    "unused_variables": [],
    "bare_excepts":     [{"line": 12}]
  },
  "syntax_error": null
}
```

`data.ai_report`（Mock 模式，模板化生成）：`content` 为 Markdown（含「## 发现的问题」与
「1. **裸 except**（第 12 行）：会连 `KeyboardInterrupt` 一起吞掉…」），`provider="mock"`、
`token_usage.completion_tokens=66`（= len(content)//4，估算用量）、`usage_estimated=true`、
`degraded=false`。`data.analysis_id = 6e58fc50-7849-4837-888c-15d48c9f1f7f`。

### 2.2 JavaScript 例（空 catch + 未使用变量）

响应 `HTTP 200`，`static_report` 关键值：

```json
{
  "lines":      {"total": 20, "code": 15, "blank": 4, "comment": 1},
  "functions":  ["addItem(line 2, args 2)", "subtotal(line 7)", "constructor(line 10)", "pay(line 12)"],
  "classes":    [{"name": "Checkout", "line": 9, "methods": 2}],
  "complexity": {"max": 2, "average": 1.5, "worst": "subtotal"},
  "issues": {
    "unused_variables": [{"name": "unused_total", "line": 20}],
    "bare_excepts":     [{"line": 15}]
  }
}
```

JavaScript 的「裸 except」对应物为**空 catch 块**（`catch (e) {}`，第 15–16 行），落同一字段。

### 2.3 复用实测（source_hash 命中）

同一学生再次提交 §2.1 的相同源码：

```
analysis_id: 6e58fc50-7849-4837-888c-15d48c9f1f7f   ← 与首次完全相同
reused: True
```

### 2.4 其余实测

| 请求 | 结果 |
|---|---|
| 未带 Token | `HTTP 401 {"code":4010,"message":"未提供登录凭证"}` |
| `language=ruby` | `HTTP 422`（Pydantic 白名单校验） |
| `source` 超 20000 字 | `HTTP 422` |
| `def f(:`（语法错误） | `HTTP 200`，`static_report.syntax_error.line=1`，不 500 |
| 响应体 `request_id` 与响应头 `x-request-id` | 两者一致（`CurrentRidDep` 注入，H3） |
| `AuditLog(action=code_analyze)` | 每次请求落一行，`detail` 含 `language/reused/provider/degraded/usage_estimated` |

---

## 3. 测试统计

| 项 | 数量 |
|---|---|
| P0+P1+P2 基线 | 476 passed / 2 skipped |
| P3 净增（后端） | **+62** |
| 后端全量 | **538 passed / 2 skipped / 0 failed**（最终验证 77.7s） |
| 前端新增（vitest，此前前端无测试设施） | **+8**（`npx vitest run` 全过） |

新增用例分布：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_mock_provider.py` | +4 | Settings 默认 30、延迟开启时流耗时显著大于 0、`complete()` 不受延迟、中断路径不被延迟拖慢 |
| `test_code_analysis.py` | 23 | Python 行数/函数/类/复杂度规则/未使用变量豁免与闭包/裸 except/语法错误；JS 函数/类/复杂度/未使用变量/空 catch/行数；未知语言拒绝；**零 IO 源码级断言** |
| `test_code_models.py` | 6 | 建表；**code_sessions / code_runs 不得存在**；JSON 列 + UTCDateTime；唯一约束；跨 user 同 hash 放行；source_hash 语言/内容区分 |
| `test_code_review_template.py` | 8 | 模板逐条列问题、无问题时「未发现」、复杂度>10 给拆分建议、语法错误展示、语言措辞区分、Markdown 输出、问题串构造 |
| `test_code_service.py` | 9 | 复用（解析一次 + LLM 零调用）、跨 user 不复用、**strict 档下 system prompt 仍为豁免标记**、Mock 模式模板化（FakeLLM 零调用）、用量逐字取自流末 Usage（1111/2222/3333 固定值）、失败降级标记、`run_in_threadpool` 卸载、审计 |
| `test_code_api.py` | 12 | 鉴权 4010、Python/JS 全报告、复用语义、语言/长度/缺参 422、语法错误不 500、审计落库、落库行数 |
| `frontend/tests/markdown.spec.ts` | 8 | 见 §4.2 |

**skip 逐条说明**（2 条，与 P2 相同，均为 P1 语料型条件跳过，非本批次新增）：

| 用例 | 原因 |
|---|---|
| `test_retrieval_quality_realistic.py::test_diluted_query_degrades_visibly_rather_than_mis_hitting[小标题讲义]` | 该断言只适用于 B 型「无标题长段」语料，在 A 型语料上按设计跳过 |
| `test_retrieval_quality_realistic.py::test_lowering_the_threshold_lets_in_unrelated_without_rescuing_the_right_one[小标题讲义]` | 同上 |

---

## 4. 并入项验证

### 4.1 Mock 提供方流式延迟（并入 1）

同一答疑请求（`use_rag=false`），同一服务，同一源码，只切 `MOCK_TOKEN_DELAY_MS`：

| 配置 | token 增量数 | 流总耗时（curl time_total） |
|---|---|---|
| `MOCK_TOKEN_DELAY_MS=30`（**默认，未设置时**） | 165 | **5.211s** |
| `MOCK_TOKEN_DELAY_MS=0` | 165 | **0.111s** |

两次 token 数完全相同（165）—— 只改节奏、不改内容。改造前 Mock 约 0.1s 生成完毕（P2 报告
§4.3），现在默认配置下浏览器有约 5 秒的可视逐字输出与「停止」可截断窗口。

**不影响非流式 / 其他链路的证据**：

- `complete()` 不受延迟：`test_complete_is_not_delayed`（50ms/字延迟下 complete 须 <0.1s）；
- OpenAI 兼容链路零改动（`openai_compat.py` 本批未触碰，延迟实现在 `mock_provider.py` 内部）；
- `/code/analyze` 在 30ms 延迟开启的服务上实测 **0.142s** 返回 —— Mock 模式下该端点由
  static_report 模板化生成，根本不发起 LLM 调用（见 §5）。

### 4.2 前端 Markdown 渲染与 XSS 消毒（并入 2）

**选型与消毒策略（双层）**：`markdown-it`（`html: false` —— 源里的原生 HTML 一律转义为文本，
第一层就不给执行机会）+ `DOMPurify.sanitize`（渲染产物二次消毒兜底，即使上游配置被改错，
脚本类载荷也进不了 DOM）+ `highlight.js/lib/core` 按需注册 python / javascript / typescript /
json / bash 五种语言控制体积。`v-html` 全前端仅 `MarkdownView.vue` 一处，且只渲染
`renderMarkdown()` 的已消毒产物（组件注释写明该契约）；用户气泡保持纯文本。

**针对消毒策略的自动化测试**（`frontend/tests/markdown.spec.ts`，8 条，`npx vitest run`）：
script 转义、img onerror 不进活 HTML、`javascript:` 链接不成活链接、iframe 剥除、基本
Markdown 结构、python 围栏高亮 class、未知语言回退、空串边界。

**构建产物体积变化**（`npx vite build`）：

| 产物 | P2 基线 | P3 | 说明 |
|---|---|---|---|
| 业务包 `index-*.js` | 56.61 kB | 56.99 kB | 几乎不变 |
| `ChatView-*.js` | 8.97 kB | 9.19 kB | markdown 依赖被拆出 |
| `markdown-*.js`（新增独立 chunk） | — | 165.65 kB（gzip 67.66） | markdown-it + DOMPurify + hljs(core+5 语言)，单独分包利于缓存 |
| `CodeReviewView-*.js`（新增） | — | 5.77 kB | 路由懒加载独立 chunk |
| `element-plus-*.js` | 941.42 kB | 941.95 kB | 不变 |

**高亮是否生效 —— 两层实证**：

1. 打包产物内（真浏览器 `import('/assets/markdown-CL9g71cN.js')`）：hljs 实例
   `listLanguages()` 返回恰好注册的 5 种语言；对 python 源码 `highlight()` 输出
   `<span class="hljs-keyword">for</span>`、`hljs-built_in`、`hljs-number`、`hljs-string`
   等 token span；`highlight.js/styles/github.css` 主题已随页面加载（styleSheets 中存在
   `.hljs` 规则）。
2. 真页面渲染：`/#/code` 填入示例 → 开始解析，AI 讲解以结构化 HTML 呈现（快照可见
   `<h2>静态解析结果</h2>`、`<strong>裸 except</strong>`、`<code>except ValueError as e:</code>`，
   而非原始 `##` / `**` / 反引号）；`/#/chat` 发问后 assistant 气泡内容经 `.md` 容器渲染。
   全程浏览器控制台 0 错误。

> 如实说明：Mock 提供方的输出不含 ``` 围栏代码块（其话术为普通文本 + 缩进行），因此真页面
> 里「围栏 → 彩色高亮」的端到端画面要等真实 LLM 接入后才直观可见；围栏高亮逻辑本身由
> vitest 用例（同一 `renderMarkdown` 源码）与打包产物内的 hljs 实例直接驱动证明。真实 LLM
> 下未验证（无 Key）。

### 4.3 spec §8.1 歧义改写（并入 3）

| | 文本 |
|---|---|
| 改前 | 截断后若首轮被丢弃，改为保留最后一轮以保证上下文连贯。 |
| 改后 | 若累加后一轮都未纳入（即最近一轮本身已超出预算），则强制纳入最近一轮，保证上下文不断裂。 |

语义与 P2 已实现行为一致（`test_history_truncation.py::test_oversized_last_round_is_kept_as_a_fallback`
未改动、仍通过），**零代码改动**（commit `87dfc2c` 仅动 spec 一行）。

---

## 5. 降级路径

| 场景 | 行为 | 验证方式 |
|---|---|---|
| **Mock 模式（无 API Key）** | `ai_report` 由 `static_report` **模板化生成**（`render_mock_review` 纯函数），**不发起任何 LLM 调用**；`provider="mock"`、`usage_estimated=true`（按 `len(content)//4` 估算） | 服务层：FakeLLM 注入后断言 `llm.messages == []` 且 content 与模板逐字相等；实测 §2.1 端点 0.142s 返回 |
| **配置了真提供方** | 经 `LLMRuntime` 流式生成、服务端收集；`token_usage` 逐字取自流末 `Usage` 元素（估算则置 `usage_estimated=true`） | 服务层 `FixedUsageLLM`（流末给与长度无关的 1111/2222/3333）断言逐字透传 |
| **真提供方调用失败** | `LLMRuntime` 全链失败抛 `5021` → `CodeService` 捕获，**改用静态模板生成**，置 `degraded=true` + `fallback_reason="llm_fallback_to_mock"`（§9 封闭枚举之一），请求仍 `200` 返回完整 static_report | 服务层 FakeLLM(fail=True) 用例 |
| **源码语法错误** | 不 500；`syntax_error={line,message}` + 行数统计照常，模板讲解展示错误并提示先修复 | 领域层 + API 层用例 + 实测 §2.4 |

「Mock 模式」的判定与 P2 口径一致，取**配置层**：`provider != openai_compat` 或无 API Key
即 Mock 模式（无 Key → Mock 是 spec §9 既定路径，不算降级，故此时 `degraded=false`）。

---

## 6. 偏离清单

| # | 偏离了什么 | 为什么 | 影响 |
|---|---|---|---|
| 1 | spec §4.1 端口清单列有 `CodeParser` / `AstParser` 端口；本批**未建独立 port/adapter**，静态解析按本批次裁定直接落领域层 `domain/code/analysis.py` | 裁定明确「纯领域层实现、零 IO、可脱离数据库单测」；ast 是标准库，领域层引用不违反「领域禁 import 基础设施」，也没有第二种解析实现需要抽象 | 若将来需要第三种解析器（如 esprima），再提炼端口即可，届时纯重构 |
| 2 | 套件级置 0 用 conftest `os.environ.setdefault("MOCK_TOKEN_DELAY_MS", "0")`，而非逐个测试显式置 0 | 裁定原文「在受影响的测试中显式把该设置调为 0」；受影响用例遍布 4+ 个文件、20+ 个构造点，逐点改易漏。conftest 集中声明与既有 `DATABASE_URL` / `JWT_SECRET` 同一模式，等效且可审计 | Settings 默认值 30 未动；延迟用例经构造参数显式开延迟，自行验证延迟行为；无漏网 |
| 3 | 前端引入 `vitest` + `happy-dom`（dev 依赖）与 `npm test` 脚本 | 裁定要求「说明 XSS 消毒策略**与针对它的测试**」；spec §10 原口径是「不引入 E2E，保证 vue-tsc + build」——消毒是安全语义，纯类型检查证明不了，vitest 单测是最低成本的可重复证明 | 不影响构建产物；新增 dev 依赖 2 个；未引入 E2E |
| 4 | `/code/analyze` 响应在 spec 最小集之上增加 `reused` 字段 | 「命中复用」需要让用户可见（前端展示「与上次分析相同」），且复用语义需要可实测 | 纯增量；P6/P5 若复用该端点可忽略该字段 |
| 5 | 本批引入的新契约（`ai_report` 内部结构、`reused`、`source_hash` 算法、`mock_token_delay_ms`）**未回写 spec** | 本批指令只授权改写 §8.1 一句；契约回写建议留到收尾批次统一处理（详见 §7 遗留 1） | P5/P6 对接 /code/analyze 或 Mock 时需参照本报告 §5 / §8 |

其余：无。除上述外，实现严格遵循分层（routers → services → domain）、`CurrentRidDep`、
`UTCDateTime`、`create_all`、无 CORS、无远端操作。

---

## 7. 遗留问题

1. **spec 回写建议**（收尾批次处理，给出建议文本）：§6.2 code 行补「响应为最小集超集：
   增 `reused`」；§5 CodeAnalysis 行补 `source_hash = sha256(language+NUL+source)`、
   唯一约束 `(user_id, language, source_hash)`、复用按 user 隔离；§8.4 补「ai_report 为
   自描述 JSON：`{content(Markdown), provider, model, token_usage, usage_estimated,
   degraded, fallback_reason}`」与「Mock 模式不发起 LLM 调用」；§7.3 或 §2 补
   `mock_token_delay_ms`。
2. **真实 OpenAI 兼容提供方下的流式讲解未实测**（无 Key）—— /code/analyze 的真提供方路径
   已由 FakeLLM 服务层用例覆盖，但真实网络下的行为标注为**未验证**。
3. **JS 轻量解析的已知限制**（设计即如此，非缺陷）：不识别字符串/正则字面量（含这些词的
   字符串可能造成近似误差）；方法清单靠行首模式匹配；不做语法校验（`syntax_error` 恒 null）。
   教学演示够用，不可当 lint 工具宣传。
4. lint 存量（P2 报告 §6.10 的 34 处）照裁定排在 P6 之后单开批次；本批新增文件已清零。

---

## 8. 关键决策记录（指令未覆盖处）

1. **Mock 模式判定取配置层而非运行时快照**（§5 口径）。`LLMRuntime.snapshot()` 在首次调用前
   `provider=None`，不能作为判定源；且按配置判定可让 Mock 模式**完全不发起 LLM 调用** ——
   这同时满足了「§8.4 Mock 模板化」与「无 Key 演示时 /code/analyze 秒回（不叠加 30ms 延迟）」。
2. **复用按 user 隔离**。static_report 虽与用户无关，但 ai_report 可能因档位/模型不同而异，
   且 CodeAnalysis 本就带 user_id；跨账号共享会让 B 学生看到 A 学生的历史讲解。唯一约束
   `(user_id, language, source_hash)` 把「不重复算」落到库层。
3. **语法错误返回报告而非 4xx/500**。教学工具对写了一半的代码更要给反馈；行号 + 消息 +
   行数统计照常产出，前端用红色 alert 呈现。
4. **`/code/analyze` 不做 RAG、不做底线检测**。RAG：spec §7.2 明示该链路只服务答疑与习题
   辅导。底线检测：输入是代码而非自然语言请求，关键词规则（「作业/考试」同现）在代码注释里
   误判率高；但 `_floor.j2` 三条底线仍由 `code_review.j2` 无条件注入，装配器无跳过开关
   （§3.2 权衡 10）—— 免的是档位，不是底线。
5. **JSON 端点不挂中断 Event**。拍板决策 4 的 per-call cancel 针对流式链路；/code/analyze
   是有界同步语义的 JSON 调用（Mock 模式不调 LLM，真提供方由 LLMRuntime 限时失败），spec
   §6.2 也未定义 stop 端点。
6. **JS 复杂度/方法的轻量口径**（正则 + 花括号配对）与 Python（ast 精确）在文档字符串里
   分别说清，全部规则被用例锁定 —— 近似但确定性、可复现。
7. **未使用变量把函数参数纳入检查**（`self`/`cls`/`_` 前缀豁免）：参数从未读取对初学者同样
   是有效反馈；闭包内读取算使用、`x += 1` 算读、`global`/`nonlocal` 跳过，全部有正反用例。
8. **markdown 相关依赖单独分包**（`manualChunks.markdown`）：内容不常变，与视图代码分开
   缓存；否则 ChatView chunk 会从 9 kB 涨到 197 kB。
9. **消毒测试断言「不出现活 HTML」而非「字符串不出现」**：`html:false` 把危险载荷转义成
   可见文本（如 `&lt;img …&gt;`），字符串级断言会误报；活标签缺失才是安全不变量
   （变异 M8b 亦验证了该断言的灵敏度，见附 1）。

---

## 附 1：变异测试指引（全部实际跑过）

用「把代码改坏 → 跑测试 → 记录失败 → 还原」逐条验证，非推断。还原方式 `git checkout -- <file>`。

| # | 怎么改坏 | 会失败的测试（实测输出） |
|---|---|---|
| M1 | `mock_provider.py`：`await asyncio.sleep(self._token_delay)` → `await asyncio.sleep(0)`（拆掉流式延迟） | `test_mock_provider.py::test_stream_takes_noticeably_longer_when_delay_is_enabled`（1 failed, 18 passed） |
| M2 | `mock_provider.py`：给 `complete()` 加同样的逐字延迟 | `test_mock_provider.py::test_complete_is_not_delayed`（1 failed, 18 passed） |
| M3a | `analysis.py`：裸 except 判定加 `and False`（检测失效） | `test_code_analysis.py::test_python_bare_except_is_flagged_but_typed_is_not`（1 failed, 22 passed） |
| M3b | `analysis.py`：未使用变量判定改为 `if False` | `test_code_analysis.py::test_python_unused_variable_is_reported_with_line`、`::test_python_unused_reports_across_functions_in_line_order`、`::test_python_underscore_self_and_cls_are_exempt_from_unused`（3 failed, 20 passed） |
| M3c | `analysis.py`：`_PY_DECISIONS` 删掉 `ast.If`（复杂度不计 if） | `test_code_analysis.py::test_python_complexity_counts_documented_decision_nodes`、`::test_python_complexity_summary_names_the_worst_function`（2 failed, 21 passed） |
| M4 | `code_service.py`：`if existing is not None:` → `if False:`（关闭 hash 复用） | `test_code_service.py::test_same_hash_is_reused_without_recompute_or_llm`、`::test_audit_log_written_for_both_fresh_and_reused_analysis`、`test_code_api.py::test_analyze_reuses_history_for_same_user`（3 failed, 18 passed） |
| M5 | `code_service.py`：`intent="review_my_code"` → `intent="seek_answer"`（ADR-0005 回退） | `test_code_service.py::test_intent_is_always_review_my_code_even_in_strict_mode`（1 failed, 8 passed） |
| M6 | `code_service.py`：`except ApiError` 分支的模板降级 `return …` → `raise`（失败不降级） | `test_code_service.py::test_provider_failure_degrades_to_template_visibly`（1 failed, 8 passed） |
| M7 | `code_service.py`：`usage = chunk` → `usage = None`（用量改按文本现算） | `test_code_service.py::test_real_provider_streams_and_usage_is_verbatim_from_stream_tail`（1 failed, 8 passed） |
| M8a | `markdown.ts`：`html: false` → `true` **且** 去掉 `DOMPurify.sanitize`（双层全拆，危险态） | vitest 3 failed：`原生 <script> 被转义为文本而非执行`、`内联事件处理器不进入活 HTML`、`iframe / object 等危险标签不进入产物` |
| M8b | `markdown.ts`：仅 `html: false` → `true`（拆第一层，留 DOMPurify） | vitest 1 failed：`内联事件处理器不进入活 HTML（整段被转义为可见文本）` —— 第二层确实挡住了 script/onerror（script 与 onerror 用例均过），但转义姿态漂移被抓住，证明该断言有灵敏度 |

复现命令：

```bash
cd backend && . .venv/bin/activate
python -m pytest tests/test_mock_provider.py tests/test_code_analysis.py \
                 tests/test_code_service.py tests/test_code_api.py -q
cd ../frontend && npx vitest run
```

**已知的单测盲区（只能端到端验，拆掉后单测仍绿）**：真提供方（真实网络）下的流式讲解与
失败降级 —— 需要真实 Key，见 §7 遗留 2。

---

## 附 2：本次交付的文件

```
docs/superpowers/plans/2026-08-30-p3-code-review.md
docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md   （§8.1 一句改写）

backend/app/core/config.py                          （+ mock_token_delay_ms）
backend/app/domain/code/{__init__,analysis,review}.py
backend/app/infrastructure/adapters/llm/mock_provider.py  （+ 流式延迟）
backend/app/infrastructure/persistence/models.py    （+ CodeAnalysis）
backend/app/services/code_service.py
backend/app/routers/code.py  ·  backend/app/schemas/code.py
backend/app/main.py                                 （注册 code 路由）
backend/tests/test_{mock_provider,code_analysis,code_models,code_review_template,code_service,code_api}.py
backend/tests/conftest.py                           （套件级 MOCK_TOKEN_DELAY_MS=0）

frontend/package.json · package-lock.json           （+ markdown-it / dompurify / highlight.js；dev + @types/markdown-it / vitest / happy-dom）
frontend/vitest.config.ts  ·  vite.config.ts        （+ markdown 分包）
frontend/src/utils/markdown.ts  ·  src/components/MarkdownView.vue
frontend/src/api/code.ts  ·  src/types/code.ts
frontend/src/views/student/CodeReviewView.vue
frontend/src/views/student/ChatView.vue             （assistant 气泡改 Markdown 渲染）
frontend/src/router/index.ts  ·  src/components/AppShell.vue
frontend/src/main.ts                                （github.css 主题）
frontend/tests/markdown.spec.ts
```
