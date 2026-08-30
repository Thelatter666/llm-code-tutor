# P1 RAG 课程知识库 —— 完成报告

- 日期：2026-08-30
- 分支：`feat/p1-rag-knowledge-base`（自 `main` 切出，P0 已合入）
- 实施计划：`docs/superpowers/plans/2026-08-30-p1-rag-knowledge-base.md`
- 环境：Apple Silicon / macOS，Python 3.12，`.venv`
- 新增依赖实测版本：`chromadb 1.5.9`、`pdfplumber 0.11.10`、`python-docx 1.2.0`
  （既有 `sentence-transformers 6.0.0` / `torch 2.13.0` / `fastapi 0.141.1`）
- **审阅轮次**：本报告为**第二版**。审阅报告见同目录 `2026-08-30-p1-review.md`
  （结论：不予合并，1 项阻塞级缺陷 B1 + 高优先级 H1–H3）。本版已完成 B1、
  ADR-0007 耦合说明、H2（spec 回写）、H3（真实粒度质量回归）、M2（logging），
  返工明细统一记在**第 10 节**。

---

## 1. 任务清单

| # | Task | 状态 | Commit |
|---|---|---|---|
| — | 编写 P1 实施计划（Goal / Architecture / Tech Stack / Global Constraints / File Structure / Task N / 验收清单） | 完成 | `4fba56d` |
| 1 | 依赖声明 + KnowledgeBase / Document / Chunk 三表 | 完成 | `4fba56d` |
| 2 | Embedder 端口 + HashingEmbed 哨兵 | 完成 | `8192160` |
| 3 | SentenceTransformer Embedder（单例懒加载 + 线程安全） | 完成 | `443098b` |
| 4 | OpenAI 兼容 Embedder + 三级回退 + EmbedderRuntime 预热就绪 | 完成 | `52979e1` |
| 5 | VectorStore 端口 + Chroma 适配器 + 进程级运行时 | 完成 | `c6ef8fe` |
| 6 | 领域层切分器（1200 / 150 字符） | 完成 | `fcec82a` |
| 7 | 领域层检索规则（阈值 / 相对截断 / 多样性截取） | 完成 | `c00c362` |
| 8 | 文档解析适配器 + 上传校验（10MB / 白名单） | 完成 | `6922261` |
| 9 | 并发控制（per-kb 锁 + 索引信号量 1） | 完成 | `162cce9` |
| 10 | KnowledgeBaseService（CRUD / 删除顺序 / 孤儿向量 GC） | 完成 | `17a279e` |
| 11 | IndexingService（BackgroundTasks + 阻塞卸载 + 进度可见） | 完成 | `fb1802b` |
| 12 | RetrievalService（§7.2 七步装配链路） | 完成 | `1a925de` |
| 13 | Embedding 切换 409 + 强制全量重建 | 完成 | `70f9a51` |
| 14 | 路由层（学生端 2 个 + 管理端 11 个端点） | 完成 | `c03839e` |
| 15 | 启动异步预热 / `/health` 就绪状态 / 一致性校验 / 4 篇 ADR（L1） | 完成 | `5fd4b8e` |
| 16 | 实测中发现并修复的 3 个缺陷 | 完成 | `9cfe14e`、`2c7b27a`、`e4c78d2` |

### 1.1 审阅返工（第二版新增）

| # | 审阅条目 | 状态 | Commit |
|---|---|---|---|
| 17 | **B1** 重建失败回滚配置（三道闸 + 3 条必测） | 完成 | `80a2bd6` |
| 18 | ADR-0007 补「按维度分区 ↔ 重建失败回 ready」成对耦合 | 完成 | `50464d2` |
| 19 | **H2** 3 处结构性偏离回写 spec（§4.3 / §5 / §6.2）+ §9 零命中说明 | 完成 | `e42d041` |
| 20 | **H3** 真实粒度（A/B 两型）语料的检索质量回归 | 完成 | `56de218` |
| 21 | **M2** `core/logging.py` 最小实现 | 完成 | `6ddd094` |
| 22 | **B1 续** 闸 1：新配置取不到可用向量化器时，在动到向量之前拒绝 | 完成 | `8cfd32b` |

> 第 16、22 行不在原计划的 15 个 Task 内 —— 都是端到端实测阶段暴露出来的真实
> 缺陷，按缺陷粒度单独 commit，未并入原 Task。

---

---

## 2. 端点实测结果

全部为**真服务**（`uvicorn app.main:app --workers 1 --port 8001`）+ 真 SQLite + 真
Chroma + 真 MiniLM 模型跑出来的结果。

> 说明：首版实测时端口 8000 被一个上一批次遗留的 dev server 占用（PID 38502，
> 运行的是 P0 代码），我改用 8001 做实测。该进程已由你清理，本版仍用 8001
> 以保持与第一版数据的可比性。

### 2.1 学生端

**`POST /api/v1/auth/login`（admin / Admin@12345）** → `code=0`，取得 access_token。

**`GET /api/v1/knowledge/bases`**
```
{"code":0,"data":[{"id":"d07002ce-…","name":"Python 编程讲义","course_code":"CS101",
  "embed_provider":"sentence_transformers",
  "embed_model":"paraphrase-multilingual-MiniLM-L12-v2","status":"ready"}],…}
```

**`GET /api/v1/knowledge/bases?course_code=CS102`** → `[("…", "CS102", "ready")]`（过滤生效）

**`GET /api/v1/knowledge/search`**（5 份文档 / 22 切片已索引，阈值 0.35）

| 查询 | rag_hit | degraded | fallback_reason | 命中 |
|---|---|---|---|---|
| 讲讲排序算法 | True | False | None | `[1] 0.7826 sorting.md`（×3） |
| 闭包是什么 | True | False | None | `[1] 0.5092 ch02.md`（×3） |
| 递归的基线条件怎么写 | True | False | None | `[1] 0.6573 plain.txt`、`[2][3] 0.5158 ch02.md` |
| 单元测试用什么断言 | True | False | None | `[1] 0.6832 testing.docx` |
| 今天食堂的红烧肉好吃吗 | **False** | **True** | `no_relevant_chunk` | 无 |

**未就绪期间的检索**（冷启动 T+2s）：
```
HTTP 503 {"code":5032,"message":"向量模型正在加载，请稍后重试","data":null,…}
```

