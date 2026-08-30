# P2 AI 答疑对话 + 防抄袭（含 P1 遗留前端）—— 完成报告

- 日期：2026-08-30
- 分支：`feat/p2-chat-anti-plagiarism`（自 `main` 切出，P0 / P1 均已合入）
- 实施计划：`docs/superpowers/plans/2026-08-30-p2-chat-anti-plagiarism.md`
- 环境：Apple Silicon / macOS 15，Python 3.12.7，Node v24.14.0，`.venv` 依赖齐全
- 测试基线：P0+P1 = `317 passed / 2 skipped`；P2 全量 = **`476 passed / 2 skipped / 0 failed`**
- 本文所有「实测」均来自真服务（`uvicorn app.main:app --workers 1`）+ 真 SQLite + 真 Chroma +
  真 MiniLM（`paraphrase-multilingual-MiniLM-L12-v2`），非 mock 推断

---

## 1. 任务清单

| # | Task | 状态 | Commit |
|---|---|---|---|
| 0 | 编写 P2 实施计划 | 完成 | `ed09192` |
| 1 | Conversation / Message 两表 + 防抄袭领域规则（意图 / 档位 / 底线 / 审计动作） | 完成 | `ed09192` |
| 2 | 四套提示词模板 + `PromptAssembler`，底线硬编码进模板不可覆盖 | 完成 | `b0683b9` |
| 3 | **M4** 端口契约测试补全：两个 Provider 跑同一组断言 | 完成 | `387ddd0` |
| 4 | **M10** LLM 降级链 `LLMRuntime`，全部失败返回 `5021` | 完成 | `3c96677` |
| 5 | 中断注册表：per-`(conversation_id, request_id)` 的 `asyncio.Event` | 完成 | `5ee4bc8` |
| 6 | 历史截断 4000 token / 10 轮，首轮被丢弃时兜底保留最后一轮 | 完成 | `f0a7501` |
| 7 | `ChatService`：SSE 编排 + RAG + 落库 + `finally` 审计 | 完成 | `89cbb55` |
| 8 | chat 路由：会话 CRUD + SSE + `/stop` | 完成 | `c49a1a2` |
| 9 | 防抄袭拦截率度量 `GET /admin/anti-plagiarism/stats` | 完成 | `dfcbb21` |
| 10 | 前端：答疑对话页 / 知识库检索页 / 知识库管理页 / `degraded` 提示条（8.2 裁定） | 完成 | `610c74d` |
| — | 缺陷：Mock 提供方未遵守防抄袭三档、未做抽取式生成（spec §7.3） | 完成 | `c4ee4d8` |
| — | 缺陷：抽取式生成把 Markdown 标题行当成片段正文 | 完成 | `207b3fa` |
| — | 缺陷：打字机渲染期间仍可发送 / 切换会话，会与消息重载打架 | 完成 | `f634ba0` |
| — | 清理 P2 新增文件的 lint 告警；中断用例改由生成进度驱动 | 完成 | `f9d6992` |
| — | 缺陷：答疑前未按 `revision` 重绑 LLM 降级链，改配置必须重启 | 完成 | `eaba51a` |
| — | 补两处变异盲区的守护（见附 2） | 完成 | `75fae39` |

> **未做**：M6（bcrypt 走线程池）已在 P0 Task 10 实现，本批次只复核 ——
> `backend/app/services/auth_service.py:28`（注册）与 `:41`（登录）均仍为
> `await run_in_threadpool(hash_password / verify_password, ...)`，**未被回退**。

---

## 2. 端点实测结果

全部在真服务上跑出（端口 8001，库为 `backend/data/e2e.db`，已 gitignore）。

### 2.1 SSE 裸报文抓包（`POST /chat/conversations/{id}/messages`）

```
→ POST /api/v1/chat/conversations/aef2e20b…/messages
  {"content":"讲讲排序算法","use_rag":true}
  headers: Authorization: Bearer …  x-request-id: rid-raw-1

← HTTP 200
  content-type: text/event-stream; charset=utf-8
  x-request-id: rid-raw-1          ← 与请求头一致（中间件原样采用）
  网络分片 157 块（逐块到达，非一次性返回）
```

前 6 帧与末帧（`⏎` 表示换行）：

```
event: citation ⏎ data: {"chunk_id": "7c002b71…:0", "document_id": "7c002b71…",
                         "doc_title": "sorting.md", "kb_id": "76026d67…",
                         "snippet": "# 排序算法讲义", "score": 0.8577669262886047, "number": 1}
event: token    ⏎ data: {"delta": "["}
event: token    ⏎ data: {"delta": "M"}
event: token    ⏎ data: {"delta": "o"}
event: token    ⏎ data: {"delta": "c"}
event: token    ⏎ data: {"delta": "k"}
   …（token × 165）
event: done     ⏎ data: {"message_id": "f026946c…",
                         "token_usage": {"prompt_tokens": 108, "completion_tokens": 41, "total_tokens": 149},
                         "usage_estimated": true, "model": "mock-1", "provider": "mock",
                         "rag_hit": true, "degraded": false, "fallback_reason": null}
```

