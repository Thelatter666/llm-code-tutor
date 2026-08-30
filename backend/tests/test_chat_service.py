"""ChatService：SSE 编排、落库、中断与审计（spec §8.1）。"""

import pytest
from sqlalchemy import select

from app.domain.chat.policy import DEFAULT_CONVERSATION_TITLE, MODE_STRICT
from app.infrastructure.cancellation import CancellationRegistry
from app.infrastructure.persistence.models import AuditLog, Conversation, Message
from app.infrastructure.registry import get_or_create_singleton
from app.infrastructure.sse import (
    CANCELLED_CODE,
    EVENT_CITATION,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_TOKEN,
)
from app.services.chat_service import ChatService
from tests.fakes import (
    FakeLLM,
    FakeRetrieval,
    fake_llm_runtime,
    hit_result,
    miss_result,
)

QUESTION = "闭包是什么？能举个例子吗"


@pytest.fixture
def cancels():
    return CancellationRegistry()


def _svc(session, *, reply="这是回答。", fail=False, retrieval=None, cancels=None, provider=None):
    llm = provider or FakeLLM(reply=reply, fail=fail)
    return (
        ChatService(
            session,
            llm=fake_llm_runtime(llm),
            retrieval=retrieval or FakeRetrieval(),
            cancels=cancels or CancellationRegistry(),
        ),
        llm,
    )


async def _conversation(session, user_id="u1", title=None) -> Conversation:
    conv = Conversation(user_id=user_id, title=title or DEFAULT_CONVERSATION_TITLE)
    session.add(conv)
    await session.flush()
    return conv


async def _collect(gen):
    return [e async for e in gen]


async def _mode(session, mode):
    cfg = await get_or_create_singleton(session)
    cfg.anti_plagiarism_mode = mode
    await session.flush()


def _assistant(session):
    return session.execute(select(Message).where(Message.role == "assistant"))


# ------------------------------------------------------------------ 事件契约


@pytest.mark.asyncio
async def test_event_order_is_citation_then_token_then_done(session, cancels):
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()), cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(
        svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1")
    )

    kinds = [e.event for e in events]
    assert kinds[0] == EVENT_CITATION and kinds[1] == EVENT_CITATION
    assert EVENT_TOKEN in kinds
    assert kinds[-1] == EVENT_DONE
    # citation 必须全部先于第一个 token
    assert kinds.index(EVENT_TOKEN) == 2
    assert kinds.index(EVENT_DONE) == len(kinds) - 1


