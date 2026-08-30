# P2 AI 答疑对话 + 防抄袭（含 P1 遗留前端）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可端到端演示的 AI 答疑对话 —— SSE 流式生成（`citation → token… → done` 事件契约）、RAG 增强装配、防抄袭三档与不可覆盖底线、意图豁免、历史截断、per-request 中断、拦截率度量；并一并补齐 P1 遗留的前端（答疑对话页、知识库检索演示页、知识库管理页、`degraded` 提示条）。

**Architecture:** 沿用 P0/P1 的模块化单体与 `routers → services → domain → infrastructure` 分层。`LLMPort` / `Embedder` / `VectorStore` 以 `Protocol` 端口定义，服务层只依赖端口。领域层（`domain/chat/`）承载请求意图、防抄袭档位与底线、历史截断规则，零 IO。新增三个进程级组件：

- `LLMRuntime` —— LLM 侧的降级链（M10 / spec §9「LLM 调用失败 → 降级到下一 Provider，全部失败 5021」），与 P1 的 `EmbedderRuntime` 同构；
- `CancellationRegistry` —— per-`(conversation_id, request_id)` 的 `asyncio.Event` 内存表，依赖单 worker（ADR-0002）；
- `PromptAssembler` —— 组合防抄袭策略、RAG 上下文与 Jinja2 模板（CONTEXT.md「提示词装配器」）。

提示词落 `app/prompts/*.j2`：四套主模板（`rag_qa` / `code_review` / `exercise_hint` / `mistake_review`）+ `_anti_plagiarism.j2`（三档）+ `_floor.j2`（不可覆盖底线）。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) + aiosqlite · Pydantic v2 · Jinja2 · SSE(`StreamingResponse`) · pytest + pytest-asyncio · Vue 3 · Vite · TypeScript · Element Plus · Pinia · Vue Router · Axios · `fetch` + `ReadableStream`（SSE 客户端）

## Global Constraints

以下约束逐字摘自 spec / ADR / AGENT.md，每个任务默认包含，不再重复说明。

- 单进程单 worker：`uvicorn --workers 1`（ADR-0002）；所有同步阻塞调用经 `run_in_threadpool` 卸载
- 不做数据库迁移，建表用 `create_all`（ADR-0006）
- 统一响应体 `{code, message, data, request_id}`；**所有端点注入 `CurrentRidDep`**，禁止硬编码 `request_id=""`（H3）
- 领域层（`backend/app/domain/`）禁止 import 任何基础设施模块，业务规则零 IO 可单测
- 服务层只依赖 `Protocol` 端口，不依赖具体 adapter（ADR-0001）
- 所有 datetime 列用 `app.infrastructure.persistence.db.UTCDateTime`，不用裸 `DateTime`
- `ModelConfig` 单例一律走 `get_or_create_singleton()`，不得自己 insert（H2）
- 术语以 `CONTEXT.md` 为唯一来源（请求意图 / 求答案 / 评改已写代码 / 判分 / 豁免 / 防抄袭档位 / 防抄袭底线 / 底线拦截 / 拦截率 / 引用 / 检索命中 / 估算用量 / 文本增量 / 用量）
- 不配置 CORS（dev / serve 均同源，M9 已结论）
- 禁止任何涉及远端的操作（`git push` / `git remote add`）
- 每个任务完成后跑全量测试（`cd backend && . .venv/bin/activate && python -m pytest -q`），**P0+P1 基线 317 passed / 2 skipped**
- 前端：`npx vue-tsc --noEmit` 必须零错误；路由组件必须懒加载；`frontend/docs/ui-baseline.md` 是强制约束

### Commit 策略

用户已于 **2026-08-30 预先授权**（`AGENT.md`「授权例外」表）：本计划每个 Task 完成且全量测试通过后，**可直接按 Task 粒度 `git commit`**，无需逐次请示。**`git merge` 与 `git push` 不在授权范围内**，仍需用户单独下令。

### 本版承接的前两批遗留项

依据 `docs/review/2026-08-30-p1-completion-report.md` §8.3 与 `docs/review/2026-08-30-p1-review.md`：

| 编号 | 问题 | 处理位置 |
|---|---|---|
| M4 | 端口契约测试只断言了 `name` 与可调用，名不副实 | Task 3 |
| M10 | spec §9 要求 LLM 降级链，`ProviderRegistry` 是单槽无 fallback | Task 4 |
| 8.2 裁定 | P1 遗留的前端合并到 P2，不另起批次 | Task 10 |
| M6 | bcrypt 走线程池 —— P0 Task 10 已实现 | Task 11 复核未被回退，**不重复做** |

M2（`backend/seeds/`，P5）、M3（`response_model=ApiResponse[T]`，P6）、L2（功能点语义重叠口径）不在本批次范围。

### 本批次的六条已拍板决策（不再讨论，直接执行）