**未鉴权**：→ `code=4010`。

### 2.2 管理端（11 个端点）

| 端点 | 实测结果 |
|---|---|
| `POST /admin/knowledge/bases` | `HTTP 200` → `{"id":"d07002ce-…","name":"Python 编程讲义","status":"ready"}` |
| `PATCH /admin/knowledge/bases/{id}` | `HTTP 200` → `name="Python 编程讲义（2026 修订版）" course_code="CS201"` |
| `DELETE /admin/knowledge/bases/{id}` | `HTTP 200 {"deleted":true}`；随后 `GET /knowledge/bases` 已不含该库 |
| `POST /admin/knowledge/bases/{id}/documents` | 5 份文档依次返回 `HTTP 200`，`status=pending 0/0`（BackgroundTasks 异步执行） |
| `GET /admin/knowledge/bases/{id}/documents` | `testing.docx ready 1/1` · `plain.txt ready 1/1` · `sorting.md ready 3/3` · `ch02.md ready 8/8` · `ch01.md ready 9/9` |
| `GET …/documents?status=failed` | 扫描版 PDF：`status=failed` · `error_msg=未提取到文本，可能是扫描版 PDF，请先做 OCR` |
| `GET /admin/knowledge/documents/{id}/chunks` | 3 片，首片 202 字，`embed_model=paraphrase-multilingual-MiniLM-L12-v2` |
| `POST /admin/knowledge/documents/{id}/reindex` | `HTTP 200` → `ready 3/3` |
| `DELETE /admin/knowledge/documents/{id}` | `HTTP 200 {"deleted":true}`；知识库本身保留（剩余 6→7 份文档） |
| `POST /admin/knowledge/bases/{id}/rebuild-vector` | `HTTP 200 {"kb_id":"…","status":"ready"}`，22 切片耗时 0.40s |
| `POST /admin/knowledge/bases/{id}/gc-orphan-vectors` | `HTTP 200 {"scanned":22,"orphans":0,"deleted":0}`；另一次手工制造孤儿实测 `{"scanned":723,"orphans":1,"deleted":1}` |
| `PUT /admin/model-config/embedding` | 见 §6.3 |
| `GET /admin/model-config/embedding-consistency` | `HTTP 200 []`（修复误报后） |

**角色拦截**：学生对上述 10 个管理端点 + `PUT /admin/model-config/embedding`
逐个请求，全部返回 `code=4030`。

**`request_id`（H3）**：响应体 `request_id` 与响应头 `x-request-id` 一致且非空。

### 2.3 上传校验

| 用例 | 实测 |
|---|---|
| `notes.exe` | `HTTP 415` `{"code":4150,"message":"不支持的文件类型：.exe，仅支持 .docx / .md / .pdf / .txt"}` |
| 11MB `huge.md` | `HTTP 413` `{"code":4130,"message":"文件超过 10MB 上限：10485761 字节"}` |
| 有文字层 `with_text.pdf` | `HTTP 200 pending` → 索引后 `ready 1/1` |
| 扫描版 `scanned.pdf` | `failed` + OCR 提示（不做 OCR，spec §3.3） |
| `testing.docx`（含表格） | `ready 1/1` |

---

## 3. 测试统计

| 项 | 数量 |
|---|---|
| P0 基线 | 64 passed |
| P1 首版新增 | 231 |
| 审阅返工新增 | 22 |
| 全量总数 | **317 passed，2 skipped，0 failed** |