**顺序符合 spec §6.1**：`citation* → token* → done`，`citation` 全部先于第一个 `token`。
`done` 载荷恰好是 spec 要求的 8 个字段（测试逐字段断言键集合，见
`tests/test_chat_api.py::test_sse_emits_citation_then_tokens_then_done`）。

### 2.2 `/stop` 中断后的流行为

请求体是 7999 字的长提问，使生成内容足够长，便于在流进行中打断：

```
→ POST /api/v1/chat/conversations/{cid}/messages   x-request-id: rid-raw-2
→ POST /api/v1/chat/conversations/{cid}/stop       {"request_id":"rid-raw-2"}

← {"code":0,"data":{"cancelled":true},"request_id":"39162299-…"}

流末帧： event: error ⏎ data: {"code": 4990, "message": "已中断生成"}
token 数：49（完整回答为 183 字符，即被截在约 1/4 处）

库中助手消息：
  truncated=True  len=50  provider=mock  anti_plagiarism_mode=guided
  内容前 40 字：[Mock 模式]先讲思路：把问题拆成「输入 → 输出」三段，逐段验证
```

要点：

- 中断后**不发 `done`，只发 `error`**（code `4990`），已生成内容照常落库并置 `truncated=true`；
- `AuditLog(action=chat)` 仍然写入（在 `finally` 中，见 §2.6）；
- `4990` 与服务端故障 `5021` 区分：前端据此只结束打字机、不弹红色错误提示；
- 浏览器里点「停止生成」按钮走的是同一条链路（`/stop → {"cancelled": true}`，库中
  `truncated=1`），实测见 §4.3。

### 2.3 三种防抄袭档位对同一求答案请求的输出对比

请求固定为 `讲讲排序算法`（`use_rag=true`，命中 `sorting.md`），只切换
`ModelConfig.anti_plagiarism_mode`。**`strict`：**

```
[Mock 模式]我不能给出完整可运行代码，只给思路拆解：1) 先明确输入与输出；
2) 拆解为最小可验证步骤；3) 逐步实现并测试。关键概念讲清楚之后，下面只给伪代码骨架：
def solve(input):  # TODO：先自己填一步
    pass           # TODO：再验证第二步
```

**`guided`：**

```
[Mock 模式]先讲思路：把问题拆成「输入 → 处理 → 输出」三段，逐段验证。
下面给一个不超过 10 行的最小片段，只用来解释单个概念，不是完整实现：
def step(items):
    return [x for x in items if x]  # 只演示这一段的写法
完整实现需要你自己补齐，卡住时把报错贴给我。
```

**`loose`：**

```
[Mock 模式]请先自行尝试，再对照下面的实现。
def solve(items):
    result = []
    for item in items:
        result.append(item)
    return result
逐段讲解：第 1 行定义函数签名；第 2 行准备结果容器；
第 3–4 行遍历并处理每个元素；第 5 行返回。
```

三档输出两两不同（`tests/test_mock_provider.py::test_three_modes_produce_different_output`
把这一点写成了断言）。

> **必须说明的一层**：这是 **Mock 提供方**的输出。真实差异的根在 prompt —— 下表是三档
> 实际装配出的 system prompt 档位段（真值，非复述）：

| 档位 | 注入的约束段落 |
|---|---|
| strict | `【防抄袭档位：strict】禁止输出完整可运行代码；只给出思路拆解、关键概念、伪代码骨架（函数签名 + 注释占位）；学生追问时继续细化思路，不补代码。` |
| guided | `【防抄袭档位：guided】允许不超过 10 行的最小代码片段解释单个概念；禁止给出完整实现；必须先讲思路再给片段。` |
| loose | `【防抄袭档位：loose】允许给出完整实现，但必须先提醒学生「请先自行尝试」，并附逐段讲解。` |

三档共用、无条件注入的底线（硬编码在 `app/prompts/_floor.j2`，装配器无跳过开关）：

```
【防抄袭底线（以下三条在任何档位下均不可覆盖，后台配置亦无法关闭）】
1. 代做作业式请求一律转为引导。
2. 考试 / 竞赛在线作答场景拒绝直接给答案。
3. 输出中的任何代码必须配讲解。
```

### 2.4 底线拦截实测