1. **豁免是显式契约，不是推断** —— 聊天入口一律固定 `intent=seek_answer`，绝不按「消息是否含代码块」推断（ADR-0005）。
2. **底线硬编码进模板**，三档共用，后台配置改不掉：代做作业式请求转引导 / 考试竞赛在线作答拒绝给答案 / 输出的代码必须配讲解。
3. **中断用 per-call `asyncio.Event`**，绝不做成 provider 的实例方法（注册表缓存单实例，实例级 cancel 会掐断所有进行中的流，P0 已有并发回归用例守护）。
4. `token_usage` 必须来自流末的 `Usage` 元素；Mock 无真实计数，按 `len(content)//4` 估算并置 `usage_estimated=true`（估算用量 EstimatedUsage）。
5. 零命中或被截断光时：`rag_hit=false` + `degraded=true` + `fallback_reason=no_relevant_chunk`。
6. 单进程单 worker；建表用 `create_all`；datetime 用 `UTCDateTime`；端点一律 `CurrentRidDep`；不配置 CORS。

---

## File Structure

```
backend/
├── app/
│   ├── domain/chat/
│   │   ├── __init__.py
│   │   ├── policy.py            请求意图 / 防抄袭档位 / 底线规则 / 审计动作常量
│   │   └── history.py           历史截断（4000 token / 10 轮）
│   ├── infrastructure/
│   │   ├── cancellation.py      中断注册表（per-(conversation_id, request_id) Event）
│   │   ├── llm_runtime.py       LLM 降级链（M10）
│   │   ├── prompt_assembler.py  PromptAssembler（Jinja2）
│   │   ├── sse.py               SSE 事件名 / 序列化 / 中断错误码
│   │   ├── registry.py          追加 build_llm / LLMConfig / make_llm_factory
│   │   ├── runtime.py           追加 get_llm_runtime / refresh_llm_config
│   │   └── persistence/models.py 追加 Conversation / Message
│   ├── prompts/
│   │   ├── rag_qa.j2 · code_review.j2 · exercise_hint.j2 · mistake_review.j2
│   │   ├── _anti_plagiarism.j2  · _floor.j2 · _citations.j2
│   ├── services/
│   │   ├── chat_service.py      流式答疑用例编排
│   │   └── anti_plagiarism_stats.py  拦截率度量
│   ├── routers/
│   │   └── chat.py              会话 CRUD + SSE + stop
│   └── schemas/chat.py
└── tests/
    ├── test_chat_models.py · test_chat_policy.py · test_prompt_assembler.py
    ├── test_history_truncation.py · test_cancellation.py
    ├── test_llm_contract.py（M4 重写）· test_llm_runtime.py
    ├── test_chat_service.py · test_chat_api.py · test_anti_plagiarism_stats.py

frontend/src/
├── api/{chat,knowledge}.ts
├── types/{chat,knowledge}.ts
├── composables/useSse.ts
├── components/
│   ├── AppShell.vue · DegradedBanner.vue · CitationList.vue
├── views/
│   ├── student/{ChatView,KnowledgeSearchView}.vue
│   └── admin/KnowledgeAdminView.vue
└── router/index.ts（改造：嵌套路由 + 角色守卫 + 懒加载）
```

---

## Task 1: Conversation / Message 两表与防抄袭领域规则

**Files:**
- Create: `backend/app/domain/chat/__init__.py`
- Create: `backend/app/domain/chat/policy.py`
- Modify: `backend/app/infrastructure/persistence/models.py`
- Create: `backend/tests/test_chat_models.py`
- Create: `backend/tests/test_chat_policy.py`

**Interfaces:**
- Consumes: `Base`、`UTCDateTime`（P0）
- Produces: `Conversation` / `Message` 两表（spec §5）；`SEEK_ANSWER` / `REVIEW_MY_CODE` / `JUDGING`、`MODE_STRICT/GUIDED/LOOSE`、`is_exempt()`、`detect_floor_violation()`、`ACTION_CHAT`

> **spec §5**：`Message` 需含 `citations` / `token_usage` / `model` / `provider` / `truncated` / `anti_plagiarism_mode` / `blocked_by_policy`。
> **ADR-0005**：豁免只认显式入口。`is_exempt()` 是纯函数，服务层按入口传入的 `intent` 调用它，绝不从消息内容推断。
> **spec §7.1**：三档 + 三档共有底线；底线判定服务于 §7.4 的「拦截率」度量 —— CONTEXT.md 明确「拦截率是度量口径，不是检测能力」，故用确定性关键词规则，不引入 LLM 分类。

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_chat_models.py
import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import Conversation, Message


@pytest.mark.asyncio
async def test_both_tables_are_created(engine):
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    assert {"conversations", "messages"} <= {r[0] for r in rows}


@pytest.mark.asyncio
async def test_message_carries_every_field_required_by_spec(session):
    """spec §5 Message：citations / token_usage / model / provider / truncated / 档位 / 底线拦截。"""
    conv = Conversation(user_id="u1", title="闭包答疑")
    session.add(conv)
    await session.flush()
    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content="回答",
        citations=[{"chunk_id": "c1", "number": 1}],
        token_usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "estimated": True},
        model="mock-1",
        provider="mock",
        truncated=False,
        anti_plagiarism_mode="guided",
        blocked_by_policy=False,
    )
    session.add(msg)
    await session.commit()

    got = (await session.execute(select(Message))).scalar_one()
    assert got.citations[0]["chunk_id"] == "c1"
    assert got.token_usage["estimated"] is True
    assert got.provider == "mock"
    assert got.truncated is False
    assert got.anti_plagiarism_mode == "guided"
    assert got.blocked_by_policy is False


