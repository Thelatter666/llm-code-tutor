# AGENT.md

本文件是本仓库对 AI 编码助手的**强制约束**。任何 Agent 在本仓库工作前必须完整阅读并遵守。

## 项目概述

**项目名称**：基于大语言模型的智能编程教学辅助系统

**功能模块**：

- 学生端：AI 编程答疑对话、RAG 课程知识库增强、代码智能解析与辅导、在线代码编辑器与运行调试模块、习题练习与 AI 习题辅导模块
- 管理员后台：用户管理、知识库管理、模型参数配置、系统日志
- 功能增强：防抄袭约束提示词、RAG 知识库检索、错题驱动学习

**技术栈**：后端 Python 3.12 · FastAPI · SQLAlchemy 2(async) · SQLite · Chroma；前端 Vue 3 + TypeScript + Vite + **Tailwind CSS v4** + shadcn-vue（骨架，ADR-0011）+ Element Plus（共存期，ADR-0012）+ Monaco。**前端设计基线 v2（`frontend/docs/ui-baseline.md`）为强制约束**；前端现状与契约详见完成报告 `docs/review/2026-09-08-frontend-redesign-completion-report.md`。

## 开发工作流约束

进行**任何代码修改**，必须按以下流程执行。确认点只有四个：阶段 3（复述对齐）、阶段 6（效果确认）、阶段 7（commit 指令）、阶段 8（合并 main）；其余阶段不问，执行过程中的子阶段确认节奏由 mywf 决定：

1. **提需求** → 2. **探索理解** → 3. **复述对齐**（用户确认后才动手）→ 4. **新建分支**（从 `main`，如 `feat/xxx`、`docs/xxx`，禁止直接改 main）→ 5. **执行任务**（加载 `mywf` skill，按其约定执行；人类决策点以 mywf 为准）→ 6. **效果确认**（只汇报效果，用户亲自检查）→ 7. **commit / merge 指令**（用户明确下令前，绝不 commit / merge）→ 8. **合并 main**

> **远端同步不在本工作流内。** 用户将在本项目本地初步开发完成后，自行创建 GitHub 仓库并推送。
> Agent 不得执行 `git remote add`、`git push` 或任何涉及远端的操作，除非用户另行明确要求。

### 阶段细则

| 阶段          | 要求                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------- |
| 1. 提需求     | 用户以自然语言提出需求，Agent 不做任何推测性修改                                          |
| 2. 探索理解   | Agent 主动检索代码库、定位相关模块、理解既有约定，形成完整上下文                          |
| 3. 复述对齐   | Agent 用自己的话复述对需求与现状的理解，**必须等用户明确确认后才进入下一阶段**            |
| 4. 新建分支   | 从 `main` 切出功能分支，命名规范 `feat/<功能>`、`fix/<问题>`、`docs/<文档>`；禁止直接改 main |
| 5. 执行任务   | 加载 `mywf` skill 执行；**人类决策点以 mywf 为准（意图确认 / 难逆转的架构选择 / 完成与合入）**，子阶段确认节奏由 mywf 决定，不强制逐子阶段确认。本文件阶段 5 的「加载 mywf」即视为用户显式调用 `/mywf`，无需用户再说「走工作流」 |
| 6. 效果确认   | Agent **只汇报改动效果与验证方式**，不做自我判定；由用户亲自检查                          |
| 7. 提交指令   | **未经用户明确下令，绝不执行 commit / merge**，包括不带参数的 `git commit`               |
| 8. 合并 main  | 用户下令后，将功能分支合并回 `main`                                                      |

### Skill 使用约束

| Skill | 约束 |
| --- | --- |
| `codebase-onboarding` | **只读**。在本仓库中仅限读取与分析（列目录、检索、读文件、语义跳转），**禁止任何写操作**——不得创建、修改、删除文件，尤其禁止生成/覆写 `AGENT.md`、`CONTEXT.md` 或 `docs/**` 下任何产物。分析结果只以对话回复形式输出；确需落盘时，必须等用户明确下令，并另行走完「开发工作流约束」。 |

### 前端约束（ADR-0011 / 0012）

详细契约见完成报告 `docs/review/2026-09-08-frontend-redesign-completion-report.md` §5–§7 与设计基线 `frontend/docs/ui-baseline.md`（v2，强制）。

