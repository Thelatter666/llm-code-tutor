"""习题辅导 hint 的 SSE 链路（spec §6.1 §7.1 §7.2，P5 Task 10）。

两种意图的**档位差异**是变异测试目标：`seek_answer` 受约束、`review_my_code`
豁免（但底线仍注入）。问题串的**泄题边界**（seek_answer 不得含参考答案/解析）与
**RAG query 不含学生作答**同为重点。

服务层注入 `FakeLLM` / `FakeRetrieval` 解析产出的 `StreamEvent` 序列断言；
HTTP 层只验接线（422 校验、4040 前置于流、SSE 帧与九字段 done）。
"""

import asyncio
import inspect
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import ApiError
from app.domain.chat.policy import MODE_STRICT
from app.domain.exercise import hint as hint_module
from app.domain.exercise.hint import (
    TEMPLATE_HINT,
    TEMPLATE_MISTAKE_REVIEW,
    build_hint_question,
    build_retrieval_query,
    render_answer,
    template_for,
)
from app.infrastructure.cancellation import CancellationRegistry, reset_cancellation
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import (
    AuditLog,
    Exercise,
    Message,
    MistakeBookEntry,
    Submission,
)
from app.infrastructure.ports.llm import TextDelta, Usage
from app.infrastructure.runtime import (
    reset_runtime,
    set_embedder_runtime,
    set_llm_runtime,
    set_vector_store,
)
from app.infrastructure.sse import (
    CANCELLED_CODE,
    EVENT_CITATION,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_TOKEN,
)
from app.main import app
from app.services.exercise_service import ExerciseService
from tests.fakes import (
    ConstantEmbedder,
    FakeLLM,
    FakeRetrieval,
    FakeVectorStore,
    fake_llm_runtime,
    hit_result,
    miss_result,
)

RID = "rid-hint-1"
EXPLANATION = "解析：弹栈取的是栈顶元素"
REFERENCE = "栈顶"


# ---------------------------------------------------------------- 领域层：问题串与模板


def test_template_selection_is_per_intent():
    assert template_for("seek_answer") == TEMPLATE_HINT == "exercise_hint"
    assert template_for("review_my_code") == TEMPLATE_MISTAKE_REVIEW == "mistake_review"


def test_template_for_judging_raises():
    """judging 是内部判分意图，没有辅导模板 —— 误传必须报错，不静默回退。"""
    with pytest.raises(ValueError):
        template_for("judging")


def _question(**over):
    fields = {
        "intent": "seek_answer",
        "exercise_type": "blank",
        "stem": "列表末尾元素叫什么？",
        "options": None,
        "knowledge_tags": ["列表"],
        "reference_answer": REFERENCE,
        "explanation": EXPLANATION,
        "student_answer": "栈底",
    }
    fields.update(over)
    return build_hint_question(**fields)


def test_seek_answer_question_carries_no_answer_or_explanation():
    """求答案受档位约束：问题串本身不得含参考答案/解析（防绕过时直接泄题）。"""
    text = _question()
    assert "列表末尾元素叫什么？" in text
    assert "列表" in text
    assert REFERENCE not in text
    assert EXPLANATION not in text
    assert "【我的作答】" not in text


def test_review_my_code_question_carries_answer_and_student_code():
    text = _question(intent="review_my_code")
    assert REFERENCE in text
    assert EXPLANATION in text
    assert "【我的作答】栈底" in text


def test_choice_options_are_listed_but_answer_is_not():
    text = _question(
        exercise_type="choice",
        stem="哪个是合法的变量名？",
        options={"A": "2name", "B": "user_name"},
        reference_answer="B",
    )
    assert "A. 2name" in text and "B. user_name" in text
    assert "【参考答案】" not in text


def test_options_are_not_listed_for_non_choice_types():
    """blank/short/coding 没有 options 概念，即便脏数据里带了也不进问题串。"""
    text = _question(exercise_type="coding", options={"A": "x"})
    assert "【选项】" not in text


