# P0 基座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建可一键启动的系统基座 —— 单 worker FastAPI 服务、SQLite(WAL) 持久化、统一响应与异常处理、端口抽象与 Provider 注册表（含 Mock 与 OpenAI 兼容两个 LLM 实现）、用户鉴权、审计日志、种子数据，以及可登录的前端骨架。

**Architecture:** 模块化单体，单进程单 worker。后端按 `routers → services → domain → infrastructure` 分层，领域层零 IO，外部能力以 `Protocol` 端口抽象、由 `ProviderRegistry` 依据 `ModelConfig.revision` 解析具体实现并缓存。前端为 Vue 3 + Vite + TypeScript + Element Plus，`make dev` 双端口开发、`make serve` 单端口演示。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) + aiosqlite · Pydantic v2 + pydantic-settings · PyJWT · bcrypt · httpx · Jinja2 · cryptography(Fernet) · pytest + pytest-asyncio · Vue 3 · Vite · TypeScript · Element Plus · Pinia · Vue Router · Axios

## Global Constraints

以下约束逐字摘自 spec，每个任务默认包含，不再重复说明。

- 单进程单 worker：`uvicorn --workers 1`（ADR-0002）
- SQLite 连接必须开 `PRAGMA journal_mode=WAL`、`busy_timeout=5000`、`foreign_keys=ON`
- 不做数据库迁移，建表用 `create_all`（ADR-0006）
- 统一响应体：`{code, message, data, request_id}`；未捕获异常统一 `code=5000` 且不暴露堆栈
- 领域层（`backend/app/domain/`）禁止 import 任何基础设施模块
- 服务层只依赖 `Protocol` 端口，不依赖具体 adapter（ADR-0001）
- JWT 存前端 `localStorage`（spec §2）
- 所有同步阻塞调用须经 `run_in_threadpool` 卸载（ADR-0002）
- 术语以 `CONTEXT.md` 为唯一来源，代码标识符与注释不得自造术语
- 每个任务完成后独立 commit，commit 前必须全量测试通过

---

## File Structure

```
backend/
├── pyproject.toml              依赖与工具配置
├── .env.example
├── app/
│   ├── main.py                 FastAPI 入口、全局异常处理、SPA 托管
│   ├── seed.py                 make seed 入口（幂等）
│   ├── core/
│   │   ├── config.py           Settings（pydantic-settings）
│   │   ├── crypto.py           Fernet 加解密与 .secret_key 自举
│   │   ├── errors.py           ApiError 与错误码常量
│   │   ├── responses.py        统一响应封装与 request_id 中间件
│   │   ├── security.py         密码哈希与 JWT
│   │   └── deps.py             依赖注入：DB session、当前用户、角色校验
│   ├── domain/
│   │   └── auth/user.py        User 角色/状态规则（零 IO）
│   ├── services/
│   │   ├── auth_service.py     注册/登录用例编排
│   │   └── audit_service.py    审计日志写入
│   ├── routers/
│   │   └── auth.py             auth 路由
│   ├── schemas/
│   │   ├── common.py           ApiResponse、Page
│   │   └── auth.py             出入参模型
│   └── infrastructure/
│       ├── ports/llm.py        LLMPort 端口定义
│       ├── registry.py         ProviderRegistry（按 revision 缓存）
│       ├── adapters/llm/
│       │   ├── mock_provider.py
│       │   └── openai_compat.py
│       └── persistence/
│           ├── db.py           engine / session / WAL
│           └── models.py       全量表定义
└── tests/
    ├── conftest.py
    ├── test_smoke.py · test_db.py · test_responses.py
    ├── test_registry.py · test_mock_provider.py · test_llm_contract.py
    ├── test_security.py · test_auth_deps.py · test_audit.py
    ├── test_auth_api.py · test_seed.py · test_ops.py · test_static_hosting.py

frontend/
├── package.json · vite.config.ts · tsconfig.json · index.html
└── src/
    ├── env.d.ts · main.ts · App.vue
    ├── api/{client.ts,auth.ts}
    ├── stores/auth.ts
    ├── router/index.ts
    ├── types/api.ts
    └── views/{LoginView.vue,HomeView.vue}

Makefile                        install / install-lite / dev / serve / test / seed / lint
```

---

## Task 1: 后端项目骨架与依赖

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_smoke.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `app.main:app`（FastAPI 实例）。后续任务全部挂载于此。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_smoke.py
from fastapi import FastAPI

from app.main import app


def test_app_is_fastapi_instance():
    assert isinstance(app, FastAPI)


def test_app_title_is_set():
    assert app.title == "LLM Programming Tutor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write minimal implementation**

```toml
# backend/pyproject.toml
[project]
name = "llm-code-tutor-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "pyjwt>=2.9",
    "bcrypt>=4.2",
    "httpx>=0.27",
    "jinja2>=3.1",
    "python-multipart>=0.0.12",
    "cryptography>=44",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.8"]
local-embed = ["sentence-transformers>=3.0", "torch>=2.5"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

```python
# backend/app/main.py
from fastapi import FastAPI

app = FastAPI(title="LLM Programming Tutor")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_smoke.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/main.py backend/tests/test_smoke.py
git commit -m "feat(backend): 项目骨架与依赖声明"
```

---

## Task 2: 配置加载与数据库连接（WAL + create_all）

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/infrastructure/persistence/db.py`
- Create: `backend/app/infrastructure/persistence/models.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_db.py`

**Interfaces:**
- Consumes: 无
- Produces: `get_session()`、`init_db()`、`Base`、`User`、`ModelConfig`、`AuditLog`。后续任务通过 `Depends(get_session)` 取会话。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_db.py
import pytest
from sqlalchemy import select, text

from app.infrastructure.persistence.db import init_db
from app.infrastructure.persistence.models import User


@pytest.mark.asyncio
async def test_init_db_creates_tables(engine):
    await init_db(engine)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        names = {r[0] for r in rows}
    assert {"users", "model_configs", "audit_logs"} <= names


@pytest.mark.asyncio
async def test_user_roundtrip(session):
    user = User(username="stu001", email="stu001@example.com", hashed_password="x")
    session.add(user)
    await session.commit()

    got = (await session.execute(select(User).where(User.username == "stu001"))).scalar_one()
    assert got.email == "stu001@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure'`

