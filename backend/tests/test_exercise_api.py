"""学生端习题端点的 HTTP 层测试（spec §6.2 exercise 行，P5 Task 7）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import Exercise
from app.main import app

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


async def _add_exercise(factory, **over) -> Exercise:
    fields: dict = {
        "type": "choice",
        "stem": "以下哪个是合法的变量名？",
        "options": {"A": "2name", "B": "user_name"},
        "answer": "B",
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


async def _token(c, username="stu"):
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return r.json()["data"]["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_requires_auth(client):
    r = await client.get("/api/v1/exercises")
    assert r.status_code == 401
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_list_exposes_only_published(client, factory):
    await _add_exercise(factory)
    await _add_exercise(factory, stem="未发布的习题", status="draft")

    token = await _token(client)
    r = await client.get("/api/v1/exercises", headers=_auth(token))

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["stem"] == "以下哪个是合法的变量名？"


@pytest.mark.asyncio
async def test_list_filters_by_type_difficulty_tag(client, factory):
    await _add_exercise(factory, stem="选择", knowledge_tags=["变量与赋值"], difficulty=1)
    await _add_exercise(factory, type="blank", stem="填空", options=None, answer="x", difficulty=2)
    await _add_exercise(
        factory, stem="另一道选择", knowledge_tags=["循环"], difficulty=1
    )

    token = await _token(client)
    auth = _auth(token)

    r = await client.get("/api/v1/exercises", params={"type": "choice"}, headers=auth)
    assert r.json()["data"]["total"] == 2

    r = await client.get("/api/v1/exercises", params={"difficulty": 2}, headers=auth)
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["type"] == "blank"

    r = await client.get("/api/v1/exercises", params={"knowledge_tag": "循环"}, headers=auth)
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["stem"] == "另一道选择"


@pytest.mark.asyncio
async def test_list_paginates_with_total(client, factory):
    for i in range(3):
        await _add_exercise(factory, stem=f"习题 {i}")

    token = await _token(client)
    r = await client.get(
        "/api/v1/exercises", params={"page": 2, "page_size": 2}, headers=_auth(token)
    )
    data = r.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_list_facets_ignore_tag_filter(client, factory):
    """facets.knowledge_tags 是筛选下拉的数据源，不受 knowledge_tag 过滤影响。"""
    await _add_exercise(factory, knowledge_tags=["变量与赋值"])
    await _add_exercise(factory, stem="循环题", knowledge_tags=["循环"])

    token = await _token(client)
    r = await client.get(
        "/api/v1/exercises", params={"knowledge_tag": "循环"}, headers=_auth(token)
    )
    data = r.json()["data"]
    assert data["total"] == 1
    assert set(data["facets"]["knowledge_tags"]) == {"变量与赋值", "循环"}


@pytest.mark.asyncio
async def test_detail_hides_answer_and_explanation(client, factory):
    """提交之前不得泄露正确答案与解析 —— 学生详情不含 answer/explanation/test_cases。"""
    row = await _add_exercise(
        factory,
        type="coding",
        options=None,
        answer={"language": "python", "solution": "print(1)"},
        test_cases={"language": "python", "cases": [{"stdin": "", "expected_stdout": "1"}]},
        explanation="因为 B 合法",
    )

    token = await _token(client)
    r = await client.get(f"/api/v1/exercises/{row.id}", headers=_auth(token))

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["stem"] == "以下哪个是合法的变量名？"
    assert data["language"] == "python"
    for leaked in ("answer", "explanation", "test_cases", "judge_detail"):
        assert leaked not in data


@pytest.mark.asyncio
async def test_detail_draft_and_missing_are_4040(client, factory):
    draft = await _add_exercise(factory, status="draft")
    token = await _token(client)

    r = await client.get(f"/api/v1/exercises/{draft.id}", headers=_auth(token))
    assert r.status_code == 404
    assert r.json()["code"] == 4040

    r = await client.get("/api/v1/exercises/no-such", headers=_auth(token))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_submit_reveals_answer_and_explanation(client, factory):
    row = await _add_exercise(factory, explanation="因为 B 合法")

    token = await _token(client, "submitter")
    r = await client.post(
        f"/api/v1/exercises/{row.id}/submit",
        json={"answer": "B"},
        headers={"Authorization": f"Bearer {token}", "x-request-id": "rid-submit-1"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["request_id"] == "rid-submit-1"
    data = body["data"]
    assert data["score"] == 100
    assert data["is_correct"] is True
    assert data["correct_answer"] == "B"
    assert data["explanation"] == "因为 B 合法"
    assert data["ai_scored"] is False
    assert data["attempt_no"] == 1


@pytest.mark.asyncio
async def test_submit_draft_is_4040(client, factory):
    draft = await _add_exercise(factory, status="draft")
    token = await _token(client, "submitter2")

    r = await client.post(
        f"/api/v1/exercises/{draft.id}/submit", json={"answer": "B"}, headers=_auth(token)
    )
    assert r.status_code == 404
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_list_rejects_bad_filters(client):
    token = await _token(client, "stu3")
    r = await client.get(
        "/api/v1/exercises", params={"difficulty": 9}, headers=_auth(token)
    )
    assert r.status_code == 422

    r = await client.get("/api/v1/exercises", params={"page_size": 0}, headers=_auth(token))
    assert r.status_code == 422