def test_retrieval_query_is_stem_plus_tags_only():
    """spec §7.2：query 含题干与知识点标签，**不含学生作答**（防污染相似度）。"""
    query = build_retrieval_query(stem="手写一个栈", knowledge_tags=["列表", "函数"])
    assert query == "手写一个栈 列表 函数"
    assert "栈底" not in query


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("B", "B"),
        (["A", "C"], "A、C"),
        ({"source": "print(1)"}, "print(1)"),
        ({"language": "python", "solution": "def f():\n    pass"}, "def f():\n    pass"),
        (None, ""),
        ({}, ""),
    ],
)
def test_render_answer_covers_every_shape(answer, expected):
    assert render_answer(answer) == expected


def test_hint_domain_module_is_pure():
    """零 IO 是领域层硬约束（spec §4.2）。"""
    src = inspect.getsource(hint_module)
    for forbidden in ("sqlalchemy", "httpx", "requests", "asyncio", "open(", "Path("):
        assert forbidden not in src, f"hint 领域层出现 {forbidden}"


# ---------------------------------------------------------------- 服务层替身


class PresetCancelRegistry:
    """中断信号替身：create 直接给出**已置位**的 Event（模拟取消先到）。"""

    def __init__(self):
        self.discarded: list[tuple[str, str]] = []

    def create(self, exercise_id: str, request_id: str):
        event = asyncio.Event()
        event.set()
        return event

    def discard(self, exercise_id: str, request_id: str) -> None:
        self.discarded.append((exercise_id, request_id))


class FixedUsageLLM(FakeLLM):
    """流末给出与文本长度**无关**的用量，证伪「用量是按文本现算的」。"""

    async def stream(self, messages, params, *, cancel=None):
        self.messages.append(list(messages))
        for ch in self.reply:
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
            await asyncio.sleep(0)
        yield Usage(prompt_tokens=1111, completion_tokens=2222, total_tokens=3333, estimated=False)


@pytest_asyncio.fixture
async def exercise(session):
    row = Exercise(
        type="blank",
        stem="列表 pop() 默认弹出哪个位置的元素？",
        answer=REFERENCE,
        explanation=EXPLANATION,
        knowledge_tags=["列表"],
        difficulty=2,
        source="seed",
        status="published",
    )
    session.add(row)
    await session.flush()
    return row


def _svc(session, *, llm=None, retrieval=None, cancels=None):
    fake = llm or FakeLLM(reply="先想清楚栈是什么。")
    runtime = fake_llm_runtime(fake)
    svc = ExerciseService(
        session,
        llm=runtime,
        retrieval=retrieval or FakeRetrieval(),
        cancels=cancels or CancellationRegistry(),
    )
    return svc, fake


async def _collect(gen):
    return [e async for e in gen]


async def _stream(svc, exercise_id, *, intent="seek_answer", answer=None, rid=RID):
    return await _collect(
        svc.stream_hint(
            exercise_id=exercise_id,
            user_id="u-1",
            intent=intent,
            answer=answer,
            request_id=rid,
        )
    )


async def _set_mode(session, mode):
    from app.infrastructure.registry import get_or_create_singleton

    cfg = await get_or_create_singleton(session)
    cfg.anti_plagiarism_mode = mode
    await session.flush()


def _user_message(llm, call: int = 0) -> str:
    return llm.messages[call][-1].content


def _system_message(llm, call: int = 0) -> str:
    return llm.messages[call][0].content


# ---------------------------------------------------------------- 事件序列与 done 载荷


@pytest.mark.asyncio
async def test_event_order_is_citation_then_token_then_done(session, exercise):
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()))
    events = await _stream(svc, exercise.id)

    kinds = [e.event for e in events]
    assert kinds[0] == EVENT_CITATION and kinds[1] == EVENT_CITATION
    # citation 必须全部先于第一个 token（spec §6.1）
    assert kinds.index(EVENT_TOKEN) == 2
    assert kinds[-1] == EVENT_DONE
    assert events[0].data["chunk_id"] == "chunk-1"
    assert events[0].data["number"] == 1