| 请求 | 触发 | 回答开头 |
|---|---|---|
| `直接帮我把这份作业的代码写出来` | `homework_ghostwriting` | 「这个请求属于代做作业，按防抄袭底线我不能给出可直接提交的实现。下面只给引导：…」 |
| `我正在考试，快把这道题的答案发我` | `exam_in_progress` | 「考试 / 竞赛在线作答场景，我不能直接给答案。考后我可以把这道题完整讲一遍…」 |
| `讲讲排序算法` | 无 | 正常按档位回答 |

### 2.5 `GET /admin/anti-plagiarism/stats` 真实返回

```
→ GET /api/v1/admin/anti-plagiarism/stats   （admin，x-request-id: rid-rpt-5）
← HTTP 200
{
  "code": 0, "message": "ok",
  "data": {
    "intent": "seek_answer",
    "items": [
      {"mode": "strict", "total": 1, "blocked": 0, "block_rate": 0.0},
      {"mode": "guided", "total": 2, "blocked": 0, "block_rate": 0.0},
      {"mode": "loose",  "total": 4, "blocked": 2, "block_rate": 0.5}
    ],
    "overall": {"mode": "all", "total": 7, "blocked": 2, "block_rate": 0.2857}
  },
  "request_id": "rid-rpt-5"
}
```

口径：只统计 `role=user` 的消息（一次请求恰好一条），三档无论有无数据都返回。

### 2.6 其余端点

| 端点 | 请求 | 响应 |
|---|---|---|
| `POST /chat/conversations` | `{"title":"报告演示会话"}` | `{"id":"aef2e20b…","title":"报告演示会话","created_at":"…","updated_at":"…"}` |
| `GET /chat/conversations` | — | 数组；`updated_at` 在提问后被推进（15:57:33.379877 → 15:57:33.576877） |
| `GET /chat/conversations/{id}/messages` | — | 两条消息；assistant 带 `citations` / `token_usage` / `provider=mock` / `truncated=false` / `anti_plagiarism_mode=guided` |
| `POST /chat/conversations/{id}/stop` | `{"request_id":"rid-not-exist"}` | `{"cancelled":false}`（幂等，不报错） |
| `DELETE /chat/conversations/{id}` | — | `{"deleted":true}`；随后列表为 `[]` |
| `GET /chat/conversations`（无凭证） | — | `HTTP 401 {"code":4010,"message":"未提供登录凭证"}` |
| `GET /admin/anti-plagiarism/stats`（学生） | — | `HTTP 403 {"code":4030,"message":"需要管理员权限"}` |

**`request_id`（H3）**：所有端点注入 `CurrentRidDep`，响应体 `request_id` 与响应头
`x-request-id` 一致且非空；SSE 端点同样回传调用方自带的 `x-request-id`。

**审计（spec §8.1）**：每次请求都在 `finally` 中落 `AuditLog(action=chat)`，实测
`detail` 形如：

```json
{"mode":"guided","blocked_by_policy":false,"floor_hit":null,"rag_hit":true,
 "citations":1,"chars":183,"error_code":null}
```

中断时 `error_code` 为 `4990`，提供方全失败时为 `5021`。

---

## 3. 测试统计

| 项 | 数量 |
|---|---|
| P0 + P1 基线 | 317 passed / 2 skipped |
| P2 净增 | **+159** |
| 全量 | **476 passed / 2 skipped / 0 failed** |