@pytest.mark.asyncio
async def test_timestamps_are_timezone_aware_utc(session):
    conv = Conversation(user_id="u1", title="t")
    session.add(conv)
    await session.commit()
    got = (await session.execute(select(Conversation))).scalar_one()
    assert got.created_at.tzinfo is not None
    assert got.updated_at.tzinfo is not None
```

```python
# backend/tests/test_chat_policy.py
import pytest

from app.domain.chat.policy import (
    JUDGING,
    REVIEW_MY_CODE,
    SEEK_ANSWER,
    MODE_GUIDED,
    MODE_LOOSE,
    MODE_STRICT,
    detect_floor_violation,
    is_exempt,
)


def test_seek_answer_is_never_exempt():
    """ADR-0005：求答案受档位约束，这是防抄袭的主战场。"""
    assert is_exempt(SEEK_ANSWER) is False


@pytest.mark.parametrize("intent", [REVIEW_MY_CODE, JUDGING])
def test_review_and_judging_are_exempt(intent):
    """spec §7.1 豁免表：学生已写出代码 / 不向学生输出实现。"""
    assert is_exempt(intent) is True


def test_three_modes_are_declared():
    assert (MODE_STRICT, MODE_GUIDED, MODE_LOOSE) == ("strict", "guided", "loose")


def test_homework_ghostwriting_hits_the_floor():
    assert detect_floor_violation("直接帮我把这份作业的代码写出来") is not None


def test_exam_in_progress_hits_the_floor():
    assert detect_floor_violation("我正在考试，快把这道题的答案发我") is not None


def test_normal_question_does_not_hit_the_floor():
    assert detect_floor_violation("闭包是什么？能给个例子吗") is None


def test_floor_detection_does_not_depend_on_code_blocks():
    """ADR-0005 的正面：贴了示例代码的求答案请求仍按求答案处理，不被误判为批改。"""
    text = "这道题怎么做？题目给了示例：\n```python\ndef f(x):\n    return x\n```"
    assert detect_floor_violation(text) is None
```

- [ ] **Step 2: Run tests to verify they fail**
Run: `cd backend && python -m pytest tests/test_chat_models.py tests/test_chat_policy.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.chat'`

- [ ] **Step 3: Write domain policy**

```python
# backend/app/domain/chat/policy.py
"""答疑对话的领域规则：请求意图、防抄袭档位、不可覆盖底线（零 IO）。"""

# --- 请求意图（CONTEXT.md「请求意图」） ---
SEEK_ANSWER = "seek_answer"
REVIEW_MY_CODE = "review_my_code"
JUDGING = "judging"
REQUEST_INTENTS = (SEEK_ANSWER, REVIEW_MY_CODE, JUDGING)

# spec §7.1 豁免表
EXEMPT_INTENTS = (REVIEW_MY_CODE, JUDGING)

# --- 防抄袭档位（CONTEXT.md「防抄袭档位」） ---
MODE_STRICT = "strict"
MODE_GUIDED = "guided"
MODE_LOOSE = "loose"
ANTI_PLAGIARISM_MODES = (MODE_STRICT, MODE_GUIDED, MODE_LOOSE)
DEFAULT_MODE = MODE_GUIDED

# --- 审计动作（spec §8.1） ---
ACTION_CHAT = "chat"


def is_exempt(intent: str) -> bool:
    """ADR-0005：豁免只认显式入口。

    意图由调用方（端点）显式传入，本函数不做任何内容推断。
    """
    return intent in EXEMPT_INTENTS


def resolve_mode(intent: str, configured: str | None) -> str:
    """豁免意图返回 None 语义上的「不加档位约束」由调用方处理。"""
    ...


# --- 防抄袭底线（spec §7.1，硬编码，后台配置无法绕过） ---
FLOOR_HOMEWORK = "homework_ghostwriting"
FLOOR_EXAM = "exam_in_progress"

_HOMEWORK_MARKERS = ("作业", "代做", "帮我写完整", "直接给我", "直接给答案", "完整可运行")
_EXAM_MARKERS = ("考试", "竞赛", "机考", "在线作答")


def detect_floor_violation(content: str) -> str | None:
    """返回命中的底线规则名，未命中返回 None。

    CONTEXT.md：拦截率是**度量口径**，不是检测能力。故用确定性关键词规则 ——
    引入 LLM 分类会让「是否触发底线」本身变成不可复现的行为。
    """
```

- [ ] **Step 4: Write models**（追加到 `models.py`）

```python
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default="新的对话")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, onupdate=_now, index=True
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)           # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    # spec §7.2 步骤 6：命中的 chunk_id 写入 citations，前端点击可溯源
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 流末 Usage；estimated=true 表示 Mock 估算（估算用量 EstimatedUsage）
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    # 流被中断：已生成内容仍落库并置 truncated=true（spec §8.1）
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_plagiarism_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    blocked_by_policy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
```

- [ ] **Step 5: Run tests to verify they pass**

- [ ] **Step 6: Run full suite** → Expected: 317 + N passed