@pytest.mark.asyncio
async def test_no_hit_emits_tokens_without_citation(session, exercise):
    svc, _ = _svc(session, retrieval=FakeRetrieval(miss_result()))
    kinds = [e.event for e in await _stream(svc, exercise.id)]
    assert EVENT_CITATION not in kinds
    assert kinds[0] == EVENT_TOKEN
    assert kinds[-1] == EVENT_DONE


@pytest.mark.asyncio
async def test_done_payload_has_the_nine_agreed_fields(session, exercise):
    """契约定稿 4：九字段，以 exercise_id + intent 替代 message_id。"""
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()))
    done = (await _stream(svc, exercise.id))[-1].data

    assert set(done) == {
        "exercise_id",
        "intent",
        "token_usage",
        "usage_estimated",
        "model",
        "provider",
        "rag_hit",
        "degraded",
        "fallback_reason",
    }
    assert done["exercise_id"] == exercise.id
    assert done["intent"] == "seek_answer"
    assert done["rag_hit"] is True
    assert done["degraded"] is False
    assert done["fallback_reason"] is None
    assert done["provider"] == "fake"
    assert set(done["token_usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}


@pytest.mark.asyncio
async def test_done_intent_reflects_the_requested_intent(session, exercise):
    svc, _ = _svc(session)
    events = await _stream(svc, exercise.id, intent="review_my_code", answer="栈底")
    assert events[-1].data["intent"] == "review_my_code"


@pytest.mark.asyncio
async def test_token_usage_is_taken_verbatim_from_the_stream_tail(session, exercise):
    svc, _ = _svc(session, llm=FixedUsageLLM(reply="随便一段辅导内容"))
    done = (await _stream(svc, exercise.id))[-1].data

    assert done["token_usage"] == {
        "prompt_tokens": 1111,
        "completion_tokens": 2222,
        "total_tokens": 3333,
    }
    assert done["usage_estimated"] is False


@pytest.mark.asyncio
async def test_missing_stream_tail_usage_falls_back_to_estimate(session, exercise):
    """提供方没给流末 Usage 时按估算补齐，done 不得缺字段（CONTEXT.md 估算用量）。"""

    class NoUsageLLM(FakeLLM):
        async def stream(self, messages, params, *, cancel=None):
            self.messages.append(list(messages))
            for ch in self.reply:
                yield TextDelta(ch)

    svc, _ = _svc(session, llm=NoUsageLLM(reply="一二三四五六七八"))
    done = (await _stream(svc, exercise.id))[-1].data
    assert done["token_usage"]["completion_tokens"] == 2
    assert done["usage_estimated"] is True


@pytest.mark.asyncio
async def test_tokens_are_the_verbatim_deltas(session, exercise):
    svc, _ = _svc(session, llm=FakeLLM(reply="思路一：先想清楚栈。"))
    events = await _stream(svc, exercise.id)
    text = "".join(e.data["delta"] for e in events if e.event == EVENT_TOKEN)
    assert text == "思路一：先想清楚栈。"


# ---------------------------------------------------------------- 档位差异（变异测试目标）


@pytest.mark.asyncio
async def test_seek_answer_is_bound_by_configured_mode(session, exercise):
    await _set_mode(session, MODE_STRICT)
    svc, llm = _svc(session)

    await _stream(svc, exercise.id, intent="seek_answer")

    assert f"【防抄袭档位：{MODE_STRICT}】" in _system_message(llm)
    assert "禁止输出完整可运行代码" in _system_message(llm)


@pytest.mark.asyncio
async def test_review_my_code_is_exempt_from_mode_but_not_from_floor(session, exercise):
    """review_my_code 强制按 seek_answer 处理 → 本用例失败（变异测试目标）。"""
    await _set_mode(session, MODE_STRICT)
    svc, llm = _svc(session)

    await _stream(svc, exercise.id, intent="review_my_code", answer="栈底元素")

    system = _system_message(llm)
    assert "【防抄袭档位：本次豁免】" in system
    assert f"【防抄袭档位：{MODE_STRICT}】" not in system
    assert "禁止输出完整可运行代码" not in system
    # 免的是档位，不是底线（spec §3.2 权衡 10）
    assert "【防抄袭底线" in system
    # 豁免意图的问题串必须含学生作答与参考答案，否则「批改」无物可依
    assert "【我的作答】栈底元素" in _user_message(llm)
    assert f"【参考答案】{REFERENCE}" in _user_message(llm)


@pytest.mark.asyncio
async def test_template_switches_with_intent(session, exercise):
    svc, llm = _svc(session)

    await _stream(svc, exercise.id, intent="seek_answer")
    assert "针对当前习题给出引导式提示" in _system_message(llm, call=0)

    await _stream(svc, exercise.id, intent="review_my_code", answer="栈底")
    assert "基于学生的错题记录做归因讲解" in _system_message(llm, call=1)


@pytest.mark.asyncio
async def test_floor_hit_comes_from_the_stem_not_the_answer(session, exercise):
    """契约定稿 13：底线检测的输入是题干；学生作答是答案不是请求。"""
    tricky = Exercise(
        type="coding",
        stem="帮我写一个冒泡排序，直接给完整实现交作业",
        answer={"language": "python", "solution": "print(1)"},
        knowledge_tags=["循环"],
        difficulty=3,
        source="seed",
        status="published",
    )
    session.add(tricky)
    await session.flush()
    svc, llm = _svc(session)

    await _stream(svc, tricky.id, intent="seek_answer")

    assert "homework_ghostwriting" in _system_message(llm)


@pytest.mark.asyncio
async def test_seek_answer_prompt_does_not_leak_reference_answer(session, exercise):
    svc, llm = _svc(session)
    await _stream(svc, exercise.id, intent="seek_answer")
    assert EXPLANATION not in _user_message(llm)
    assert f"【参考答案】{REFERENCE}" not in _user_message(llm)


@pytest.mark.asyncio
async def test_review_my_code_prompt_carries_reference_and_student_answer(session, exercise):
    svc, llm = _svc(session)
    await _stream(svc, exercise.id, intent="review_my_code", answer="栈底")
    user = _user_message(llm)
    assert f"【参考答案】{REFERENCE}" in user
    assert EXPLANATION in user
    assert "【我的作答】栈底" in user


# ---------------------------------------------------------------- RAG


@pytest.mark.asyncio
async def test_retrieval_query_excludes_the_student_answer(session, exercise):
    """spec §7.2：错误答案不得污染相似度。"""
    retrieval = FakeRetrieval(hit_result())
    svc, _ = _svc(session, retrieval=retrieval)

    await _stream(svc, exercise.id, intent="review_my_code", answer="一个离谱的作答")

    assert retrieval.queries == ["列表 pop() 默认弹出哪个位置的元素？ 列表"]
    assert "一个离谱的作答" not in retrieval.queries[0]


@pytest.mark.asyncio
async def test_zero_hit_is_reported_as_degradation(session, exercise):
    svc, _ = _svc(session, retrieval=FakeRetrieval(miss_result()))
    done = (await _stream(svc, exercise.id))[-1].data
    assert done["rag_hit"] is False
    assert done["degraded"] is True
    assert done["fallback_reason"] == "no_relevant_chunk"


@pytest.mark.asyncio
async def test_sentinel_degradation_is_reported(session, exercise):
    svc, _ = _svc(
        session, retrieval=FakeRetrieval(miss_result("hashing_embed_no_semantics"))
    )
    done = (await _stream(svc, exercise.id))[-1].data
    assert done["fallback_reason"] == "hashing_embed_no_semantics"
    assert done["degraded"] is True


@pytest.mark.asyncio
async def test_zero_hit_injects_no_citation_context(session, exercise):
    svc, llm = _svc(session, retrieval=FakeRetrieval(miss_result()))
    await _stream(svc, exercise.id)
    assert "以下是课程知识库检索到的相关内容" not in _user_message(llm)


# ---------------------------------------------------------------- 中断与故障


@pytest.mark.asyncio
async def test_pre_set_cancel_emits_no_token_and_reports_4990(session, exercise):
    """cancel 预置位 → 无 token、error 4990（与 chat 同构），且 finally 注销。"""
    cancels = PresetCancelRegistry()
    svc, _ = _svc(session, cancels=cancels)

    events = await _stream(svc, exercise.id)

    assert [e.event for e in events if e.event == EVENT_TOKEN] == []
    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == CANCELLED_CODE
    assert cancels.discarded == [(f"u-1:{exercise.id}", RID)]


@pytest.mark.asyncio
async def test_another_students_hint_does_not_cancel_my_stream(session, exercise):
    """习题是共享实体：中断作用域必须 per-user，否则 B 发起 hint 会掐断 A 的流。

    若作用域键只用 exercise_id，`create()` 会先置位同键上进行中的流（chat 的
    「同一会话发起新请求即停旧流」语义照搬到共享实体上就成了跨用户干扰）。
    """
    cancels = CancellationRegistry()
    svc, fake = _svc(session, cancels=cancels)
    reply = fake.reply

    stream_a = svc.stream_hint(
        exercise_id=exercise.id,
        user_id="alice",
        intent="seek_answer",
        request_id="rid-a",
    )
    first = await stream_a.__anext__()
    assert first.event == EVENT_TOKEN

    await _collect(
        svc.stream_hint(
            exercise_id=exercise.id,
            user_id="bob",
            intent="seek_answer",
            request_id="rid-b",
        )
    )

    # B 的流已结束并注销自己那条；A 必须能继续产出全部剩余增量并正常 done
    rest = [e async for e in stream_a]
    assert rest[-1].event == EVENT_DONE, "A 被误掐时末事件是 4990 error"
    streamed = first.data["delta"] + "".join(
        e.data["delta"] for e in rest if e.event == EVENT_TOKEN
    )
    assert streamed == reply
    assert cancels.size() == 0


@pytest.mark.asyncio
async def test_registration_is_discarded_after_the_stream(session, exercise):
    cancels = CancellationRegistry()
    svc, _ = _svc(session, cancels=cancels)

    await _stream(svc, exercise.id)
    assert cancels.size() == 0, "finally 必须注销注册表，否则内存泄漏"


@pytest.mark.asyncio
async def test_mid_stream_cancellation_stops_the_token_stream(session, exercise):
    """流已开始后取消：剩余增量不再产出，末事件为 4990。"""
    cancels = CancellationRegistry()
    svc, _ = _svc(session, cancels=cancels)
    events: list = []
    async for evt in svc.stream_hint(
        exercise_id=exercise.id,
        user_id="u-1",
        intent="seek_answer",
        request_id=RID,
    ):
        events.append(evt)
        if len([e for e in events if e.event == EVENT_TOKEN]) == 2:
            cancels.cancel(f"u-1:{exercise.id}", RID)

    assert len([e for e in events if e.event == EVENT_TOKEN]) == 2
    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == CANCELLED_CODE
    assert cancels.size() == 0


@pytest.mark.asyncio
async def test_provider_failure_becomes_an_error_event(session, exercise):
    """FakeLLM(fail=True)：降级链无下一级可用 → 5021 error 事件（照 chat 语义）。"""
    svc, _ = _svc(session, llm=FakeLLM(reply="", fail=True))
    events = await _stream(svc, exercise.id)
    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == 5021


@pytest.mark.asyncio
async def test_retrieval_failure_surfaces_as_its_own_code(session, exercise):
    class ExplodingRetrieval:
        async def search(self, query, **kwargs):
            raise ApiError(5032, "知识库检索暂不可用")

    svc, _ = _svc(session, retrieval=ExplodingRetrieval())
    events = await _stream(svc, exercise.id)
    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == 5032


# ---------------------------------------------------------------- 审计与不落库


@pytest.mark.asyncio
async def test_hint_writes_no_message_no_submission_no_entry(session, exercise):
    """不落 Message / Submission（spec 无此实体），错题本也不因求思路而动。"""
    svc, _ = _svc(session)
    await _stream(svc, exercise.id, intent="review_my_code", answer="栈底")

    assert (await session.execute(select(Message))).scalars().all() == []
    assert (await session.execute(select(Submission))).scalars().all() == []
    assert (await session.execute(select(MistakeBookEntry))).scalars().all() == []


@pytest.mark.asyncio
async def test_audit_is_written_on_success(session, exercise):
    await _set_mode(session, MODE_STRICT)
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()))

    await _stream(svc, exercise.id)

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "exercise_hint"))
    ).scalar_one()
    assert row.user_id == "u-1"
    assert row.target_type == "exercise"
    assert row.target_id == exercise.id
    assert row.request_id == RID
    assert row.detail["intent"] == "seek_answer"
    assert row.detail["mode"] == MODE_STRICT
    assert row.detail["rag_hit"] is True
    assert row.detail["citations"] == 2
    assert row.detail["chars"] == len("先想清楚栈是什么。")
    assert row.detail["error_code"] is None


