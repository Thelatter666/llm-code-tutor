# 项目总指挥交接文档

- 交接日期：2026-08-31
- 交接方：原总指挥（本会话）
- 项目根目录：**`/Users/happy/CodeBuddy/20260830111027`**（仓库目录名保持旧名，勿再重命名 —— 重命名会危及 IDE 会话）
- 项目：基于大语言模型的智能编程教学辅助系统（毕设演示原型）

---

## 1. 角色定义：总指挥做什么

| 职责 | 具体内容 |
|---|---|
| 审阅交付 | 批次完成后**独立验证**（不采信 agent 的自证）：复跑测试、查实现、做变异测试 |
| 裁定 | 对 agent 提出的遗留/待定项给出明确裁决，并把裁决写进 `docs/review/` 持久化 |
| 防漂移 | 每批检查 spec ↔ 代码一致性，agent 引入新契约必须回写 spec（H2 类问题） |
| 验证纪律 | 区分「查过且干净」与「没查」；报告里出现「应该/预计/大概」一律退回 |
| 批次编排 | 按 `docs/review/2026-08-30-agent-assignment.md` 分档（P2/P4 强档，P3/P5/P6 便宜档），串行推进 |
| 环境与回归 | 每批合入 main 后复跑 `make test` 全量；维护测试基线数字的准确性 |

**铁律**（来自 AGENT.md，新总指挥同样受约束）：
- 禁止任何远端操作（`git push` / `git remote add`）—— 远端同步由用户本人在本地开发完成后自行处理
- `merge` 必须用户明确下令；`commit` 按各批次已登记的授权例外执行
- 分支必须从 `main` 切出，禁止直接在 main 上提交

---

## 2. 项目概况

**题目**：基于大语言模型的智能编程教学辅助系统设计与实现

**12 个功能点**：
- 学生端：AI 编程答疑对话 / RAG 课程知识库增强 / 代码智能解析与辅导 / 在线代码编辑器与运行调试 / 习题练习与 AI 习题辅导
- 管理员后台：用户管理 / 知识库管理 / 模型参数配置 / 系统日志
- 功能增强：防抄袭约束提示词 / RAG 知识库检索 / 错题驱动学习

**定位**：毕设演示原型 —— 功能完整、可端到端演示、本地一键启动；外部依赖允许 Mock；不追求高并发与生产级安全加固。

**技术栈**：Python 3.12 + FastAPI + SQLAlchemy 2(async) + SQLite(WAL) + Chroma + Vue 3 + Vite + TypeScript + Element Plus + Monaco + SSE

**架构**：模块化单体 + 端口适配器，单进程单 worker（ADR-0002）。分层 `routers → services → domain → infrastructure`；领域层零 IO；服务层只依赖 `Protocol` 端口；外部能力（LLM / Embedding / VectorStore / CodeExecutor / DocumentParser）全部端口抽象 + Mock 同签名实现。

---

## 3. 进度全景

| 批次 | 内容 | 状态 | 分支 |
|---|---|---|---|
| P0 | 基座：分层/配置/持久化/统一响应/端口/注册表/JWT/审计/seed/前端骨架 | ✅ 已合并 | feat/p0-foundation |
| P1 | RAG 知识库：三表/Embedder三级回退/Chroma/切分/索引/检索/删除GC/切换409 | ✅ 已合并（含返工 B1） | feat/p1-rag-knowledge-base |
| P2 | 答疑对话+防抄袭+前端：SSE/中断/三档/度量/知识库管理页/检索演示页 | ✅ 已合并 | feat/p2-chat-anti-plagiarism |
| P3 | 代码解析+Mock延迟+Markdown渲染：/code/analyze/ast解析/消毒 | ✅ 已合并 | feat/p3-code-review |
| P4 | 编辑器+受限执行器：Monaco/四层限制/进程组kill/黑名单 | ✅ 已合并 | feat/p4-editor-sandbox |
| 健康检查 | 11 维度全查 + 3 处缺陷修复 + spec 回写 P4 契约 | ✅ 已合并 | fix/health-check-p5-prereq |
| P5 | 习题与错题本（**待开工**，提示词已就绪） | ⏳ 分支已对齐 | feat/p5-exercise-mistakebook |
| P6 | 管理后台收口（用户/模型配置/日志/仪表盘/防抄袭统计） | 未开工 | — |
| README+收尾 | 强档统一撰写 + lint 清理 | 未开工 | — |