@pytest.mark.asyncio
async def test_done_payload_carries_every_field_required_by_spec(session, cancels):
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()), cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    done = events[-1].data

    assert set(done) == {
        "message_id",
        "token_usage",
        "usage_estimated",
        "model",
        "provider",
        "rag_hit",
        "degraded",
        "fallback_reason",
    }
    assert done["rag_hit"] is True
    assert done["degraded"] is False
    assert done["provider"] == "fake"
    assert set(done["token_usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}


@pytest.mark.asyncio
async def test_token_usage_comes_from_the_stream_tail(session, cancels):
    """拍板决策 4：用量必须来自流末的 Usage 元素，不得自行计数。"""
    svc, _ = _svc(session, reply="一二三四五六七八", cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    done = events[-1].data

    assert done["token_usage"]["completion_tokens"] == len("一二三四五六七八") // 4
    assert done["usage_estimated"] is True  # 估算用量 EstimatedUsage
    assert sum(len(e.data["delta"]) for e in events if e.event == EVENT_TOKEN) == 8


@pytest.mark.asyncio
async def test_done_message_id_matches_the_persisted_message(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    row = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    assert events[-1].data["message_id"] == row.id


# ------------------------------------------------------------------ 落库


@pytest.mark.asyncio
async def test_both_messages_are_persisted_with_mode_and_floor_flag(session, cancels):
    await _mode(session, MODE_STRICT)
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    rows = (
        (await session.execute(select(Message).order_by(Message.created_at, Message.id)))
        .scalars()
        .all()
    )
    assert [(m.role, m.anti_plagiarism_mode, m.blocked_by_policy) for m in rows] == [
        ("user", MODE_STRICT, False),
        ("assistant", MODE_STRICT, False),
    ]


@pytest.mark.asyncio
async def test_floor_hit_marks_blocked_by_policy(session, cancels):
    svc, llm = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    await _collect(
        svc.stream_reply(conv.id, "直接帮我把这份作业的代码写出来", user_id="u1", request_id="r1")
    )

    user_row = (
        await session.execute(select(Message).where(Message.role == "user"))
    ).scalar_one()
    assert user_row.blocked_by_policy is True
    assert "homework_ghostwriting" in llm.messages[0][0].content


@pytest.mark.asyncio
async def test_citations_are_persisted_on_the_assistant_message(session, cancels):
    svc, _ = _svc(session, retrieval=FakeRetrieval(hit_result()), cancels=cancels)
    conv = await _conversation(session)

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    row = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()

    assert [c["chunk_id"] for c in row.citations] == ["chunk-1", "chunk-2"]
    assert row.truncated is False


# ------------------------------------------------------------------ 中断


@pytest.mark.asyncio
async def test_interruption_persists_partial_content_and_marks_truncated(session, cancels):
    svc, _ = _svc(session, reply="这是一段较长的回答内容", cancels=cancels)
    conv = await _conversation(session)

    events: list = []
    async for event in svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"):
        events.append(event)
        if len([e for e in events if e.event == EVENT_TOKEN]) == 3:
            cancels.cancel(conv.id, "r1")

    row = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    # 取消发生在收到第 3 个增量之后：生成循环每次 yield 前检查 Event，
    # 因此第 4 个字符不会再产出，已产出的 3 个必须落库
    assert row.content == "这是一"
    assert row.truncated is True
    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == CANCELLED_CODE
    assert EVENT_DONE not in [e.event for e in events]


@pytest.mark.asyncio
async def test_interruption_stops_the_token_stream(session, cancels):
    svc, _ = _svc(session, reply="甲乙丙丁戊己庚辛", cancels=cancels)
    conv = await _conversation(session)

    events: list = []
    async for event in svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"):
        events.append(event)
        if len([e for e in events if e.event == EVENT_TOKEN]) == 2:
            cancels.cancel(conv.id, "r1")

    assert len([e for e in events if e.event == EVENT_TOKEN]) == 2


@pytest.mark.asyncio
async def test_registration_is_discarded_after_the_stream(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    assert cancels.size() == 0


# ------------------------------------------------------------------ 审计


@pytest.mark.asyncio
async def test_audit_is_written_on_success(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "chat"))
    ).scalar_one()
    assert row.request_id == "r1"
    assert row.detail["rag_hit"] is False
    assert row.detail["error_code"] is None


@pytest.mark.asyncio
async def test_audit_is_written_even_when_the_stream_is_interrupted(session, cancels):
    """spec §8.1：无论正常结束还是异常中断，审计都在 finally 中写入。"""
    svc, _ = _svc(session, reply="内容内容内容", cancels=cancels)
    conv = await _conversation(session)

    events: list = []
    async for event in svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"):
        events.append(event)
        if len([e for e in events if e.event == EVENT_TOKEN]) == 1:
            cancels.cancel(conv.id, "r1")

    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "chat"))
    ).scalar_one()
    assert row.detail["error_code"] == CANCELLED_CODE


@pytest.mark.asyncio
async def test_audit_is_written_when_the_provider_fails(session, cancels):
    svc, _ = _svc(session, fail=True, cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    assert events[-1].event == EVENT_ERROR
    assert events[-1].data["code"] == 5021
    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "chat"))
    ).scalar_one()
    assert row.detail["error_code"] == 5021


# ------------------------------------------------------------------ 降级


