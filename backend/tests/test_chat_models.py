import pytest
from sqlalchemy import select, text

from app.infrastructure.persistence.models import Conversation, Message


@pytest.mark.asyncio
async def test_both_tables_are_created(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    assert {"conversations", "messages"} <= {r[0] for r in rows}


@pytest.mark.asyncio
async def test_conversation_defaults_and_owner(session):
    conv = Conversation(user_id="u1", title="闭包答疑")
    session.add(conv)
    await session.commit()

    got = (await session.execute(select(Conversation))).scalar_one()
    assert got.user_id == "u1"
    assert got.title == "闭包答疑"
    assert got.created_at.tzinfo is not None
    assert got.updated_at is not None


@pytest.mark.asyncio
async def test_message_carries_every_field_required_by_spec(session):
    """spec §5 Message：citations / token_usage / model / provider / truncated / 档位 / 底线拦截。"""
    conv = Conversation(user_id="u1", title="t")
    session.add(conv)
    await session.flush()
    session.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content="回答",
            citations=[{"chunk_id": "c1", "number": 1}],
            token_usage={
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "estimated": True,
            },
            model="mock-1",
            provider="mock",
            truncated=False,
            anti_plagiarism_mode="guided",
            blocked_by_policy=False,
        )
    )
    await session.commit()

    got = (await session.execute(select(Message))).scalar_one()
    assert got.citations[0]["chunk_id"] == "c1"
    assert got.token_usage["estimated"] is True
    assert got.model == "mock-1"
    assert got.provider == "mock"
    assert got.truncated is False
    assert got.anti_plagiarism_mode == "guided"
    assert got.blocked_by_policy is False


@pytest.mark.asyncio
async def test_message_defaults(session):
    """未落库的新消息：truncated / blocked_by_policy 默认 false，引用默认空。"""
    msg = Message(conversation_id="c1", role="user", content="问题")
    session.add(msg)
    await session.commit()

    got = (await session.execute(select(Message))).scalar_one()
    assert got.truncated is False
    assert got.blocked_by_policy is False
    assert got.citations is None
    assert got.token_usage is None
    assert got.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_messages_are_orderable_by_creation_time(session):
    conv = Conversation(user_id="u1", title="t")
    session.add(conv)
    await session.flush()
    for role, content in (("user", "问"), ("assistant", "答")):
        session.add(Message(conversation_id=conv.id, role=role, content=content))
    await session.commit()

    rows = (
        await session.execute(select(Message).order_by(Message.created_at, Message.id))
    ).scalars().all()
    assert [m.role for m in rows] == ["user", "assistant"]