**当前仓库状态**（2026-08-31 核实）：
- `main` @ `beb2379`，工作区干净
- 测试基线：后端 **661 passed / 2 skipped**；前端 `npm test` 8 passed；`vue-tsc --noEmit` 零错误；业务包约 57 kB
- 验证命令：`make test`（同时跑 pytest + vitest）
- 测试必须离线：conftest 已内置 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`

---

## 4. 关键文档索引

| 文档 | 承载内容 |
|---|---|
| `AGENT.md` | 工作流 8 步 / 铁律 / 授权例外表（P0–P5 已登记 commit 预授权） |
| `CONTEXT.md` | 术语表（代码标识符必须使用正式术语） |
| `docs/superpowers/specs/2026-08-30-llm-programming-tutor-design.md` | 总体架构 spec（12 节，已历经 4 轮回写） |
| `docs/adr/0001~0010` | 架构决策记录（0002 单 worker / 0003 沙箱 / 0004 哨兵 / 0005 豁免 / 0006 无迁移 / 0007 维度分区） |
| `docs/superpowers/plans/2026-08-30-p0~p4-*.md` | 各批实施计划 |
| `docs/review/2026-08-30-p1-completion-report.md` + `p1-review.md` | P1 交付与审阅（含 B1 返工） |
| `docs/review/2026-08-30-p2/p3/p4-completion-report.md` | 各批完成报告 |
| `docs/review/2026-08-30-agent-assignment.md` | 档位分配 + P2 遗留裁定 + P3 扩大范围 |
| `docs/review/2026-08-31-health-check-report.md` | 11 维度健康检查（含 3 处已修复缺陷） |
| `docs/review/2026-08-30-documents-review.md` | 早期 spec/plan 审阅（B1–B6 阻塞项来源） |
| 本文件 | 当前交接文档 |

---

## 5. 已裁定决策库（新总指挥不得推翻或重问）

| 决策 | 裁定 | 出处 |
|---|---|---|
| 交付定位 | 毕设演示原型，Mock 可接受 | 需求澄清 R1 |
| 架构 | 模块化单体 + 端口适配器，单 worker | R1 / ADR-0002 |
| LLM 接入 | Provider 抽象 + 内置 Mock，OpenAI 兼容 | R1 |
| Embedding | 三级回退：OpenAI → MiniLM(384维) → HashingEmbed 哨兵 | R2 / ADR-0004 |
| 鉴权 | 自建账号 + JWT，student/admin | R2 |
| 前端 | Vue3+TS+Element Plus，uiuxpromax 定基线 | R2 |
| 习题来源 | 内置种子 ~40 题 + 后台 CRUD（**spec §6.2 缺口，P5 需回写**） | R3 |
| 防抄袭 | 三档可配 + 硬编码底线 + 意图显式豁免（不推断） | R3 / ADR-0005 |
| 流式协议 | SSE | R3 |
| 解析 | Python ast 精确 / JS 轻量近似（不可当 lint 宣传） | R4 / spec §8.4 |
| 错题 | 自动归集 + 掌握度（连续 2 次答对）+ 画像/推荐 + **掌握度必须可回滚** | R4 / P1 Grilling Q23 |
| 启动 | Makefile 一键（install/install-lite/dev/serve/test/seed/lint） | R4 |
| 日志 | 业务审计日志落库 | R4 |
| 模型预热 | 方案 B：启动异步预热，/health 暴露就绪态 | 2026-08-30 拍板 |
| 检索阈值 | MiniLM 档 0.35 保持；**降阈值会反转排序（错的排前面）**；管理端开放留 P6 | 2026-08-31 裁定 |
| 混合检索 | 独立成项暂不排期；P6 后用真实讲义语料实测零命中率再评估 | 2026-08-31 裁定 |
| CodeSession 归属 | 归 P4（已实现）；P3 禁止创建 | 2026-08-31 裁定 |
| Mock 流式延迟 | mock_token_delay_ms 默认 30ms，只影响 stream() | 2026-08-31 裁定 |
| Chroma 维度 | 按维度分区集合 course_chunks_d{dim}（删集合可重置但失败不安全） | ADR-0007 修订 |
| reindexing 检索 | 显式 kb_ids → 5032；默认作用域**静默排除**非 ready 库 | 2026-08-31 修复 |
| 向量库故障 | 一律 5032，不得漏成 5000 | 2026-08-31 修复 |
| 档位分配 | P2/P4 强档、P3/P5/P6 便宜档、README 强档；**P2/P4 是底线** | agent-assignment |
| 便宜档控制 | 约定写死 + 指定范本文件 + 变异测试指引 | agent-assignment |
| P5 判题超时 | 端口无 per-call 超时，「单题 15s 累计」由服务层自计 | 2026-08-31 审计 |
| 远端 | 本项目所有批次完成后由用户本人推 GitHub，agent 一律不碰 | 2026-08-30 |

---

## 6. 遗留台账（开放项 + 归属）

| 开放项 | 归属 | 备注 |
|---|---|---|
| 服务层 4 处直连适配器（indexing_service:30,136 / model_config_service:15-19,223,315） | 清理批次 | **修复必须回归 B1 的变异测试**；P5 提示词已禁止模仿 |
| lint 35 处 | 清理批次（P6 后） | 全在 P0/P1 文件，P3/P4 新增已清零 |
| README 默认密码警示 | P6 | spec 验收清单要求 |
| favicon 404 | P6 | 控制台唯一 error |
| 管理端习题 CRUD（spec 缺口） | P5 | 已写进 P5 提示词 |
| M2 `backend/seeds/` 目录 | P5 | 已写进 P5 提示词 |
| M4 端口契约测试补全 | P5 | 已写进 P5 提示词 |
| 混合检索 | 暂不排期 | P6 后实测评估 |
| 真实 LLM Key 全链路 | 答辩前 | 建议答辩前买一个 DeepSeek key 实测 |
| Chroma 宕机时聊天流行为 | 未验证 | 健康检查标注 |
| 对比度视觉检查 | 未验证 | 健康检查标注 |

**已确认无需处理的**：CodeParser 端口未建（落领域层合规）、bcrypt 线程池（P0 已做）、M6 已落实。

---

## 7. 已知陷阱与技术债务（新总指挥验证时优先查）

1. **macOS rlimit**：`RLIMIT_AS/DATA/RSS` 设不进去（抛 ValueError），只能用 RLIMIT_CPU/FSIZE/NOFILE + psutil 采样（ADR-0003）。便宜 agent 容易照抄 Linux 写法。
2. **单例 cancel**：注册表缓存单实例，中断必须是 per-call `asyncio.Event`，绝不可做成 provider 实例方法（P0 有并发回归用例守护）。
3. **Chroma 维度**：集合首次写入后维度固定，删记录不重置；删集合可重置但失败不安全。换维度走分区集合 + 重建。
4. **掌握度回滚**：错误时必须重置 `mastered=false, mastered_at=null`，否则单向门让错题本特性失效。P5 必须有专门用例。
5. **HF 联网**：sentence-transformers 加载缓存模型仍会查 Hub，受限网络下无限等待。测试已用 conftest 强制离线。
6. **时区**：SQLite 回读 naive datetime，必须用 `UTCDateTime` 类型装饰器。
7. **`.env.example`** 曾被 `.env.*` 规则误伤，已加 `!.env.example` negation。
8. **变异测试方法论**：验证 agent 测试有效性 = 拆掉修复 → 跑测试 → 必须失败。P1 之后每批 agent 都被要求提供「变异指引」，新总指挥应保持此惯例。

---

## 8. 审阅方法论（新总指挥的工作方式）

每批交付后，按以下顺序：

1. **独立复跑**：`make test`、`vue-tsc`、`vite build` —— 数字对不上报告即退回。
2. **查 skip**：逐个 skip 说明原因，判断是否掩盖问题。
3. **变异测试**：抽 1–2 个安全敏感点，拆掉实现看测试是否真的失败。
4. **spec 漂移检查**：grep 新契约是否已回写 spec；spec 里有的端点是否在 `/openapi.json` 里都注册。
5. **纪律 grep**：`request_id=""` 应为 0 处；models 只用 UTCDateTime；domain 无 infra import；services 不 import adapters。
6. **裁定**：阻塞级 → 不合并；高危 → 同批处理；中低 → 归批次。裁定必须写进 `docs/review/` 持久化。
7. **合入**：用户下令后 ff 合并到 main，复验，再切下一个批次分支。

**对 agent 报告的要求**（写进每个批次提示词）：真实执行结果、禁止推测表述、未验证项必须标注「未验证」、给出变异测试指引。

---

## 9. 下一步行动

1. **P5 开工**：分支 `feat/p5-exercise-mistakebook` 已对齐 main（beb2379），授权已登记（AGENT.md）。提示词在会话历史中（含审计后的三段补充：防传播硬规则 / 判题超时语义 / 基线更新），新总指挥按同一口径重发。
2. P5 完成后：审阅（重点盯掌握度回滚 + 种子自校验 + 多选漏选）+ 合并。
3. P6 管理后台收口（便宜档）：用户管理/模型配置/日志/仪表盘/防抄袭统计 + README 默认密码警示 + favicon。
4. README + lint 清理批次（强档，最后统一写）。
5. 全部完成：合并所有功能分支 → 交还用户推 GitHub（agent 不碰远端）。

---

## 10. 给新总指挥的提醒

- **不要重命名项目目录**（会危及 IDE 会话，此前发生过）。
- **不要相信任何 agent 的自证** —— 包括历次报告里声称已做过的验证。保持独立复跑与变异测试。
- **测试基线数字要自己跑**：P2 报告把 34 处 lint 写成 48，审计报告把「已回写的 4 条契约」写成「未回写」—— 连审计都会出错，唯一可靠的是自己查。
- 每个批次开工前把该批的**已裁定决策**写进提示词，防止 agent 重问或推翻。