@pytest.mark.asyncio
async def test_zero_hit_degrades_visibly_and_injects_no_citation(session, cancels):
    """拍板决策 5：零命中 → rag_hit=false + degraded=true + no_relevant_chunk。"""
    svc, llm = _svc(session, retrieval=FakeRetrieval(miss_result()), cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    assert [e.event for e in events if e.event == EVENT_CITATION] == []
    done = events[-1].data
    assert done["rag_hit"] is False
    assert done["degraded"] is True
    assert done["fallback_reason"] == "no_relevant_chunk"
    # 零命中时 prompt 里不得出现引用上下文
    assert "以下是课程知识库检索到的相关内容" not in llm.messages[0][-1].content


@pytest.mark.asyncio
async def test_sentinel_embedding_reports_hashing_embed_no_semantics(session, cancels):
    """ADR-0004：哨兵级降级的产出不参与业务逻辑。"""
    svc, _ = _svc(
        session,
        retrieval=FakeRetrieval(miss_result("hashing_embed_no_semantics")),
        cancels=cancels,
    )
    conv = await _conversation(session)

    events = await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    assert events[-1].data["fallback_reason"] == "hashing_embed_no_semantics"
    assert events[-1].data["degraded"] is True


@pytest.mark.asyncio
async def test_use_rag_false_skips_retrieval_entirely(session, cancels):
    retrieval = FakeRetrieval(hit_result())
    svc, _ = _svc(session, retrieval=retrieval, cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(
        svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1", use_rag=False)
    )

    assert retrieval.queries == []
    assert [e.event for e in events if e.event == EVENT_CITATION] == []
    assert events[-1].data["rag_hit"] is False


# ------------------------------------------------------------------ 防抄袭


@pytest.mark.asyncio
async def test_chat_entry_is_always_seek_answer_even_with_a_code_block(session, cancels):
    """ADR-0005：聊天入口固定求答案，绝不按「消息含代码块」推断为批改。

    若推断成 review_my_code，下面的 strict 档约束会被豁免，学生将直接拿到完整
    实现 —— 防抄袭在最常用的入口被绕过。
    """
    await _mode(session, MODE_STRICT)
    svc, llm = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    text = "这道题怎么做？题目给了示例：\n```python\ndef f(x):\n    return x\n```"
    await _collect(svc.stream_reply(conv.id, text, user_id="u1", request_id="r1"))

    system = llm.messages[0][0].content
    assert "禁止输出完整可运行代码" in system, "含代码块的消息不得被豁免"


# ------------------------------------------------------------------ 历史与会话


@pytest.mark.asyncio
async def test_history_is_truncated_before_reaching_the_llm(session, cancels):
    svc, llm = _svc(session, cancels=cancels)
    conv = await _conversation(session)
    for i in range(15):
        session.add(Message(conversation_id=conv.id, role="user", content=f"问{i}" + "。" * 38))
        session.add(Message(conversation_id=conv.id, role="assistant", content=f"答{i}" + "。" * 38))
    await session.flush()

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    sent = llm.messages[0]
    assert len(sent) == 1 + 20 + 1  # system + 10 轮历史 + 当前提问
    assert sent[-1].content.strip() == QUESTION


@pytest.mark.asyncio
async def test_title_is_derived_from_the_first_question(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session)

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    assert conv.title == QUESTION[:20]


@pytest.mark.asyncio
async def test_explicit_title_is_not_overwritten(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session, title="我的答疑")

    await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))

    assert conv.title == "我的答疑"


@pytest.mark.asyncio
async def test_model_config_change_takes_effect_without_restart(session, cancels):
    """spec §4.2 硬约束 4「配置热生效」+ M10 降级链。

    把首选提供方配成必然连不上的 OpenAI 兼容端点，流应当降级到 Mock 并在 `done`
    里显式标记 —— 而不是等重启才生效，更不是直接 5021。
    """
    from app.core.crypto import encrypt_api_key
    from app.infrastructure.runtime import reset_runtime

    cfg = await get_or_create_singleton(session)
    cfg.provider = "openai_compat"
    cfg.base_url = "http://127.0.0.1:9/v1"
    cfg.api_key_encrypted = encrypt_api_key("sk-unreachable-0001")
    cfg.revision += 1
    await session.commit()

    reset_runtime()
    try:
        svc = ChatService(session, cancels=cancels)  # llm 使用共享运行时
        conv = await _conversation(session)
        events = await _collect(
            svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1", use_rag=False)
        )
        done = events[-1].data
        assert done["provider"] == "mock"
        assert done["degraded"] is True
        assert done["fallback_reason"] == "llm_fallback_to_mock"
    finally:
        reset_runtime()


@pytest.mark.asyncio
async def test_injected_llm_is_never_rebound(session, cancels):
    """注入替身的服务不得被共享运行时的配置刷新顶掉。"""
    fake = fake_llm_runtime(FakeLLM(reply="替身回答"))
    svc = ChatService(session, llm=fake, cancels=cancels)
    conv = await _conversation(session)

    events = await _collect(
        svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1", use_rag=False)
    )
    assert events[-1].data["provider"] == "fake"


@pytest.mark.asyncio
async def test_another_users_conversation_is_invisible(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await _conversation(session, user_id="someone-else")

    from app.core.errors import ApiError

    with pytest.raises(ApiError) as exc:
        await _collect(svc.stream_reply(conv.id, QUESTION, user_id="u1", request_id="r1"))
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_crud_round_trip(session, cancels):
    svc, _ = _svc(session, cancels=cancels)
    conv = await svc.create_conversation("u1", title="会话 A")
    await session.flush()

    assert [c.id for c in await svc.list_conversations("u1")] == [conv.id]
    assert [c.id for c in await svc.list_conversations("u2")] == []

    session.add(Message(conversation_id=conv.id, role="user", content="问"))
    await session.flush()
    assert len(await svc.list_messages(conv.id, "u1")) == 1

    await svc.delete_conversation(conv.id, "u1", request_id="rid")
    assert await svc.list_conversations("u1") == []