新增用例分布（19 个测试文件）：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_kb_models.py` | 5 | 三表建表、进度字段、`vector_id`/`embed_model`、UTCDateTime 可空性 |
| `test_hashing_embed.py` | 8 | 端口符合性、`is_sentinel`、确定性、单位长度、**字面重合压过语义** |
| `test_sentence_transformer_embed.py` | 9 | 384 维、归一化、**进程级单例**、10 线程并发唯一实例、质量回归 |
| `test_embedder_runtime.py` | 10 | 三级回退、降级记忆、全链路失败 5032、snapshot |
| `test_embedder_resolution.py` | 8 | 各级可用性判定、**OpenAI 模型名不得带偏本地级** |
| `test_chroma_store.py` | 17 | 真实 Chroma：过滤、余弦换算、删除、**维度切换**、空集合清理 |
| `test_runtime.py` | 10 | 进程级单例、注入、revision 变更 rebind |
| `test_chunker.py` | 11 | 1200/150、标题分段、重叠、覆盖率 |
| `test_retrieval_rules.py` | 17 | 三档阈值、相对截断边界（含浮点容差）、多样性截取、串联顺序 |
| `test_document_parsers.py` | 14 | txt/md/docx/pdf，**手工构造有/无文字层 PDF**，表格纳入 |
| `test_upload_validation.py` | 14 | 白名单、大小写、10MB、413 优先于 415 |
| `test_concurrency.py` | 7 | 同 kb 互斥、跨 kb 并发、索引并发上限 1、锁清理 |
| `test_knowledge_service.py` | 17 | 删除顺序、**Chroma 失败仍继续删 DB + 审计告警**、GC |
| `test_indexing_service.py` | 15 | 索引落库、**进度分批提交**、失败置 failed、阻塞卸载到非主线程 |
| `test_retrieval_service.py` | 16 | 七步链路、4040/5032、哨兵短路、孤儿命中丢弃 |
| `test_retrieval_quality.py` | 6 | **真模型 + 真 Chroma 端到端质量回归**（小语料） |
| `test_retrieval_quality_realistic.py` | 10 | **H3：A/B 两型真实粒度语料的质量回归** |
| `test_embedding_switch.py` | 22 | 409、确认后重建、**维度切换回归**、一致性校验、**B1 三道闸** |
| `test_knowledge_api.py` | 27 | 全部端点 + 鉴权 + request_id + **B1 的 HTTP 层失败路径** |
| `test_health_ready.py` | 6 | `/health` 就绪状态、**预热不阻塞调用方** |
| `test_logging.py` | 6 | **M2**：幂等、级别解析、噪音库压制、格式 |

**第二版新增 22 条**（B1 失败路径 5 条 + 闸 1 共 4 条 + 真实粒度质量 10 条 +
logging 6 条 − 复用）。`test_retrieval_quality_realistic.py` 有 2 条 skip ——
那两条断言只适用于 B 型长切片语料，在 A 型语料上按设计跳过。

**测试有效性已验证**：B1 的三道闸逐个人为去掉后，对应测试**确实会失败**
（闸 1 → 1 条失败；闸 2+3 → 4 条失败），不是「写了就绿」的空断言。
验证脚本见交付说明，可复跑。

---

## 4. 检索质量实测

### 4.0 语料粒度（H3 的前置结论）

首版用的语料是 193/131/37 字，比 spec §8.2 的目标切片小 6–10 倍。补真实粒度后发现
一件首版没说清楚的事：**「1200 字切片」在有标题的讲义里根本不会出现**。

切分器是「先按 Markdown 标题切小节，再在节内按 1200 字打包」，所以切片长度取决于
文档结构，而不是 chunk_size 参数：

| 语料形态 | 实测切片长度 | 何时出现 |
|---|---|---|
| **A 型**：小标题密布的讲义 | 105–183 字（中位 132） | 现实中最常见 |
| **B 型**：无标题长段正文（prose / PDF 抽取） | 621–947 字（中位 903） | 教科书、扫描件抽取 |

这意味着 H3 担心的「语义稀释只会更严重」**在 B 型上成立**，而 A 型反而是被高估的。
两型都测，结论才站得住。

### 4.1 A 型语料（小节级切片，105–183 字）

| 查询 | A1 排序 | A2 闭包 | A3 面向对象 | A4 食堂 | 判定 |
|---|---|---|---|---|---|
| 讲讲排序算法 | **0.6561** | 0.3463 | 0.3480 | 0.1974 | ✓ |
| 怎么用 Python 写一个快排？ | 0.3237 | **0.4016** | 0.3147 | 0.0526 | ✗ 错误文档第一 |
| 冒泡排序的时间复杂度是多少 | **0.6690** | 0.3584 | 0.2164 | 0.1740 | ✓ |
| 闭包是什么 | 0.1377 | **0.4842** | 0.1162 | 0.1959 | ✓ |
| 装饰器怎么用 | 0.0954 | **0.5851** | 0.2712 | 0.1156 | ✓ |
| Python 多继承的方法解析顺序 | **0.5672** | 0.3765 | 0.5274 | −0.0463 | ✗ 错误文档第一 |
| pytest 的断言怎么写 | 0.2286 | 0.2732 | **0.2920** | 0.0687 | 零命中（0.2920 < 0.35） |
| 今天中午食堂的饭菜怎么样？ | 0.0888 | 0.0877 | −0.0261 | **0.7195** | ✓ |

5 / 8 命中正确，1 条零命中，2 条错命中。

### 4.2 B 型语料（长切片，621–947 字 —— 真正的稀释场景）

| 查询 | B1 算法 | B2 函数式 | B3 食堂 | 判定 |
|---|---|---|---|---|
| 讲讲排序算法 | **0.7757** | 0.2459 | 0.1684 | ✓ |
| 怎么用 Python 写一个快排？ | 0.3282 | **0.4885** | 0.0926 | ✗ 错误文档第一 |
| 冒泡排序的时间复杂度是多少 | **0.5231** | 0.1299 | 0.1709 | ✓ |
| 闭包是什么 | 0.1247 | **0.0800** | 0.1900 | 零命中（正确项 0.08，反被食堂 0.19 压过）|
| 装饰器怎么用 | 0.1182 | **0.1224** | 0.1411 | 零命中 |
| 今天中午食堂的饭菜怎么样？ | 0.0234 | 0.0060 | **0.7227** | ✓ |

对比 A 型同一查询：`冒泡排序` 从 0.6690 掉到 0.5231，`闭包` 从 0.4842 掉到 0.0800
—— **稀释确实更严重，H3 的推断成立**。无关项（食堂）则始终 ≤ 0.20，
「相关 vs 无关」的分离度依然充足。

### 4.3 阈值敏感性（裁定 5.1 的依据）

| 阈值 | A 型：首位落错误文档 | A 型：通过阈值的错误切片 | B 型：错误切片 | 被救回的正确项 |
|---|---|---|---|---|
| 0.35 | 2 / 8 | 7 个 | 2 个 | 0 |
| 0.30 | 2 / 8 | 11 个 | 4 个 | 1 |
| 0.25 | 2 / 8 | 20 个 | 5 个 | 2 |
| 0.20 | 2 / 8 | 24 个 | 8 个 | 2 |

**结论：降低阈值主要是在放噪声，不是在救正确项。** 从 0.35 降到 0.20，A 型通过
阈值的错误切片从 7 个涨到 24 个（3.4×），而「首位落在错误文档」的条数**始终是 2**，
一条都没改善 —— 因为那 2 条是查询措辞把语义带偏（"怎么用 Python 写" 指向了语法
文档），不是阈值能救的。

### 4.4 首版遗留的 8.1 问题：已裁定，采纳 (c)

首版把这三条列为待决，审阅方裁定 **采纳 (c)：保持 0.35 默认，管理端开放
`score_threshold` 配置**，并指出我对 (a)「降到 0.25」的评估需要修正。

**修正后的论证**（审阅方指出，我复核确认）：

首版 §4.1 第三行里，错误切片的分数已经高于正确切片：

| 查询 | 正确：排序算法 | 错误：Python 语法 |
|---|---|---|
| 怎么用 Python 写一个快排？ | 0.2695 | **0.2849** |

降到 0.25 后**两条都会通过，且错的排在第一位**。这比零命中更糟 —— 零命中会触发
可见降级，错命中则是把无关内容当引用喂给模型。所以 (a) 不是「多些弱相关噪声」
的程度问题，而是**会反转排序**。

B 型语料给出了更强的证据：`闭包是什么` 的正确项只有 0.0800，而无关的食堂通知有
0.1900。把阈值降到 0.15，进来的是**食堂通知**，正确项仍然进不来 ——
**阈值下调的收益为零，代价却是注入无关引用**。这条已写成断言
（`test_lowering_the_threshold_lets_in_unrelated_without_rescuing_the_right_one`）。

顺带也说明 spec §7.2 步骤 3 的相对截断兜底**解决不了这个问题**：0.2849 与 0.2695
分差仅 0.0154 < 0.15，两条都不会被相对截断掉，**绝对阈值是唯一防线**。

**默认阈值结论：保持 0.35。** 配置面随 P6 的 `PUT /admin/model-config` 落地
—— `ModelConfig.score_threshold` 列已存在，`resolve_score_threshold()` 也已按
「管理员配置 → 按模型默认值」的优先级读取，差的只是一个写入入口。

### 4.5 哨兵对照（ADR-0004 的实证）

| 句对 | 真模型 | HashingEmbed |
|---|---|---|
| A「如何用 Python 实现快速排序？」 vs B「怎样编写代码把一个序列按大小重新排列？」 | **0.5489** | 0.0000 |
| A vs C「如何用 Python 实现冒泡排序？」 | 0.8382 | **0.8235** |

真模型靠语义匹配（零字面重合也能匹配上），哨兵只认字面重合且把反义雷同句排到前面
—— 这正是 ADR-0004「哨兵结果不得注入 prompt」的实证依据。

### 4.6 已知局限（非阈值问题，见 8.1）

`怎么用 Python 写一个快排？` 在 A、B 两型语料上都是错误文档排第一（0.4016 vs
0.3237；0.4885 vs 0.3282），且**任何阈值都救不回来**。根因是查询里的「怎么用
Python 写」把语义带向了语言语法文档，属于查询与语料的匹配问题，不是阈值标定问题。
可行的改进是查询改写（HyDE / 去停用词），超出 P1 范围。

---

## 5. 索引性能实测

### 5.1 常规语料（5 份文档 / 22 切片）

上传 5 份文档全部返回 `pending 0/0`，7.50s 后全部落定为 `ready`，切片分布
9 / 8 / 3 / 1 / 1。上传请求本身不等待索引。

### 5.2 大文档（778 KB，700 切片）

- 上传返回耗时 **0.03s**（BackgroundTasks 立即返回）
- 进度采样（每 0.4s 轮询 `chunk_indexed/chunk_total`）：

```
0/700 → 64/700 → 96 → 160 → 192 → 256 → 288 → 320 → 352 → 416 → 448 → 480 → 512 → … → 700/700
```

- 完成于 **T+9.8s**，速率约 **71 切片/秒**
- **进度可见**：`chunk_indexed / chunk_total` 分批（32 片/批）提交，中间态清晰可轮询

### 5.3 阻塞卸载验证（ADR-0002）

索引 700 切片的同时高频打 `/health`（51 次采样）：

| | 中位数 | P95 | 最大 |
|---|---|---|---|
| 空闲时 `/health` | 2.6 ms | 302.3 ms | — |
| 索引进行中 `/health` | 7.2 ms | 108.3 ms | 243.0 ms |

事件循环在 11.3 秒的密集索引期间仍保持毫秒级响应 —— 解析与 embedding 推理确实
被卸载到了线程池，没有冻结后端。另有用例直接在 embedder 内部断言
`threading.current_thread().name != "MainThread"`。

### 5.4 全量重建

- 22 切片 KB：`rebuild-vector` 耗时 **0.40s**
- 723 切片 KB：耗时 **7.3s**（约 99 切片/秒）
- 切到 HashingEmbed 后重建 723 切片：0.42s（哈希编码远快于神经网络推理）

---

## 6. 降级路径验证

三种情形均用真进程跑通（`EmbedderRuntime` 完整走一遍降级链，非 mock）。

### 6.1 无 API Key 且有本地模型（默认演示路径）

```
配置 provider=None model=None api_key=无
各级可用性：L0=不可用, L1=SentenceTransformerEmbedder, L2=HashingEmbed
最终生效：sentence_transformers/paraphrase-multilingual-MiniLM-L12-v2 (sentinel=False, level=1)
```
✓ 落在第二级，检索可用。这也是线上实测服务的实际状态。

### 6.2 无 API Key 且无本地模型（HashingEmbed 哨兵）

把 `registry.local_embed_available` 换成 `False` 模拟 `make install-lite` 后未补装：

```
配置 provider=None model=None api_key=无
各级可用性：L0=不可用, L1=不可用, L2=HashingEmbed
最终生效：hashing/hashing-256 (sentinel=True, level=2)
```

配合真服务端到端：切到 hashing 后 `/health` 显示
`{"name":"hashing","model":"hashing-256","ready":true}`，检索返回

```
rag_hit=False  degraded=True  fallback_reason=hashing_embed_no_semantics  citations=0
```

✓ 索引照常写入（链路可跑通），但结果不注入 prompt，符合 ADR-0004。

额外验证**运行期降级**：配置 OpenAI 级 + key，但 base_url 指向必然连不上的地址 →
```
向量化器 openai_compat 调用失败，降级到下一级：…
最终生效：hashing/hashing-256 (sentinel=True, level=2)
```
（该场景下本地级也不可用，故落到哨兵；本地级可用时会落在 L1，见 6.4）

### 6.3 embedding 配置切换触发 409

真服务上已有 22 切片：

```
PUT /api/v1/admin/model-config/embedding  {"provider":"hashing","model":"hashing-256","confirm":false}
→ HTTP 409
  {"code":4090,"message":"切换 embedding 配置需要全量重建向量，请确认后重试",
   "data":{"need_rebuild":true,
           "knowledge_base_ids":["48cf2e9d-…"],
           "from":{"provider":null,"model":null},
           "to":{"provider":"hashing","model":"hashing-256"}}}