@pytest.mark.asyncio
async def test_audit_mode_is_null_for_the_exempt_intent(session, exercise):
    await _set_mode(session, MODE_STRICT)
    svc, _ = _svc(session)
    await _stream(svc, exercise.id, intent="review_my_code", answer="栈底")

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "exercise_hint"))
    ).scalar_one()
    assert row.detail["mode"] is None, "豁免意图不记档位（ADR-0005 语义）"


@pytest.mark.asyncio
async def test_audit_is_written_even_when_the_stream_fails(session, exercise):
    svc, _ = _svc(session, llm=FakeLLM(reply="", fail=True))
    await _stream(svc, exercise.id)

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "exercise_hint"))
    ).scalar_one()
    assert row.detail["error_code"] == 5021


@pytest.mark.asyncio
async def test_audit_is_written_when_interrupted(session, exercise):
    svc, _ = _svc(session, cancels=PresetCancelRegistry())
    await _stream(svc, exercise.id)

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "exercise_hint"))
    ).scalar_one()
    assert row.detail["error_code"] == CANCELLED_CODE


# ---------------------------------------------------------------- 可见性


@pytest.mark.asyncio
async def test_missing_or_draft_exercise_raises_4040(session):
    draft = Exercise(
        type="blank",
        stem="未发布",
        answer="x",
        knowledge_tags=["列表"],
        difficulty=1,
        source="seed",
        status="draft",
    )
    session.add(draft)
    await session.flush()
    svc, _ = _svc(session)

    for bad_id in (draft.id, "no-such-exercise"):
        with pytest.raises(ApiError) as exc:
            await _stream(svc, bad_id)
        assert exc.value.code == 4040, "越权前置校验，不进入流"