- [ ] **Step 3: Write conftest**

```python
# backend/tests/conftest.py
import os

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("APP_SECRET_PATH", ".secret_key.test")


@pytest_asyncio.fixture
async def engine():
    from app.infrastructure.persistence.db import Base, _apply_pragmas

    eng = create_async_engine(os.environ["DATABASE_URL"])
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
```

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/core/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LLM Programming Tutor"
    env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    app_secret_path: str = ".secret_key"
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/app/infrastructure/persistence/db.py
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _apply_pragmas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _build_engine():
    url = get_settings().database_url
    if url.startswith("sqlite") and ":///" in url and ":memory:" not in url:
        Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, future=True)
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


engine = _build_engine()
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db(target_engine=None) -> None:
    from app.infrastructure.persistence import models  # noqa: F401

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
```

```python
# backend/app/infrastructure/persistence/models.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="student")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String, default="mock")
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String, default="mock-1")
    temperature: Mapped[float] = mapped_column(default=0.7)
    top_p: Mapped[float] = mapped_column(default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    anti_plagiarism_mode: Mapped[str] = mapped_column(String, default="guided")
    score_threshold: Mapped[float] = mapped_column(default=0.35)
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/infrastructure/persistence backend/tests/conftest.py backend/tests/test_db.py
git commit -m "feat(backend): 配置加载与 SQLite(WAL) 持久化"
```

---

## Task 3: 统一响应与全局异常处理

**Files:**
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/responses.py`
- Create: `backend/app/schemas/common.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_responses.py`

**Interfaces:**
- Consumes: 无
- Produces: `ApiError(code, message)`、`ok(data, request_id=...)`、`install_request_id`、`install_exception_handlers`。后续所有路由依赖。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_responses.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ApiError, install_exception_handlers
from app.core.responses import install_request_id, ok


def _build() -> TestClient:
    app = FastAPI()
    install_request_id(app)
    install_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret stack detail")

    @app.get("/biz")
    async def biz():
        raise ApiError(4040, "资源不存在")

    @app.get("/good")
    async def good():
        return ok({"a": 1}, request_id="rid-1")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_error_returns_5000_without_stack():
    r = _build().get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == 5000
    assert "secret stack detail" not in r.text


def test_api_error_maps_to_status_and_code():
    r = _build().get("/biz")
    assert r.status_code == 404
    assert r.json()["code"] == 4040


def test_ok_response_shape():
    body = _build().get("/good").json()
    assert body == {"code": 0, "message": "ok", "data": {"a": 1}, "request_id": "rid-1"}


def test_request_id_is_injected_and_echoed():
    assert _build().get("/good").headers.get("x-request-id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_responses.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.errors'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/errors.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CODE_STATUS = {
    4010: 401,
    4030: 403,
    4040: 404,
    4090: 409,
    4290: 429,
    5000: 500,
    5021: 502,
    5032: 503,
}


class ApiError(Exception):
    def __init__(self, code: int, message: str, status: int | None = None):
        self.code = code
        self.message = message
        self.status = status or CODE_STATUS.get(code, 400)
        super().__init__(message)


def _payload(code: int, message: str, request_id: str) -> dict:
    return {"code": code, "message": message, "data": None, "request_id": request_id}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content=_payload(exc.code, exc.message, getattr(request.state, "request_id", "")),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_payload(5000, "服务器内部错误", getattr(request.state, "request_id", "")),
        )
```

```python
# backend/app/core/responses.py
import uuid

from fastapi import FastAPI, Request


def install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def _mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def ok(data=None, *, request_id: str, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data, "request_id": request_id}
```

```python
# backend/app/schemas/common.py
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    request_id: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
```

- [ ] **Step 4: Wire into main.py**

```python
# backend/app/main.py
from fastapi import FastAPI

from app.core.errors import install_exception_handlers
from app.core.responses import install_request_id

app = FastAPI(title="LLM Programming Tutor")

install_request_id(app)
install_exception_handlers(app)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_responses.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/errors.py backend/app/core/responses.py backend/app/schemas/common.py backend/app/main.py backend/tests/test_responses.py
git commit -m "feat(backend): 统一响应、request_id 与全局异常处理"
```

---

## Task 4: LLM 端口、Fernet 加密与 Provider 注册表

**Files:**
- Create: `backend/app/infrastructure/ports/llm.py`
- Create: `backend/app/core/crypto.py`
- Create: `backend/app/infrastructure/registry.py`
- Create: `backend/tests/test_registry.py`

**Interfaces:**
- Consumes: `ModelConfig`、`get_session`（Task 2）
- Produces: `LLMPort`、`ChatMessage`、`LLMParams`、`ProviderRegistry.get_llm(session)`、`encrypt_api_key` / `decrypt_api_key` / `mask_api_key`。Task 5/6 实现端口；P2 起所有 AI 调用经注册表取实例。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_registry.py
import pytest

from app.core.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.infrastructure.persistence.models import ModelConfig
from app.infrastructure.registry import ProviderRegistry


def test_api_key_roundtrip():
    cipher = encrypt_api_key("sk-test-1234")
    assert "sk-test-1234" not in cipher
    assert decrypt_api_key(cipher) == "sk-test-1234"


def test_mask_api_key():
    assert mask_api_key("sk-test-1234") == "sk-****1234"
    assert mask_api_key(None) == ""


@pytest.mark.asyncio
async def test_registry_caches_by_revision(session):
    cfg = ModelConfig(provider="mock", revision=7)
    session.add(cfg)
    await session.commit()

    registry = ProviderRegistry()
    first = await registry.get_llm(session)
    assert await registry.get_llm(session) is first

    cfg.revision = 8
    await session.commit()
    assert await registry.get_llm(session) is not first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.ports'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/infrastructure/ports/llm.py
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMParams:
    model: str
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 2048


@runtime_checkable
class LLMPort(Protocol):
    @property
    def name(self) -> str: ...

    async def stream(self, messages: list[ChatMessage], params: LLMParams) -> AsyncIterator[str]: ...

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> str: ...
```