新增用例分布（13 个测试文件；`test_llm_contract` / `test_mock_provider` 是 P0 已有文件，
本批次重写 / 扩充）：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_chat_models.py` | 5 | 两表建表、字段默认值、`citations` / `token_usage` JSON 列、`UTCDateTime` |
| `test_chat_policy.py` | 15 | 意图豁免、档位解析、底线判定（含**不误伤**正常提问的反向用例）、审计动作常量 |
| `test_prompt_assembler.py` | 15 | 四套模板装配、**三档都含三条底线**、豁免免档位不免底线、引用上下文注入、意图豁免 |
| `test_history_truncation.py` | 16 | 4000 / 10 轮、兜底保留最后一轮、时间顺序、不改输入 |
| `test_cancellation.py` | 15 | per-request 隔离、同会话新请求置位、注销、**B2 并发回归**（跨会话） |
| `test_sse.py` | 5 | 帧格式、中文不转义、按前端解析方式反解、`citation` 可溯源字段 |
| `test_llm_runtime.py` | 13 | 降级链、降级记忆、空流不算失败、流中途失败不重试、rebind 重置 |
| `test_llm_resolution.py` | 8 | `build_llm` 各级可用性、revision 变更 rebind |
| `test_chat_service.py` | 25 | 事件顺序、`done` 八字段、**用量逐字取自流末 Usage**、落库、中断、审计、三档、历史截断、越权 |
| `test_chat_api.py` | 8 | SSE HTTP 层、中断、CRUD、鉴权、`request_id` |
| `test_anti_plagiarism_stats.py` | 7 | 拦截率口径、只数 user、除零、鉴权 |
| `test_llm_contract.py` | 26（P0 为 7） | **M4**：Mock 与 OpenAICompat 跑同一组断言 |
| `test_mock_provider.py` | 15（P0 为 8） | 三档话术、**底线话术**、抽取式生成、B2 并发回归 |

**skip 逐条说明**（2 条，均为 P1 遗留，非本批次新增）：

| 用例 | 原因 |
|---|---|
| `test_retrieval_quality_realistic.py::test_diluted_query_degrades_visibly_rather_than_mis_hitting[小标题讲义]` | 该断言只适用于 B 型「无标题长段」语料，在 A 型语料上按设计跳过 |
| `test_retrieval_quality_realistic.py::test_lowering_the_threshold_lets_in_unrelated_without_rescuing_the_right_one[小标题讲义]` | 同上 |

---

## 4. 前端实测

### 4.1 类型检查与构建

```
npx vue-tsc --noEmit   → 零错误
npx vite build         → ✓ built in 2.87s，1702 modules
```

构建产物（关键几项）：

| 产物 | 体积 | gzip |
|---|---|---|
| `index-*.js`（业务包） | 56.61 kB | 21.70 kB |
| `vue-*.js` | 111.39 kB | 43.43 kB |
| `element-plus-*.js` | 941.42 kB | 302.78 kB |
| `ChatView-*.js` | 8.97 kB | 4.20 kB |
| `KnowledgeAdminView-*.js` | 7.38 kB | 2.99 kB |
| `KnowledgeSearchView-*.js` | 3.71 kB | 1.92 kB |
| `AppShell-*.js` | 1.82 kB | 1.11 kB |
| `LoginView-*.js` | 1.47 kB | 0.83 kB |

**路由懒加载成立**：`LoginView` / `AppShell` / `ChatView` / `KnowledgeSearchView` /
`KnowledgeAdminView` 各自独立成 chunk，业务包 56.61 kB 与 P1 报告的「约 55 kB」同量级。

### 4.2 页面可交互（Playwright 驱动真浏览器，控制台错误数 0）

构建产物由后端托管（单端口 8001，同源，无 CORS）。

**答疑对话页 `/#/chat`**

```
登录后 URL: http://127.0.0.1:8001/#/chat
打字机长度采样: 26 → 30 → 33 → 37 → 41 → 44 → 48 → 51 → 55   ← 逐字增长，非一次性渲染
助手回答: [Mock 模式]依据知识库片段：…请先自行尝试，再对照下面的实现。…
消息元信息: mock  估算用量  150 tokens  知识库命中
引用条数: 1
```

**知识库检索页 `/#/knowledge`**

```
检索结果行数: 1
检索摘要: 知识库命中  相关度阈值 0.35  向量化器 sentence_transformers  命中 1 条
```

**知识库管理页 `/#/admin/knowledge`**

```
管理端 URL: http://127.0.0.1:8001/#/admin/knowledge
知识库行数: 2 → 建库后 3
上传后索引进度采样: 0 / 0 切片 → 0 / 3 切片 → 3 / 3 切片   ← 轮询 chunk_indexed / chunk_total
```

### 4.3 中断按钮（真浏览器）

```
点击停止 → POST /chat/conversations/{cid}/stop → 200 {"cancelled": true}
刷新页面（从库里重载）后：assistant 消息 truncated=1，content 长度 0
```

**关于「点停止是否真的截断内容」—— 如实说明两条实测结论：**

1. **不限速时**：Mock 提供方约 0.1 s 就生成完毕，浏览器在按钮出现的瞬间点到停止，
   `/stop` 返回 `cancelled: true`，但此时一个增量都还没吐出 → 库中
   `truncated=1`、内容长度 0。截断语义成立，只是窗口极窄。
2. **CDP 限速（下行 512 B/s）时**：服务端已生成完（uvicorn 会把响应体缓冲在内存里，
   不施加背压），浏览器侧看到的是「传输慢」而非「生成慢」，此时点停止后内容仍会
   继续补齐到完整长度。

结论：**在 Mock 提供方下，浏览器驱动的中断几乎总是「来不及截断」；截断语义的可靠
证据在 API 层（§2.2，49 / 183 增量，库中 `truncated=True`）**。真实 LLM 单次生成
数秒，窗口足够宽，按钮是真能用的。这是 Mock 的性质，不是实现的缺陷 —— 但我没有
真实 LLM Key，无法在真 LLM 下实测，标注为**未验证**。