PUT … {"confirm":true}
→ HTTP 200 {"need_rebuild":true,"knowledge_base_ids":[...],"rebuilt":["48cf2e9d-…","d07002ce-…"]}
```

确认后自动触发全量重建，**所有含切片的知识库都被重建**（响应里是 2 个 KB）。
重建后 `/health` 变为 hashing，检索强制 `rag_hit=false`。

再切回 `sentence_transformers` → 重建 → 检索恢复 `rag_hit=True`、`0.7826`。
**维度 384 ↔ 256 双向切换都成功了**（这是修完缺陷 8.4 之后的结果）。

### 6.3.1 B1 修复后的真实失败路径（第二版新增）

真服务上用**真实失败**（切到一个不存在的模型名），不做任何注入：

```
1. 索引 a.md → ready 1/1
2. 检索「讲讲排序算法」→ rag_hit=True 分数 [0.7184]

3. PUT /admin/model-config/embedding
   {"provider":"sentence_transformers",
    "model":"sentence-transformers/this-model-does-not-exist-xyz","confirm":false}
   → HTTP 409 code=4090 need_rebuild=True

4. PUT … {"confirm":true}
   → HTTP 500 code=5000  耗时 0.4s
   message = 配置的 embedding 模型不可用（…），已回滚到切换前：None/None
   data.failed = ["a59ef573-…"]
   data.rolled_back_to = {"provider": null, "model": null}
   data.reason = embedding_unavailable_falls_back_to_sentinel

