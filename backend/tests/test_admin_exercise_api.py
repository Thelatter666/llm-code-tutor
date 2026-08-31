"""admin 习题 CRUD 的 HTTP 层测试（spec §6.2 缺口补全，P5 Task 11）。

三条裁定红线：PATCH 的 schema 外字段（含 `source`）一律 **422 显式拒绝**、
不静默忽略；`source` 由服务端写死；DELETE 手工级联删 Submission + 错题条目并在
审计 detail 记删除数（全库无 ForeignKey，M-2 现状）。
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
    Exercise,
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


async def _admin_token(c, factory, username="root"):
    token = await _register(c, username)
    async with factory() as s:
        row = (
            await s.execute(select(User).where(User.username == username))
        ).scalar_one()
        row.role = ADMIN
        await s.commit()
    return token


def _auth(token: str, rid: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if rid:
        headers["x-request-id"] = rid
    return headers


def _choice_body(**over) -> dict:
    body: dict = {
        "type": "choice",
        "stem": "以下哪个是合法的变量名？",
        "options": {"A": "2name", "B": "user_name"},
        "answer": "B",
        "explanation": "标识符不能以数字开头",
        "knowledge_tags": ["变量与赋值"],
        "difficulty": 1,
    }
    body.update(over)
    return body


async def _create(client, token, body):
    return await client.post("/api/v1/admin/exercises", json=body, headers=_auth(token))


# ---------------------------------------------------------------- 鉴权与角色


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/v1/admin/exercises", {"type": "blank", "stem": "x", "answer": "y", "difficulty": 1}),
        ("get", "/api/v1/admin/exercises", None),
        ("get", "/api/v1/admin/exercises/e1", None),
        ("patch", "/api/v1/admin/exercises/e1", {"status": "published"}),
        ("delete", "/api/v1/admin/exercises/e1", None),
    ],
)
async def test_admin_endpoints_require_auth(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 401
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/v1/admin/exercises", {"type": "blank", "stem": "x", "answer": "y", "difficulty": 1}),
        ("get", "/api/v1/admin/exercises", None),
        ("get", "/api/v1/admin/exercises/e1", None),
        ("patch", "/api/v1/admin/exercises/e1", {"status": "published"}),
        ("delete", "/api/v1/admin/exercises/e1", None),
    ],
)
async def test_student_is_forbidden(client, factory, method, path, body):
    token = await _register(client, "student-one")
    kwargs = {"json": body} if body is not None else {}
    r = await getattr(client, method)(path, headers=_auth(token), **kwargs)
    assert r.status_code == 403
    assert r.json()["code"] == 4030


# ---------------------------------------------------------------- 创建


@pytest.mark.asyncio
async def test_create_writes_admin_source_and_creator(client, factory):
    token = await _admin_token(client, factory)
    r = await _create(client, token, _choice_body())

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["source"] == "admin", "source 由服务端写死"
    assert data["status"] == "draft", "缺省不对外可见"
    assert data["answer"] == "B"
    assert data["explanation"] == "标识符不能以数字开头"
    async with factory() as s:
        admin = (
            await s.execute(select(User).where(User.username == "root"))
        ).scalars().one()
    assert data["created_by"] == admin.id

    async with factory() as s:
        row = await s.get(Exercise, data["id"])
        assert row.created_by == admin.id


@pytest.mark.asyncio
async def test_create_ignores_source_from_body_but_keeps_it_admin(client, factory):
    """POST 的 body 没有 source 字段：传 seed/ai 也只是「schema 外字段」，落 admin。

    与 PATCH 的差异是裁定过的：创建时 source 根本不由学生/管理员决定，
    覆盖即可；PATCH 时它是「改不动的字段」，静默忽略会变成「看起来成功实际没生效」。
    """
    token = await _admin_token(client, factory, "root2")
    r = await _create(client, token, _choice_body(source="seed"))
    assert r.status_code == 200
    assert r.json()["data"]["source"] == "admin"


@pytest.mark.asyncio
async def test_create_can_publish_immediately(client, factory):
    token = await _admin_token(client, factory, "root3")
    r = await _create(client, token, _choice_body(status="published"))
    assert r.json()["data"]["status"] == "published"


@pytest.mark.asyncio
async def test_create_writes_audit(client, factory):
    token = await _admin_token(client, factory, "root4")
    r = await _create(client, token, _choice_body())
    async with factory() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admin_exercise_create"))
        ).scalar_one()
    assert row.target_type == "exercise"
    assert row.target_id == r.json()["data"]["id"]
    assert row.detail["type"] == "choice"


# ---------------------------------------------------------------- 写入校验


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        # multi 缺 options
        {"type": "multi", "stem": "哪些是可变类型？", "answer": ["A", "B"], "difficulty": 2},
        # multi answer 键不在 options
        {
            "type": "multi",
            "stem": "哪些是可变类型？",
            "options": {"A": "list", "B": "dict"},
            "answer": ["A", "Z"],
            "difficulty": 2,
        },
        # multi 空答案
        {
            "type": "multi",
            "stem": "哪些是可变类型？",
            "options": {"A": "list", "B": "dict"},
            "answer": [],
            "difficulty": 2,
        },
        # choice answer 不在 options
        {
            "type": "choice",
            "stem": "哪个是？",
            "options": {"A": "1", "B": "2"},
            "answer": "Z",
            "difficulty": 1,
        },
        # choice 缺 options
        {"type": "choice", "stem": "哪个是？", "answer": "A", "difficulty": 1},
        # coding 缺 test_cases
        {
            "type": "coding",
            "stem": "读一个整数并输出它的平方",
            "answer": {"language": "python", "solution": "print(int(input())**2)"},
            "difficulty": 2,
        },
        # coding test_cases 缺 cases
        {
            "type": "coding",
            "stem": "读一个整数并输出它的平方",
            "answer": {"language": "python", "solution": "print(int(input())**2)"},
            "test_cases": {"language": "python", "cases": []},
            "difficulty": 2,
        },
        # coding test_cases 缺 language
        {
            "type": "coding",
            "stem": "读一个整数并输出它的平方",
            "answer": {"language": "python", "solution": "print(int(input())**2)"},
            "test_cases": {"cases": [{"expected_stdout": "4"}]},
            "difficulty": 2,
        },
        # coding 答案不是对象
        {
            "type": "coding",
            "stem": "读一个整数并输出它的平方",
            "answer": "print(1)",
            "test_cases": {"language": "python", "cases": [{"expected_stdout": "4"}]},
            "difficulty": 2,
        },
        # 用例缺 expected_stdout
        {
            "type": "coding",
            "stem": "读一个整数并输出它的平方",
            "answer": {"language": "python", "solution": "print(1)"},
            "test_cases": {"language": "python", "cases": [{"stdin": "2"}]},
            "difficulty": 2,
        },
        # blank 答案必须是字符串
        {
            "type": "blank",
            "stem": "len 的返回值类型是 ____",
            "answer": ["int"],
            "difficulty": 1,
        },
        # short 答案必须是字符串
        {
            "type": "short",
            "stem": "说明什么是闭包",
            "answer": {"text": "闭包"},
            "difficulty": 3,
        },
        # blank 不该带 options
        {
            "type": "blank",
            "stem": "len 的返回值类型是 ____",
            "options": {"A": "int"},
            "answer": "int",
            "difficulty": 1,
        },
        # 题型枚举
        {
            "type": "essay",
            "stem": "写点东西",
            "answer": "x",
            "difficulty": 1,
        },
        # difficulty 越界
        _choice_body(difficulty=6),
        _choice_body(difficulty=0),
        # 空题干
        _choice_body(stem=""),
    ],
)
async def test_create_rejects_bad_shapes(client, factory, body):
    token = await _admin_token(client, factory, "validator")
    r = await _create(client, token, body)
    assert r.status_code == 422, f"{body.get('type')} 的脏数据应被拒绝：{r.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        _choice_body(),
        {
            "type": "multi",
            "stem": "哪些是可变类型？",
            "options": {"A": "list", "B": "dict", "C": "tuple"},
            "answer": ["A", "B"],
            "difficulty": 2,
            "knowledge_tags": ["列表", "字典"],
        },
        {
            "type": "blank",
            "stem": "len 的返回值类型是 ____",
            "answer": "int",
            "difficulty": 1,
            "knowledge_tags": ["数据类型"],
        },
        {
            "type": "short",
            "stem": "说明什么是闭包",
            "answer": "内层函数引用外层函数变量，且外层已返回",
            "explanation": "关键在引用有效期",
            "difficulty": 4,
            "knowledge_tags": ["函数"],
        },
        {
            "type": "coding",
            "stem": "读一个整数，输出它的平方",
            "answer": {"language": "python", "solution": "print(int(input()) ** 2)"},
            "test_cases": {
                "language": "python",
                "cases": [
                    {"stdin": "2\n", "expected_stdout": "4"},
                    {"stdin": "3\n", "expected_stdout": "9"},
                ],
            },
            "difficulty": 2,
            "knowledge_tags": ["运算符"],
        },
    ],
)
async def test_create_accepts_every_type_shape(client, factory, body):
    token = await _admin_token(client, factory, "acceptor")
    r = await _create(client, token, body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["type"] == body["type"]


@pytest.mark.asyncio
async def test_create_rejects_difficulty_out_of_range_as_422(client, factory):
    token = await _admin_token(client, factory, "range")
    r = await _create(client, token, _choice_body(difficulty=99))
    assert r.status_code == 422


# ---------------------------------------------------------------- 列表与详情


@pytest.mark.asyncio
async def test_list_includes_drafts_and_paginates(client, factory):
    token = await _admin_token(client, factory, "lister")
    for i in range(3):
        await _create(client, token, _choice_body(stem=f"习题 {i}", difficulty=1 + i))
    await _create(client, token, _choice_body(stem="已发布", status="published", difficulty=5))

    r = await client.get(
        "/api/v1/admin/exercises", params={"page": 1, "page_size": 2}, headers=_auth(token)
    )
    data = r.json()["data"]
    assert data["total"] == 4
    assert len(data["items"]) == 2
    # admin 列表回完整字段（学生端看不到的 draft 与答案都在这里）
    assert data["items"][0]["answer"] == "B"


@pytest.mark.asyncio
async def test_list_filters_by_status_type_difficulty_tag(client, factory):
    token = await _admin_token(client, factory, "filterer")
    await _create(client, token, _choice_body(stem="草稿选择", difficulty=1))
    await _create(client, token, _choice_body(stem="发布选择", status="published", difficulty=1))
    await _create(
        client,
        token,
        {
            "type": "blank",
            "stem": "填空",
            "answer": "int",
            "difficulty": 3,
            "knowledge_tags": ["数据类型"],
            "status": "published",
        },
    )

    auth = _auth(token)

    drafts = (
        await client.get("/api/v1/admin/exercises", params={"status": "draft"}, headers=auth)
    ).json()["data"]
    assert [i["stem"] for i in drafts["items"]] == ["草稿选择"]

    published = (
        await client.get("/api/v1/admin/exercises", params={"status": "published"}, headers=auth)
    ).json()["data"]
    assert published["total"] == 2

    blanks = (
        await client.get("/api/v1/admin/exercises", params={"type": "blank"}, headers=auth)
    ).json()["data"]
    assert [i["stem"] for i in blanks["items"]] == ["填空"]

    hard = (
        await client.get("/api/v1/admin/exercises", params={"difficulty": 3}, headers=auth)
    ).json()["data"]
    assert hard["total"] == 1

    by_tag = (
        await client.get(
            "/api/v1/admin/exercises", params={"knowledge_tag": "数据类型"}, headers=auth
        )
    ).json()["data"]
    assert by_tag["total"] == 1

    r = await client.get(
        "/api/v1/admin/exercises", params={"status": "archived"}, headers=auth
    )
    assert r.status_code == 422, "status 取值封闭"


@pytest.mark.asyncio
async def test_detail_exposes_answer_and_missing_is_4040(client, factory):
    token = await _admin_token(client, factory, "detailer")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.get(f"/api/v1/admin/exercises/{created['id']}", headers=_auth(token))
    data = r.json()["data"]
    assert data["answer"] == "B"
    assert data["explanation"] == "标识符不能以数字开头"
    assert data["source"] == "admin"

    r = await client.get("/api/v1/admin/exercises/no-such", headers=_auth(token))
    assert r.status_code == 404
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_admin_detail_shows_draft_that_student_endpoint_hides(client, factory):
    token = await _admin_token(client, factory, "visibility")
    student = await _register(client, "watcher")
    created = (await _create(client, token, _choice_body())).json()["data"]

    admin_view = await client.get(f"/api/v1/admin/exercises/{created['id']}", headers=_auth(token))
    assert admin_view.status_code == 200
    student_view = await client.get(
        f"/api/v1/exercises/{created['id']}", headers=_auth(student)
    )
    assert student_view.status_code == 404, "draft 对学生不可见（spec §6.2）"


# ---------------------------------------------------------------- 更新


@pytest.mark.asyncio
async def test_patch_publishing_makes_it_visible_to_students(client, factory):
    token = await _admin_token(client, factory, "publisher")
    student = await _register(client, "learner")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}",
        json={"status": "published"},
        headers=_auth(token, "rid-patch"),
    )

    assert r.status_code == 200
    assert r.json()["request_id"] == "rid-patch"
    assert r.json()["data"]["status"] == "published"
    visible = await client.get(f"/api/v1/exercises/{created['id']}", headers=_auth(student))
    assert visible.status_code == 200


@pytest.mark.asyncio
async def test_patch_updates_fields_and_keeps_source(client, factory):
    token = await _admin_token(client, factory, "editor")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}",
        json={
            "stem": "改过的题干：哪个变量名合法？",
            "difficulty": 4,
            "knowledge_tags": ["变量与赋值", "数据类型"],
            "explanation": "改过的解析",
        },
        headers=_auth(token),
    )

    data = r.json()["data"]
    assert data["stem"] == "改过的题干：哪个变量名合法？"
    assert data["difficulty"] == 4
    assert data["knowledge_tags"] == ["变量与赋值", "数据类型"]
    assert data["explanation"] == "改过的解析"
    assert data["source"] == "admin", "PATCH 不改 source"
    assert data["answer"] == "B", "未提供的字段保持原值"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"source": "seed"},
        {"source": "ai"},
        {"created_by": "someone-else"},
        {"id": "override-me"},
        {"totally_unknown": 1},
        {},
    ],
)
async def test_patch_rejects_out_of_schema_fields(client, factory, patch):
    """裁定 1 修订：schema 外字段（含 source）一律 422，不静默忽略。"""
    token = await _admin_token(client, factory, "patcher")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}", json=patch, headers=_auth(token)
    )
    assert r.status_code == 422, f"{patch} 应被显式拒绝"


@pytest.mark.asyncio
async def test_patch_answer_must_stay_consistent_with_type(client, factory):
    """合并后重新校验跨题型形状：改答案改到与 options 不匹配 → 422。"""
    token = await _admin_token(client, factory, "consistency")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}", json={"answer": "Z"}, headers=_auth(token)
    )
    assert r.status_code == 422
    async with factory() as s:
        row = await s.get(Exercise, created["id"])
        assert row.answer == "B", "校验失败不得留下半截改动"


@pytest.mark.asyncio
async def test_patch_coding_requires_test_cases(client, factory):
    """把 choice 改成 coding 而没有 test_cases → 422（合并校验）。"""
    token = await _admin_token(client, factory, "morph")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}",
        json={"type": "coding", "answer": {"language": "python", "solution": "print(1)"}},
        headers=_auth(token),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"stem": None},
        {"type": None},
        {"difficulty": None},
        {"status": None},
        {"knowledge_tags": None},
        {"explanation": None},
        {"answer": None},
    ],
)
async def test_patch_rejects_explicit_null_on_non_null_columns(client, factory, patch):
    """显式 null 若放过，落库时才撞 NOT NULL → 5000。入口就该 422。"""
    token = await _admin_token(client, factory, "nuller")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}", json=patch, headers=_auth(token)
    )
    assert r.status_code == 422, f"{patch} 应被入口拒绝而不是 500"
    async with factory() as s:
        row = await s.get(Exercise, created["id"])
        assert row.difficulty == 1 and row.status == "draft", "拒绝后不得留下改动"


@pytest.mark.asyncio
async def test_patch_options_null_is_accepted_but_shape_checked(client, factory):
    """options 是真可空列：清空 choice 的 options 由合并校验拒（不是 NOT NULL 崩溃）。"""
    token = await _admin_token(client, factory, "nuller2")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.patch(
        f"/api/v1/admin/exercises/{created['id']}", json={"options": None}, headers=_auth(token)
    )
    assert r.status_code == 422, "choice 没有 options 就是判不了的脏数据"

    blank = (
        await _create(
            client, token, {"type": "blank", "stem": "填空", "answer": "int", "difficulty": 1}
        )
    ).json()["data"]
    ok = await client.patch(
        f"/api/v1/admin/exercises/{blank['id']}", json={"options": None}, headers=_auth(token)
    )
    assert ok.status_code == 200, "blank 的 options 本就该为空"


@pytest.mark.asyncio
async def test_patch_missing_exercise_is_4040(client, factory):
    token = await _admin_token(client, factory, "ghost")
    r = await client.patch("/api/v1/admin/exercises/no-such", json={"status": "published"}, headers=_auth(token))
    assert r.status_code == 404
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_patch_writes_audit(client, factory):
    token = await _admin_token(client, factory, "auditor")
    created = (await _create(client, token, _choice_body())).json()["data"]

    await client.patch(
        f"/api/v1/admin/exercises/{created['id']}",
        json={"status": "published"},
        headers=_auth(token, "rid-patch-audit"),
    )

    async with factory() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admin_exercise_update"))
        ).scalar_one()
    assert row.target_id == created["id"]
    assert row.request_id == "rid-patch-audit"
    assert row.detail["fields"] == ["status"], "审计只记改了哪些字段，不回填值"


# ---------------------------------------------------------------- 删除与级联


@pytest.mark.asyncio
async def test_delete_cascades_submissions_and_mistake_entries(client, factory):
    token = await _admin_token(client, factory, "deleter")
    student = await _register(client, "victim")
    created = (
        await _create(client, token, _choice_body(status="published"))
    ).json()["data"]

    # 一次错误提交：自动落 Submission 与错题条目
    await client.post(
        f"/api/v1/exercises/{created['id']}/submit",
        json={"answer": "A"},
        headers=_auth(student),
    )
    async with factory() as s:
        assert len(list((await s.execute(select(Submission))).scalars().all())) == 1
        assert len(list((await s.execute(select(MistakeBookEntry))).scalars().all())) == 1

    r = await client.delete(
        f"/api/v1/admin/exercises/{created['id']}", headers=_auth(token, "rid-del")
    )
    assert r.status_code == 200
    assert r.json()["data"] == {
        "deleted": True,
        "submissions_deleted": 1,
        "mistake_entries_deleted": 1,
    }

    async with factory() as s:
        assert await s.get(Exercise, created["id"]) is None
        assert (
            await s.execute(select(func.count()).select_from(Submission))
        ).scalar_one() == 0
        assert (
            await s.execute(select(func.count()).select_from(MistakeBookEntry))
        ).scalar_one() == 0

    # 级联删后学生端与错题本都不该再看到它
    still_gone = await client.get(f"/api/v1/exercises/{created['id']}", headers=_auth(student))
    assert still_gone.status_code == 404
    mistakes = (await client.get("/api/v1/mistakes", headers=_auth(student))).json()["data"]
    assert mistakes == []


@pytest.mark.asyncio
async def test_delete_records_counts_in_audit(client, factory):
    token = await _admin_token(client, factory, "counter")
    created = (
        await _create(client, token, _choice_body(status="published"))
    ).json()["data"]
    student = await _register(client, "submitter-two")
    await client.post(
        f"/api/v1/exercises/{created['id']}/submit",
        json={"answer": "A"},
        headers=_auth(student),
    )

    await client.delete(f"/api/v1/admin/exercises/{created['id']}", headers=_auth(token))

    async with factory() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admin_exercise_delete"))
        ).scalar_one()
    assert row.target_type == "exercise"
    assert row.target_id == created["id"]
    assert row.detail["submissions_deleted"] == 1
    assert row.detail["mistake_entries_deleted"] == 1
    assert row.detail["stem"] == "以下哪个是合法的变量名？"


@pytest.mark.asyncio
async def test_delete_of_missing_exercise_is_4040(client, factory):
    token = await _admin_token(client, factory, "nuker")
    r = await client.delete("/api/v1/admin/exercises/no-such", headers=_auth(token))
    assert r.status_code == 404
    assert r.json()["code"] == 4040


@pytest.mark.asyncio
async def test_delete_without_dependencies_reports_zero_counts(client, factory):
    token = await _admin_token(client, factory, "cleaner")
    created = (await _create(client, token, _choice_body())).json()["data"]

    r = await client.delete(f"/api/v1/admin/exercises/{created['id']}", headers=_auth(token))
    assert r.json()["data"]["submissions_deleted"] == 0
    assert r.json()["data"]["mistake_entries_deleted"] == 0
