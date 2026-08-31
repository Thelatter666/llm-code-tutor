"""admin 用户 CRUD 的 HTTP 层测试（spec §6.2 admin 行 / §8.9，P6 Task 1）。

裁定红线（2026-08-31）：出参含 email 但永不含 hashed_password（裁定 4）；
PATCH schema 外字段一律 422（extra=forbid）；禁自删/自降权/自停用（4220）；
对其他 admin 的停用/降权须剩余 ≥1 名 active admin（裁定 1）；写操作落
admin_user_create / admin_user_update 审计且密码明文与哈希不进审计。
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.auth.user import ADMIN
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.infrastructure.persistence.models import (
    AuditLog,
    CodeAnalysis,
    CodeRun,
    CodeSession,
    Conversation,
    Exercise,
    KnowledgeBase,
    Message,
    MistakeBookEntry,
    Submission,
    User,
)
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


async def _register(c, username: str, password: str = PASSWORD) -> str:
    await c.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": password})
    return r.json()["data"]["access_token"]


async def _admin_token(c, factory, username="root") -> str:
    token = await _register(c, username)
    async with factory() as s:
        row = (await s.execute(select(User).where(User.username == username))).scalar_one()
        row.role = ADMIN
        await s.commit()
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _audit_count(factory, action: str) -> int:
    async with factory() as s:
        return (
            await s.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
            )
        ).scalar_one()


# ------------------------------------------------------------ 列表


@pytest.mark.asyncio
async def test_list_users_requires_admin(client):
    token = await _register(client, "student1")
    r = await client.get("/api/v1/admin/users", headers=_auth(token))
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_list_users_paginates_and_returns_total(client, factory):
    token = await _admin_token(client, factory)
    for i in range(3):
        await client.post(
            "/api/v1/admin/users",
            headers=_auth(token),
            json={"username": f"u{i}", "email": f"u{i}@x.com", "password": PASSWORD},
        )
    r = await client.get(
        "/api/v1/admin/users", headers=_auth(token), params={"page": 1, "page_size": 2}
    )
    data = r.json()["data"]
    assert data["total"] == 4 and len(data["items"]) == 2
    # 出参字段面（裁定 4）：含 email，不含密码
    item = data["items"][0]
    assert set(item) == {
        "id",
        "username",
        "email",
        "role",
        "status",
        "created_at",
        "last_login_at",
    }


@pytest.mark.asyncio
async def test_list_users_filters(client, factory):
    token = await _admin_token(client, factory)
    await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "alice", "email": "alice@x.com", "password": PASSWORD},
    )
    await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={
            "username": "bob",
            "email": "bob@x.com",
            "password": PASSWORD,
            "role": "admin",
            "status": "disabled",
        },
    )

    r = await client.get("/api/v1/admin/users", headers=_auth(token), params={"q": "ali"})
    assert [i["username"] for i in r.json()["data"]["items"]] == ["alice"]

    r = await client.get("/api/v1/admin/users", headers=_auth(token), params={"role": "admin"})
    usernames = {i["username"] for i in r.json()["data"]["items"]}
    # root（建号时被提升为 admin）与 bob 都是 admin
    assert usernames == {"bob", "root"}

    r = await client.get(
        "/api/v1/admin/users", headers=_auth(token), params={"status": "disabled"}
    )
    assert [i["username"] for i in r.json()["data"]["items"]] == ["bob"]

    r = await client.get(
        "/api/v1/admin/users", headers=_auth(token), params={"role": "teacher"}
    )
    assert r.status_code == 422


# ------------------------------------------------------------ 创建


@pytest.mark.asyncio
async def test_create_user_and_duplicate_4090(client, factory):
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "new1", "email": "new1@x.com", "password": PASSWORD},
    )
    assert r.json()["code"] == 0
    assert "hashed_password" not in r.json()["data"]

    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "new1", "email": "other@x.com", "password": PASSWORD},
    )
    assert r.json()["code"] == 4090

    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "new2", "email": "new1@x.com", "password": PASSWORD},
    )
    assert r.json()["code"] == 4090

    assert await _audit_count(factory, "admin_user_create") == 1


@pytest.mark.asyncio
async def test_create_user_rejects_weak_password_and_bad_role(client, factory):
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "weak", "email": "weak@x.com", "password": "short"},
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "bad", "email": "bad@x.com", "password": PASSWORD, "role": "teacher"},
    )
    assert r.status_code == 422


# ------------------------------------------------------------ 更新（软删除路径）


@pytest.mark.asyncio
async def test_patch_disable_is_soft_delete_keeps_login_blocked(client, factory):
    """软删除是日常路径：保留全部数据，登录与已发 token 都被 4030 拦下。"""
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "victim", "email": "victim@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=_auth(token),
        json={"status": "disabled"},
    )
    assert r.json()["data"]["status"] == "disabled"

    # 旧 token 立即失效（get_current_user 4030），数据仍在库里
    victim_token = await _register(client, "victim")
    r = await client.get("/api/v1/auth/me", headers=_auth(victim_token))
    assert r.json()["code"] == 4030

    async with factory() as s:
        row = await s.get(User, uid)
        assert row is not None and row.status == "disabled"

    # 重新启用后可正常使用
    await client.patch(
        f"/api/v1/admin/users/{uid}", headers=_auth(token), json={"status": "active"}
    )
    r = await client.get("/api/v1/auth/me", headers=_auth(victim_token))
    assert r.json()["code"] == 0


@pytest.mark.asyncio
async def test_patch_rejects_unknown_fields_and_empty_body(client, factory):
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "p1", "email": "p1@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{uid}", headers=_auth(token), json={"source": "seed"}
    )
    assert r.status_code == 422

    r = await client.patch(f"/api/v1/admin/users/{uid}", headers=_auth(token), json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_reset_password_takes_effect(client, factory):
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "p2", "email": "p2@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{uid}", headers=_auth(token), json={"password": "NewPass123!"}
    )
    assert r.json()["code"] == 0

    login = await client.post(
        "/api/v1/auth/login", json={"username": "p2", "password": "NewPass123!"}
    )
    assert login.json()["code"] == 0


@pytest.mark.asyncio
async def test_patch_unknown_user_4040(client, factory):
    token = await _admin_token(client, factory)
    r = await client.patch(
        "/api/v1/admin/users/no-such-id", headers=_auth(token), json={"status": "disabled"}
    )
    assert r.json()["code"] == 4040


# ------------------------------------------------------------ 裁定 1：自操作与末位 admin


@pytest.mark.asyncio
async def test_admin_cannot_change_own_role_or_status(client, factory):
    """裁定 1 扩面：自降权/自停用与自删同样锁死系统，一律 4220。"""
    token = await _admin_token(client, factory)
    me = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=_auth(token), json={"role": "student"}
    )
    assert r.json()["code"] == 4220

    r = await client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=_auth(token), json={"status": "disabled"}
    )
    assert r.json()["code"] == 4220

    # email / password 自改允许
    r = await client.patch(
        f"/api/v1/admin/users/{me['id']}",
        headers=_auth(token),
        json={"email": "root-new@x.com"},
    )
    assert r.json()["code"] == 0


@pytest.mark.asyncio
async def test_last_admin_guard_blocks_demote_of_other_admin(session):
    """裁定 1：操作后须剩余 ≥1 名 active admin，否则 4220。

    HTTP 层执行者本人必是 active admin 且自操作被禁，守卫在正常流量下不可达；
    这里直接在服务层构造「执行者已被库层停用」的反常前置态来验证不变量兜底。
    """
    from app.services.user_service import UserService

    admin_a = User(username="a", email="a@x.com", hashed_password="x", role=ADMIN)
    admin_b = User(username="b", email="b@x.com", hashed_password="x", role=ADMIN)
    session.add_all([admin_a, admin_b])
    await session.flush()

    # 反常前置态：执行者被库层手动停用（绕过本服务的软删除路径）
    admin_a.status = "disabled"
    await session.flush()

    with pytest.raises(Exception) as exc:
        await UserService(session).update(
            admin_b.id,
            fields={"role": "student"},
            admin_id=admin_a.id,
            request_id="t",
        )
    assert getattr(exc.value, "code", None) == 4220


@pytest.mark.asyncio
async def test_patch_update_writes_audit_without_secret_values(client, factory):
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "aud", "email": "aud@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]
    await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=_auth(token),
        json={"email": "aud2@x.com", "password": "NewPass123!"},
    )

    async with factory() as s:
        row = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "admin_user_update")
            )
        ).scalar_one()
    # password 字段在服务层转成 hashed_password 落库，审计记的是落库字段名
    assert sorted(row.detail["fields"]) == ["email", "hashed_password"]
    # 密码新值与新 email 值都不进审计 detail
    assert "NewPass123!" not in str(row.detail)
    assert "aud2@x.com" not in str(row.detail)


# ------------------------------------------------------------ 硬删除级联（Task 2）


async def _seed_user_with_all_data(factory, user_id: str) -> None:
    """造全七类关联数据（spec §8.9 级联清单）供删除用例。"""
    async with factory() as s:
        conv = Conversation(user_id=user_id, title="c")
        s.add(conv)
        await s.flush()
        s.add(Message(conversation_id=conv.id, role="user", content="hi"))
        exercise = Exercise(
            type="choice", stem="q", answer="A", difficulty=1, source="seed"
        )
        s.add(exercise)
        await s.flush()
        s.add(
            Submission(
                user_id=user_id,
                exercise_id=exercise.id,
                answer="A",
                is_correct=True,
                score=100,
            )
        )
        s.add(
            MistakeBookEntry(
                user_id=user_id,
                exercise_id=exercise.id,
                wrong_count=1,
                last_wrong_at=None,
            )
        )
        s.add(CodeSession(user_id=user_id, language="python", source_code="x"))
        s.add(
            CodeAnalysis(
                user_id=user_id,
                language="python",
                source_hash="h1",
                static_report={"issues": []},
            )
        )
        s.add(
            CodeRun(
                user_id=user_id,
                language="python",
                source_code="x",
                status="accepted",
                stdout="",
                stderr="",
            )
        )
        # 审计行是「不级联例外」之一：硬删除后必须原样保留
        s.add(AuditLog(user_id=user_id, action="login", target_type="user"))
        await s.commit()


@pytest.mark.asyncio
async def test_hard_delete_cascades_all_tables_and_keeps_audit(client, factory):
    """spec §8.9：七表级联归零、AuditLog 一律保留、计数进删除审计。"""
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "victim", "email": "victim@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]
    await _seed_user_with_all_data(factory, uid)

    r = await client.delete(f"/api/v1/admin/users/{uid}", headers=_auth(token))
    assert r.json()["code"] == 0
    assert r.json()["data"]["deleted"] is True
    assert r.json()["data"]["conversations_deleted"] == 1
    assert r.json()["data"]["messages_deleted"] == 1
    assert r.json()["data"]["submissions_deleted"] == 1
    assert r.json()["data"]["mistake_entries_deleted"] == 1
    assert r.json()["data"]["code_sessions_deleted"] == 1
    assert r.json()["data"]["code_analyses_deleted"] == 1
    assert r.json()["data"]["code_runs_deleted"] == 1

    async with factory() as s:
        assert await s.get(User, uid) is None
        # 七表全部归零
        assert (
            (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 0
        )
        assert (
            (await s.execute(select(func.count()).select_from(Conversation))).scalar_one()
            == 0
        )
        assert (
            (
                await s.execute(
                    select(func.count())
                    .select_from(Submission)
                    .where(Submission.user_id == uid)
                )
            ).scalar_one()
            == 0
        )
        assert (
            (
                await s.execute(
                    select(func.count())
                    .select_from(MistakeBookEntry)
                    .where(MistakeBookEntry.user_id == uid)
                )
            ).scalar_one()
            == 0
        )
        assert (
            (
                await s.execute(
                    select(func.count())
                    .select_from(CodeSession)
                    .where(CodeSession.user_id == uid)
                )
            ).scalar_one()
            == 0
        )
        assert (
            (
                await s.execute(
                    select(func.count())
                    .select_from(CodeAnalysis)
                    .where(CodeAnalysis.user_id == uid)
                )
            ).scalar_one()
            == 0
        )
        assert (
            (
                await s.execute(
                    select(func.count())
                    .select_from(CodeRun)
                    .where(CodeRun.user_id == uid)
                )
            ).scalar_one()
            == 0
        )
        # AuditLog 不随用户删除（spec §8.9：审计可追溯性优先）
        kept = (
            await s.execute(select(AuditLog).where(AuditLog.user_id == uid))
        ).scalars().all()
        assert {row.action for row in kept} == {"login"}

        # 删除操作本身的审计行带级联计数
        delete_log = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "admin_user_delete")
            )
        ).scalar_one()
        assert delete_log.detail["submissions_deleted"] == 1
        assert delete_log.detail["code_runs_deleted"] == 1


@pytest.mark.asyncio
async def test_hard_delete_unknown_user_4040(client, factory):
    token = await _admin_token(client, factory)
    r = await client.delete("/api/v1/admin/users/no-such", headers=_auth(token))
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_hard_delete_self_rejected_4220(client, factory):
    """裁定 1：禁自删 —— 最后一个管理员不能被自己锁死系统。"""
    token = await _admin_token(client, factory)
    me = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]
    r = await client.delete(f"/api/v1/admin/users/{me['id']}", headers=_auth(token))
    assert r.json()["code"] == 4220


@pytest.mark.asyncio
async def test_hard_delete_last_admin_guard(session):
    """裁定 1：删其他 admin 后须剩余 ≥1 名 active admin（服务层不变量兜底）。"""
    from app.services.user_service import UserService

    admin_a = User(username="da", email="da@x.com", hashed_password="x", role=ADMIN)
    admin_b = User(username="db", email="db@x.com", hashed_password="x", role=ADMIN)
    session.add_all([admin_a, admin_b])
    await session.flush()

    # 反常前置态：执行者被库层手动停用
    admin_a.status = "disabled"
    await session.flush()

    with pytest.raises(Exception) as exc:
        await UserService(session).delete(
            admin_b.id, admin_id=admin_a.id, request_id="t"
        )
    assert getattr(exc.value, "code", None) == 4220


@pytest.mark.asyncio
async def test_hard_delete_keeps_owned_knowledge_base(client, factory):
    """裁定 9：KB.owner_id 悬空例外 —— 删除建库管理员不级联知识库、展示不 5000。"""
    token = await _admin_token(client, factory)
    r = await client.post(
        "/api/v1/admin/users",
        headers=_auth(token),
        json={"username": "kbowner", "email": "kbowner@x.com", "password": PASSWORD},
    )
    uid = r.json()["data"]["id"]

    async with factory() as s:
        s.add(KnowledgeBase(name="kb-of-victim", owner_id=uid))
        await s.commit()

    await client.delete(f"/api/v1/admin/users/{uid}", headers=_auth(token))

    # 知识库行保留，owner_id 悬空指向已删除用户
    async with factory() as s:
        kb = (await s.execute(select(KnowledgeBase))).scalar_one()
        assert kb.name == "kb-of-victim" and kb.owner_id == uid

    # 展示路径（学生端列表）对 owner 缺失容忍：200 + 数据仍在，不是 5000
    student_token = await _register(client, "student-kb")
    r = await client.get("/api/v1/knowledge/bases", headers=_auth(student_token))
    assert r.json()["code"] == 0
    assert "kb-of-victim" in [b["name"] for b in r.json()["data"]]
