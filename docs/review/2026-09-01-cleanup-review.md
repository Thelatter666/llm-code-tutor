# 清理批次审阅与裁定（第三任总指挥）

- 审阅日期：2026-09-01
- 审阅对象：`feat/cleanup-batch`（计划 37d4968 → 完成报告 7dedab3）
- 审阅依据：清理批次执行提示词六项范围 + 阶段一裁定 R1–R6/A1–A6 + 健康检查 M-1/M-3/M-4/M-5/H-3/漂移清单
- 审阅方式：全部独立复跑与实拆，不采信 agent 自证；变异测试「改坏 → 目标用例必须失败 → 字节级还原 → `git status` 干净」
- **结论：验收通过，可进入合并。六项全部落地，未发现存活变异或测试缺口。**

---

## 1. 独立复跑结果

| 门槛 | 报告声称 | 本任独立实测 | 判定 |
|---|---|---|---|
| 后端 pytest | 1006 passed / 2 skipped（202.19s） | **1006 passed / 2 skipped（205.82s）** | ✅ |
| 收集数 | — | **1008 collected**（= 1006 + 2） | ✅ |
| 2 条 skip | 语料条件 | `test_retrieval_quality_realistic.py:286/308`，与前各批相同 | ✅ |
| make lint | 0 errors | **All checks passed** | ✅ 清零 |
| 前端 vitest / vue-tsc / build | 8 / 0 / 37.22s | **8 passed / exit 0 / 29.41s** | ✅ |
| 新增锁用例文件 | 3 个 | `test_architecture.py` / `test_terminology.py` / `test_openapi_envelope.py` 均在 | ✅ |
| H-3 红线 | grep=0 | `grep -rn "infrastructure.adapters" app/services/` **0 处** | ✅ |
| M-4 | 死配置删除 | `Settings.llm_provider` 零残留（仅存 registry 的 `LLM_PROVIDER_*` provider 名常量，属另一概念） | ✅ |
| M-5 | 草稿改口 | app/frontend 源码零「草稿」（唯一残留为 models.py:212 禁词说明 docstring，属计划边界，正确保留） | ✅ |

## 2. 变异测试逐条实拆（C1–C5 六组，全部独立重做）

| # | 变异 | 实拆位置 | 击杀用例（本任实测） | 判定 |
|---|---|---|---|---|
| C1 | indexing 回退直连 parse_document | `indexing_service.py` `_run` | `test_architecture.py::test_services_never_import_adapters`（结构锁）+ `test_indexing_service.py::test_parse_goes_through_injected_document_parser`（功能锁，**2 failed**） | ✅ 双重击杀，与报告一致 |
| C2a | registry 哨兵常量错值 | `registry.py` `HASHING_EMBED_MODEL` | `test_registry.py::test_default_embedding_model_maps_each_provider`（**1 failed**） | ✅ |
| C2b | 服务层恢复适配器直引 | `model_config_service.py` | `test_architecture.py`（AST 精确报出 `model_config_service.py -> ...hashing_embed`，**1 failed**） | ✅ |
| C3 | 拆 409 门 | `model_config_service.py:62` | `test_switching_with_existing_chunks_returns_409` + `test_unconfirmed_switch_does_not_persist`（**2 failed，其余 20 条仍绿**——击杀精确非连坐） | ✅ B1 红线独立证实 |
| C4 | 默认标题改回「未命名草稿」 | `models.py:222` | `test_terminology.py::test_default_title_is_named_conversation`（三层一致性锁，**1 failed**） | ✅ |
| C5 | 撤 /auth/me 信封 | `auth.py:61` | `test_openapi_envelope.py::test_all_json_endpoints_declare_envelope`（**1 failed**） | ✅ |

六组全部击杀，全部字节级还原，结束时 `git status` clean。**本批未发现存活变异**（对比 P6 的 S1 缺口——本批锁用例设计质量到位，执行 agent 的「先验证改坏」纪律落实）。

> 纪律复核：本任 C2b 首次施变时曾留出语法错误写法（import 括号内嵌 import），已自行改为合法变异后击杀——与 P6 V6、执行 agent 报告的教训同源，处置正确。