- [ ] **Step 7: Commit**
```bash
git add backend/app/domain/chat backend/app/infrastructure/persistence/models.py backend/tests/test_chat_models.py backend/tests/test_chat_policy.py
git commit -m "feat(backend): Conversation/Message 两表与防抄袭领域规则（spec §5 §7.1）"
```

---

## Task 2: 提示词模板与 PromptAssembler

**Files:**
- Create: `backend/app/prompts/rag_qa.j2` `code_review.j2` `exercise_hint.j2` `mistake_review.j2`
- Create: `backend/app/prompts/_anti_plagiarism.j2` `_floor.j2` `_citations.j2`
- Create: `backend/app/infrastructure/prompt_assembler.py`
- Create: `backend/tests/test_prompt_assembler.py`

**Interfaces:**
- Consumes: `domain/chat/policy.py`（Task 1）、`ChatMessage`（P0）
- Produces: `PromptAssembler.assemble(...) -> list[ChatMessage]`。Task 7 使用。

> **spec §7**：四套主模板 + 一个 `PromptAssembler`。
> **底线硬编码进模板，不开放配置**（spec §3.2 权衡 10）—— `_floor.j2` 由所有模板无条件 include，代码里不存在任何「跳过底线」的开关。
> **spec §7.2 步骤 5**：片段编号 `[1][2][3]` 注入 prompt，要求模型内联引用编号。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_prompt_assembler.py
import pytest

from app.domain.chat.policy import JUDGING, REVIEW_MY_CODE, SEEK_ANSWER
from app.infrastructure.prompt_assembler import PromptAssembler

FLOOR_LINES = (
    "代做作业式请求一律转为引导",
    "考试 / 竞赛在线作答场景拒绝直接给答案",
    "输出中的任何代码必须配讲解",
)


@pytest.fixture
def asm():
    return PromptAssembler()


@pytest.mark.parametrize("mode", ["strict", "guided", "loose"])
def test_every_mode_keeps_all_three_floor_rules(asm, mode):
    """spec §7.1：三档共有的底线不可覆盖 —— 后台配置改不掉。"""
    system = asm.assemble("rag_qa", question="怎么排序", mode=mode, intent=SEEK_ANSWER)[0]
    for line in FLOOR_LINES:
        assert line in system.content


def test_strict_forbids_complete_code(asm):
    system = asm.assemble("rag_qa", question="写个快排", mode="strict", intent=SEEK_ANSWER)[0]
    assert "禁止输出完整可运行代码" in system.content


def test_guided_allows_short_snippet_only(asm):
    system = asm.assemble("rag_qa", question="写个快排", mode="guided", intent=SEEK_ANSWER)[0]
    assert "10 行" in system.content


def test_loose_requires_walkthrough_and_self_attempt(asm):
    system = asm.assemble("rag_qa", question="写个快排", mode="loose", intent=SEEK_ANSWER)[0]
    assert "请先自行尝试" in system.content


@pytest.mark.parametrize("intent", [REVIEW_MY_CODE, JUDGING])
def test_exempt_intent_drops_mode_constraints_but_keeps_floor(asm, intent):
    """ADR-0005：豁免免的是档位约束，不是底线。"""
    system = asm.assemble("code_review", question="帮我看看", mode="strict", intent=intent)[0]
    assert "禁止输出完整可运行代码" not in system.content
    assert "输出中的任何代码必须配讲解" in system.content


def test_citations_are_numbered_and_injected(asm):
    cits = [{"number": 1, "doc_title": "第1讲", "snippet": "排序有三大类"},
            {"number": 2, "doc_title": "第2讲", "snippet": "快排是分治"}]
    user = asm.assemble("rag_qa", question="怎么排序", mode="guided",
                        intent=SEEK_ANSWER, citations=cits)[-1]
    assert "[1]" in user.content and "[2]" in user.content
    assert "排序有三大类" in user.content


def test_question_and_history_are_appended_in_order(asm):
    history = [{"role": "user", "content": "上一问"}, {"role": "assistant", "content": "上一答"}]
    msgs = asm.assemble("rag_qa", question="这一问", mode="guided",
                        intent=SEEK_ANSWER, history=history)
    assert [m.content for m in msgs[1:]] == ["上一问", "上一答", "这一问"]


def test_four_templates_are_all_available(asm):
    for name in ("rag_qa", "code_review", "exercise_hint", "mistake_review"):
        assert asm.assemble(name, question="q", mode="guided", intent=SEEK_ANSWER)


def test_floor_hit_strengthens_the_prompt(asm):
    msgs = asm.assemble("rag_qa", question="帮我写作业", mode="loose",
                        intent=SEEK_ANSWER, floor_hit="homework_ghostwriting")
    assert "homework_ghostwriting" in msgs[0].content
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write templates**（`app/prompts/`）

```jinja
{# _floor.j2 —— spec §7.1 三档共有的不可覆盖底线，硬编码，后台配置无法绕过 #}
【防抄袭底线（以下三条在任何档位下均不可覆盖）】
1. 代做作业式请求一律转为引导。
2. 考试 / 竞赛在线作答场景拒绝直接给答案。
3. 输出中的任何代码必须配讲解。
{% if floor_hit %}
【本次请求已触发底线：{{ floor_hit }}】你必须按上述底线执行，不得给出可直接提交的实现。
{% endif %}
```