### 4.4 设计基线遵守情况（`frontend/docs/ui-baseline.md`）

- 配色 / 字体 / 圆角 / 组件密度全部走 CSS 变量（`src/styles/theme.css`），本批次另补了
  基线 §4 的间距（`--space-1…8`）、圆角（`--radius-control/card/dialog`）、
  页面外边距（`--page-gutter`，<768px 降为 16px）
- 可点击元素 `cursor: pointer`；`:focus-visible` 用 `--color-ring`
- `prefers-reduced-motion` 下打字机改为直接显示（`useSse.ts::prefersReducedMotion`）
- **未使用任何 emoji 充当图标**，一律 Element Plus Icons 的 SVG
- 三点脉冲打字指示器（基线 §1「核心效果」）已实现，仅在网络流进行中显示
- 375 / 768 / 1024 / 1440 断点：<1024px 侧边导航收窄为图标条，主区不溢出

---

## 5. 降级路径验证

### 5.1 无 API Key（Mock 提供方）

```
GET /health → {"embedder":{"name":"sentence_transformers",
                          "model":"paraphrase-multilingual-MiniLM-L12-v2","ready":true}}
SSE done → {"provider":"mock","usage_estimated":true,"rag_hit":true,"degraded":false}
```

**流式输出照常**：单次抓包 157 个网络分片、167 个 SSE 帧，逐块到达。
`usage_estimated=true` 成立 —— Mock 无真实计数，按 `len(content)//4` 估算。

### 5.2 知识库零命中

```
请求: 今天食堂的红烧肉好吃吗
citation 事件数: 0
done: {"rag_hit": false, "degraded": true, "fallback_reason": "no_relevant_chunk",
       "provider":"mock","usage_estimated":true}
```

前端 `DegradedBanner` 据此显示：「知识库无相关内容，以下为通用回答 / 本次未命中任何
切片，请注意区分通用回答与课程内容」。

### 5.3 哨兵降级（`hashing_embed_no_semantics`）

沿用 P1 的 `RetrievalService`，聊天链路直接透传：服务层测试
`test_sentinel_embedding_reports_hashing_embed_no_semantics` 断言
`fallback_reason == "hashing_embed_no_semantics"` 且 `rag_hit=false`、
不注入任何引用。**本轮未切换真实 embedding 配置去触发它**（那会触发 P1 的全量重建
流程，代价大），故真实服务端到端为**未验证**，仅服务层验证。

### 5.4 LLM 提供方降级（M10 / spec §9）—— 真服务，不重启

```
改配置前：provider=openai_compat 不可达 → 不适合对照，先看基线
  done: {"provider":"mock","degraded":false,"fallback_reason":null}

把 ModelConfig 改成 provider=openai_compat / base_url=http://127.0.0.1:9/v1（必然连不上）
  / api_key=sk-unreachable-0001 / revision+1   ← 不重启服务

  done: {"provider":"mock","degraded":true,"fallback_reason":"llm_fallback_to_mock",
         "usage_estimated":true}
  token 数：183（流式输出照常）
```

即：**首选失败 → 降级到 Mock 并在 `done` 里显式标记**，且配置改完立即生效（§6 偏离 1
记录了这条的实现过程）。

---

## 6. 偏离清单

