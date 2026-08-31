# P6 管理后台收口完成报告

- 分支：`feat/p6-admin-console`（自 main @ 8264001 切出，16 次提交）
- 交付：2026-08-31
- 总指挥裁定：计划 + 八项裁定（含 2 处修订/补充）+ 新增裁定 9 全部于 2026-08-31 回填入库后开工

## 1. 交付内容（对照 §3 范围清单，全部完成）

| 范围 | 交付 |
|---|---|
| 用户 CRUD | `routers/admin_users.py` + `services/user_service.py`：GET（q/role/status+分页）、POST、PATCH（含 status:disabled 软删除、重置密码、禁自降权/自停用）、DELETE 硬删除级联（会话→消息→提交→错题条目→代码会话→代码分析→代码运行，单事务同步）；审计 `admin_user_create/update/delete`（delete 带七项级联计数）；末位 active admin 守卫；KB.owner_id 悬空例外（裁定 9） |
| 模型配置全量 | `GET/PUT /admin/model-config`（裁定 2 字段面、api_key 缺省=不变更/空串 4220、openai 无 key 4220 拒绝保存、revision+=1 热生效、掩码出参）+ `POST /admin/model-config/test`（只测首选级、失败 ok=false 不抛 5xx）；embedding 仍走既有 409 流程（未动） |
| 日志查询 | `GET /admin/logs`：action/user_id 精确、start/end ISO 时间区间（纯日期闭合区间、无时区按 UTC）、倒序分页、审计行全字段回显 |
| 仪表盘聚合 | `GET /admin/overview`（裁定 3 最小集：users/conversations/messages/kb/documents/code_*/exercises/submissions/mistake_entries/audit_logs + model_config 摘要 + embedder 快照） |
| 删除 /admin/ping | main.py 移除（L-1）；test_auth_api.py:111 改打 /admin/users；补「占位已删除 → 4040」断言 |
| 前端五页 + 遗留一页 | 用户管理 / 模型配置 / 系统日志 / 仪表盘 / 防抄袭统计 + 习题管理（对接 P5 五端点）；六个懒加载独立 chunk + requiresAdmin；导航按角色显隐；零硬编码色值；三页口径文案（裁定 8） |
| 顺带项 | M-15 README（默认管理员警示+40 题说明+后台安全边界声明条）；L-3 favicon.svg + index.html link；M-8「token 有效但用户已删 → 4010」用例；L-2 短密钥掩码（≤7 位整体 `****`）+ 用例 |

## 2. 测试基线（逐 Task 实跑，非转述）

| Task | 提交 | 全量结果 |
|---|---|---|
| 0 计划 | 6669d9f / c14ba63 | — |
| 1 用户 CRUD+L-2+M-8 | 6fe8c54 | 969 passed / 2 skipped |
| 2 硬删除级联 | a1d4014 | 974 passed / 2 skipped |
| 3 model-config GET/PUT | 9a1bac1 | 983 passed / 2 skipped |
| 4 model-config/test | 2a27026 | 986 passed / 2 skipped |
| 5 logs | 7b56a4e | 990 passed / 2 skipped |
| 6 overview | c9c1ff8 | 993 passed / 2 skipped |
| 7 删除 ping | 53a34a8 | 994 passed / 2 skipped |
| 8 前端基建 | a225b32 | vitest 8 / vue-tsc 0 / build 通过 |
| 9 用户管理页 | b25a8aa | 同上 |
| 10 模型配置页 | 6c82a99 | 同上 |
| 11 日志/仪表盘/统计页 | 1c2daa5 | 同上 |
| 12 习题管理页 | 01b8aa4 | 同上 |
| 13 README/favicon | e5511d9 | 同上（favicon 已确认拷入 dist） |
| 14a spec 回写+热生效用例修复 | 07f6caa | 994 passed / 2 skipped |

- 最终全量：**994 passed / 2 skipped**（2 条 skip 为语料条件，与本批无关）。
- `make lint` 全程保持 **35 errors 存量不变**（新文件零告警；main.py 随 ping 删除由 2→1，净减）。
- 2 条 skip 说明：`test_retrieval_quality_realistic.py` 语料条件（同总指挥基线）。
- H-1 纪律：后端 pytest 全程单跑；vite build 串行单构建 28–32s 无 OOM（§8 更正后口径），仅一次并发双构建 OOM 的教训已记录。

## 3. 变异测试实拆（§6 指引 V1–V7，全部「改坏→目标用例失败→字节级还原→git status 干净」）