5. 回滚后的状态
   /health     = sentence_transformers/paraphrase-multilingual-MiniLM-L12-v2 ready=true
   consistency = []                      ← 配置与切片自洽
   检索        = rag_hit=True 分数 [0.7184]   ← 与切换前完全一致，向量毫发无损
   文档状态    = [('a.md','ready',None)]  ← 没有被误置 failed
```

**修复前的实测行为**（第一版，同一次操作）：

```
PUT … {"confirm":true} → HTTP 200 {"rebuilt":[...], "failed":[]}   ← 静默成功
/health     = hashing/hashing-256           ← 运行时降级到了哨兵
consistency = []                            ← 还查不出问题
检索        = rag_hit=False fallback=hashing_embed_no_semantics ← RAG 已死
```

对照即 B1 的价值：**HTTP 200 + rebuilt 成功 + consistency 干净**，而系统其实已经
把全部切片用无语义的哈希向量重写了一遍，好向量已被删除不可恢复。

### 6.4 三级回退链各级可用性实测

| 配置 | L0 OpenAI | L1 本地 | L2 Hashing | 最终 |
|---|---|---|---|---|
| 未配置任何 embedding | 不可用 | ✓ | ✓ | **L1 MiniLM** |
| openai_compat + key（端点不可达） | ✓→调用失败 | ✓ | ✓ | **L1 MiniLM** |
| openai_compat + key + 本地不可用 | ✓→调用失败 | 不可用 | ✓ | **L2 哨兵** |
| 显式 hashing | 不可用 | 不可用 | ✓ | **L2 哨兵** |

---

## 7. 偏离清单

| # | 偏离了什么 | 为什么 | 影响 |
|---|---|---|---|
| 7.1 | `KnowledgeBase` 增加 `status` 列（spec §5 未列） | §6.2 要求「KB 未就绪 → 5032」，§8.7 要求重建期间 KB 置 `reindexing`，两者都需要 KB 级状态；§5 是「关键字段」清单而非穷举 | 无负面。文档索引**不**改 KB 状态（spec §3.2 权衡 16：检索允许读中间态），只有全量重建才置 `reindexing` **✅ 已回写 spec §5（`e42d041`）** |
| 7.2 | **Chroma 集合按维度分区**（`course_chunks_d{维度}`），而非 ADR-0007 原文的「单集合」 | 实测：集合首次写入后维度固定，**删光记录也不重置**，导致「全量重建换维度」在单集合下不可能（详见 8.4）。这是 spec §8.7 的前提性缺陷 | ADR-0007 已追加「修订」小节记录。语义仍是「单集合 + 元数据过滤」；同一时刻通常只有一个活跃集合，维度迁移期间短暂并存，重建后旧集合由 GC 清掉 |
| 7.3 | 新增 `PUT /admin/model-config/embedding` 与 `GET /admin/model-config/embedding-consistency`，而 spec §6.2 的 `GET/PUT /admin/model-config` 归 P6 | §8.7 的 409 + 强制重建归 P1，没有入口就无法验证。只实现其中的 embedding 部分 | P6 需在本文件上补齐其余配置项（provider / 防抄袭档位 / top_k 等）。端点路径带 `/embedding` 后缀，与 P6 的 `PUT /admin/model-config` 不冲突 **✅ 已回写 spec §6.2（`e42d041`）** |
| 7.4 | 新增 `DocumentParser` 端口（spec §4.3 的端口清单未列） | 文档解析是知识库接入第一环，同样需要「真实实现与测试实现同签名」的接缝 | 纯增量，不影响既有端口 **✅ 已回写 spec §4.3，并补齐了同样遗漏的 `Embedder` / `VectorStore` 两个端口（`e42d041`）** |
| 7.5 | `ApiError` 增加 `data` 字段 | §8.7 的 409 要回传 `need_rebuild` 与待重建清单，塞进 message 字符串前端无法解析 | 纯增量；`data` 默认 `None`，P0 行为不变 |
| 7.6 | 「极短」判定（spec §8.2）**只对 PDF 生效** | 该判据的目的是识别无文字层的扫描版。对 txt/md/docx 而言文件正文就是全部内容，用长度阈值会误杀合法的小文档（如只有几十字的一页讲义） | 扫描版 PDF 判定不受影响；短 txt/md 现在可以正常索引 |
| 7.7 | 零命中时 `degraded=true` + `fallback_reason="no_relevant_chunk"` | spec §7.2 步骤 7 只强制 `rag_hit=false`，但 §9 又要求「降级必须可见」。让前端能用同一个 `degraded` 标志出提示条，比另设字段简单 | 与哨兵降级靠 `fallback_reason` 区分；若评审认为「正常未命中不算降级」，改为 `degraded=false` 只需一行 **✅ 审阅方认可，已回写 spec §9（`e42d041`）** |
| 7.10 | 判定「重建是否成功」增加了结果复核，不再只看有没有抛异常 | 逐份文档的索引失败会被 `IndexingService._run` 各自吞掉并置 failed，于是**全部失败也会走成功分支** —— 实测切到不存在的模型时，响应写着 `rebuilt` 成功，实际已把切片全删光 | 由 B1 的闸 3 覆盖；新增闸 1（新配置取不到可用向量化器时，在动到向量之前拒绝）。已回写 spec §8.7 步骤 5、6 |
| 7.8 | 相对截断加 `1e-9` 浮点容差 | `0.90 − 0.75` 实为 `0.15000000000000002`，不加容差会把「分差恰好 0.15」误判为超过阈值，与 spec 表述相反 | 无 |
| 7.9 | `KnowledgeBaseService.list_bases` 不叫 `list` | 方法名 `list` 遮蔽内置类型，会让同类注解在类体内解析失败（实际踩到） | 无 |

---

## 8. 遗留问题

### 8.1 ✅ 已裁定：默认阈值保持 0.35，管理端开放 `score_threshold` 配置（c）

**裁定结论（审阅方）**：采纳 (c)。我对 (a) 的评估已按审阅意见修正，修正后的论证
见 §4.3 / §4.4 —— 核心是 (a) 不是「多些弱相关噪声」的程度问题，而是**会反转排序**
（错误切片 0.2849 > 正确切片 0.2695），且 B 型语料上降低阈值根本救不回正确项。

**本批次做了什么**：用 A/B 两型真实粒度语料重跑质量回归（H3），据此确认 0.35
无需调整。配置写入面随 P6 的 `PUT /admin/model-config` 落地 ——
`ModelConfig.score_threshold` 列已存在，`resolve_score_threshold()` 已按
「管理员配置 → 按模型默认值」的优先级读取，只差一个写入入口。

**未做、留待确认的一点**：我没有在本批次给 `PUT /admin/model-config/embedding`
加 `score_threshold` 入参。理由是它是**检索**参数而非 embedding 参数，塞进
embedding 端点会让两者耦合；spec §6.2 已把 `PUT /admin/model-config` 划给 P6。
若你希望 P1 就把它开放出来，我可以补一个 `PUT /admin/model-config/retrieval`
（约 1 个 Task，含 spec 回写与测试）。

### 8.2 ✅ 已裁定：前端不做，与 P2 批次合并

**裁定结论（审阅方）**：不同意推迟到 P6。RAG 是三个增强特性中的两个，推到 P6
意味着直到最后一批才能第一次看见它工作；且 P2 本来就要做 citation 展示与 SSE UI，
分两批等于各搭一次骨架。

**安排**：P2 批次一并补齐 —— 知识库管理页（含 `chunk_indexed/chunk_total`
进度轮询）、检索演示页、`degraded` 提示条。**P1 内不动前端。**

### 8.3 审阅报告中标注 P1 但本批次仍未处理的项

- **M2** `backend/seeds/` 目录（P5）
- **M3** 路由 `response_model=ApiResponse[T]`（P6）
- **M4** 契约测试补全同组断言（P2）
- **M6** bcrypt 走线程池（P2）
- **L2** 功能点语义重叠口径（「学生端·RAG 课程知识库增强」与「功能增强·RAG 知识库检索」）
- ~~**L4** `core/logging.py` 缺失~~ **✅ 本批次已补（`6ddd094`）**
- **M1**（审阅新增）多 KB 重建无整体事务边界 —— 已由 B1 的回滚 + 响应区分
  `rebuilt` / `failed` 覆盖，见 8.6
- **H1**（审阅新增）重建在 PUT 请求内同步执行 —— 见 8.6，本批次不改

### 8.4 实测中已修复的 3 个缺陷（供你复核）

1. **`9cfe14e` Chroma 维度切换失败** —— spec §8.7 的「全量重建」在单集合下换不了
   维度。改为按维度分区集合（详见 7.2）。
2. **`2c7b27a` 一致性校验误报** —— `ModelConfig.embedding_model` 为 NULL（管理员从未
   配置）时，校验拿 NULL 去比切片上记的模型，把「一切正常」报成不一致。
3. **`e4c78d2` 本地级被 OpenAI 模型名带偏** —— OpenAI 级失效后降级到本地时，
   `cfg.model` 仍是 `text-embedding-3-small`，`SentenceTransformerEmbedder` 会去
   HuggingFace 拉 `sentence-transformers/text-embedding-3-small`，404 后本地级也失败，
   本该可用的本地语义检索直接掉到哨兵。

### 8.5 ✅ 已裁定：H1 重建保持同步执行，不改 BackgroundTasks

审阅方 H1 指出重建在 PUT 请求内同步执行，KB 多时请求会长时间挂起，客户端中途
断开同样会留下 B1 描述的不一致状态。审阅方同时说明「演示规模下是否值得，可由你
权衡」。

**本批次的判断：不改。** 理由：

1. B1 修复后这条路径的风险已大幅下降 —— 失败会回滚且返回 5000，不再是静默不一致；
   客户端断开在 ASGI 层通常表现为任务被取消，此时配置**尚未提交成功**即被回滚，
   比修复前安全得多。
2. 改成异步需要管理端轮询 KB 状态，而管理端页面按 8.2 裁定属于 P2。现在改等于
   先造一个没有 UI 可用的异步接口。
3. 实测规模：723 切片重建 7.3s，778KB 文档索引 6.3s。演示规模下同步等待可接受。

**触发重评的条件**：若单个知识库重建超过 60s（约 6000 切片量级），或 P2 管理端
页面落地后需要展示重建进度条 —— 届时改为 `reindexing` + 轮询，spec §8.7 已定义
好该状态与 5032 语义，改动是收敛的。

### 8.6 ✅ 已处理：M1 多 KB 重建的状态参差

响应现在区分 `rebuilt` 与 `failed` 两个清单。全部失败即整体回滚配置，因此不会
出现「前几个用新模型、后一个还是旧模型」的混合态 —— 回滚后所有 KB 的配置与
切片仍在旧模型上，检索自洽。

### 8.7 其他观察

- `session.expunge_all()` 之后改动已脱离会话的 ORM 对象不会被 flush（测试脚手架踩到，
  已在测试里加注释说明），产物代码不受影响。
- 后台索引任务用 `db.SessionFactory()` 新开会话；测试必须把它指向本用例的库，
  否则会静默写进 `data/app.db`（已在 conftest 加 autouse fixture 兜住，
  并补了 `session_factory` fixture 避免用例自己拿 `session.bind` 造会话 ——
  那会落到另一个库上）。
- 切分器「先按标题切小节，再在节内按 1200 字打包」，所以**有标题的讲义切不出
  1200 字切片**（实测 105–183 字）。这是 H3 的关键前提，见 §4.0。
- 端口 8000 上的旧 dev server 已由你清理，实测改用 8001。

---

## 9. 关键决策记录

以下是你没覆盖到、由我自行判断的地方：

1. **集合按维度分区**（7.2）—— 依据：实测 Chroma 维度不可变。维度作为分区键是
   自洽的：查询向量的维度就是索引时的模型维度，「用与索引时不同的模型去查」在
   结构上不可能发生，比运行时校验可靠。

2. **模型缓存到模块级字典而非实例字段** —— 适配器实例随 `ModelConfig.revision`
   变更被重建，若模型挂在实例上，改一次配置就要重新加载一次 13–20 秒。
   缓存后，10 个线程并发首次调用也只加载一次（已写成断言）。

3. **索引批处理 32 片/批**（实测 64 片/批约 0.8–1.2s）—— 取更小的值让进度条更细，
   代价是批次数翻倍。78% 的时间花在编码上，批大小对总耗时影响很小（实测 71 片/秒）。

4. **切片 id 直接作为 `vector_id`**（`{document_id}:{ordinal}`）—— 省掉一张映射表，
   重复索引不产生重复向量，孤儿比对也只需看 id 是否出现在 `Chunk` 表里。

5. **后台索引任务自带会话，不复用请求会话** —— 响应返回时请求会话已关。通过
   `session_factory` 参数可注入，默认取 `db.SessionFactory`。曾尝试从
   `AsyncSession.bind` 派生新会话，实测会落到另一个库上（该属性每次返回新包装），已放弃。

6. **重建失败后把 KB 状态放回 `ready`** —— 卡在 `reindexing` 会让检索永久不可用；
   具体失败原因由各文档的 `status=failed` + `error_msg` 承载，并写审计日志。

7. **一致性校验只告警不自动修复** —— 自动重建可能在无人值守时吃掉几分钟 CPU。

8. **孤儿向量命中一律丢弃** —— 有向量无 `Chunk` 行的命中若进引用，前端点击溯源
   会 404，宁可少一条引用。

9. **`upload_dir` / `chroma_persist_dir` / `index_concurrency` 进 `Settings`** ——
   相对路径以 `backend/` 为基准，测试可 monkeypatch 到临时目录，避免污染工作区。

10. **未就绪且知识库为空时检索返回零命中而非 5032** —— 没有知识库就没有要检索的
    对象，此时不需要向量化器。5032 只在「有 KB 但模型未就绪」时返回。

11. **切换 embedding 的三道闸**（B1，`80a2bd6` / `8cfd32b`）—— 见 §10.1。
12. **回滚是三步而非两步**（改库 + refresh + **重新预热**）—— 见 §10.1。
13. **真实粒度语料分 A/B 两型**（H3）—— 见 §4.0。
14. **H1 保持同步执行** —— 见 §8.5，含触发重评的条件。

---

## 10. 审阅返工记录（第二版新增）

本节记录针对 `docs/review/2026-08-30-p1-review.md` 的返工，供复审时逐条对照。

### 10.1 B1 · 重建失败导致配置与向量不一致（阻塞级）

**审阅方指出的问题**：`PUT /admin/model-config/embedding` 是「先改配置 + commit →
再 rebuild」，而 `RebuildService.rebuild()` 捕获异常后只把 KB 状态放回 `ready`、
不回滚配置。查询于是拿新模型的新维度向量去查空的 `course_chunks_d{新维度}`，
**静默零命中，没有任何错误码**，违反 spec §9「降级必须可见」。且该路径零测试覆盖。

**修复**：`ModelConfigService.switch_embedding_with_rebuild()` 把切换与重建绑成
「要么全成、要么回滚」的单元，设三道闸：

| 闸 | 检查什么 | 挡住什么 |
|---|---|---|
| 1 | 新配置能否取到**可用**向量化器（管理员显式选 hashing 除外） | 切到不存在的模型 → 一路降到哨兵，把好向量换成噪声还报成功 |
| 2 | 重建是否抛异常 | DB 写入失败等越出逐文档错误边界的异常 |
| 3 | 重建是否**真的换掉了切片**（残留旧模型 / 切片数为 0 都算失败） | 逐份文档索引失败会被 `IndexingService._run` 吞掉，全失败也走成功分支 |

**回滚是三步，缺一不可**：改库（`revision` 再 +1）→ `refresh_embedder_config`
→ **重新预热**。第三步是本批次补上的 —— `refresh_embedder_config` 会把 `_ready`
置回 `False`，不重新预热的话回滚后检索会一直返回 5032，等于只做了一半。

路由改为调用该方法，并在 `finally` 中再刷一次运行时兜底。

**三条必测（审阅方指定）+ 补充**：

| 测试 | 断言 | 去掉修复后 |
|---|---|---|
| `test_failed_rebuild_rolls_back_the_embedding_config` | provider/model 回滚、`revision` +2 | ✗ 失败 |
| `test_search_still_hits_after_a_rolled_back_switch` | `check_embedding_consistency()==[]` 且检索命中 | ✗ 失败 |
| `test_failed_switch_returns_500_and_rolls_back_the_config`（HTTP 层） | 500 + `code=5000` + 库内确实回滚 | ✗ 失败 |
| `test_a_rebuild_that_converted_nothing_counts_as_failed` | 全文档失败也判失败 | ✗ 失败 |
| `test_switching_to_an_unavailable_model_is_refused_before_rebuilding` | 闸 1：拒绝且**重建从未被调用** | ✗ 失败 |

**测试有效性已验证**：逐闸把修复改回原行为后跑测试，闸 1 → 1 条失败；
闸 2+3 → 4 条失败。不是「写了就绿」。

**真实失败路径的端到端验证**：见 §6.3.1。修复前后对照明确 —— 修复前是
`HTTP 200 + rebuilt 成功 + consistency 干净`，而切片已被哈希向量全量重写。

### 10.2 ADR-0007 补耦合说明（B1 附注）

补了一节「与『重建失败 → KB 回 ready』是成对设计」：

- 认可审阅方实测的「删集合后重建也能重置维度」确实更简单，**但仍选分区**，
  决定性理由是**失败安全**而非简洁性；
- 写明两者是成对出现的，前者是后者成立的前提；
- 写明**若将来改为删集合重建，决策 6 会立刻变成缺陷**，以及届时必须同步改什么
  （KB 状态改为 `failed` 或保持 `reindexing` + 人工介入入口）；
- 点出 `switch_embedding_with_rebuild` 的回滚分支同样建立在本 ADR 之上。

### 10.3 H2 · 3 处结构性偏离回写 spec

| 偏离 | 回写位置 |
|---|---|
| `KnowledgeBase.status` | spec §5 数据模型表（并说明 `embed_*` 记的是实际用于索引的模型，与 `ModelConfig` 的期望值分列） |
| `PUT /admin/model-config/embedding`、`GET .../embedding-consistency` | spec §6.2 端点清单（含 409 载荷与重建失败回滚语义） |
| `DocumentParser` 端口（另补齐同样遗漏的 `Embedder` / `VectorStore`） | spec §4.3 新增「端口清单」小节 |

另外按审阅建议补了三处：
- spec §9 加「零命中亦属降级」，与哨兵降级靠 `fallback_reason` 区分；
- spec §9 表格加「切换 embedding 后重建失败」一行；
- spec §8.7 加步骤 5（原子单元，不回滚会静默零命中）与步骤 6（不能只靠异常判定）。

### 10.4 H3 · 真实粒度语料的质量回归

新增 `tests/test_retrieval_quality_realistic.py`（10 条），A/B 两型语料各测一遍，
真模型 + 真 Chroma + 完整七步链路。关键发现见 §4.0：切分器按 Markdown 标题先切
小节，所以**有标题的讲义切不出 1200 字切片**（实测 105–183 字），1200 字只出现在
无标题长段上（实测 621–947 字）。两型都测，结论才站得住。

据此**确认默认阈值保持 0.35**（裁定 (c)），并把「(a) 降到 0.25 会反转排序」
这条理由写成了断言。

### 10.5 M2 · `core/logging.py`

新增最小实现：统一格式（时间 · 级别 · 模块名 · 消息）、按环境取级别、
`LOG_LEVEL` 环境变量优先、噪音库（uvicorn.access / sqlalchemy.engine / httpx /
chromadb）压到 WARNING、幂等、非法级别回落 INFO。6 条测试。
与审计日志的分工写进模块 docstring：前者面向运维排查，后者面向管理员追溯。

### 10.6 未采纳 / 未做

| 项 | 处理 |
|---|---|
| H1 重建改 BackgroundTasks | 不改，理由与触发重评条件见 §8.5 |
| 阈值配置写入面 | 随 P6 的 `PUT /admin/model-config` 落地；若希望 P1 就开放，见 §8.1 末段 |

---

## 附：本次交付的文件

```
backend/app/domain/knowledge/{__init__,status,errors,upload,chunker,retrieval}.py
backend/app/infrastructure/ports/{embedding,vectorstore,document}.py
backend/app/infrastructure/adapters/embedding/{hashing_embed,sentence_transformer,openai_compat_embed}.py
backend/app/infrastructure/adapters/vectorstore/chroma_store.py
backend/app/infrastructure/adapters/document/parsers.py
backend/app/infrastructure/{concurrency,embedder_runtime,runtime}.py
backend/app/infrastructure/registry.py                （追加 build_embedder / EmbeddingConfig）
backend/app/infrastructure/persistence/models.py      （追加 3 张表）
backend/app/services/{knowledge,document,indexing,retrieval,rebuild,model_config}_service.py
backend/app/routers/{knowledge,admin_knowledge,admin_model_config}.py
backend/app/schemas/knowledge.py
backend/app/core/{errors,config,logging}.py           （ApiError.data / 新增 3 个设置项 / M2 日志）
backend/app/main.py                                   （lifespan 异步预热 / /health 就绪状态 / 启用日志）
backend/pyproject.toml                                （3 个新依赖 + 批次标注）
backend/tests/                                        （21 个新测试文件 + fakes.py + conftest 改动）
docs/adr/0007–0010                                    （L1 补齐，0007 含实测修订 + 耦合说明）
docs/superpowers/plans/2026-08-30-p1-rag-knowledge-base.md
docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md
                                                      （H2：§4.3 端口清单 / §5 KB.status / §6.2 端点 / §8.7 步骤 5·6 / §9 降级说明）
