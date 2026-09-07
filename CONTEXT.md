# 术语表（Ubiquitous Language）

本文件是项目的正式术语表，为**活文档**，贯穿 brainstorming → grilling → spec → plan → 实现 全流程。
所有设计文档、计划文档、代码标识符、接口字段必须使用本表中的正式术语，不得混用或自造。

> 状态：初稿（随 grilling 阶段精炼定稿）

---

## 领域实体

| 术语 | 英文 / 代码标识符 | 定义 | 消歧说明 |
|---|---|---|---|
| 用户 | User | 系统的登录主体，分为学生与管理员两种角色 | 不使用「账户」「成员」 |
| 学生 | Student | 角色为 `student` 的用户，使用学习功能 | — |
| 管理员 | Admin | 角色为 `admin` 的用户，使用管理后台 | 不使用「教师」；教学场景中的教师在本系统中即管理员 |
| 会话 | Conversation | 一次完整的答疑对话容器，包含多条消息 | 与「对话（Chat）」区分：Chat 指功能，Conversation 指数据实体 |
| 消息 | Message | 会话中的单条发言，角色为 user / assistant / system | — |
| 知识库 | KnowledgeBase | 一组同源课程文档的集合，是检索的作用域单位 | 不使用「空间」「库」等简称 |
| 文档 | Document | 知识库中的一份原始文件（PDF/MD/TXT/DOCX） | 与「文件」区分：Document 是业务实体，文件是存储层概念 |
| 切片 | Chunk | 文档经切分后产生的最小检索单位 | 不使用「分块」「片段」；Chunk 特指带 vector_id 的已索引单元 |
| 引用 | Citation | 模型回答中所依据的切片来源，`Message.citations` 中持久化 | 与「参考」区分；Citation 是可点击溯源的结构化数据 |
| 代码会话 | CodeSession | 在线编辑器中的一份代码草稿 | 不使用「代码片段」「草稿」 |
| 代码分析 | CodeAnalysis | 一次代码解析的完整结果，含静态报告与 AI 报告 | — |
| 静态报告 | StaticReport | 不依赖大模型、由解析器产出的客观结构化结果 | — |
| AI 报告 | AIReport | 大模型基于静态报告与源码生成的讲解与改进建议 | 可为 null（Mock 或降级时） |
| 代码运行 | CodeRun | 一次代码执行的完整记录，含状态、输出与耗时 | 与「调试」区分：本系统只提供运行与输出观测，不提供断点调试 |
| 习题 | Exercise | 题库中的一道题目，含题干、答案与知识点标签 | 不使用「题目」「试题」 |
| 提交 | Submission | 学生对某道习题的一次作答记录 | 与「答案」区分：答案是一个字段，提交是实体 |
| 错题条目 | MistakeBookEntry | 学生在某道习题上的错误累积状态，按 (user, exercise) 唯一 | 不使用「错题」作为实体名；「错题本」是功能名 |
| 错题本 | MistakeBook | 错题条目的集合视图，是功能名而非实体 | — |
| 掌握度 | Mastery | 错题条目的状态：连续答对 2 次即视为已掌握（mastered） | 与「得分」「正确率」区分 |
| 薄弱知识点 | WeakKnowledgePoint | 按知识点标签聚合错题后得出的薄弱项，实时聚合，无独立表 | — |
| 模型配置 | ModelConfig | 全局单例的大模型参数配置，带 revision 版本号 | 与「模型参数」「配置」区分 |
| 审计日志 | AuditLog | 用户关键行为的结构化留痕 | 与「运行日志」区分：运行日志面向运维，不落库 |

---

## 端口与适配器

| 术语 | 英文 / 代码标识符 | 定义 |
|---|---|---|
| 端口 | Port | 基础设施能力的抽象接口，以 `Protocol` 定义 |
| 适配器 | Adapter | 端口的具体实现 |
| 模型提供方 | Provider | 大模型服务的具体实现，如 OpenAICompat、Mock |
| 向量化器 | Embedder | 将文本转为向量的端口 |
| 向量库 | VectorStore | 存储与检索向量的端口 |
| 代码执行器 | CodeExecutor | 在受限环境中执行代码的端口 |
| 代码解析器 | CodeParser | 对源码做静态结构分析的端口 |
| 提供方注册表 | ProviderRegistry | 依据 ModelConfig 解析并缓存具体适配器的组件 |
| 提示词装配器 | PromptAssembler | 组合防抄袭策略、RAG 上下文与模板，产出最终 prompt 的组件 |
| Mock 提供方 | MockProvider | 无需 API Key 即可跑通全链路的提供方实现 |

---

## 请求意图