| # | 变异 | 目标用例 | 结果 |
|---|---|---|---|
| V1 | 级联里连带删除 AuditLog | 硬删除级联+审计保留用例 | 失败 ✓（还原） |
| V2 | `admin_user_delete` detail 去掉级联计数 | 同用例（计数断言） | 失败 ✓（还原） |
| V3 | `update_llm_config` 去掉 `revision += 1` | 热生效端到端用例 | **首次变异未生效（perl 模式全/半角括号不匹配）；修正后失败 ✓**；期间发现并修复用例真实缺口（见下） |
| V4 | PATCH setattr 跳过 status | 停用 4030 用例 | 失败 ✓（还原） |
| V5 | `list_logs` 去掉 action where | 日志 action 筛选用例 | 失败 ✓（还原） |
| V6 | `mask_api_key` 禁用短密钥分支 | L-2 掩码用例 | 失败 ✓（还原） |
| V7 | code_runs 删除条件改为不匹配 | 级联用例（code_runs 计数归零） | 失败 ✓（还原） |

**变异 V3 揭示的真实测试缺口（已修复，随 07f6caa 提交）**：
`test_put_hot_reload_takes_effect_without_restart` 原实现以 `reset_runtime()` 起手，
把进程级 `_llm_revision` 置为 None —— 于是「PUT 未 bump revision」的变异下，
`refresh_llm_config` 因 `None != revision` 仍返回 True 并重绑，变异被静默掩盖（1 passed）。
修复：PUT 前先做一次基线 `refresh_llm_config` 固定 `_llm_revision`，再 PUT、再刷新，
断言 `changed is True` —— 变异下第二次刷新 `_llm_revision(旧)==revision(不变)` 返回 False，
用例如期失败。修复后用例在正常实现下通过（全量 994/2 复跑确认）。

> 注：V1/V7 说明 —— 无 FK 下七表删除彼此独立，「顺序」只有配合漏删才可观测，故以
> 漏删/连带删作变异体（裁定 V7 附带要求）；真顺序断言不做（裁定采纳）。

## 4. 真服务冒烟（uvicorn 单 worker + 临时库 `/tmp/p6_smoke.db`，HTTP 黑盒）

全部通过，脚本打印 `SMOKE_OK`：

| 项 | 验证点 | 结果 |
|---|---|---|
| 软删除停用 4030 | 建用户→停用→`GET /auth/me` → 4030 → 重启用恢复 | ✓ |
| 硬删除级联计数 | 造全七类数据→DELETE→`admin_user_delete` 审计 detail 计数 == 1/1/1/1/1/1/1 | ✓ |
| 审计保留 | 被删用户登录审计行在 `GET /admin/logs?user_id=` 仍可查 | ✓ |
| 配置热生效 | PUT model=smoke-model-1 → GET revision 自增（≥2）、model 更新 | ✓ |
| model-config/test | mock 配置 ok=true | ✓ |
| logs / overview / stats 真数据 | 各端点 code 0；overview `exercises.published == 40`（seed 幂等） | ✓ |
| /admin/ping 已删除 | GET → 4040 | ✓ |

冒烟后已停服务、删除临时库与脚本（工作区无残留）。

## 5. spec 回写（07f6caa）

- §6.2 新增「**admin 端点补记（P6，管理后台收口）**」：users 出参/校验/自操作禁令/末位守卫/
  KB.owner_id 例外、model-config GET/PUT 字段面与 api_key 语义、test 端点（只测首选级）、
  logs 筛选与出参、overview 最小集（标注「实际响应为超集」）、stats 口径、ping 移除说明。
- §8.9 新增「**P6 实记（2026-08-31）**」：级联单事务同步+计数审计、自删禁令+末位守卫、
  KB.owner_id 悬空例外、docstring 逐项列级联清单要求。
- 零新错误码（未触碰 §9）。

## 6. 未验证项（如实列出）

- 真实 OpenAI 兼容提供方全链路（无 Key，同 P3 遗留 2）——test 端点在 mock 下验证 ok=true，
  坏 base_url 验证 ok=false；真 Key 行为未验。
- 浏览器视觉项（对比度、断点溢出）与前端路由守卫的交互行为（本批未引入新 vitest；
  spec §10 前端只保证类型检查与构建，已达成）。
- 并发双构建 OOM 的本机复现（不再复现——串行纪律下无此场景）。

## 7. 提交清单（16 次，均未触碰 main）

见 §2 表 + `docs`（6669d9f/c14ba63）。分支 `feat/p6-admin-console` @ 07f6caa，工作树 clean。
**merge 未执行** —— 按指令停下等总指挥审阅。

## 8. 遗留与建议（不属本批范围，按裁定归清理批次）

- lint 35 存量（M-1）、M-3 response_model 横切、M-4 .env.example 死配置、M-5「未命名草稿」改口、
  H-3 分层违规重构、混合检索 —— 均按 P6 后清理批次处理，本批未动。
- 热生效用例的修复已随本批入库；若后续再改 `reset_runtime` 语义，注意该用例的基线绑定前置。