```python
# backend/app/core/crypto.py
import os
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET")
    if not key:
        path = Path(get_settings().app_secret_path)
        if not path.exists():
            key = Fernet.generate_key().decode()
            path.write_text(key)
        else:
            key = path.read_text().strip()
    return Fernet(key.encode())


def encrypt_api_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode()).decode()


def mask_api_key(plain: str | None) -> str:
    if not plain:
        return ""
    return f"{plain[:3]}****{plain[-4:]}"
```

```python
# backend/app/infrastructure/registry.py
from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import decrypt_api_key
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.persistence.models import ModelConfig
from app.infrastructure.ports.llm import LLMPort


class ProviderRegistry:
    """依据 ModelConfig.revision 解析并缓存 LLM 适配器。

    缓存位于进程内存，依赖单 worker（ADR-0002）。
    """

    def __init__(self) -> None:
        self._cache: LLMPort | None = None
        self._revision: int | None = None

    async def get_llm(self, session) -> LLMPort:
        cfg = (
            await session.execute(
                select(ModelConfig).order_by(ModelConfig.updated_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

        revision = cfg.revision if cfg else 0
        if self._cache is not None and self._revision == revision:
            return self._cache

        self._cache = self._build(cfg)
        self._revision = revision
        return self._cache

    def _build(self, cfg: ModelConfig | None) -> LLMPort:
        provider = cfg.provider if cfg else get_settings().llm_provider
        if provider == "openai_compat" and cfg is not None and cfg.api_key_encrypted:
            return OpenAICompatProvider(
                base_url=cfg.base_url or "",
                api_key=decrypt_api_key(cfg.api_key_encrypted),
            )
        return MockLLMProvider()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/ports backend/app/core/crypto.py backend/app/infrastructure/registry.py backend/tests/test_registry.py
git commit -m "feat(backend): LLM 端口、API Key 加密与 Provider 注册表"
```

---

## Task 5: Mock LLM Provider

**Files:**
- Create: `backend/app/infrastructure/adapters/__init__.py`
- Create: `backend/app/infrastructure/adapters/llm/__init__.py`
- Create: `backend/app/infrastructure/adapters/llm/mock_provider.py`
- Create: `backend/tests/test_mock_provider.py`

**Interfaces:**
- Consumes: `LLMPort`、`ChatMessage`、`LLMParams`（Task 4）
- Produces: `MockLLMProvider()`，无 API Key 时的全链路兜底（spec §7.3）。`cancel()` 供 P2 的 SSE 中断复用。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mock_provider.py
import pytest

from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.ports.llm import ChatMessage, LLMParams

PARAMS = LLMParams(model="mock-1")


@pytest.mark.asyncio
async def test_stream_yields_non_empty_deltas():
    provider = MockLLMProvider()
    deltas = [d async for d in provider.stream([ChatMessage("user", "你好")], PARAMS)]
    assert deltas and all(isinstance(d, str) for d in deltas)
    assert "".join(deltas)


@pytest.mark.asyncio
async def test_stream_stops_when_cancelled():
    provider = MockLLMProvider()
    out = []
    async for d in provider.stream([ChatMessage("user", "讲讲递归")], PARAMS):
        out.append(d)
        if len(out) == 2:
            provider.cancel()
    assert len(out) == 2


@pytest.mark.asyncio
async def test_complete_equals_joined_stream():
    provider = MockLLMProvider()
    messages = [ChatMessage("user", "冒泡排序怎么用")]
    streamed = "".join([d async for d in provider.stream(messages, PARAMS)])
    assert await provider.complete(messages, PARAMS) == streamed


def test_name_is_mock():
    assert MockLLMProvider().name == "mock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_mock_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.adapters'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/infrastructure/adapters/__init__.py
```

```python
# backend/app/infrastructure/adapters/llm/__init__.py
```

```python
# backend/app/infrastructure/adapters/llm/mock_provider.py
import asyncio
from typing import AsyncIterator

from app.infrastructure.ports.llm import ChatMessage, LLMParams


