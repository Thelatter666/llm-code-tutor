"""错题本端点的 HTTP 层测试（spec §6.2 mistake 行，P5 Task 9）。

三态筛选、跨用户隔离与 `filled_by=random` 标注可见是重点。
「重置掌握 = consecutive_correct 清零」的语义由服务层用例守护，本文件只验
HTTP 层把重置后的状态如实回传。

`GET /mistakes` 返回裸数组 —— 与仓内其它学生端列表端点（会话列表、知识库列表、
文档列表）同构：spec §6.2 的 `page/page_size` 约定只约束分页端点，而单个学生的
错题条目上限就是题库规模（声明规模内无需分页）。
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import AuditLog, Exercise, MistakeBookEntry
from app.main import app

PASSWORD = "Secret123!"
NOW = datetime(2026, 8, 31, 10, 30, 0, tzinfo=UTC)


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


async def _add_entry(factory, user_id: str, exercise_id: str, **over) -> MistakeBookEntry:
    fields: dict = {
        "user_id": user_id,
        "exercise_id": exercise_id,
        "wrong_count": 1,
        "consecutive_correct": 0,
        "last_wrong_answer": "A",
        "last_wrong_at": NOW,
        "mastered": False,
        "mastered_at": None,
    }
    fields.update(over)
    async with factory() as s:
        row = MistakeBookEntry(**fields)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def _register(c, username: str) -> str:
    """注册 + 登录，返回 access_token。"""
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return r.json()["data"]["access_token"]


async def _user_id(c, username: str) -> str:
    token = await _register(c, username)
    me = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["data"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 鉴权


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/mistakes"),
        ("get", "/api/v1/mistakes/profile"),
        ("get", "/api/v1/mistakes/recommendations"),
        ("delete", "/api/v1/mistakes/entry-1/mastered"),
    ],
)
async def test_every_endpoint_requires_auth(client, method, path):
    r = await getattr(client, method)(path)
    assert r.status_code == 401
    assert r.json()["code"] == 4010


# ---------------------------------------------------------------- 条目列表


@pytest.mark.asyncio
async def test_list_returns_entry_with_exercise_summary(client, factory):
    ex = await _add_exercise(factory)
    token = await _register(client, "owner")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    await _add_entry(factory, uid, ex.id)

    r = await client.get("/api/v1/mistakes", headers=_auth(token))

    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 1
    entry = items[0]
    assert entry["exercise_id"] == ex.id
    assert entry["wrong_count"] == 1
    assert entry["consecutive_correct"] == 0
    assert entry["mastered"] is False
    assert entry["last_wrong_answer"] == "A"
    assert entry["last_wrong_at"].startswith("2026-08-31T10:30:00")
    # 条目必须带习题摘要，但不得泄题
    assert entry["exercise"]["stem"] == "以下哪个是合法的变量名？"
    assert entry["exercise"]["type"] == "choice"
    assert entry["exercise"]["difficulty"] == 1
    assert entry["exercise"]["knowledge_tags"] == ["变量与赋值"]
    assert entry["exercise"]["options"] == {"A": "2name", "B": "user_name"}
    for leaked in ("answer", "explanation", "test_cases"):
        assert leaked not in entry["exercise"]


@pytest.mark.asyncio
async def test_list_mastered_three_states(client, factory):
    ex1 = await _add_exercise(factory)
    ex2 = await _add_exercise(factory, stem="另一道习题", knowledge_tags=["循环"])
    token = await _register(client, "owner2")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    await _add_entry(factory, uid, ex1.id)
    await _add_entry(
        factory,
        uid,
        ex2.id,
        wrong_count=2,
        consecutive_correct=2,
        mastered=True,
        mastered_at=NOW,
    )

    auth = _auth(token)

    everything = (await client.get("/api/v1/mistakes", headers=auth)).json()["data"]
    assert len(everything) == 2, "不传 mastered 即三态全返回"

    unmastered = (
        await client.get("/api/v1/mistakes", params={"mastered": "false"}, headers=auth)
    ).json()["data"]
    assert [i["exercise_id"] for i in unmastered] == [ex1.id]

    mastered = (
        await client.get("/api/v1/mistakes", params={"mastered": "true"}, headers=auth)
    ).json()["data"]
    assert [i["exercise_id"] for i in mastered] == [ex2.id]


@pytest.mark.asyncio
async def test_list_rejects_non_boolean_mastered(client):
    token = await _register(client, "owner3")
    r = await client.get("/api/v1/mistakes", params={"mastered": "maybe"}, headers=_auth(token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_is_isolated_per_user(client, factory):
    ex = await _add_exercise(factory)
    alice = await _user_id(client, "alice")
    await _add_entry(factory, alice, ex.id)

    bob = await _register(client, "bob")
    assert (await client.get("/api/v1/mistakes", headers=_auth(bob))).json()["data"] == []


@pytest.mark.asyncio
async def test_list_echoes_request_id(client):
    token = await _register(client, "owner9")
    r = await client.get(
        "/api/v1/mistakes", headers={"Authorization": f"Bearer {token}", "x-request-id": "rid-ml"}
    )
    assert r.json()["request_id"] == "rid-ml"


# ---------------------------------------------------------------- 重置掌握


@pytest.mark.asyncio
async def test_reset_mastered_returns_reset_state(client, factory):
    """裁定 2：mastered=false、mastered_at=null、consecutive_correct=0，历史保留。"""
    ex = await _add_exercise(factory)
    token = await _register(client, "owner4")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    entry = await _add_entry(
        factory,
        uid,
        ex.id,
        wrong_count=3,
        consecutive_correct=2,
        mastered=True,
        mastered_at=NOW,
        last_wrong_answer="C",
    )

    r = await client.delete(
        f"/api/v1/mistakes/{entry.id}/mastered",
        headers={"Authorization": f"Bearer {token}", "x-request-id": "rid-reset"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["request_id"] == "rid-reset"
    data = body["data"]
    assert data["mastered"] is False
    assert data["mastered_at"] is None
    assert data["consecutive_correct"] == 0
    assert data["wrong_count"] == 3, "wrong_count 是历史，重置不动它"
    assert data["last_wrong_answer"] == "C"
    assert data["last_wrong_at"].startswith("2026-08-31")


@pytest.mark.asyncio
async def test_reset_mastered_records_audit_log(client, factory):
    """手动重置掌握度是改变学习状态的用户关键行为，与 chat 会话删除同例留痕。"""
    ex = await _add_exercise(factory)
    token = await _register(client, "owner6")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    entry = await _add_entry(factory, uid, ex.id, mastered=True, consecutive_correct=2)

    await client.delete(
        f"/api/v1/mistakes/{entry.id}/mastered",
        headers={"Authorization": f"Bearer {token}", "x-request-id": "rid-audit"},
    )

    async with factory() as s:
        rows = list(
            (
                await s.execute(select(AuditLog).where(AuditLog.action == "mistake_reset_mastered"))
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].user_id == uid
    assert rows[0].target_type == "mistake_book_entry"
    assert rows[0].target_id == entry.id
    assert rows[0].request_id == "rid-audit"


@pytest.mark.asyncio
async def test_reset_mastered_of_other_user_is_4040(client, factory):
    ex = await _add_exercise(factory)
    owner = await _user_id(client, "owner7")
    entry = await _add_entry(factory, owner, ex.id, mastered=True, consecutive_correct=2)

    intruder = await _register(client, "intruder")
    r = await client.delete(f"/api/v1/mistakes/{entry.id}/mastered", headers=_auth(intruder))
    assert r.status_code == 404
    assert r.json()["code"] == 4040, "非本人条目 4040，不泄露存在性"

    r = await client.delete("/api/v1/mistakes/no-such/mastered", headers=_auth(intruder))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reset_mastered_of_orphan_entry_is_4040(client, factory):
    """条目指向已被删走的习题（无 FK 现状下的脏数据）：不出半截视图，一律 4040。"""
    token = await _register(client, "orphan")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    entry = await _add_entry(factory, uid, "no-such-exercise", mastered=True, consecutive_correct=2)

    r = await client.delete(f"/api/v1/mistakes/{entry.id}/mastered", headers=_auth(token))
    assert r.status_code == 404
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_reset_mastered_then_list_unmastered_shows_it(client, factory):
    """重置后条目重新出现在未掌握视图（错题驱动学习闭环）。"""
    ex = await _add_exercise(factory)
    token = await _register(client, "owner8")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    entry = await _add_entry(
        factory, uid, ex.id, mastered=True, consecutive_correct=2, mastered_at=NOW
    )

    await client.delete(f"/api/v1/mistakes/{entry.id}/mastered", headers=_auth(token))

    items = (
        await client.get("/api/v1/mistakes", params={"mastered": "false"}, headers=_auth(token))
    ).json()["data"]
    assert [i["id"] for i in items] == [entry.id]


# ---------------------------------------------------------------- 画像


@pytest.mark.asyncio
async def test_unpublished_exercise_disappears_from_the_book(client, factory):
    """admin 把已入错题本的习题下架后，题干与选项不得再从错题本泄出。

    学生端列表/详情对 draft 一律 4040（spec §6.2），错题本是同一批数据的第三个出口，
    少过滤一次就等于绕过那条不变量。
    """
    ex = await _add_exercise(factory)
    token = await _register(client, "unpub")
    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    uid = me.json()["data"]["id"]
    entry = await _add_entry(factory, uid, ex.id)

    listed = await client.get("/api/v1/mistakes", headers=_auth(token))
    assert len(listed.json()["data"]) == 1

    async with factory() as s:
        row = await s.get(Exercise, ex.id)
        row.status = "draft"
        await s.commit()

    hidden = await client.get("/api/v1/mistakes", headers=_auth(token))
    assert hidden.json()["data"] == [], "已下架习题的题干不得再从错题本泄出"
    profile = await client.get("/api/v1/mistakes/profile", headers=_auth(token))
    assert profile.json()["data"] == [], "已下架习题不进画像聚合"
    rec = await client.get("/api/v1/mistakes/recommendations", headers=_auth(token))
    picked = {i["exercise"]["id"] for i in rec.json()["data"]["items"]}
    assert ex.id not in picked
    reset = await client.delete(f"/api/v1/mistakes/{entry.id}/mastered", headers=_auth(token))
    assert reset.status_code == 404, "下架习题的条目不出完整视图，也不接受重置"

    async with factory() as s:
        row = await s.get(Exercise, ex.id)
        row.status = "published"
        await s.commit()
    back = await client.get("/api/v1/mistakes", headers=_auth(token))
    assert len(back.json()["data"]) == 1, "重新发布后条目回来了"


@pytest.mark.asyncio
async def test_reset_of_unmastered_entry_starts_a_new_round(client, factory):
    """未掌握的条目也可重置（语义统一为「开启新一轮」）：连对归零、历史保留。

    前端只在已掌握条目上放按钮，但接口不该因此有隐式分支 —— 定义为幂等的
    「重开一轮」并由用例锁住，比留一个未定义行为诚实。
    """
    ex = await _add_exercise(factory)
    token = await _register(client, "unmastered-reset")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    entry = await _add_entry(factory, uid, ex.id, wrong_count=4, consecutive_correct=1, mastered=False)

    r = await client.delete(f"/api/v1/mistakes/{entry.id}/mastered", headers=_auth(token))

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["consecutive_correct"] == 0, "进行中的连对进度被清零"
    assert data["wrong_count"] == 4 and data["mastered"] is False


@pytest.mark.asyncio
async def test_profile_aggregates_and_excludes_mastered(client, factory):
    e1 = await _add_exercise(factory, knowledge_tags=["变量与赋值", "数据类型"])
    e2 = await _add_exercise(factory, stem="循环题", knowledge_tags=["循环"], difficulty=2)
    e3 = await _add_exercise(factory, stem="已掌握题", knowledge_tags=["函数"])
    token = await _register(client, "prof")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    await _add_entry(factory, uid, e1.id, wrong_count=3)
    await _add_entry(factory, uid, e2.id, wrong_count=1)
    await _add_entry(factory, uid, e3.id, wrong_count=9, mastered=True)

    data = (await client.get("/api/v1/mistakes/profile", headers=_auth(token))).json()["data"]

    by_tag = {p["knowledge_tag"]: p["wrong_count"] for p in data}
    assert by_tag["变量与赋值"] == 3
    assert by_tag["数据类型"] == 3
    assert by_tag["循环"] == 1
    assert "函数" not in by_tag, "已掌握条目不进画像"
    assert data[0]["wrong_count"] >= data[-1]["wrong_count"], "按 wrong_count 降序"


@pytest.mark.asyncio
async def test_profile_is_empty_without_mistakes(client):
    token = await _register(client, "fresh")
    r = await client.get("/api/v1/mistakes/profile", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["data"] == []


# ---------------------------------------------------------------- 推荐


@pytest.mark.asyncio
async def test_recommendations_marks_profile_and_random(client, factory):
    weak = await _add_exercise(factory, knowledge_tags=["循环"], difficulty=2)
    filler = await _add_exercise(
        factory, stem="补足习题", knowledge_tags=["字符串"], difficulty=4
    )
    token = await _register(client, "rec")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    await _add_entry(factory, uid, weak.id, wrong_count=2)

    r = await client.get(
        "/api/v1/mistakes/recommendations", params={"limit": 2}, headers=_auth(token)
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["weak_tags"] == ["循环"]
    marks = {i["exercise"]["id"]: i["filled_by"] for i in data["items"]}
    assert marks[weak.id] == "profile"
    assert marks[filler.id] == "random", "随机补足必须标注 filled_by=random（CONTEXT.md）"
    for item in data["items"]:
        for leaked in ("answer", "explanation", "test_cases"):
            assert leaked not in item["exercise"], "推荐不得泄题"


@pytest.mark.asyncio
async def test_recommendations_default_limit_is_five(client, factory):
    for i in range(9):
        await _add_exercise(factory, stem=f"习题 {i}", difficulty=1 + i % 5)

    token = await _register(client, "rec2")
    data = (
        await client.get("/api/v1/mistakes/recommendations", headers=_auth(token))
    ).json()["data"]

    assert len(data["items"]) == 5
    assert all(i["filled_by"] == "random" for i in data["items"]), "无错题时全为随机补足"


@pytest.mark.asyncio
async def test_recommendations_validates_limit_range(client):
    token = await _register(client, "rec3")
    for bad in (0, 21, -1):
        r = await client.get(
            "/api/v1/mistakes/recommendations", params={"limit": bad}, headers=_auth(token)
        )
        assert r.status_code == 422, f"limit={bad} 应被拒绝"


@pytest.mark.asyncio
async def test_recommendations_exclude_mastered_exercises(client, factory):
    ex = await _add_exercise(factory, knowledge_tags=["循环"])
    other = await _add_exercise(factory, stem="另一题", knowledge_tags=["循环"], difficulty=2)
    token = await _register(client, "rec4")
    uid = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]["id"]
    await _add_entry(factory, uid, ex.id, wrong_count=1, mastered=True, mastered_at=NOW)

    data = (
        await client.get("/api/v1/mistakes/recommendations", headers=_auth(token))
    ).json()["data"]
    picked = {i["exercise"]["id"] for i in data["items"]}
    assert ex.id not in picked, "推荐排除已掌握"
    assert other.id in picked


@pytest.mark.asyncio
async def test_mistake_book_closed_loop_after_submit(client, factory):
    """端到端：答错 → 错题本出现条目 → 推荐命中薄弱 tag（P5 特性主链路）。"""
    ex = await _add_exercise(factory, knowledge_tags=["推导式"], difficulty=3)
    token = await _register(client, "loop")

    await client.post(
        f"/api/v1/exercises/{ex.id}/submit", json={"answer": "A"}, headers=_auth(token)
    )

    items = (await client.get("/api/v1/mistakes", headers=_auth(token))).json()["data"]
    assert [i["exercise_id"] for i in items] == [ex.id]

    profile = (await client.get("/api/v1/mistakes/profile", headers=_auth(token))).json()["data"]
    assert profile == [{"knowledge_tag": "推导式", "wrong_count": 1}]

    rec = (await client.get("/api/v1/mistakes/recommendations", headers=_auth(token))).json()[
        "data"
    ]
    assert rec["weak_tags"] == ["推导式"]
    assert rec["items"][0]["filled_by"] == "profile"