| 术语 | 英文 / 代码标识符 | 定义 | 消歧说明 |
|---|---|---|---|
| 请求意图 | RequestIntent | 一次 AI 请求的语义类别，决定防抄袭档位是否生效 | 与「题型」「端点」区分：意图是语义概念，同一端点可承载多种意图 |
| 求答案 | SeekAnswer | 学生索取可直接提交的实现或答案 | `intent=seek_answer`，**受防抄袭档位约束** |
| 评改已写代码 | ReviewMyCode | 学生对已写出的代码请求诊断与改进 | `intent=review_my_code`，**豁免防抄袭档位约束** |
| 判分 | Judging | 系统内部对作答的评分行为 | 完全豁免；不向学生输出实现 |
| 豁免 | Exemption | 某类请求不受防抄袭档位约束的显式声明 | 与「绕过」区分：豁免是设计意图，绕过是缺陷 |

## 行为与策略

| 术语 | 英文 / 代码标识符 | 定义 | 消歧说明 |
|---|---|---|---|
| 防抄袭档位 | AntiPlagiarismMode | `strict` / `guided` / `loose` 三档，由管理员在后台配置 | 与「防抄袭底线」区分 |
| 防抄袭底线 | AntiPlagiarismFloor | 三档均不可覆盖的硬约束，硬编码进模板 | 后台配置无法绕过 |
| 检索增强 | RAG | 检索知识库切片注入 prompt 以增强回答的过程 | — |
| 检索命中 | RAG Hit | 存在相关度高于阈值的切片 | `rag_hit=false` 时明确告知用户知识库无相关内容 |
| 相关度阈值 | ScoreThreshold | 切片被采纳的最低相关度，默认 0.35 | — |
| 多样性截取 | DiversityTruncation | 单文档最多采纳 3 个切片，防止长文档霸占上下文 | — |
| 降级 | Degradation | 外部能力不可用时切换到备用实现 | 所有降级必须在响应中带 `degraded=true` 与 `fallback_reason` |
| 抽取式生成 | ExtractiveGeneration | Mock 提供方基于命中切片拼装回答的策略 | — |
| 哨兵级降级 | SentinelDegradation | 该降级实现**仅保证调用链路可跑通，其产出不参与业务逻辑** | 特指 HashingEmbed：向量照常写入，但检索结果一律不注入 prompt |
| 相对截断 | RelativeTruncation | 按「与最佳命中分差 > 0.15」丢弃命中，而非依赖绝对阈值 | 与「相关度阈值」区分：前者跨 embedding 模型可比，后者绑定模型 |
| 孤儿向量 | OrphanVector | Chroma 中已无对应 `Chunk` 行、但仍占据存储的向量 | 由 `gc-orphan-vectors` 端点清理 |
| 拦截率 | BlockRate | 触发防抄袭底线的请求数 / 总请求数，按档位分别统计 | 是度量口径，不是检测能力 |
| 底线拦截 | BlockedByPolicy | 单次请求是否触发防抄袭底线，落 `Message.blocked_by_policy` | 与「档位约束」区分：档位约束塑形输出，底线拦截直接拒绝 |
| 阻塞卸载 | BlockingOffload | 将同步阻塞调用经 `run_in_threadpool` 移出事件循环的做法 | 与「异步化」区分：底层仍是同步代码，只是不在事件循环上执行 |
| 知识库锁 | KnowledgeBaseLock | per-`kb_id` 的 `asyncio.Lock`，保护索引 / 删除 / 重建 / GC | 检索**不持锁**，允许读到中间态 |
| 课程代码 | CourseCode | `KnowledgeBase` 上的检索作用域标识，可空表示不限课程 | 与「课程」区分：本系统无课程实体与选课关系 |
| API Key 掩码 | ApiKeyMask | 读取接口返回的密钥脱敏形式 `sk-****abcd` | 与「加密存储」区分：掩码面向展示，Fernet 面向落盘 |
| 执行队列上限 | ExecutionQuota | 代码执行的全局并发上限（2）与信号量等待超时（10s）；知识库索引并发上限为 1 | 超限返回 `429`，不无限排队 |
| 估算用量 | EstimatedUsage | Mock 提供方无真实 token 计数时按 `len(content)//4` 估算，并置 `usage_estimated=true` | 与「真实用量」区分：估算值仅供展示，不用于计费或限流判断 |
| 随机补足 | RandomFill | 定向推荐数量不足 `limit` 时，按难度递增补足同课程随机题，响应标注 `filled_by=random` | 与「个性化推荐」区分：补足题不来自薄弱知识点画像 |
| 文本增量 | TextDelta | LLM 流式输出的文本片段，与 `Usage`（用量）并列为流的两种消息类型 | 与「token」区分：增量是传输单位，token 是计量单位 |
| 用量 | Usage | 单次 LLM 调用的 token 统计（prompt / completion / total），流的最后一个 chunk | 与「估算用量」区分：Usage 由提供方给出，估算用量由系统推算 |

