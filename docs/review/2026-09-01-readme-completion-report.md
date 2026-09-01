# README + 收尾批次完成报告（2026-09-01）

- 分支：`feat/readme-finalize`（自 main @ f3a8686 切出）
- 批次性质：**纯文档批次 · 项目最后一批**（不改任何业务代码）
- 计划：`docs/superpowers/plans/2026-09-01-readme-finalize.md`（阶段一获批后执行）
- 阶段一裁定已全部落实：①「无页面入口」措辞纪律；② 提示语出入列已知边界；③ ADR-0006 保留（第 6 条）；④ 映射表拆 12 个 h4 小节 + 3 列紧凑速览表；⑤ V2 排除规则；⑥ Mock 总结论句必含；⑦ 三条未验证项必列。

## 1. 交付清单

| Commit | 内容 |
|---|---|
| `42617c3` | docs: 实施计划 + AGENT.md 授权登记 |
| `04b3837` | docs(readme): 五大块补全（README +185/-1 行，80 → 264 行） |
| 本 commit | docs: 完成报告（门槛证据） |

## 2. 五块逐条证据

### 块 1 · 功能点 → 演示路径映射表（答辩口径核心）

README 新增「功能一览与答辩口径」：

- **Mock 总结论句已含（裁定项）**：「12 个功能点全部无需 API Key 即可演示」+ 两处口头声明（AI 文本质量、RAG 语义精度），置于表前引用块。
- 3 列速览表（功能点 | 页面（导航项）| 关键端点）+ 12 个 h4 小节（按裁定拆表），每小节三个行内 label：**实现落点 / 演示路径 / Mock 可演示性**。
- 学生端 5（答疑对话、RAG 增强、代码解析、编辑器运行、习题与辅导）+ 管理端 4（用户、知识库、模型配置、系统日志）+ 功能增强 3（防抄袭提示词、RAG 检索、错题驱动学习），与 spec §11 十二功能点一一对应。
- 全部端点/页面/按钮文案实测来源见 §4/§5；无编造。
- 「无页面入口」如实声明 2 处（功能点 7 切片核对、功能点 8 embedding 409 流程 + 一致性检查，均注 curl 黑盒口径）。

### 块 2 · 演示机跑法