class MockLLMProvider:
    """无需 API Key 即可跑通全链路的提供方（spec §7.3）。

    抽取式生成：以用户末条消息与系统提示拼装话术，逐字流式吐出。
    """

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def name(self) -> str:
        return "mock"

    def cancel(self) -> None:
        self._cancelled = True

    def _render(self, messages: list[ChatMessage]) -> str:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        system = next((m.content for m in messages if m.role == "system"), "")
        topic = last_user.strip() or "该问题"
        guard = "教学提示：请先自行尝试，再对照下面的思路。" if system else ""
        return (
            f"[Mock 模式] 关于「{topic}」，给出如下思路："
            f"1) 先明确输入与输出；2) 拆解为最小可验证步骤；3) 逐步实现并测试。{guard}"
        )

    async def stream(self, messages: list[ChatMessage], params: LLMParams) -> AsyncIterator[str]:
        text = self._render(messages)
        self._cancelled = False
        for ch in text:
            if self._cancelled:
                return
            yield ch
            await asyncio.sleep(0)

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> str:
        return self._render(messages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_mock_provider.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/adapters backend/tests/test_mock_provider.py
git commit -m "feat(backend): Mock LLM Provider（抽取式生成 + 可中断流式）"
```

---

## Task 6: OpenAI 兼容 Provider 与端口契约测试

**Files:**
- Create: `backend/app/infrastructure/adapters/llm/openai_compat.py`
- Create: `backend/tests/test_llm_contract.py`

**Interfaces:**
- Consumes: `LLMPort`、`ChatMessage`、`LLMParams`（Task 4）、`ApiError`（Task 3）
- Produces: `OpenAICompatProvider(base_url, api_key, transport=None)`。P2 起真实模型调用入口。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_llm_contract.py
from typing import AsyncIterator

import httpx
import pytest

from app.core.errors import ApiError
from app.infrastructure.adapters.llm.mock_provider import MockLLMProvider
from app.infrastructure.adapters.llm.openai_compat import OpenAICompatProvider
from app.infrastructure.ports.llm import ChatMessage, LLMParams

PARAMS = LLMParams(model="m", temperature=0.0)
MESSAGES = [ChatMessage("system", "你是助教"), ChatMessage("user", "什么是闭包")]


async def collect(provider) -> str:
    return "".join([d async for d in provider.stream(MESSAGES, PARAMS)])


@pytest.mark.parametrize(
    "provider",
    [MockLLMProvider(), OpenAICompatProvider("http://x", "k")],
)
def test_contract_providers_expose_llm_port_surface(provider):
    assert isinstance(provider.name, str) and provider.name
    assert callable(provider.stream) and callable(provider.complete)


@pytest.mark.asyncio
async def test_mock_stream_matches_complete():
    provider = MockLLMProvider()
    assert await collect(provider) == await provider.complete(MESSAGES, PARAMS)


@pytest.mark.asyncio
async def test_openai_compat_parses_sse():
    body = (
        b'data: {"choices":[{"delta":{"content":"\xe9\x97\xad"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"\xe5\x8c\x85"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )
    assert await collect(OpenAICompatProvider("http://x", "k", transport=transport)) == "闭包"


@pytest.mark.asyncio
async def test_openai_compat_raises_5021_on_http_500():
    transport = httpx.MockTransport(lambda _r: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as exc:
        await collect(OpenAICompatProvider("http://x", "k", transport=transport))
    assert exc.value.code == 5021
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.adapters.llm.openai_compat'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/infrastructure/adapters/llm/openai_compat.py
import json
from typing import AsyncIterator

import httpx

from app.core.errors import ApiError
from app.infrastructure.ports.llm import ChatMessage, LLMParams


class OpenAICompatProvider:
    """OpenAI 兼容协议提供方；base_url 可指向 DeepSeek / 通义 / Ollama。

    transport 参数仅用于测试注入 httpx.MockTransport。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    @property
    def name(self) -> str:
        return "openai_compat"

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": httpx.Timeout(60.0, connect=10.0)}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def _payload(self, messages: list[ChatMessage], params: LLMParams, stream: bool) -> dict:
        return {
            "model": params.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": stream,
        }

    async def stream(self, messages: list[ChatMessage], params: LLMParams) -> AsyncIterator[str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=self._payload(messages, params, stream=True),
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    raise ApiError(5021, "模型服务不可用")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                    except (ValueError, KeyError, IndexError):
                        continue
                    if content := delta.get("content"):
                        yield content

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> str:
        return "".join([d async for d in self.stream(messages, params)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_contract.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/adapters/llm/openai_compat.py backend/tests/test_llm_contract.py
git commit -m "feat(backend): OpenAI 兼容 Provider 与端口契约测试"
```

---

## Task 7: User 领域实体与密码哈希

**Files:**
- Create: `backend/app/domain/__init__.py`
- Create: `backend/app/domain/auth/__init__.py`
- Create: `backend/app/domain/auth/user.py`
- Create: `backend/app/core/security.py`
- Create: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: 无
- Produces: `STUDENT` / `ADMIN` / `ACTIVE` / `DISABLED`、`is_admin()`、`can_login()`、`hash_password()`、`verify_password()`。Task 8 继续扩展 `security.py`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_security.py
from app.core.security import hash_password, verify_password
from app.domain.auth.user import ACTIVE, ADMIN, DISABLED, STUDENT, can_login, is_admin


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("Secret123!")
    assert h != "Secret123!"
    assert verify_password("Secret123!", h)
    assert not verify_password("wrong", h)


def test_can_login_only_active():
    assert can_login(ACTIVE)
    assert not can_login(DISABLED)


def test_is_admin():
    assert is_admin(ADMIN)
    assert not is_admin(STUDENT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/domain/auth/user.py
"""用户角色与状态的纯业务规则。禁止 IO —— 可脱离数据库单测。"""

STUDENT = "student"
ADMIN = "admin"
ROLES = (STUDENT, ADMIN)

ACTIVE = "active"
DISABLED = "disabled"
STATUSES = (ACTIVE, DISABLED)


def is_admin(role: str) -> bool:
    return role == ADMIN


def can_login(status: str) -> bool:
    return status == ACTIVE
```

```python
# backend/app/core/security.py
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_security.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain backend/app/core/security.py backend/tests/test_security.py
git commit -m "feat(backend): User 领域规则与 bcrypt 密码哈希"
```

---

## Task 8: JWT 签发校验与鉴权依赖

**Files:**
- Modify: `backend/app/core/security.py`（追加 JWT 部分）
- Create: `backend/app/core/deps.py`
- Create: `backend/tests/test_auth_deps.py`

**Interfaces:**
- Consumes: `get_settings()`（Task 2）、`User`（Task 2）、领域规则（Task 7）、`ApiError`（Task 3）
- Produces: `create_access_token`、`create_refresh_token`、`decode_token`、`get_session` 之上的 `get_current_user` / `require_admin` / `current_request_id`。Task 10 使用。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth_deps.py
import pytest

from app.core.errors import ApiError
from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_token_roundtrip():
    payload = decode_token(create_access_token("u1", "student"))
    assert payload["sub"] == "u1"
    assert payload["role"] == "student"


def test_refresh_token_has_no_role():
    assert "role" not in decode_token(create_refresh_token("u1"))


def test_invalid_token_raises_4010():
    with pytest.raises(ApiError) as exc:
        decode_token("not-a-jwt")
    assert exc.value.code == 4010


def test_access_token_rejected_when_refresh_expected():
    with pytest.raises(ApiError) as exc:
        decode_token(create_access_token("u1", "student"), expect="refresh")
    assert exc.value.code == 4010
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_access_token'`

- [ ] **Step 3: Append JWT 部分到 security.py**

```python
# 追加到 backend/app/core/security.py 末尾
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.errors import ApiError


def _issue(payload: dict, ttl: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**payload, "iat": now, "exp": now + ttl},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user_id: str, role: str) -> str:
    ttl = timedelta(minutes=get_settings().access_token_ttl_minutes)
    return _issue({"sub": user_id, "role": role, "typ": "access"}, ttl)


def create_refresh_token(user_id: str) -> str:
    ttl = timedelta(days=get_settings().refresh_token_ttl_days)
    return _issue({"sub": user_id, "typ": "refresh"}, ttl)


def decode_token(token: str, expect: str | None = None) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise ApiError(4010, "登录凭证无效或已过期") from exc
    if expect is not None and payload.get("typ") != expect:
        raise ApiError(4010, "登录凭证无效或已过期")
    return payload
```

- [ ] **Step 4: Write deps.py**

```python
# backend/app/core/deps.py
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import decode_token
from app.domain.auth.user import can_login, is_admin
from app.infrastructure.persistence.db import get_session
from app.infrastructure.persistence.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _bearer(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(4010, "未提供登录凭证")
    return decode_token(header[7:], expect="access")


async def get_current_user(request: Request, session: SessionDep) -> User:
    payload = _bearer(request)
    user = (
        await session.execute(select(User).where(User.id == payload["sub"]))
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(4010, "用户不存在")
    if not can_login(user.status):
        raise ApiError(4030, "账号已被停用")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not is_admin(user.role):
        raise ApiError(4030, "需要管理员权限")
    return user


def current_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/security.py backend/app/core/deps.py backend/tests/test_auth_deps.py
git commit -m "feat(backend): JWT 签发校验与鉴权依赖"
```

---

## Task 9: 审计日志服务

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/audit_service.py`
- Create: `backend/tests/test_audit.py`

**Interfaces:**
- Consumes: `AuditLog`（Task 2）、`AsyncSession`
- Produces: `AuditService(session).record(action, *, user_id, target_type, target_id, detail, ip, request_id)`。Task 10 及后续所有批次调用。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_audit.py
import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import AuditLog
from app.services.audit_service import AuditService


@pytest.mark.asyncio
async def test_record_persists_audit_log(session):
    await AuditService(session).record(
        "login", user_id="u1", detail={"ok": True}, request_id="rid"
    )
    await session.commit()

    row = (await session.execute(select(AuditLog).where(AuditLog.request_id == "rid"))).scalar_one()
    assert row.action == "login"
    assert row.user_id == "u1"
    assert row.detail == {"ok": True}


@pytest.mark.asyncio
async def test_audit_log_survives_without_user(session):
    """审计日志不随用户删除：user_id 可空（spec §8.9）。"""
    await AuditService(session).record(
        "admin_user_delete", user_id=None, target_type="user", target_id="u9"
    )
    await session.commit()

    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.user_id is None
    assert row.target_id == "u9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audit_service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.models import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        action: str,
        *,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict | None = None,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=ip,
            request_id=request_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_audit.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/tests/test_audit.py
git commit -m "feat(backend): 审计日志服务"
```

---

## Task 10: auth 路由

**Files:**
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/services/auth_service.py`
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `SessionDep` / `get_current_user` / `require_admin` / `current_request_id`（Task 8）、`AuditService`（Task 9）、`ok()`（Task 3）
- Produces: `/api/v1/auth/*` 端点与 `/health`、`/api/v1/admin/ping` 占位。前端 Task 14 对接。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth_api.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.db import Base, _apply_pragmas, get_session
from app.main import app


@pytest_asyncio.fixture
async def client():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async def _override():
        async with factory() as s:
            yield s

    # 覆盖键必须是路由注册时使用的同一个函数对象，不能重载模块后重绑
    app.dependency_overrides[get_session] = _override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

    app.dependency_overrides.clear()
    await eng.dispose()


async def _register(c, username: str):
    return await c.post("/api/v1/auth/register", json={
        "username": username, "email": f"{username}@example.com", "password": "Secret123!"})


@pytest.mark.asyncio
async def test_register_then_login(client):
    r = await _register(client, "stu001")
    assert r.status_code == 200 and r.json()["code"] == 0

    r = await client.post("/api/v1/auth/login", json={
        "username": "stu001", "password": "Secret123!"})
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["access_token"] and body["data"]["refresh_token"]


@pytest.mark.asyncio
async def test_register_defaults_to_student(client):
    await _register(client, "s2")
    r = await client.post("/api/v1/auth/login", json={"username": "s2", "password": "Secret123!"})
    token = r.json()["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["role"] == "student"


@pytest.mark.asyncio
async def test_duplicate_username_is_rejected(client):
    assert (await _register(client, "dup")).json()["code"] == 0
    assert (await _register(client, "dup")).json()["code"] == 4090


@pytest.mark.asyncio
async def test_wrong_password_rejected(client):
    await _register(client, "s3")
    r = await client.post("/api/v1/auth/login", json={"username": "s3", "password": "bad"})
    assert r.json()["code"] == 4010


@pytest.mark.asyncio
async def test_missing_token_rejected(client):
    assert (await client.get("/api/v1/auth/me")).json()["code"] == 4010


@pytest.mark.asyncio
async def test_admin_route_blocks_student(client):
    await _register(client, "s4")
    r = await client.post("/api/v1/auth/login", json={"username": "s4", "password": "Secret123!"})
    token = r.json()["data"]["access_token"]
    r = await client.get("/api/v1/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["code"] == 4030


@pytest.mark.asyncio
async def test_refresh_issues_new_access_token(client):
    await _register(client, "s5")
    tokens = (await client.post("/api/v1/auth/login", json={
        "username": "s5", "password": "Secret123!"})).json()["data"]
    r = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200 and r.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client):
    await _register(client, "s6")
    tokens = (await client.post("/api/v1/auth/login", json={
        "username": "s6", "password": "Secret123!"})).json()["data"]
    r = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["access_token"]})
    assert r.json()["code"] == 4010
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_auth_api.py -v`
Expected: FAIL with `AssertionError: 404 != 200`（路由未注册）

- [ ] **Step 3: Write schemas**

```python
# backend/app/schemas/auth.py
from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    status: str
```

- [ ] **Step 4: Write auth_service**

```python
# backend/app/services/auth_service.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.auth.user import STUDENT
from app.infrastructure.persistence.models import User


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, username: str, email: str, password: str) -> User:
        exists = (
            await self._session.execute(
                select(User).where((User.username == username) | (User.email == email))
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ApiError(4090, "用户名或邮箱已存在")

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=STUDENT,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def login(self, username: str, password: str) -> tuple[User, str, str]:
        user = (
            await self._session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            raise ApiError(4010, "用户名或密码错误")

        user.last_login_at = datetime.now(timezone.utc)
        await self._session.flush()
        return user, create_access_token(user.id, user.role), create_refresh_token(user.id)
```

- [ ] **Step 5: Write router**

```python
# backend/app/routers/auth.py
from fastapi import APIRouter, Depends, Request

from app.core.deps import SessionDep, current_request_id, get_current_user
from app.core.responses import ok
from app.core.security import create_access_token, decode_token
from app.infrastructure.persistence.models import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, UserOut
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register")
async def register(body: RegisterIn, request: Request, session: SessionDep):
    user = await AuthService(session).register(body.username, body.email, body.password)
    await AuditService(session).record(
        "register",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=_ip(request),
        request_id=current_request_id(request),
    )
    await session.commit()
    return ok(UserOut.model_validate(user).model_dump(), request_id=current_request_id(request))


@router.post("/login")
async def login(body: LoginIn, request: Request, session: SessionDep):
    user, access, refresh = await AuthService(session).login(body.username, body.password)
    await AuditService(session).record(
        "login",
        user_id=user.id,
        ip=_ip(request),
        request_id=current_request_id(request),
    )
    await session.commit()
    return ok(
        {"access_token": access, "refresh_token": refresh},
        request_id=current_request_id(request),
    )


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request, session: SessionDep):
    payload = decode_token(body.refresh_token, expect="refresh")
    user = await AuthService(session).get_by_id(payload["sub"])
    return ok(
        {
            "access_token": create_access_token(user.id, user.role),
            "refresh_token": body.refresh_token,
        },
        request_id=current_request_id(request),
    )


@router.get("/me")
async def me(request: Request, user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump(), request_id=current_request_id(request))


@router.post("/logout")
async def logout(request: Request, session: SessionDep, user: User = Depends(get_current_user)):
    await AuditService(session).record(
        "logout", user_id=user.id, request_id=current_request_id(request)
    )
    await session.commit()
    return ok({"logged_out": True}, request_id=current_request_id(request))
```

- [ ] **Step 6: Append `get_by_id` to AuthService**

```python
# 追加到 backend/app/services/auth_service.py 的 AuthService 类中
    async def get_by_id(self, user_id: str) -> User:
        user = (
            await self._session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(4010, "用户不存在")
        return user
```

- [ ] **Step 7: Register routers in main.py**

```python
# backend/app/main.py
from fastapi import APIRouter, Depends, FastAPI

from app.core.deps import require_admin
from app.core.errors import install_exception_handlers
from app.core.responses import install_request_id, ok
from app.routers import auth as auth_router

app = FastAPI(title="LLM Programming Tutor")

install_request_id(app)
install_exception_handlers(app)

app.include_router(auth_router.router)

_admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@_admin.get("/ping")
async def admin_ping(user=Depends(require_admin)):
    """P0 占位：用于验证角色拦截。P6 将被真实管理端点取代。"""
    return ok({"role": user.role}, request_id="")


app.include_router(_admin)


@app.get("/health")
async def health():
    return ok({"status": "ok"}, request_id="")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_auth_api.py -v`
Expected: PASS (8 passed)

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/services/auth_service.py backend/app/routers backend/app/main.py backend/tests/test_auth_api.py
git commit -m "feat(backend): auth 路由、注册登录刷新与角色拦截"
```

---

## Task 11: make seed（初始管理员 + 默认 ModelConfig）

**Files:**
- Create: `backend/app/seed.py`
- Create: `backend/tests/test_seed.py`

**Interfaces:**
- Consumes: `User`、`ModelConfig`（Task 2）、`hash_password`（Task 7）
- Produces: `seed(session)` 幂等函数与 `python -m app.seed` 入口。P5 追加习题种子。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_seed.py
import pytest
from sqlalchemy import select

from app.domain.auth.user import ADMIN
from app.infrastructure.persistence.models import ModelConfig, User
from app.seed import DEFAULT_ADMIN_USERNAME, seed


@pytest.mark.asyncio
async def test_seed_creates_admin_and_model_config(session):
    await seed(session)
    await session.commit()

    admin = (
        await session.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    ).scalar_one()
    assert admin.role == ADMIN
    assert (await session.execute(select(ModelConfig))).scalars().first() is not None


@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    await seed(session)
    await session.commit()
    await seed(session)
    await session.commit()

    assert len((await session.execute(select(User))).scalars().all()) == 1
    assert len((await session.execute(select(ModelConfig))).scalars().all()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.seed'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/seed.py
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.domain.auth.user import ACTIVE, ADMIN
from app.infrastructure.persistence.db import SessionFactory, engine, init_db
from app.infrastructure.persistence.models import ModelConfig, User

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@12345"


async def seed(session: AsyncSession) -> None:
    """幂等：已存在则跳过，不覆盖既有数据。"""
    existing = (
        await session.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            User(
                username=DEFAULT_ADMIN_USERNAME,
                email="admin@example.com",
                hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
                role=ADMIN,
                status=ACTIVE,
            )
        )

    cfg = (await session.execute(select(ModelConfig).limit(1))).scalar_one_or_none()
    if cfg is None:
        session.add(ModelConfig(provider="mock", model="mock-1", revision=1))

    await session.flush()


async def _main() -> None:
    await init_db(engine)
    async with SessionFactory() as session:
        await seed(session)
        await session.commit()
    print(f"seed 完成：管理员 {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")


if __name__ == "__main__":
    url = get_settings().database_url
    if ":///" in url and ":memory:" not in url:
        Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_seed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/seed.py backend/tests/test_seed.py
git commit -m "feat(backend): make seed 幂等写入初始管理员与默认模型配置"
```

---

## Task 12: 一键脚本与健康检查

**Files:**
- Create: `Makefile`
- Create: `backend/.env.example`
- Create: `backend/tests/test_ops.py`

**Interfaces:**
- Consumes: 全部后端产物
- Produces: `make install / install-lite / dev / serve / test / seed / lint`。`dev` 与 `serve` 均固定 `--workers 1`（ADR-0002）。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ops.py
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


async def test_health_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200 and r.json()["code"] == 0


def test_makefile_declares_required_targets():
    text = (ROOT / "Makefile").read_text()
    for target in ("install:", "install-lite:", "dev:", "serve:", "test:", "seed:"):
        assert target in text, f"Makefile 缺少目标 {target}"


def test_makefile_pins_single_worker():
    """ADR-0002：dev 与 serve 均必须固定 --workers 1。"""
    text = (ROOT / "Makefile").read_text()
    assert text.count("--workers 1") >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ops.py -v`
Expected: FAIL with `FileNotFoundError`（`Makefile` 尚不存在）

- [ ] **Step 3: Write Makefile 与 .env.example**

```makefile
# Makefile
BACKEND := backend
FRONTEND := frontend
PY := . .venv/bin/activate &&

.PHONY: install install-lite setup-local-embed dev serve test seed lint

install:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev]"
	cd $(FRONTEND) && npm install

install-lite:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev]"
	@echo "已跳过本地 embedding extras（torch 约 1GB）；需要真实语义检索时执行 make setup-local-embed"
	cd $(FRONTEND) && npm install

setup-local-embed:
	cd $(BACKEND) && $(PY) pip install -e ".[local-embed]"

dev:
	@echo "双端口开发：前端 http://localhost:5173 · 后端 http://localhost:8000"
	(cd $(BACKEND) && $(PY) uvicorn app.main:app --reload --workers 1 --port 8000) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

serve:
	@echo "单端口演示：http://localhost:8000"
	cd $(FRONTEND) && npm run build
	cd $(BACKEND) && $(PY) uvicorn app.main:app --workers 1 --port 8000

test:
	cd $(BACKEND) && $(PY) python -m pytest -q

seed:
	cd $(BACKEND) && $(PY) python -m app.seed

lint:
	cd $(BACKEND) && $(PY) ruff check app tests
```

```dotenv
# backend/.env.example
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
JWT_SECRET=change-me-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_TTL_MINUTES=30
REFRESH_TOKEN_TTL_DAYS=7
APP_SECRET_PATH=.secret_key
LLM_PROVIDER=mock
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ops.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add Makefile backend/.env.example backend/tests/test_ops.py
git commit -m "chore: 一键脚本（install/dev/serve/test/seed）与健康检查"
```

---

## Task 13: 前端脚手架与 uiuxpromax 设计基线

**Files:**
- Create: `frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/index.html`
- Create: `frontend/src/env.d.ts`、`frontend/src/main.ts`、`frontend/src/App.vue`

**Interfaces:**
- Consumes: 无
- Produces: 可构建的 Vue 3 + TS 前端工程，以及 `uipro` 产出的设计基线。后续所有页面遵守该基线。

- [ ] **Step 1: Write scaffold files**

```json
// frontend/package.json
{
  "name": "llm-code-tutor-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@element-plus/icons-vue": "^2.3.1",
    "axios": "^1.7.9",
    "element-plus": "^2.9.1",
    "pinia": "^2.3.0",
    "vue": "^3.5.13",
    "vue-router": "^4.5.0"
  },
  "devDependencies": {
    "@types/node": "^22.10.2",
    "@vitejs/plugin-vue": "^5.2.1",
    "typescript": "^5.7.2",
    "vite": "^6.0.5",
    "vue-tsc": "^2.2.0"
  }
}
```

```ts
// frontend/vite.config.ts
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
```

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] },
    "types": ["vite/client", "node"]
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.vue", "vite.config.ts"]
}
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>智能编程教学辅助系统</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

```ts
// frontend/src/env.d.ts
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
```

```ts
// frontend/src/main.ts
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
```

```vue
<!-- frontend/src/App.vue（Task 14 将替换为带鉴权初始化的版本） -->
<template>
  <div>前端脚手架已就绪</div>
</template>
```

- [ ] **Step 2: Install dependencies**

```bash
cd frontend && npm install
```

- [ ] **Step 3: 建立 uiuxpromax 设计基线**

```bash
uipro init --ai codebuddy
```

> 执行后必须把产出内容落盘到 `frontend/docs/ui-baseline.md`。后续所有页面的配色、间距、字号、圆角一律遵守，避免批次间视觉漂移（Grilling Q15 结论）。

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx vue-tsc --noEmit && npx vite build`
Expected: 无类型错误，产出 `frontend/dist`

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Vue3+TS+Element Plus 脚手架与 uiuxpromax 设计基线"
```

---

## Task 14: 前端鉴权骨架

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/HomeView.vue`
- Modify: `frontend/src/main.ts`（无变化，已在 Task 13 写好）
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: `/api/v1/auth/*`（Task 10）
- Produces: 可登录的前端骨架。P1–P6 新页面挂载到同一路由表。

- [ ] **Step 1: 类型定义与 Axios 客户端**

```ts
// frontend/src/types/api.ts
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T | null
  request_id: string
}

export interface UserOut {
  id: string
  username: string
  email: string
  role: 'student' | 'admin'
  status: 'active' | 'disabled'
}

export interface TokenPair {
  access_token: string
  refresh_token: string
}
```

```ts
// frontend/src/api/client.ts
import axios, { type AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

export const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

export const ACCESS_KEY = 'lct.access_token'
export const REFRESH_KEY = 'lct.refresh_token'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body && typeof body.code === 'number' && body.code !== 0) {
      ElMessage.error(body.message)
      return Promise.reject(new Error(body.message))
    }
    return resp
  },
  (error: AxiosError<ApiResponse>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    }
    ElMessage.error(error.response?.data?.message ?? '网络异常')
    return Promise.reject(error)
  },
)
```

- [ ] **Step 2: auth API 与 store**

```ts
// frontend/src/api/auth.ts
import { api } from './client'
import type { ApiResponse, TokenPair, UserOut } from '@/types/api'

export const register = (body: { username: string; email: string; password: string }) =>
  api.post<ApiResponse<UserOut>>('/auth/register', body)

export const login = (body: { username: string; password: string }) =>
  api.post<ApiResponse<TokenPair>>('/auth/login', body)

export const refresh = (refreshToken: string) =>
  api.post<ApiResponse<TokenPair>>('/auth/refresh', { refresh_token: refreshToken })

export const me = () => api.get<ApiResponse<UserOut>>('/auth/me')

export const logout = () => api.post<ApiResponse<{ logged_out: boolean }>>('/auth/logout')
```

```ts
// frontend/src/stores/auth.ts
import { ACCESS_KEY, REFRESH_KEY } from '@/api/client'
import * as authApi from '@/api/auth'
import type { UserOut } from '@/types/api'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserOut | null>(null)

  const isAdmin = computed(() => user.value?.role === 'admin')
  const isAuthed = computed(() => user.value !== null)

  async function doLogin(username: string, password: string) {
    const { data } = await authApi.login({ username, password })
    if (!data.data) throw new Error('登录失败')
    localStorage.setItem(ACCESS_KEY, data.data.access_token)
    localStorage.setItem(REFRESH_KEY, data.data.refresh_token)
    await fetchMe()
  }

  async function fetchMe() {
    const { data } = await authApi.me()
    user.value = data.data
  }

  async function doLogout() {
    try {
      await authApi.logout()
    } finally {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      user.value = null
    }
  }

  return { user, isAdmin, isAuthed, doLogin, fetchMe, doLogout }
})
```

- [ ] **Step 3: 路由与守卫**

```ts
// frontend/src/router/index.ts
import { ACCESS_KEY } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    { path: '/', component: () => import('@/views/HomeView.vue'), meta: { requiresAuth: true } },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true
  if (!localStorage.getItem(ACCESS_KEY)) return { path: '/login' }

  const store = useAuthStore()
  if (!store.user) {
    try {
      await store.fetchMe()
    } catch {
      return { path: '/login' }
    }
  }
  return true
})

export default router
```

- [ ] **Step 4: 登录页与主页**

```vue
<!-- frontend/src/views/LoginView.vue -->
<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const auth = useAuthStore()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await auth.doLogin(form.value.username, form.value.password)
    router.push('/')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <h2>智能编程教学辅助系统</h2>
      </template>
      <el-form @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="submit">登录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
}
.login-card {
  width: 380px;
}
</style>
```

```vue
<!-- frontend/src/views/HomeView.vue -->
<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.doLogout()
  router.push('/login')
}
</script>

<template>
  <div class="home">
    <header class="home__bar">
      <span>当前用户：{{ auth.user?.username }}（{{ auth.user?.role }}）</span>
      <el-button link @click="onLogout">退出登录</el-button>
    </header>
    <el-empty description="P0 基座已就绪，功能模块将在后续批次接入" />
  </div>
</template>

<style scoped>
.home__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
}
</style>
```

- [ ] **Step 5: 替换 App.vue**

```vue
<!-- frontend/src/App.vue -->
<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const token = localStorage.getItem('lct.access_token')
if (token) {
  auth.fetchMe().catch(() => undefined)
}
</script>

<template>
  <router-view />
</template>
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && npx vue-tsc --noEmit && npx vite build`
Expected: 无类型错误，构建成功

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): 鉴权骨架、Axios 拦截器与路由守卫"
```

---

## Task 15: make serve 单端口托管

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_static_hosting.py`

**Interfaces:**
- Consumes: `frontend/dist`（Task 13/14 构建产物）
- Produces: `make serve` 后 `http://localhost:8000` 同时提供前端与 API（Grilling Q20：演示只给一个 URL）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_static_hosting.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import install_spa_fallback


def _dist(tmp_path) -> "Path":
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text("<h1>app</h1>")
    return tmp_path


def test_unknown_path_falls_back_to_index(tmp_path):
    app = FastAPI()
    install_spa_fallback(app, _dist(tmp_path))
    r = TestClient(app).get("/some/spa/route")
    assert r.status_code == 200
    assert "app" in r.text


def test_api_path_is_not_swallowed(tmp_path):
    """Starlette 按注册顺序匹配：API 路由必须先于 catch-all 注册。"""
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    install_spa_fallback(app, _dist(tmp_path))
    assert TestClient(app).get("/api/v1/ping").json() == {"ok": True}


def test_missing_dist_dir_is_noop(tmp_path):
    app = FastAPI()
    install_spa_fallback(app, tmp_path / "nope")
    assert TestClient(app).get("/anything").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_static_hosting.py -v`
Expected: FAIL with `ImportError: cannot import name 'install_spa_fallback'`

- [ ] **Step 3: Implement**

```python
# 追加到 backend/app/main.py 末尾
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def install_spa_fallback(app: FastAPI, dist: Path = DIST_DIR) -> None:
    """挂载前端构建产物并提供 SPA fallback。

    dist 不存在时完全不挂载（开发模式走 Vite dev server）。
    必须在所有 API 路由注册之后调用，否则 catch-all 会吞掉 /api/*。
    """
    if not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def _spa(full_path: str):
        if full_path.startswith(("api/", "health")):
            raise ApiError(4040, "资源不存在")
        index = dist / "index.html"
        if not index.exists():
            raise ApiError(4040, "资源不存在")
        return FileResponse(index)


install_spa_fallback(app)
```

> `ApiError` 已在 main.py 顶部导入（Task 3），此处无需重复导入。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_static_hosting.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full suite**

Run: `cd backend && python -m pytest -q`
Expected: 全部通过（约 40 项）

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_static_hosting.py
git commit -m "feat(backend): make serve 单端口托管前端构建产物"
```

---

## 验收清单（P0 完成标准）

- [ ] `make install` 可完成安装
- [ ] `make seed` 输出管理员账号；重复执行不产生重复数据
- [ ] `make dev` 起双端口，登录页可用，注册 → 登录 → `/auth/me` 全通
- [ ] `make serve` 起单端口 8000，浏览器可得前端页面，刷新子路径不 404
- [ ] `make test` 全绿
- [ ] 未配置 API Key 时 `ProviderRegistry.get_llm()` 返回 `MockLLMProvider`
- [ ] `GET /api/v1/admin/ping` 对 student 返回 `4030`
- [ ] 任意未捕获异常返回 `code=5000` 且响应体无堆栈
- [ ] `frontend/docs/ui-baseline.md` 已落盘，后续页面遵守

## 后续计划（不在本文件范围）

P1 RAG 知识库 · P2 答疑对话与防抄袭 · P3 代码解析辅导 · P4 编辑器与执行器 · P5 习题与错题本 · P6 管理后台收口

每批在上一批验收通过后单独成文。原因：P0 落地会暴露新的实测信息，现在一次性锁定七批细节等于固化未经检验的假设。