---

## 待定 / 需消歧

| 术语 | 状态 |
|---|---|
| 课程（Course） | **已定稿** —— 引入 `KnowledgeBase.course_code`（可空）作为检索作用域维度；**选课关系仍属边界外**，不做排课体系。 |

---

## 修订记录

- 2026-08-30 · Grilling 第 1 轮：新增「请求意图」「求答案」「评改已写代码」「判分」「豁免」「哨兵级降级」「相对截断」「孤儿向量」「拦截率」「底线拦截」；同步 spec §3.2 / §3.3 / §5 / §6.2 / §7.1 / §7.3 / §7.4 / §8.2 / §8.3 / §8.6 / §8.7 / §9。
- 2026-08-30 · Grilling 第 2 轮：新增「阻塞卸载」「知识库锁」「API Key 掩码」「课程代码」；「课程」由待决转为定稿；同步 spec §3.2 / §3.3 / §5 / §6.2 / §7.1 / §8.1 / §8.2 / §8.3 / §8.5 / §8.6 / §8.8 / §9 / §11。
- 2026-08-30 · Grilling 第 3 轮：新增「估算用量」「随机补足」；同步 spec §2 / §3.2 / §3.3 / §6.1 / §8.2 / §8.5 / §10 / §11。
- 2026-08-30 · Grilling 第 4 轮：明确「掌握度可回滚」「习题辅导复用 RAG 链路」「硬删除保留审计」；同步 spec §6.2 / §7.2 / §8.5 / §8.9 / §9 / §11。Grilling 结束，结论：有条件通过。
- 2026-09-01 · 清理批次：M-5 落地——CodeSession 用户可见文案「未命名草稿」→「未命名会话」、「草稿不存在」→「代码会话不存在」（禁词纪律只收紧不放宽，实体定义不变；Exercise.status 的「草稿」发布态不属 CodeSession 禁词范围）；M-4 消解 spec 漂移 5（`LLM_PROVIDER` 死配置删除）；H-3 收口使 `DocumentParser` 端口首次被服务层真实消费（签名定稿含 `source_type`）；spec §4.1 端口表补记 `CodeParser` 有意偏离与 `DocumentParser` 接缝定稿；P3/P4 五条契约（漂移 4）逐条核验已在 spec，无补文。
- 2026-09-08 · 前端重设计 P0+P2（分支 `feat/fe-redesign-p0-p2`，ADR-0011 / 0012）：新增术语 **设计令牌 v2**（`--fs-*` 字阶 / `--shadow-e1..e4` / `--duration-*` / `--ease-standard` / `--color-border-strong` / `--color-overlay` / `--radius-pill`）、**UI 适配层**（`src/ui/*` 薄封装，页面/外壳只依赖 `@/ui` 而不直接 import `el-*` 或 `components/ui/*`）、**导航模型**（`src/nav.ts` `NavItem{path,label,icon,group,adminOnly}`，分组「学习/管理」）、**视觉回归基线**（`tests/screenshots/v1-old/` 14 路由为冻结参照；Playwright 冒烟 + md5 逐字节比对确认 Tailwind 引入对 v1 页面零视觉变化——三处差异均为冷启动渲染抖动与时间戳，已用「预热后采集」规避）。`shadcn-vue` 正式组件接入**推迟到 P1**（本次只做了 `components.json` 骨架与 `@/lib/utils.ts#cn`），@/ui 的 el-* 包装件保留至 P1 替换。
- 2026-09-08 · 前端重设计 P3–P6 全部收口（分支 `feat/fe-redesign-p3-student` / `-p4-student` / `-p5-admin` / `-p6-finalize`）：**14 页面 + 登录页全部脱离 el-* 模板依赖**，统一走 `src/ui/`（终态 21 件）与 `useNotify` / `useConfirm` / `usePagedList` 三个组合式。新增术语：**同构表格页骨架**（UiCard 工具行 + 原生 `<table>` + UiPagination，Logs/Users/ExerciseAdmin/KnowledgeAdmin 四页共用）、**最小 box-sizing 重置**（`@layer base` 仅 border-box 一条，P5 实测缺失会使 `w-full` + 内边距元素按 content-box 溢出容器，登录页最先暴露）、**工具栏定宽容器**（UiInput/UiSelect 基类自带 w-full，定宽须外层包裹）。加载遮罩统一保留 `v-loading` 指令（共存期豁免，已写入 ui-baseline §9/§12）。设计基线 v2 经设计确认生效（`ui-baseline.md` 替换 v1，草稿文件已删）。