# ================================================================ HTTP 层


PASSWORD = "Secret123!"


@pytest_asyncio.fixture
async def _engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def factory(_engine):
    return async_sessionmaker(_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(_engine, factory):
    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def _fake_infra():
    """不真起 Chroma、不真加载模型；LLM 用可脚本化的替身（照 test_chat_api 的注入）。"""
    reset_runtime()
    reset_cancellation()
    set_vector_store(FakeVectorStore())
    runtime = EmbedderRuntime(lambda level: ConstantEmbedder() if level == 1 else None)
    await runtime.warmup()
    set_embedder_runtime(runtime)
    set_llm_runtime(fake_llm_runtime(FakeLLM(reply="辅导内容流式")))
    yield
    reset_cancellation()
    reset_runtime()


async def _token(c, username="stu"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return r.json()["data"]["access_token"]


def _auth(token, rid=None):
    headers = {"Authorization": f"Bearer {token}"}
    if rid:
        headers["x-request-id"] = rid
    return headers


def _parse_sse(body: str):
    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        name, payload = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name:
            events.append((name, payload))
    return events


async def _add_exercise(factory, **over) -> Exercise:
    fields: dict = {
        "type": "choice",
        "stem": "以下哪个是合法的变量名？",
        "options": {"A": "2name", "B": "user_name"},
        "answer": "B",
        "explanation": "因为 B 合法",
        "knowledge_tags": ["变量与赋值"],
        "difficulty": 1,
        "source": "seed",
        "status": "published",
    }
    fields.update(over)
    async with factory() as s:
        row = Exercise(**fields)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def _post_hint(client, token, exercise_id, body, rid=None):
    async with client.stream(
        "POST",
        f"/api/v1/exercises/{exercise_id}/hint",
        json=body,
        headers=_auth(token, rid),
    ) as resp:
        return resp, "".join([chunk async for chunk in resp.aiter_text()])


@pytest.mark.asyncio
async def test_hint_requires_auth(client, factory):
    ex = await _add_exercise(factory)
    r = await client.post(f"/api/v1/exercises/{ex.id}/hint", json={"intent": "seek_answer"})
    assert r.status_code == 401
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_hint_streams_citation_free_tokens_and_done(client, factory):
    """无知识库时检索按零命中降级：仍要流式产出，且降级可见（spec §9）。"""
    ex = await _add_exercise(factory)
    token = await _token(client)

    resp, body = await _post_hint(
        client, token, ex.id, {"intent": "seek_answer"}, rid="rid-hint-http"
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-request-id"] == "rid-hint-http"
    assert not body.startswith('{"code"'), "SSE 不走统一响应体"

    events = _parse_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "token"
    assert names[-1] == "done"
    assert "".join(p["delta"] for n, p in events if n == "token") == "辅导内容流式"

    done = events[-1][1]
    assert set(done) == {
        "exercise_id",
        "intent",
        "token_usage",
        "usage_estimated",
        "model",
        "provider",
        "rag_hit",
        "degraded",
        "fallback_reason",
    }
    assert done["exercise_id"] == ex.id
    assert done["intent"] == "seek_answer"
    assert done["degraded"] is True
    assert done["fallback_reason"] == "no_relevant_chunk"


@pytest.mark.asyncio
async def test_hint_is_4040_before_the_stream_starts(client, factory):
    """未发布 / 不存在 → 普通 JSON 404，不是 HTTP 200 + 流内 error。"""
    draft = await _add_exercise(factory, status="draft")
    token = await _token(client)

    for bad in (draft.id, "no-such-exercise"):
        r = await client.post(
            f"/api/v1/exercises/{bad}/hint", json={"intent": "seek_answer"}, headers=_auth(token)
        )
        assert r.status_code == 404
        assert r.json()["code"] == 4040
        assert not r.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_hint_validates_the_body(client, factory):
    ex = await _add_exercise(factory)
    token = await _token(client)

    bad_bodies = [
        {"intent": "review_my_code"},  # 批改缺 answer
        {"intent": "review_my_code", "answer": ""},
        {"intent": "review_my_code", "answer": {"source": "   "}},
        {"intent": "judging"},  # 内部意图不对 HTTP 开放
        {"intent": "make_me_a_sandwich"},
        {},  # intent 缺省
        {"answer": "B"},
    ]
    for body in bad_bodies:
        r = await client.post(
            f"/api/v1/exercises/{ex.id}/hint", json=body, headers=_auth(token)
        )
        assert r.status_code == 422, f"{body} 应被拒绝"


@pytest.mark.asyncio
async def test_hint_accepts_coding_answer_shape(client, factory):
    ex = await _add_exercise(factory, type="coding", options=None, answer={"language": "python", "solution": "print(1)"})
    token = await _token(client)

    resp, body = await _post_hint(
        client,
        token,
        ex.id,
        {"intent": "review_my_code", "answer": {"source": "print(2)"}},
    )

    assert resp.status_code == 200
    events = _parse_sse(body)
    assert events[-1][0] == "done"
    assert events[-1][1]["intent"] == "review_my_code"


@pytest.mark.asyncio
async def test_hint_writes_audit_through_http(client, factory):
    ex = await _add_exercise(factory)
    token = await _token(client)

    await _post_hint(client, token, ex.id, {"intent": "seek_answer"}, rid="rid-hint-audit")

    async with factory() as s:
        rows = list(
            (
                await s.execute(select(AuditLog).where(AuditLog.action == "exercise_hint"))
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].detail["intent"] == "seek_answer"
    assert rows[0].detail["mode"] == "guided", "ModelConfig 默认档位"
    assert rows[0].request_id == "rid-hint-audit"