| # | 偏离了什么 | 为什么 | 影响 |
|---|---|---|---|
| 1 | `stream_reply()` 里按 `ModelConfig.revision` 调 `refresh_llm_config()`（spec §8.1 未写这一步） | 实现中途发现：`LLMRuntime` 只在启动时绑定，管理员改了 base_url / Key 后不重启就不生效，违反 spec §4.2 硬约束 4「配置热生效」。已补 `eaba51a` | 每次请求多一次 `ModelConfig` 查询 + revision 比较，可忽略；注入替身的服务不受影响（`_shared_llm` 标记 + `set_llm_runtime` 后刷新只记账不覆盖） |
| 2 | `done` 事件额外回传 `fallback_reason` 的优先级规则：检索降级优先于提供方降级 | 两者可能同时发生，但 `done` 只有一个 `fallback_reason` 位。检索降级是学生更可感知的那个 | 极端情况下只报一个原因；`degraded` 取二者或，不会漏报"有降级" |
| 3 | 中断错误码用 `4990`（非 HTTP 状态码） | 学生主动停止不是服务端故障，与 `5021` 混用会让前端弹红色错误提示 | 只出现在 SSE 载荷里，不进 `CODE_STATUS` 映射 |
| 4 | 拦截率只统计 `role=user` 的消息 | assistant 消息也带同样的 `anti_plagiarism_mode` / `blocked_by_policy`，两行都记会重复计数 | 口径变更需同步 P6 的统计页说明 |
| 5 | 底线"是否触发"用确定性关键词规则（双词组各命中一个）而非 LLM 分类 | CONTEXT.md 明确「拦截率是度量口径，不是检测能力」。若判定本身由模型给出，该指标不可复现也无法单测 | 会漏判与误判；已用反向用例锁住"不误伤"（`考试怎么复习` 不触发） |
| 6 | 会话标题在无显式标题时由首条提问生成（截取 20 字） | spec §5 只有 `title` 列，未定义取值。全部叫「新的对话」的会话列表在演示中不可用 | 纯增量；显式传 title 时不被覆盖 |
| 7 | 前端 SSE 用 `fetch` + `ReadableStream` 而非 `EventSource` | `EventSource` 带不了 `Authorization` 与 `x-request-id` 头，而中断键 `(conversation_id, request_id)` 要求前端必须自报 request_id | 需手写帧解析（`useSse.ts`），已按「前端怎么解析」写了反向测试 |
| 8 | `Message.token_usage` 落库时多存一个 `estimated` 布尔 | `done` 需要 `usage_estimated`，落库后要能复原该标志，否则消息列表页无法标注"估算用量" | 无 |
| 9 | Mock 提供方通过**解析 system prompt 里的档位标记**来遵守三档（而非另接参数） | Mock 是装配链路的下游，解析 prompt 让它模拟的正是真实模型看到的东西；档位一旦没写进 prompt，Mock 行为同步退化，缺陷不会在 Mock 下被掩盖 | 无 |
| 10 | `make lint` 仍非全绿 | 仓库在 P2 之前就有 48 处 ruff 告警（`app/core/security.py`、`models.py`、`auth_service.py` 等 P0/P1 文件）。本批次把**新增文件**清到 0，仅留 `chat_service.py` 一处 `UP017` 与 codebase 现有风格保持一致 | 未引入新的 lint 债务；存量告警建议单开一个批次清理 |

---

## 7. 遗留问题

### 7.1 召回的结构性弱点 —— 按裁定不做，此处只记录

P1 已知的「窄查询 × 宽切片」问题本批次再次被观测到：

```
GET /knowledge/search?query=怎么用 Python 写一个快排？
  → 对含三种排序算法的切片 0.2695 < 0.35 → 判零命中 → 可见降级
```

本批次**未调整任何阈值**（裁定 5.1：不动）。对话里出现零命中是**预期行为**，走
spec §7.2 步骤 7 的可见降级。

**我发现的一个可能更好的解法，按你的要求不动手，只写在这里**：做**查询改写 + 混合
检索**两步 —— (a) 查询侧用 LLM 或规则生成 2–3 个改写（去「怎么用 Python 写」这类
语言前缀，补「排序」「算法」等实体词）；(b) 检索侧把向量分与 BM25/字符 n-gram 分做
RRF 融合。理由是实测数据显示失败模式集中在「查询里的语言语法词把语义带偏」，而这
一类问题召回侧（top_k 放大 + 重排）比阈值侧更容易解。代价：需要引入一个 rerank
步骤或 BM25 实现，且要重跑 P1 的 A/B 两型质量回归才能确认没有回退。**建议作为 P6 之后
的独立优化项，不要混在功能批次里做。**

### 7.2 Mock 提供方下浏览器中断窗口过窄

见 §4.3。实现无缺陷，但演示时「点停止看不到截断」。若要让答辩现场可演示，有两条路：
(a) 给 Mock 加一个可配置的逐字延迟（仅演示环境）；(b) 等有真实 LLM Key 时演示。
**我没有自行动手**，等你决定。

### 7.3 `GET /admin/overview` 未实现

spec §6.2 把它与 `anti-plagiarism/stats` 列在同一行，但它在 §11 里归 P6（仪表盘）。
本批次只落地防抄袭统计端点，**管理端的统计页面本身也要等 P6**。

### 7.4 前端未引入 Markdown 渲染

答疑回答目前按纯文本 `white-space: pre-wrap` 渲染，代码块没有语法高亮。引入
`markdown-it` + `highlight.js` 会新增两个依赖并需要防 XSS 处理（AI 输出不可信）。
**未自行动手**，建议与 P5 的习题解析一并决策。

### 7.5 `hashing_embed_no_semantics` 的真实服务端到端未验证

见 §5.3。触发它需要切 embedding 配置并触发 P1 的全量重建，本轮没有做。

---

## 8. 关键决策记录

以下是你没有覆盖到、由我自行判断的地方：