```jinja
{# _anti_plagiarism.j2 #}
{% if exempt %}
【本次为「评改已写代码 / 判分」请求，豁免防抄袭档位约束】（ADR-0005）
{% else %}
【防抄袭档位：{{ mode }}】
{% if mode == "strict" %}
禁止输出完整可运行代码；只给思路拆解、关键概念、伪代码骨架（函数签名 + 注释占位）；
学生追问时继续细化思路，不补代码。
{% elif mode == "guided" %}
允许 ≤10 行的最小片段解释单个概念；禁止给出完整实现；必须先讲思路再给片段。
{% elif mode == "loose" %}
允许给出完整实现，但必须先提醒「请先自行尝试」，并附逐段讲解。
{% endif %}
{% endif %}
```

- [ ] **Step 4: Write PromptAssembler**

```python
# backend/app/infrastructure/prompt_assembler.py
"""提示词装配器（CONTEXT.md「提示词装配器 PromptAssembler」）。

组合防抄袭策略、RAG 上下文与模板，产出最终 prompt。
模板目录即装配规则：**底线在模板里无条件 include**，代码侧不存在跳过底线的开关
（spec §3.2 权衡 10）。
"""

class PromptAssembler:
    TEMPLATES = ("rag_qa", "code_review", "exercise_hint", "mistake_review")

    def assemble(self, template, *, question, mode, intent,
                 citations=(), history=(), floor_hit=None) -> list[ChatMessage]:
        ...
```

- [ ] **Step 5: Run test to verify it passes**
- [ ] **Step 6: full suite → Commit**

---

## Task 3: M4 端口契约测试补全

**Files:**
- Rewrite: `backend/tests/test_llm_contract.py`

> **M4**：现有文件里唯一的「契约测试」只断言了 `name` 是字符串、`stream` / `complete` 可调用 —— 名不副实。改为：**两个 provider 跑同一组断言**，确保同签名同语义。

- [ ] **Step 1: Write the failing contract suite**

同一组断言用 `@pytest.mark.parametrize` 对两个 provider 各跑一遍：

| 断言 | 锁住什么 |
|---|---|
| `stream()` 的最后一个元素是 `Usage` | B1：流末必须带用量，否则 `done` 拿不到 `token_usage` |
| `complete().text` 与 `stream()` 收集到的文本一致 | 两条路径语义必须相同 |
| 文本增量全部是 `TextDelta`，不含 `Usage` | 联合类型不得混用 |
| `cancel` 置位后不再产生 `TextDelta`，但仍产生 `Usage` | B2：中断后调用方仍要拿得到用量 |
| 空 messages 不抛异常 | 边界健壮性 |
| `cancel` 是 per-call 的：两个并发流共享同一实例，取消一个不影响另一个 | **B2 的并发回归**（P0 已埋，此处下沉为契约） |

`OpenAICompatProvider` 用 `httpx.MockTransport` 注入 SSE body；`MockLLMProvider` 直接实例化。

- [ ] **Step 2: Run → 确认失败**（改写后应暴露 Mock 与 OpenAICompat 的行为差异，补齐实现）
- [ ] **Step 3: 补齐实现差异**（如 Mock 的 `complete` 与 `stream` 一致性、空 messages 处理）
- [ ] **Step 4: full suite → Commit**

---

## Task 4: M10 LLM 降级链（LLMRuntime）

**Files:**
- Create: `backend/app/infrastructure/llm_runtime.py`
- Modify: `backend/app/infrastructure/registry.py`（追加 `LLMConfig` / `llm_config` / `build_llm` / `make_llm_factory`）
- Modify: `backend/app/infrastructure/runtime.py`（`get_llm_runtime` / `refresh_llm_config` / `set_llm_runtime`）
- Create: `backend/tests/test_llm_runtime.py`

**Interfaces:**
- Consumes: `LLMPort`（P0）、`ModelConfig`、`get_or_create_singleton`（P0）
- Produces: `LLMRuntime`：`stream()` / `complete()` / `degraded` / `fallback_reason` / `snapshot()`

> **M10 / spec §9**：LLM 调用失败 / 超时 → 降级到下一 Provider；全部失败返回 `5021`。
> 与 P1 的 `EmbedderRuntime` 同构：0 = OpenAI 兼容（按 `ModelConfig`），1 = Mock。运行期失败即降级并记住级别。
> **`degraded` 的判定**：配置期望 `openai_compat` 但实际生效 `mock` 才算降级。无 API Key 时配置本就解析为 Mock（spec §9「无 API Key → 解析为 MockProvider」），**不算降级**，只是 Mock 模式。

- [ ] **Step 1: Write the failing tests**（`tests/test_llm_runtime.py`）

| 断言 | 锁住什么 |
|---|---|
| 首选可用 → `degraded=False`，provider 为首选 | 正常路径 |
| 首选抛出 → 落到 Mock，`degraded=True`，`fallback_reason="llm_fallback_to_mock"` | M10 降级 |
| 降级后记住级别，下一次不再重试首选 | 与 `EmbedderRuntime` 一致的降级记忆 |
| 全部失败 → `ApiError(5021)` | spec §9 |
| 无 API Key（首选即 Mock）→ `degraded=False` | spec §9「无 API Key → Mock 模式」不是降级 |
| 流中途失败不重试（已吐出的内容不能重复） | 降级只发生在拿到首个元素之前 |
| `snapshot()` 暴露 `provider` / `degraded` | 供 `/health` 与前端角标 |