README 新增「演示机跑法（答辩环境）」：`make install-lite` → `.env`（换 JWT_SECRET）→ `make seed`（40 道习题、幂等）→ `make serve` 单端口同源 + `/health` 预热轮询（本地模型首载实测约 13–20s，措辞「实测约」不写死）；H-1 负载纪律（演示/构建勿并行 `make test`、测试单独跑）；`test_memory_hog` flake 机理（唯一真实 256MB 用例、CPU 层先触发 → `timeout` ≠ `memory_exceeded`）+ 隔离复跑命令；受限网络 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`（P4 实测根因）；演示动线建议（管理端先建库 → 学生端 1–5 → 管理端三页留痕闭环收尾）。

### 块 3 · 配置说明

README 新增「配置说明」三小节：

- `.env.example` 7 变量逐行表（含 `APP_SECRET` 留空走文件、缺失首启自动生成）；
- `Settings` 其余 6 项 env 简表（`MOCK_TOKEN_DELAY_MS` 只作用 Mock 流式、执行队列 2/10s 超限 429 不无限排队）；
- 真实 LLM 接入段：提供方只走后台模型配置页（`.env` 无提供方开关，`LLM_PROVIDER` 字样零出现）→ `openai_compat` 缺 Key 保存被拒 4220 → Fernet 加密落库 → **L-2 掩码规则**（≤7 位整体 `****`，长密钥 `前3****后4` 如 `sk-****abcd`，与 `crypto.py:29-36` 实测一致）→ revision 热生效 → 「测试连接」只测已保存配置；
- Embedding 三级回退一段：OpenAI 兼容 → 本地 MiniLM（`paraphrase-multilingual-MiniLM-L12-v2`，需 local-embed extras）→ HashingEmbed 哨兵（只保链路不保语义，ADR-0004）。

### 块 4 · 已知限制与边界（答辩口径）

6 条：单 worker（ADR-0002）、真实提供方全链路未实测（含「Mock 输出形态 ≠ 真实模型遵循度」）、混合检索未排期、后台无白名单/锁定（引用声明不重复）、执行器非沙箱（引用声明不重复）、**无迁移框架（ADR-0006，按裁定保留）**。管理后台安全边界声明末尾加一句指向本节。

### 块 5 · L-2 掩码说明收口

「真实 LLM 接入」段第 3 句即掩码规则全文（长度 ≤7 位整体 `****` + 前 3 后 4 示例），清理批次移交项就此收口。

## 3. 门槛结果总表（计划 §8 V1–V6）

| # | 验证 | 结果 | 证据 |
|---|---|---|---|
| V1 | 禁词 grep | ✅ 0 命中 | `rg -n "题目\|试题\|草稿" README.md` → exit 1（无匹配）；扩查 `账户\|帐号\|账号\|教师\|分块\|成员\|空间` → 0 命中（「账号」虽非 CONTEXT 明列禁词，按只收紧纪律改「学生用户」） |
| V2 | 链接核验 | ✅ 零断链 | 清单见 §5 |
| V3 | 端点/页面核对 | ✅ 零编造 | 对照表见 §4 |
| V4 | 术语一致性 | ✅ | 见 §6 |
| V5 | 交付态基线 | ✅ 与 f3a8686 验收一致 | `make lint` → All checks passed!（0 errors）；backend `python -m pytest -q` → **1006 passed / 2 skipped**（227.16s，单独串行）；frontend `npm test` → **8 passed**；`npx vue-tsc --noEmit` → 零错误；`npm run build` → 成功（45.13s） |
| V6 | 改动面 | ✅ | `git diff --name-only main..HEAD` 仅 `AGENT.md`、`README.md`、`docs/superpowers/plans/2026-09-01-readme-finalize.md`、`docs/review/2026-09-01-readme-completion-report.md`（本文件）——4 个授权文件，业务代码零改动 |

## 4. V3 端点/页面核对（脚本 `main.py` routers 装饰器 + `router/index.ts` 实况 diff）

- README 引用的 **33 条端点引用**（含复合写法 `GET/POST/PATCH/DELETE` 展开）逐一比对 `backend/app/routers/*.py` 的 55 个注册端点 + `/health`（main.py:100）：**全部命中**，零编造、零多余。两个 SSE 端点（`POST /chat/conversations/{id}/messages` chat.py:70-71、`POST /exercises/{id}/hint` exercise.py:110-111）为跨行装饰器，已源码实读确认。
- README 引用的 **12 个页面路径**（`/chat` `/code` `/editor` `/knowledge` `/exercises` `/mistakes` + 7 个 `/admin/*`）逐一比对 `frontend/src/router/index.ts`：**全部存在**；导航标签逐字取 `AppShell.vue:33-45`。
- UI 文案逐处实读（不编造按钮名）：「新建会话」「启用知识库增强（RAG）」「发送」「停止生成」「填入示例」「开始解析」「与上次分析相同，已复用历史结果」「保存会话」「运行」「提交判分」「获取思路」「批改我的作答」「停用/启用」「清理孤儿向量」「重建向量」「保存配置」「测试连接」「薄弱知识点」「推荐练习」「重置掌握度」「随机补足」「知识库命中/未命中知识库」「严格（只给思路与伪代码）/引导（默认，允许 ≤10 行片段）/宽松（允许完整实现，需讲解）」「AI 参考评分（Mock 启发式）」。
- 判分四路描述与 spec §5.1 及 `ExerciseView.vue` 对齐：choice/blank 规则比对、multi 全对/漏选/错选、coding 真执行器 + `judge_detail`、short AI 参考评分（Mock 启发式、降级可见）。

## 5. V2 链接核验清单

脚本提取 README 反引号路径与 markdown 链接目标（按裁定排除：shell 命令、http(s) URL、`@` 包名、示例配置值、环境变量名、代码标识符引用、`::` 测试选择器）：

| 引用 | 存在性 |
|---|---|
| `AGENT.md` / `CONTEXT.md` / `backend/.env.example` | ✅ |
| `docs/adr/` / `docs/superpowers/specs/` / `docs/superpowers/plans/` / `docs/review/` / `frontend/docs/ui-baseline.md` | ✅ |
| `docs/adr/0003-code-sandbox-resource-limits.md` | ✅（既有章节，保留） |
| `tests/test_code_executor.py::test_memory_hog_is_killed_by_memory_layer` | ✅ 文件存在（`::` 后为 pytest 选择器，非路径） |

排除类（示例值/标识符，非链接目标，逐条甄别）：`sqlite+aiosqlite:///./data/app.db`、`.secret_key`、`data/chroma`、`data/uploads`（配置默认值）；`os.system`、`RLIMIT_AS/DATA/RSS`、`CodeRun.limit_detail`、`Message.blocked_by_policy`（代码标识符）；ADR-0002/0004/0005/0006/0009 编号引用（对应 `docs/adr/0002-…` 等文件均实存，目录级链接已核）。**结论：零断链。**

## 6. 术语一致性（对照 CONTEXT.md 逐条）

使用正式术语：习题 / 题库 / 题干、错题本（功能名）/ 错题条目（实体）、代码会话（CodeSession）、代码运行（CodeRun）、会话（Conversation，「新建会话」为 UI 文案引用）、知识库 / 文档 / 切片 / 引用、模型配置（页面名引用「模型配置」照 AppShell 标签）、审计日志、防抄袭档位 / 防抄袭底线、降级 / 哨兵级降级 / 降级可见、相对截断、多样性截取、相关度阈值、随机补足、掌握度、薄弱知识点、求答案 / 评改已写代码（意图译名）、豁免、请求意图、执行队列上限、API Key 掩码（内容表述，规则实测）、阻塞卸载未涉。「题目/试题/草稿」0 命中；「错题」仅以「错题本/错题条目」复合词出现，无裸实体误用；「对话」仅在功能名「AI 答疑对话」（导航标签）与「会话」实体不混用。**零违禁、零自造。**

## 7. 已知边界记录（不修代码，如实登记）

1. **切片预览无页面入口**：`GET /admin/knowledge/documents/{id}/chunks` 端点存在，`listChunks` 已在 `frontend/src/api/knowledge.ts:63` 定义但全前端零调用。README 功能点 7 写「以接口（curl 黑盒）演示」。
2. **embedding 切换 409 流程与一致性检查无页面入口**：`PUT /admin/model-config/embedding`、`GET /admin/model-config/embedding-consistency` 无前端消费；模型配置页该区域只读回显。**页面提示语与实际 UI 存在出入**（`ModelConfigView.vue:14` 注释称「409 重建流程在知识库管理页」，而知识库管理页仅有 per-KB「重建向量」按钮，非 embedding 配置切换表单）——按总指挥裁定登记为已知边界：接口优先架构的排期外残留，非缺陷。README 功能点 8 写「无页面入口」+ 清理批次真服务冒烟已黑盒实测该链路的证据指引。
3. 两处均未写成「有页面入口」（裁定纪律落实：grep 复核 README 中「入口」相关句全部为「无页面入口」或接口级表述）。

## 8. 未验证项（如实申报）

1. **Mock 输出形态 ≠ 真实模型遵循度**：防抄袭三档约束在 Mock 下的可见性有限（Mock 文案固定），真实模型下的遵循深度未验证。
2. **真实 OpenAI 兼容提供方全链路未实测**：开发环境无 API Key；`openai_compat` 提供方与 Embedding 第一级仅有代码实现 + 契约单测，端到端以 Mock 验证（README「已知限制」第 2 条已声明，含答辩机先跑「测试连接」的建议）。
3. **前端四断点视觉回归**：本批未跑（纯文档批次，未触任何样式代码）；归「答辩前可选」。
4. 附带：README 中演示路径为源码级文案核对（按钮/标签逐字实读），未做「照演示路径点一遍」的浏览器级走查——答辩彩排时建议按映射表走一遍真机。

## 9. 与既有内容关系

- 既有 7 章节（快速开始 / 默认管理员 / 两条安全声明 / 文档索引 / 技术栈）**内容零重写**：仅加 3 处交叉指引句（快速开始 2 行指向新章节、后台安全声明 1 行指向已知限制、文档表 ADR 行描述补 0001–0010 与关键条目标注）。
- spec 回写：本批**零新增**（漂移已全收口，README 表述全部以现行 spec 正文为据）。

## 10. 结论

五块全交付，V1–V6 门槛全过，交付态基线复跑与第三任总指挥验收一致（lint 0 / 1006+2 / 前端三件套绿），改动面 4 文件白名单内。工作树 clean。**停下等总指挥审阅**——本批为项目最后一批，审阅通过后进入整体收尾（用户推 GitHub）。