1. **底线判定用双词组各命中一个**（§6 偏离 5）。单看「作业」或「考试」就拦截会污染
   拦截率这个度量口径 —— 它本来就不是检测能力，唯一价值是可复现地统计，被污染后
   一文不值。因此 `作业里这道排序题的思路是什么？` 不触发，`直接帮我把这份作业的
   代码写出来` 才触发。已用双向用例锁住。

2. **中断错误码 `4990`**（§6 偏离 3）。刻意不复用 `5021`：前者是学生主动行为，前端
   只结束打字机；后者是故障，前端要弹错误提示。

3. **`done` 的 `degraded` 取「检索降级 或 提供方降级」**，二者同时发生时
   `fallback_reason` 报检索的。理由已在偏离 2 说明。

4. **Mock 解析 prompt 里的档位标记**（§6 偏离 9）。这让 spec §7.3「Mock 也遵守三档」
   变成可验证的行为，而不是一句无法观测的声明；同时也让三档演示在没有 Key 的情况下
   也能看出来。

5. **历史截断的 token 估算沿用 `len//4`**，与 Mock 的估算用量同口径，不引入 tiktoken
   —— spec §8.2 已论证中文 token 密度与英文差 2–3 倍，用 tokenizer 会让预算在不同
   语言下不可比。

6. **spec §8.1「若首轮被丢弃则改为保留最后一轮」的歧义处理**。原文可有两种读法，我取
   「倒序累加若一条都留不下，则兜底保留最近一轮」，因为只有这种读法能让该句产生实际
   约束（先加后判的话结果永远非空，这句话就是废话）。已写成断言
   `test_oversized_last_round_is_kept_as_a_fallback`。**若你的原意不同，这里需要改。**

7. **同一会话发起新请求会置位此前的中断 Event**（spec §8.1 明要求）。副作用是同一会话
   内不存在两条并发流；`test_cancellation.py` 的 B2 并发回归因此改用跨会话场景，并在
   用例 docstring 里写明了原因。

8. **`set_llm_runtime()` 注入的运行时不被配置刷新覆盖**。原本不加这层保护时，
   `refresh_llm_config()` 会把测试替身悄悄换成库里的配置，测试会以一种很难查的方式
   失败。生产语义也成立：运维手动注入的实现不该被下一次配置刷新顶掉。

9. **中断用例由「固定 sleep 0.15s」改为「由生成进度驱动」**。原写法在 CI 上抖动过
   一次（实测出现过 1 次 NoResultFound，5 轮复跑未复现）。改后 `/stop` 一定发在
   "已吐出第 3 个增量"这个确定进度上，不再依赖墙钟。

10. **前端打字机与网络流解耦，但用 `busy = streaming || 队列未排空` 统一守卫**。
    网络常在 0.1 s 内结束而打字机还要渲染数秒，只判 `streaming` 会让学生在打字过程中
    发出下一条，新气泡随后被 `loadMessages()` 整段覆盖 —— 表现为「问题凭空消失」。

---

## 附 1：本次交付的文件

```
backend/app/domain/chat/{__init__,policy,history}.py
backend/app/infrastructure/{cancellation,llm_runtime,prompt_assembler,sse}.py
backend/app/infrastructure/registry.py          （追加 build_llm / LLMConfig / make_llm_factory）
backend/app/infrastructure/runtime.py           （追加 get_llm_runtime / refresh_llm_config / set_llm_runtime）
backend/app/infrastructure/persistence/models.py（追加 Conversation / Message）
backend/app/infrastructure/adapters/llm/mock_provider.py  （重写：遵守三档 + 抽取式生成）
backend/app/prompts/                            （rag_qa / code_review / exercise_hint / mistake_review
                                                  + _system / _user / _anti_plagiarism / _floor / _context）
backend/app/services/{chat_service,anti_plagiarism_stats}.py
backend/app/routers/{chat,admin_stats}.py
backend/app/schemas/chat.py
backend/app/main.py                             （注册 chat / admin_stats 路由）
backend/tests/                                  （11 个新测试文件 + fakes 扩充 + 2 个文件重写）

frontend/src/api/{chat,knowledge,params}.ts
frontend/src/types/{chat,knowledge}.ts
frontend/src/composables/useSse.ts
frontend/src/components/{AppShell,DegradedBanner,CitationList}.vue
frontend/src/views/student/{ChatView,KnowledgeSearchView}.vue
frontend/src/views/admin/KnowledgeAdminView.vue
frontend/src/router/index.ts                    （嵌套路由 + 角色守卫 + 懒加载）
frontend/src/styles/theme.css                   （补基线 §4 的间距/圆角/页面外边距/focus 态）
frontend/src/views/HomeView.vue                 （删除，被 AppShell + 三个功能页取代）

docs/superpowers/plans/2026-08-30-p2-chat-anti-plagiarism.md
docs/review/2026-08-30-p2-completion-report.md
```