- [ ] **Step 2–5**：实现；`registry.build_llm(cfg, level)`；`runtime.refresh_llm_config(session)` 按 `ModelConfig.revision` rebind（配置热生效，spec §4.2 硬约束 4）。
- [ ] **Step 6: full suite → Commit**

---

## Task 5: 中断注册表（per-call `asyncio.Event`）

**Files:**
- Create: `backend/app/infrastructure/cancellation.py`
- Create: `backend/tests/test_cancellation.py`

> **spec §8.1 / ADR-0002**：`asyncio.Event` 存于内存注册表，键为 `(conversation_id, request_id)`；`/stop` 端点与「同一会话发起新请求」两种情形均置位；流结束或异常时在 `finally` 中注销。**该内存注册表依赖单 worker**，必须在代码注释里写明。
> **B2（P0）**：绝不可做成 provider 的实例方法 —— 注册表缓存的是单实例，实例级 cancel 会让一个学生点「停止」掐断所有进行中的流。

- [ ] **Step 1: Write the failing tests**（`tests/test_cancellation.py`）

| 断言 | 锁住什么 |
|---|---|
| 同一 `(conv, rid)` 两次 `create` 返回同一个 Event | 注册表语义 |
| 不同 `rid` 的 Event 互不相同 | 键的维度 |
| `cancel(conv, rid)` 只置位目标 Event | **B2 并发回归**：另一条流不受影响 |
| 「同一会话发起新请求」会置位该会话的全部旧 Event | spec §8.1 |
| `discard` 后注册表不再持有该键 | 防止内存泄漏 |
| 生成器每次 yield 前检查 Event → 中断后不再产出 token | spec §8.1 |

- [ ] **Step 2–5**：实现 `CancellationRegistry`（`create` / `cancel` / `cancel_conversation` / `discard` / `size`）。
- [ ] **Step 6: full suite → Commit**

---

## Task 6: 历史截断（4000 token / 10 轮）

**Files:**
- Create: `backend/app/domain/chat/history.py`
- Create: `backend/tests/test_history_truncation.py`

> **spec §8.1**：按时间倒序累加最近轮次，累计 token 超过 **4000**，或轮数超过 **10 轮**（一问一答计一轮）即停止累加；截断后若首轮被丢弃，改为保留最后一轮以保证上下文连贯。**固定值，不开放配置。**
> token 估算口径与 Mock 的估算用量一致：`len(content) // 4`（CONTEXT.md「估算用量」）。不引入 tiktoken（spec §8.2 已论证中文 token 密度不可预测）。

- [ ] **Step 1: Write the failing tests**

| 断言 | 锁住什么 |
|---|---|
| 常量 `MAX_HISTORY_TOKENS == 4000`、`MAX_HISTORY_ROUNDS == 10` | spec 固定值 |
| 历史很短 → 全部保留 | 不误截 |
| 20 轮历史 → 只保留最近 10 轮 | 轮数上限 |
| 单轮极长（> 4000 token）→ 兜底保留最后一轮 | **「首轮被丢弃则保留最后一轮」** |
| 累计 token 超限即停，即使轮数未到 10 | token 上限 |
| 奇数条消息（孤立的 user）也能正确配对 | 边界 |
| 结果与原始时间顺序一致 | 不得倒置 |

- [ ] **Step 2–5**：实现 `truncate_history(messages) -> list[dict]`（纯函数，输入为 `{"role", "content"}` 字典列表，领域层不碰 ORM）。
- [ ] **Step 6: full suite → Commit**

---

## Task 7: ChatService（SSE 编排 + RAG + 落库 + 审计）

**Files:**
- Create: `backend/app/infrastructure/sse.py`
- Create: `backend/app/services/chat_service.py`
- Create: `backend/tests/test_chat_service.py`
- Modify: `backend/tests/fakes.py`（追加 `FakeLLM` / `ExplodingLLM`）

**Interfaces:**
- Consumes: `LLMRuntime`（Task 4）、`RetrievalService`（P1）、`PromptAssembler`（Task 2）、`CancellationRegistry`（Task 5）、`truncate_history`（Task 6）、`AuditService`（P0）
- Produces: `ChatService.stream_reply()` → `AsyncIterator[StreamEvent]`。Task 8 路由使用。

> **spec §8.1**：落 user message → 装配 RAG 并发 `citation` → 渲染 prompt → 流式转发，每 token 检查 cancel → 落 assistant message → 发 `done` → 写 `AuditLog(action=chat)`。
> **spec §6.1**：`citation` 先于 `token`；`done` 带 `message_id / token_usage / usage_estimated / model / provider / rag_hit / degraded / fallback_reason`。
> **审计必须在 `finally` 中写入**（无论正常结束还是异常中断）。

- [ ] **Step 1: Write the failing tests**