## 3. 真服务冒烟（本任独立复跑，28/28 通过）

独立临时库 + 临时 Chroma/uploads + `uvicorn --workers 1`，全程 HTTP 黑盒：

- **信封完整性**：6 个端点（含 401 错误路径、/health 无前缀路径）顶层键严等 `{code, message, data, request_id}`——M-3 未引入字段过滤，嵌套超集（facets / limit_detail / judge_detail）实测存活
- **/code/analyze** 形状 + 二次同源 `reused=true`；**/code/run** accepted + `limit_detail` 六层结构
- **model-config** GET 掩码 / PUT revision 自增 / test ok=true
- **M-5 新词**：`PATCH /code/sessions/nope` → 4040「代码会话不存在」
- **习题/错题链**：facets 超集 → 判分 → 错题本 → recommendations `filled_by` 标注——防横切回归
- **hint SSE / chat SSE** 均未被 M-3 破坏（token 流 + done 载荷完整）——SSE 豁免决策正确
- **H-3 全链路（核心）**：建库 → 上传 → **索引 ready（端口注入后的真实解析链路，真实 MiniLM 缓存加载）** → `PUT /admin/model-config/embedding` 不带 confirm → **4090 + need_rebuild/knowledge_base_ids** → confirm=true → **rebuilt 含本库** → 检索 **`degraded=true + fallback_reason=hashing_embed_no_semantics + rag_hit=false`**（哨兵降级可见）——409 门与重建语义在重构后零变化

## 4. 裁定分级

- **阻塞**：无
- **高危**：无
- **中低**：无——本批未发现产品缺陷、测试缺口或报告失实（对比 P5 M-5R、P6 P6-GAP 的历轮发现）。六项交付全部经得起独立复现。

## 5. 附加要求 A1–A6 落实核对

| 要求 | 落实 |
|---|---|
| A1 openapi 只增量化 | 报告 +194/−58，删除行全为占位符→$ref 替换 + SSE 媒体类型描述修正；本任以 openapi 信封锁用例 + 真实响应体抽查交叉印证 |
| A2 UP046 PEP 695 fallback | 报告已先行最小用例验证 pydantic 2.13.5 运行时求值正常，未启用 noqa fallback |
| A3 收尾干净串行全量 | 1006/2 实测达成（本任复跑 205.82s 亦为串行单跑） |
| A4 「草稿不存在」前置 grep | 报告称全仓仅一处抛出点；本任独立查证 `代码会话不存在` 在 code_service.py:246，`草稿不存在` 零残留 |
| A5 MultiFormatDocumentParser 行为等价 | 报告含成功/ValueError/FileNotFoundError 三路径对比用例；本任冒烟以真实索引链路间接验证 |
| A6 C3 双用例击杀 | 本任实测 2 failed + 20 绿，精确击杀达成 |

## 6. spec / CONTEXT 漂移收口核对

- 漂移 3：spec §4.1 端口表「清理批次补记（2026-09-01）」——CodeParser 有意偏离 + DocumentParser 接缝定稿，已落档 ✅
- 漂移 4：P3/P4 五条契约逐条核验已在 spec（本任独立抽查 §8.3 stdin 重定向/8KB 截断/200 语义/limit_detail 结构与 §5 source_hash 等均在），无补文 ✅
- 漂移 5：随 M-4 消解（spec 正文从未引用 `LLM_PROVIDER` env，grep 零命中）✅
- CONTEXT.md 修订记录登记 M-4/M-5/H-3/漂移 3 全部动作 ✅

## 7. 遗留移交（README+收尾批次，确认非本批范围）

README 统一撰写（含默认密码警示已随 P6 落库部分的核对）、答辩口径、混合检索、真实 LLM Key 全链路、L-2 掩码的 README 说明。

## 8. 审阅处置记录

本任审阅执行 6 组变异（C1/C2a/C2b/C3/C4/C5）全部击杀并字节级还原；真服务冒烟 28/28；临时文件已清理；审阅结束时工作区 clean。未修改任何仓库文件。

**结论：清理批次验收通过，可进入合并。等待用户下达合并令。**