- 一切 UI 经 `src/ui/` 适配层：页面/组件**禁止**直接 import `el-*`、`ElMessage`、`ElMessageBox`；通知用 `useNotify`、确认用 `useConfirm`、空态用 `UiEmpty`、加载遮罩用 `v-loading` 指令（共存期豁免）。
- **不可动**：`composables/useSse.ts`（自实现 SSE，非 EventSource）、`components/MarkdownView.vue`（唯一 `v-html` 豁免点，只收 `renderMarkdown()` 产物）、`components/CodeEditor.vue`（Monaco 动态 import + worker）、`main.ts` 的 CSS 引入顺序（ADR-0012 共存前提）。
- 前端改动验证门槛：`npm run build` + `npm test` + `npm run test:e2e` 三者全绿；涉及视觉的改动须与 `tests/screenshots/` 基线比对。
- 定宽控件用外层容器包裹（适配层组件基类自带 `w-full`，直接传宽度类会被覆盖）。

### 铁律

- 前端改动必须遵守「前端约束」小节与 `frontend/docs/ui-baseline.md`（v2 强制基线）。
- `codebase-onboarding` 在本仓库限定为**只读**，禁止落盘任何文件（见「Skill 使用约束」）。
- 第 3 阶段（复述对齐）未获用户确认前，不得创建/修改任何代码文件。
- 第 7 阶段前，禁止任何形式的 `git commit`、`git merge`、`git rebase`。
- 子代理（subagent）同样受第 7 阶段 commit 禁令约束：无论「授权例外」表如何登记，`git commit` 一律由主会话执行（主会话可依据该表不经请示），子代理只交付代码与测试结果。
- 禁止直接在 `main` 分支上提交。
- 禁止任何涉及远端的操作（`git push`、`git remote add` 等）—— 远端同步由用户本人处理。
- 用户只提出需求、不指定实现细节时，Agent 必须先完成「意图对齐」并落盘方案文档（spec）；grilling 与 plan 按 mywf 的「可选工具，不是步骤」处理——需要时才取用，不得跳过的只有意图确认。

### 授权例外

第 7 阶段的 commit 禁令可由用户**书面预先授权**解除。已授权的例外登记如下，超出范围的仍需单独下令。

| 日期 | 授权范围 | 授权内容 |
|---|---|---|
| 2026-08-30 | P0 基座实施（`docs/superpowers/plans/2026-08-30-p0-foundation.md` 的 Task 1–15） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-30 | P1 RAG 知识库实施（分支 `feat/p1-rag-knowledge-base`） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-30 | P2 答疑对话与防抄袭实施（分支 `feat/p2-chat-anti-plagiarism`） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-31 | P3 代码解析与辅导（分支 `feat/p3-code-review`，含并入的 Mock 流式延迟、前端 Markdown 渲染、spec §8.1 歧义改写） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-31 | P4 在线编辑器与受限执行器（分支 `feat/p4-editor-sandbox`） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-31 | P5 习题与错题本（分支 `feat/p5-exercise-mistakebook`） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-08-31 | P6 管理后台收口（分支 `feat/p6-admin-console`） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-09-01 | 清理批次实施（分支 `feat/cleanup-batch`，计划 `docs/superpowers/plans/2026-09-01-cleanup-batch.md` 的 Task 1–7） | 用户预先授权：每个 Task 完成且全量测试通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |
| 2026-09-01 | README + 收尾批次实施（分支 `feat/readme-finalize`，纯文档批次，计划 `docs/superpowers/plans/2026-09-01-readme-finalize.md` 的 Task 1–3） | 用户预先授权：每个 Task 完成且门槛通过后，可直接按 Task 粒度 `git commit`，无需逐次请示。**`merge` 不在本次授权内**，仍需单独下令。 |

## 产出物落盘约定

| 产物     | 路径                                                     |
| -------- | -------------------------------------------------------- |
| 方案文档 | `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`    |
| 术语表   | `CONTEXT.md`                                             |
| ADR      | `docs/adr/<NNNN>-<slug>.md`                              |
| 实施计划 | `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`    |

懒创建：首次需要时再建文件/目录，不预建空文件。

本仓库内 spec 为**必须落盘**（见「铁律」最后一条）；其余三项按上表的懒创建原则处理，需要时才建。