| 断言 | 锁住什么 |
|---|---|
| 事件顺序严格为 `citation* → token* → done` | spec §6.1 |
| `done` 载荷含全部 8 个字段 | spec §6.1 |
| `token_usage` 来自流末 `Usage`，Mock 下 `usage_estimated=True` | 拍板决策 4 |
| user / assistant 两条消息均落库，含 `anti_plagiarism_mode` / `blocked_by_policy` | spec §7.4 |
| 中断后 assistant 消息仍落库且 `truncated=True` | spec §8.1 |
| 中断后不再产出 token，且发 `error` 事件 | spec §8.1 |
| 正常结束与异常中断**都**写 `AuditLog(action=chat)` | spec §8.1 `finally` |
| 零命中 → `rag_hit=False` + `degraded=True` + `fallback_reason=no_relevant_chunk`，且不注入引用 | 拍板决策 5 |
| 命中 → `citation` 事件数与 citations 数一致，且先于首个 token | spec §6.1 |
| 哨兵 embedding → `fallback_reason=hashing_embed_no_semantics` | ADR-0004 |
| 聊天入口固定 `seek_answer`，即使消息含代码块也不豁免 | ADR-0005 |
| 触发底线 → `blocked_by_policy=True` | spec §7.4 |
| 会话不属于当前用户 → `4040` | 越权隔离 |

- [ ] **Step 2–5**：实现 `sse.py`（事件名常量、`CANCELLED_CODE=4990`、`format_sse()`）与 `ChatService`。
- [ ] **Step 6: full suite → Commit**

---

## Task 8: chat 路由（会话 CRUD + SSE + stop）

**Files:**
- Create: `backend/app/schemas/chat.py`
- Create: `backend/app/routers/chat.py`
- Modify: `backend/app/main.py`（注册路由 + lifespan 刷新 LLM 配置）
- Create: `backend/tests/test_chat_api.py`

> **spec §6.2 chat 行**：`POST /chat/conversations`、`GET /chat/conversations`、`GET /chat/conversations/{id}/messages`、`DELETE /chat/conversations/{id}`、`POST /chat/conversations/{id}/messages`（SSE）、`POST /chat/conversations/{id}/stop`。
> **`/stop` 的键是 `(conversation_id, request_id)`** —— 前端必须能拿到 `request_id`。P0 的 `install_request_id` 中间件已支持调用方自带 `x-request-id`（`request.headers.get("x-request-id") or uuid4()`），故前端生成 UUID 放在请求头，SSE 响应头与 `done` 之前的响应头都会回传，前端据此调用 `/stop`。

- [ ] **Step 1: Write the failing tests**（`httpx.AsyncClient` + 内存 SQLite，照 `test_knowledge_api.py` 的脚手架）

| 断言 | 锁住什么 |
|---|---|
| SSE 响应 `content-type: text/event-stream`，事件顺序正确 | spec §6.1 |
| 响应头 `x-request-id` 与自带 `x-request-id` 一致 | 中断键可回传 |
| `POST /stop {request_id}` → `{"cancelled": true}` | spec §6.2 |
| 会话 CRUD 全通；他人的会话返回 `4040` | 越权隔离 |
| 未鉴权 → `4010` | 鉴权 |
| 所有端点响应体 `request_id` 与响应头一致 | H3 |
| `/stop` 对不存在的 request_id 返回 `cancelled: false` | 幂等 |

- [ ] **Step 2–6**：实现路由、schema、main 注册；全量测试；commit。

---

## Task 9: 防抄袭效果度量

**Files:**
- Create: `backend/app/services/anti_plagiarism_stats.py`
- Modify: `backend/app/routers/chat.py`（或新建 `admin_stats.py`）
- Create: `backend/tests/test_anti_plagiarism_stats.py`

> **spec §7.4**：`Message` 落库时写入当次生效的 `anti_plagiarism_mode` 与 `blocked_by_policy`；`GET /admin/anti-plagiarism/stats` 返回各档位下的「触发底线次数 / 总请求数」。
> **CONTEXT.md**：拦截率是**度量口径，不是检测能力** —— 响应字段命名与文档措辞都必须体现这一点。

- [ ] **Step 1: Write the failing tests**

| 断言 | 锁住什么 |
|---|---|
| 三档全部返回，即使某档 total=0 | 前端表格不缺行 |
| `blocked / total / block_rate` 数值正确 | 度量口径 |
| `total=0` 时 `block_rate=0.0`，不除零 | 边界 |
| 只统计 `role=user` 的消息 | 一次请求只计一次 |
| 学生对端点请求 → `4030` | 角色拦截 |
| 端点注入 `CurrentRidDep` | H3 |

- [ ] **Step 2–6**：实现；full suite；commit。

---

## Task 10: 前端（骨架 + 三个页面 + degraded 提示条）

**Files:**
- Modify: `frontend/src/router/index.ts`（嵌套路由 + 角色守卫 + 懒加载）
- Modify: `frontend/src/views/HomeView.vue` → 改为 `AppShell` 容器
- Create: `frontend/src/components/{AppShell,DegradedBanner,CitationList}.vue`
- Create: `frontend/src/views/student/{ChatView,KnowledgeSearchView}.vue`
- Create: `frontend/src/views/admin/KnowledgeAdminView.vue`
- Create: `frontend/src/api/{chat,knowledge}.ts`、`frontend/src/types/{chat,knowledge}.ts`
- Create: `frontend/src/composables/useSse.ts`
- Modify: `frontend/src/styles/theme.css`（补齐基线未落地的变量）