```

---

## 附 2：复审指引

你提到会重点复核 B1 的三条新测试是否真的会失败。**我已经先自己验过一轮**：
逐闸把修复改回原行为后跑测试，闸 1 → 1 条失败，闸 2+3 → 4 条失败，全部符合预期。

要自己复现，改 `backend/app/services/model_config_service.py` 里的三处即可
（`switch_embedding_with_rebuild` 的当前行号见文件，改动都很短）：

**① 拆掉闸 1** —— 把

```python
        if await self._falls_back_to_sentinel(provider, model, effective):
```

改成 `if False:`（同时把紧跟其后的 `raise ApiError(5000, ...)` 整块删掉，否则会有
悬空的 `data={...}`）。期望失败：

```
tests/test_embedding_switch.py::test_switching_to_an_unavailable_model_is_refused_before_rebuilding
tests/test_knowledge_api.py::test_switching_to_an_unavailable_model_is_refused_at_http_level
```

**② 拆掉闸 2+3** —— 把

```python
        if failed:
            await self._roll_back(old, refresh, effective)
            raise ApiError(5000, ...)
```

改成 `if failed:  pass`（同样删掉 `raise` 块）。期望失败（4 条）：

```
tests/test_embedding_switch.py::test_failed_rebuild_rolls_back_the_embedding_config
tests/test_embedding_switch.py::test_search_still_hits_after_a_rolled_back_switch
tests/test_embedding_switch.py::test_a_rebuild_that_converted_nothing_counts_as_failed
tests/test_knowledge_api.py::test_failed_switch_returns_500_and_rolls_back_the_config
```

**③ 只拆回滚的第三步** —— 把 `_roll_back()` 末尾的 `await runtime.warmup()` 删掉。
期望：**单测全绿**。这是已知的单测盲区：不重新预热在单测里看不出来，但真服务上
回滚后 `/health` 会停在 `ready=false`、检索一直返回 5032。它只能端到端验，
证据见 §6.3.1 的第 5 步（`/health` 回到 `ready=true`、检索分数 0.7184 与切换前一致）。

跑测试：

```bash
cd backend && . .venv/bin/activate
python -m pytest tests/test_embedding_switch.py tests/test_knowledge_api.py -q
```

端到端（需先起 `uvicorn app.main:app --workers 1 --port 8001`）：建库 → 上传一份
文档 → `PUT /admin/model-config/embedding` 切到一个不存在的模型名并 `confirm=true`
→ 期望 HTTP 500 / `code=5000` / `reason=embedding_unavailable_falls_back_to_sentinel`
→ 再查 `/health`、`embedding-consistency`、检索，应与 §6.3.1 的输出一致。