---

## 附 2：复审指引（变异测试）

**下面每一条我都已实际跑过** —— 用脚本把代码改坏、跑测试、记录失败、再还原。
不是推断，是真实输出。

| # | 怎么改坏 | 会失败的测试 |
|---|---|---|
| A | `chat_service.py`：`resolve_mode(SEEK_ANSWER, …)` → `resolve_mode(REVIEW_MY_CODE if '```' in content else SEEK_ANSWER, …)`（ADR-0005：改回按内容推断） | `test_chat_service.py::test_chat_entry_is_always_seek_answer_even_with_a_code_block` |
| B | `cancellation.py`：`self._events[(conversation_id, request_id)]` → `self._events[(conversation_id,)]`（B2：退回会话级 cancel） | `test_cancellation.py::test_different_request_ids_get_different_events` |
| C | `history.py`：删掉 `kept = [rounds[-1]]` 兜底（改为 `kept = []`） | `test_history_truncation.py::test_oversized_last_round_is_kept_as_a_fallback` |
| D | `chat_service.py`：审计在 `error is not None` 时 `return`（移出 `finally` 的效力） | `test_chat_service.py::test_audit_is_written_even_when_the_stream_is_interrupted` |
| E | `retrieval_service.py`：零命中分支 `degraded=True` → `False` | `test_retrieval_service.py::test_sentinel_embedder_forces_rag_hit_false` |
| F | `chat_service.py`：`if self._shared_llm:` → `if False:`（去掉配置热刷新） | `test_chat_service.py::test_model_config_change_takes_effect_without_restart` |
| G | `_system.j2`：删掉 `{% include "_floor.j2" %}`（底线可被后台绕过） | `test_prompt_assembler.py::test_every_mode_keeps_all_three_floor_rules[strict/guided/loose]`、`…::test_exempt_intent_drops_mode_constraints_but_keeps_floor[review_my_code/judging]`、`…::test_floor_hit_strengthens_the_prompt`（共 6 条） |
| H | `chat_service.py`：`if usage is None: …` → 无条件按文本长度现算用量 | `test_chat_service.py::test_token_usage_is_taken_verbatim_from_the_stream_tail` |
| I | `policy.py`：`resolve_mode` 删掉 `if is_exempt(intent): return None`（豁免失效） | `test_chat_policy.py::test_exempt_intent_resolves_to_no_mode_constraint[review_my_code/judging]`、`test_prompt_assembler.py::test_exempt_intent_drops_mode_constraints_but_keeps_floor[review_my_code/judging]`（共 4 条） |
| J | `policy.py`：考试底线由双词组退化为单词匹配 | `test_chat_policy.py::test_mentioning_exam_without_being_in_one_does_not_hit_the_floor` |
| K | `policy.py`：考试底线判定完全失效 | `test_chat_policy.py::test_exam_in_progress_hits_the_floor` |
| L | `anti_plagiarism_stats.py`：统计范围从 `role == ROLE_USER` 放宽到 user + assistant | `test_anti_plagiarism_stats.py` 全部 6 条（含端点层 1 条） |

**两处曾经没有守护、现已补齐**（这是我跑变异的直接收获，值得一并复核）：

1. **H 原先无人看守**：Mock 的估算值恰好等于 `len(text)//4`，只断言
   `completion_tokens` 无法区分「取了 Usage」与「按文本现算」。已新增
   `FixedUsageLLM`（流末给 `1111/2222/3333` 这种与长度无关的值）+ 对应断言。
2. **J 原先无人看守**：只有「提到作业不触发」的反向用例，没有「提到考试不触发」的。
   已补 `test_mentioning_exam_without_being_in_one_does_not_hit_the_floor`。

**已知的单测盲区（只能端到端验，拆掉后单测仍绿）**：

- 拆掉 §5.4 的配置热刷新后，**在单测里**会被 F 抓到；但「改完配置不重启仍生效」这件事
  只有真服务能验（§5.4 给了实测对照）。
- `/stop` 的截断语义在 `httpx.ASGITransport` 下无法真实验证（该 transport 会把整个
  响应体缓冲成一块返回，客户端无法边收边发）。服务层与真服务层分别有
  `test_stop_interrupts_the_stream_and_persists_partial_content` 与 §2.2 的实测把守。

复现命令：

```bash
cd backend && . .venv/bin/activate
python -m pytest tests/test_chat_service.py tests/test_chat_policy.py \
                 tests/test_prompt_assembler.py tests/test_cancellation.py \
                 tests/test_history_truncation.py tests/test_retrieval_service.py \
                 tests/test_anti_plagiarism_stats.py -q
```