> **8.2 裁定**：P1 遗留的知识库管理页、检索演示页、对话页、`degraded` 提示条全部并入 P2。
> **`frontend/docs/ui-baseline.md` 是强制约束，不是参考** —— 配色 / 字体 / 间距 / 圆角 / 组件密度 / 交付前检查清单逐条遵守。
> SSE 不能用 `EventSource`（无法带 `Authorization` 与 `x-request-id` 请求头），用 `fetch` + `ReadableStream` 手动解析 `event:` / `data:` 帧。
> 打字机效果：把到达的 token 入队，按固定间隔出队渲染；`prefers-reduced-motion` 下改为直接全量显示（基线 §5）。

- [ ] **Step 1: 类型与 API 层**
- [ ] **Step 2: `DegradedBanner`** —— 按 `fallback_reason` 区分三种文案：

| `fallback_reason` | 文案 |
|---|---|
| `hashing_embed_no_semantics` | 当前为无语义向量模式，已停用知识库增强 |
| `no_relevant_chunk` | 知识库无相关内容，以下为通用回答 |
| `llm_fallback_to_mock` | 模型服务不可用，已降级到 Mock 模式 |

- [ ] **Step 3: `CitationList`** —— 引用卡片，点击展开 `snippet` 溯源
- [ ] **Step 4: `ChatView`** —— 会话列表 + 消息流 + 输入框 + 中断按钮 + 打字机 + 引用展示
- [ ] **Step 5: `KnowledgeSearchView`** —— 检索演示（query / kb / top_k → 命中表 + 提示条）
- [ ] **Step 6: `KnowledgeAdminView`** —— 知识库 CRUD + 文档上传/删除 + `chunk_indexed / chunk_total` 进度轮询
- [ ] **Step 7: 路由与守卫** —— 组件全部懒加载；admin 路由校验 `auth.isAdmin`
- [ ] **Step 8: 类型检查与构建**：`npx vue-tsc --noEmit && npx vite build`
- [ ] **Step 9: Commit**

---

## Task 11: 端到端实测、M6 复核与完成报告

**Files:**
- Create: `docs/review/2026-08-30-p2-completion-report.md`

- [ ] **Step 1: 复核 M6**（bcrypt 走线程池）未被回退 —— 只确认，不重做
- [ ] **Step 2: 真服务实测**（`uvicorn app.main:app --workers 1 --port 8001`）：
  - SSE 事件序列真实抓包（`citation → token… → done` 的顺序与内容）
  - `/stop` 中断后的流行为
  - 三种防抄袭档位对同一求答案请求的实际输出对比
  - `GET /admin/anti-plagiarism/stats` 真实返回
  - 无 API Key（Mock）下 `usage_estimated=true`；知识库零命中的可见降级
- [ ] **Step 3: 前端实测**：类型检查、构建产物体积、路由懒加载、页面可交互
- [ ] **Step 4: 变异测试指引** —— 给出「拆掉某个修复后哪几条测试会失败」
- [ ] **Step 5: 写完成报告并 commit**

---

## 验收清单（P2 完成标准）

- [ ] `python -m pytest -q` 全绿，无 P0/P1 回归（基线 317 passed / 2 skipped）
- [ ] SSE 事件顺序为 `citation* → token* → done`，`done` 含 spec §6.1 全部 8 个字段
- [ ] `token_usage` 来自流末 `Usage`；Mock 下 `usage_estimated=true`
- [ ] `/stop` 能中断流，已生成内容落库且 `truncated=true`，`AuditLog(action=chat)` 仍写入
- [ ] 中断是 per-request 的：两流并发，取消一个不影响另一个（B2 回归）
- [ ] 三档对同一求答案请求的输出差异可见；三档模板都含三条不可覆盖底线
- [ ] 聊天入口固定 `seek_answer`，消息含代码块也不豁免（ADR-0005）
- [ ] 历史超过 10 轮 / 4000 token 被截断；首轮被丢弃时兜底保留最后一轮
- [ ] 零命中与哨兵降级都能靠 `fallback_reason` 区分，前端提示条文案不同
- [ ] LLM 首选失败降级到 Mock 并置 `degraded=true`；全部失败返回 `5021`（M10）
- [ ] `GET /admin/anti-plagiarism/stats` 返回三档的「触发底线次数 / 总请求数」
- [ ] 所有端点注入 `CurrentRidDep`，响应体与响应头 `request_id` 一致
- [ ] 前端：`npx vue-tsc --noEmit` 零错误；`npx vite build` 通过；路由组件懒加载
- [ ] 前端三页均可交互：对话页能收到流式输出、管理页能看到上传进度
- [ ] M6 未被回退（只复核）

## 待处理项（留到后续批次）

M2 `backend/seeds/`（P5）· M3 `response_model=ApiResponse[T]`（P6）· L2 功能点语义重叠口径 · `/exercises/{id}/hint` 的 SSE（P5，复用本批的 `PromptAssembler` 与 `LLMRuntime`）· 管理端防抄袭统计页（P6，本批只提供端点）
