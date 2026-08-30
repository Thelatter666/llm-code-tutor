# P1 RAG 课程知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可端到端演示的 RAG 课程知识库 —— 文档接入（上传校验 / 解析 / 切分）、向量化（三级回退 Embedder）、Chroma 存储与检索（spec §7.2 七步装配链路）、管理端全生命周期（含删除顺序、孤儿向量 GC、embedding 切换 409 + 强制重建），以及学生侧的两个只读端点。

**Architecture:** 沿用 P0 的模块化单体与 `routers → services → domain → infrastructure` 分层。`Embedder` / `VectorStore` / `DocumentParser` 以 `Protocol` 端口定义，服务层只依赖端口，具体适配器由 `ProviderRegistry` + `EmbedderRuntime` 依据 `ModelConfig` 解析。领域层（`domain/knowledge/`）承载切分与检索装配规则，零 IO。所有同步阻塞调用（模型加载、embedding 推理、文档解析、Chroma IO）经 `run_in_threadpool` 卸载（ADR-0002）。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) + aiosqlite · Pydantic v2 · Chroma 本地持久化（`chromadb`）· sentence-transformers（`paraphrase-multilingual-MiniLM-L12-v2`，384 维）· pdfplumber · python-docx · httpx · pytest + pytest-asyncio

## Global Constraints

以下约束逐字摘自 spec / ADR / AGENT.md，每个任务默认包含，不再重复说明。

- 单进程单 worker：`uvicorn --workers 1`（ADR-0002）；所有同步阻塞调用经 `run_in_threadpool` 卸载
- 不做数据库迁移，建表用 `create_all`（ADR-0006）
- 统一响应体 `{code, message, data, request_id}`；**所有端点注入 `CurrentRidDep`**，禁止硬编码 `request_id=""`（H3）
- 领域层（`backend/app/domain/`）禁止 import 任何基础设施模块，业务规则零 IO 可单测
- 服务层只依赖 `Protocol` 端口，不依赖具体 adapter（ADR-0001）
- 所有 datetime 列用 `app.infrastructure.persistence.db.UTCDateTime`，不用裸 `DateTime`
- `ModelConfig` 单例一律走 `get_or_create_singleton()`，不得自己 insert（H2）
- 术语以 `CONTEXT.md` 为唯一来源（向量化器 / 向量库 / 切片 / 引用 / 检索命中 / 相关度阈值 / 相对截断 / 多样性截取 / 孤儿向量 / 哨兵级降级 / 知识库锁 / 阻塞卸载 / 课程代码）
- 不引入 Celery，索引走 `BackgroundTasks`（spec §3.2 权衡 6）
- 不做 OCR（spec §3.2 权衡 19）
- 不配置 CORS（dev / serve 均同源，M9 已结论）
- 禁止任何涉及远端的操作（`git push` / `git remote add`）
- 每个任务完成后跑全量测试（`cd backend && . .venv/bin/activate && python -m pytest -q`），P0 基线 **64 passed**

### Commit 策略

用户已于 **2026-08-30 预先授权**（`AGENT.md`「授权例外」表）：本计划 Task 1–15 中每个 Task 完成且全量测试通过后，**可直接按 Task 粒度 `git commit`**，无需逐次请示。**`git merge` 与 `git push` 不在授权范围内**，仍需用户单独下令。

### 本版承接的审阅报告条目

依据 `docs/review/2026-08-30-documents-review.md`：

| 编号 | 问题 | 处理位置 |
|---|---|---|
| M1 | `score_threshold` 需按 embedding 模型解析默认值（0.25 / 0.35 / 0.30） | Task 7 |
| L1 | 补 4 篇 ADR（Chroma 单集合 / 薄弱知识点聚合 / 按字符切分 / 相对截断） | Task 15 |
| L5 | 依赖引入批次标注 | Task 1 |
| M10 | provider 降级链结构 | Task 4（embedding 三级回退落 `EmbedderRuntime`） |

M2（`backend/seeds/`，P5）、M3（`response_model=ApiResponse[T]`，P6）、M4（契约测试补全，P2）、M6（bcrypt 卸载，P2）不在本批次范围。

---

## File Structure

```
backend/
├── pyproject.toml               追加 chromadb / pdfplumber / python-docx（L5 标注批次）
├── app/
│   ├── main.py                  追加 lifespan（异步后台预热）、/health 就绪状态
│   ├── domain/knowledge/
│   │   ├── __init__.py
│   │   ├── status.py            文档/知识库状态与来源类型常量
│   │   ├── upload.py            上传校验规则（10MB / 扩展名白名单）
│   │   ├── chunker.py           按字符切分（1200 / 150 重叠）
│   │   └── retrieval.py         相关度阈值 / 相对截断 / 多样性截取 / 编号
│   ├── infrastructure/
│   │   ├── ports/{embedding,vectorstore,document}.py
│   │   ├── adapters/embedding/{hashing_embed,sentence_transformer,openai_compat_embed}.py
│   │   ├── adapters/vectorstore/chroma_store.py
│   │   ├── adapters/document/parsers.py
│   │   ├── concurrency.py       per-kb asyncio.Lock + 索引信号量（知识库锁）
│   │   ├── embedder_runtime.py  三级回退、异步后台预热、就绪状态
│   │   ├── registry.py          追加 resolve_embedder（依据 ModelConfig）
│   │   └── persistence/models.py  追加 KnowledgeBase / Document / Chunk
│   ├── services/
│   │   ├── knowledge_service.py    KB CRUD / 删除顺序 / 孤儿向量 GC
│   │   ├── document_service.py     上传落盘与 Document 行
│   │   ├── indexing_service.py     索引流水线（BackgroundTasks + 阻塞卸载）
│   │   ├── retrieval_service.py    §7.2 七步装配链路
│   │   └── model_config_service.py §8.7 embedding 切换 409 + 强制重建
│   ├── routers/
│   │   ├── knowledge.py           学生侧只读端点
│   │   └── admin_knowledge.py     管理端 10 个端点
│   └── schemas/knowledge.py
└── tests/
    ├── fakes.py                     FakeEmbedder / FakeVectorStore / RecordingEmbedder
    ├── test_kb_models.py · test_chunker.py · test_retrieval_rules.py
    ├── test_hashing_embed.py · test_sentence_transformer_embed.py
    ├── test_embedder_runtime.py · test_chroma_store.py
    ├── test_document_parsers.py · test_upload_validation.py · test_concurrency.py
    ├── test_knowledge_service.py · test_indexing_service.py
    ├── test_retrieval_service.py · test_embedding_switch.py
    ├── test_knowledge_api.py · test_health_ready.py
```

---

## Task 1: 依赖声明与 KnowledgeBase / Document / Chunk 三表

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/infrastructure/persistence/models.py`
- Create: `backend/tests/test_kb_models.py`

**Interfaces:**
- Consumes: `Base`、`UTCDateTime`（P0）
- Produces: `KnowledgeBase` / `Document` / `Chunk` 三张表；`create_all` 自动建表（ADR-0006）

> **L5**：新增依赖在 `pyproject.toml` 中以注释标注引入批次。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_kb_models.py
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase


@pytest.mark.asyncio
async def test_three_tables_are_created(engine):
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    assert {"knowledge_bases", "documents", "chunks"} <= {r[0] for r in rows}


@pytest.mark.asyncio
async def test_document_exposes_indexing_progress(session):
    """spec §8.2：管理端轮询 chunk_indexed / chunk_total 展示索引进度。"""
    kb = KnowledgeBase(name="Python 基础", owner_id="u1")
    session.add(kb)
    await session.flush()
    doc = Document(kb_id=kb.id, title="第 1 讲", source_type="md", status="pending")
    session.add(doc)
    await session.flush()

    got = (await session.execute(select(Document))).scalar_one()
    assert got.status == "pending"
    assert got.chunk_indexed == 0 and got.chunk_total == 0


@pytest.mark.asyncio
async def test_chunk_carries_vector_reference_and_embed_model(session):
    """spec §8.7 步骤 4：Chunk.embed_model 记录实际索引所用模型。"""
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.flush()
    doc = Document(kb_id=kb.id, title="t", source_type="txt")
    session.add(doc)
    await session.flush()
    session.add(
        Chunk(
            document_id=doc.id,
            kb_id=kb.id,
            content="切片内容",
            ordinal=0,
            char_count=4,
            embed_model="paraphrase-multilingual-MiniLM-L12-v2",
            vector_id="vec-1",
        )
    )
    await session.commit()

    got = (await session.execute(select(Chunk))).scalar_one()
    assert got.vector_id == "vec-1"
    assert got.embed_model == "paraphrase-multilingual-MiniLM-L12-v2"


@pytest.mark.asyncio
async def test_timestamps_are_timezone_aware_utc(session):
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.commit()

    got = (await session.execute(select(KnowledgeBase))).scalar_one()
    assert got.created_at.tzinfo is not None
    assert got.created_at.tzinfo == timezone.utc
    assert isinstance(got.created_at, datetime)


@pytest.mark.asyncio
async def test_knowledge_base_course_code_is_nullable(session):
    """CONTEXT.md：course_code 可空表示不限课程。"""
    kb = KnowledgeBase(name="kb", owner_id="u1")
    session.add(kb)
    await session.commit()
    assert (await session.execute(select(KnowledgeBase))).scalar_one().course_code is None
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && python -m pytest tests/test_kb_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'KnowledgeBase'`

- [ ] **Step 3: Declare dependencies**

```toml
# backend/pyproject.toml（dependencies 追加，L5：标注引入批次）
    "chromadb>=0.5",       # P1 RAG 知识库：向量持久化
    "pdfplumber>=0.11",    # P1 RAG 知识库：PDF 解析
    "python-docx>=1.1",    # P1 RAG 知识库：DOCX 解析
```

- [ ] **Step 4: Write models**

```python
# 追加到 backend/app/infrastructure/persistence/models.py
class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # 课程代码：可空表示不限课程（CONTEXT.md）
    course_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    embed_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # §6.2 要求「kb 未就绪 → 5032」，§8.7 要求重建期间 KB 置 reindexing；
    # 二者都需要 KB 级状态，故在 §5 的关键字段清单之外补此列
    status: Mapped[str] = mapped_column(String, default="ready")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)          # pdf|md|txt|docx
    source_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_indexed: Mapped[int] = mapped_column(Integer, default=0)
    chunk_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String, index=True)
    kb_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer)
    meta_: ...  # 字段名 meta 与 SQLAlchemy Declarative 的 metadata 冲突，列名取 meta
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
```

> `meta` 是 `DeclarativeBase` 保留名，模型属性命名为 `meta_` 并显式 `mapped_column("meta", JSON)`，保持与 spec §5 的列名 `meta` 一致。

- [ ] **Step 5: Run test to verify it passes**
Run: `cd backend && python -m pytest tests/test_kb_models.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Run full suite**
Run: `cd backend && python -m pytest -q`
Expected: 69 passed（64 + 5）

- [ ] **Step 7: Commit**
```bash
git add backend/pyproject.toml backend/app/infrastructure/persistence/models.py backend/tests/test_kb_models.py
git commit -m "feat(backend): P1 依赖声明与 KnowledgeBase/Document/Chunk 三表"
```

---

## Task 2: Embedder 端口与 HashingEmbed 哨兵

**Files:**
- Create: `backend/app/infrastructure/ports/embedding.py`
- Create: `backend/app/infrastructure/adapters/embedding/__init__.py`
- Create: `backend/app/infrastructure/adapters/embedding/hashing_embed.py`
- Create: `backend/tests/test_hashing_embed.py`

**Interfaces:**
- Consumes: 无
- Produces: `Embedder` Protocol、`HashingEmbed()`。Task 3/4 实现同端口的另两个适配器。

> **ADR-0004**：HashingEmbed 是哨兵，其检索结果**一律不注入 prompt**。端口因此必须暴露 `is_sentinel`，让服务层能据此强制 `rag_hit=false`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hashing_embed.py
from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.ports.embedding import Embedder


def test_satisfies_embedder_port():
    emb = HashingEmbed()
    assert isinstance(emb, Embedder)  # Protocol 运行时检查（@runtime_checkable）


def test_is_sentinel():
    """ADR-0004：哨兵标记是服务层强制 rag_hit=false 的唯一依据。"""
    assert HashingEmbed().is_sentinel is True


def test_embed_is_deterministic():
    emb = HashingEmbed()
    a = emb.embed(["闭包是什么"])
    b = emb.embed(["闭包是什么"])
    assert a == b


def test_vectors_are_unit_length():
    import math

    v = HashingEmbed().embed(["列表推导式"])[0]
    assert len(v) == HashingEmbed().dimension
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6


def test_semantically_related_texts_are_not_close():
    """哨兵无语义：相近句与无关句的相似度不应呈现可用的区分度。

    该断言锁住「它不可用」这一事实 —— 若哪天它真的可分了，说明实现被改坏了。
    """
    emb = HashingEmbed()
    va, vb, vc = emb.embed([
        "如何用 Python 实现快速排序？",
        "Python 里快速排序的代码要怎么写？",
        "今天食堂的红烧肉味道不错。",
    ])

    def cos(x, y):
        return sum(i * j for i, j in zip(x, y))

    assert abs(cos(va, vb) - cos(va, vc)) < 0.3


def test_empty_input_returns_empty_list():
    assert HashingEmbed().embed([]) == []
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && python -m pytest tests/test_hashing_embed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.ports.embedding'`

- [ ] **Step 3: Write port**

```python
# backend/app/infrastructure/ports/embedding.py
"""向量化器端口（CONTEXT.md：向量化器 Embedder）。

embed() 设计为**同步**方法：底层是 CPU 密集的阻塞调用，由调用方统一经
run_in_threadpool 卸载（阻塞卸载 BlockingOffload，ADR-0002）。端口若声明为
async，就会把「是否卸载」的决定权推给适配器，容易出现忘记卸载的实现。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def is_sentinel(self) -> bool:
        """是否为哨兵级降级实现（ADR-0004）。

        True 表示其产出不参与业务逻辑：检索结果一律不注入 prompt。
        """
        ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- [ ] **Step 4: Write HashingEmbed**

```python
# backend/app/infrastructure/adapters/embedding/hashing_embed.py
import hashlib
import math

from app.infrastructure.ports.embedding import Embedder


class HashingEmbed:
    """哨兵级向量化器（ADR-0004）。

    字符 n-gram 哈希 + L2 归一化。向量**无语义**，检索结果近似随机。
    索引仍照常写入以保证链路可跑通，但检索阶段由服务层依据 is_sentinel
    强制 rag_hit=false + degraded=true + fallback_reason=hashing_embed_no_semantics。
    """

    name = "hashing"
    model = "hashing-256"
    dimension = 256
    is_sentinel = True

    _NGRAM = 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        grams = self._grams(text)
        if not grams:
            return vec
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:2], "big") % self.dimension
            sign = 1.0 if digest[2] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    def _grams(self, text: str) -> list[str]:
        s = "".join(ch for ch in text if not ch.isspace())
        if len(s) < self._NGRAM:
            return [s] if s else []
        return [s[i : i + self._NGRAM] for i in range(len(s) - self._NGRAM + 1)]
```

- [ ] **Step 5: Run test to verify it passes**
Run: `cd backend && python -m pytest tests/test_hashing_embed.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Run full suite → Commit**
```bash
git add backend/app/infrastructure/ports/embedding.py backend/app/infrastructure/adapters/embedding backend/tests/test_hashing_embed.py
git commit -m "feat(backend): Embedder 端口与 HashingEmbed 哨兵（ADR-0004）"
```

---

## Task 3: SentenceTransformer Embedder（单例懒加载 + 线程安全）

**Files:**
- Create: `backend/app/infrastructure/adapters/embedding/sentence_transformer.py`
- Create: `backend/tests/test_sentence_transformer_embed.py`

**Interfaces:**
- Consumes: `Embedder` 端口（Task 2）
- Produces: `SentenceTransformerEmbedder(model_name=...)`、`local_embed_available()`、`DEFAULT_LOCAL_EMBED_MODEL`

> **实测基准（Apple Silicon / macOS）**：`paraphrase-multilingual-MiniLM-L12-v2` 维度 384；模型缓存后加载 **13–20 秒**（阻塞调用，必须卸载到线程池）；64 段批量编码约 1 秒。语义相近句余弦相似度 > 0.9，语义无关句 < 0.05。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sentence_transformer_embed.py
import threading

import pytest

from app.infrastructure.adapters.embedding.sentence_transformer import (
    DEFAULT_LOCAL_EMBED_MODEL,
    SentenceTransformerEmbedder,
    local_embed_available,
)

pytestmark = pytest.mark.skipif(
    not local_embed_available(), reason="未安装 local-embed extras"
)


def test_dimension_matches_spec():
    """spec §7.3：MiniLM 为 384 维。"""
    assert SentenceTransformerEmbedder().dimension == 384


def test_embed_is_normalized():
    import math

    v = SentenceTransformerEmbedder().embed(["列表推导式"])[0]
    assert len(v) == 384
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-5


def test_model_is_lazily_loaded_once():
    """单例懒加载：连续调用不得重复加载模型（实测加载 13–20 秒）。"""
    emb = SentenceTransformerEmbedder()
    assert emb._model is None
    emb.embed(["预热"])
    first = emb._model
    emb.embed(["第二次"])
    assert emb._model is first


def test_concurrent_embed_shares_one_model_instance():
    """线程安全：10 个线程并发触发加载，模型实例必须唯一。"""
    emb = SentenceTransformerEmbedder()
    seen: list = []
    lock = threading.Lock()

    def work(i: int) -> None:
        emb.embed([f"第{i}段内容"])
        with lock:
            seen.append(emb._model)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 10
    assert all(m is seen[0] for m in seen)


def test_semantic_quality_regression():
    """检索质量回归断言：语义相近与无关必须能被明显分开。

    实测基准（2026-08-30，Apple Silicon CPU）：相近 ≈ 0.92，无关 ≈ 0.02。
    """
    emb = SentenceTransformerEmbedder()
    va, vb, vc = emb.embed([
        "如何用 Python 实现快速排序？",
        "Python 里快速排序的代码要怎么写？",
        "今天食堂的红烧肉味道不错。",
    ])

    def cos(x, y):
        return sum(i * j for i, j in zip(x, y))

    near, far = cos(va, vb), cos(va, vc)
    assert near > 0.80, f"语义相近句相似度偏低：{near}"
    assert far < 0.20, f"语义无关句相似度偏高：{far}"
    assert near - far > 0.60
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && python -m pytest tests/test_sentence_transformer_embed.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# backend/app/infrastructure/adapters/embedding/sentence_transformer.py
import threading
from importlib.util import find_spec

from app.infrastructure.ports.embedding import Embedder

DEFAULT_LOCAL_EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_DEFAULT_DIMENSION = 384
_BATCH_SIZE = 32


def local_embed_available() -> bool:
    """local-embed 是 optional extras，未装时须能优雅判定（ADR-0004）。"""
    return find_spec("sentence_transformers") is not None


class SentenceTransformerEmbedder:
    """本地向量化器（spec §2 三级回退的第二级）。

    模型**单例懒加载 + 线程安全**：实测加载耗时 13–20 秒，每次调用重新加载会
    让索引直接不可用。双检锁保证并发首次调用只加载一次。
    """

    name = "sentence_transformers"
    is_sentinel = False

    def __init__(self, model: str = DEFAULT_LOCAL_EMBED_MODEL, dimension: int = _DEFAULT_DIMENSION):
        self._model_name = model
        self._dimension = dimension
        self._model = None
        self._load_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        # normalize_embeddings=True：使余弦相似度等价于点积，与 Chroma 的
        # cosine 空间一致；show_progress_bar 在线程池中会污染日志
        vectors = model.encode(
            texts,
            batch_size=_BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd backend && python -m pytest tests/test_sentence_transformer_embed.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run full suite → Commit**

---

## Task 4: OpenAI 兼容 Embedder、三级回退与 EmbedderRuntime（异步后台预热）

**Files:**
- Create: `backend/app/infrastructure/adapters/embedding/openai_compat_embed.py`
- Create: `backend/app/infrastructure/embedder_runtime.py`
- Modify: `backend/app/infrastructure/registry.py`（追加 `resolve_embedder`）
- Create: `backend/tests/test_embedder_runtime.py`

**Interfaces:**
- Consumes: `Embedder` 端口（Task 2/3）、`ModelConfig`、`get_or_create_singleton`（P0）
- Produces: `EmbedderRuntime`：`embed()`（含三级回退）、`warmup()`、`is_ready`、`snapshot()`。Task 12/13/15 使用。

> **M10**：spec §9「Embedding 失败 → 三级回退」此前无落点。落 `EmbedderRuntime.embed()`：解析期回退（按可用性选级）+ 运行期回退（调用失败降级到下一级并记住该级）。
>
> **决策（用户拍板 1）**：启动时**异步后台预热**，不等它完成就对外提供服务；未就绪期间检索返回 5032。**禁止启动时同步阻塞加载**。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_embedder_runtime.py
import pytest

from app.core.errors import ApiError
from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.embedder_runtime import EmbedderRuntime


class _FakeEmb:
    def __init__(self, name="fake", model="fake-1", dimension=8, sentinel=False, boom=False):
        self.name, self.model = name, model
        self.dimension, self.is_sentinel = dimension, sentinel
        self._boom = boom
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        if self._boom:
            raise RuntimeError("上游不可用")
        return [[0.1] * self.dimension for _ in texts]


class _Broken(_FakeEmb):
    def __init__(self):
        super().__init__(name="broken", boom=True)


def _runtime(levels):
    return EmbedderRuntime(lambda level: levels[level] if level < len(levels) else None, levels=len(levels))


@pytest.mark.asyncio
async def test_not_ready_until_warmup():
    rt = _runtime([_FakeEmb()])
    assert rt.is_ready is False
    with pytest.raises(ApiError) as exc:
        rt.require_ready()
    assert exc.value.code == 5032


@pytest.mark.asyncio
async def test_warmup_offloads_and_marks_ready():
    rt = _runtime([_FakeEmb()])
    await rt.warmup()
    assert rt.is_ready is True
    assert rt.current.name == "fake"


@pytest.mark.asyncio
async def test_embed_falls_back_to_next_level_on_failure():
    """M10 / spec §9：调用失败降级到下一级，并记住降级后的级别。"""
    rt = _runtime([_Broken(), _FakeEmb()])
    await rt.warmup()
    assert rt.current.name == "fake"
    assert await rt.embed(["x"]) == [[0.1] * 8]


@pytest.mark.asyncio
async def test_embed_falls_back_to_hashing_sentinel_when_all_fail():
    rt = _runtime([_Broken(), _Broken(), HashingEmbed()])
    await rt.warmup()
    assert rt.current.is_sentinel is True


@pytest.mark.asyncio
async def test_embed_raises_5032_when_every_level_fails():
    rt = _runtime([_Broken()])
    await rt.warmup()
    assert rt.is_ready is False
    with pytest.raises(ApiError) as exc:
        await rt.embed(["x"])
    assert exc.value.code == 5032


@pytest.mark.asyncio
async def test_snapshot_exposes_status_for_health():
    rt = _runtime([_FakeEmb()])
    assert rt.snapshot() == {"name": None, "model": None, "ready": False, "error": None}
    await rt.warmup()
    snap = rt.snapshot()
    assert snap["ready"] is True and snap["name"] == "fake"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && python -m pytest tests/test_embedder_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write OpenAI 兼容 embedder**

```python
# backend/app/infrastructure/adapters/embedding/openai_compat_embed.py
import httpx

from app.infrastructure.ports.embedding import Embedder

_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSION = 1536
_BATCH = 64


class OpenAICompatEmbedder:
    """OpenAI 兼容 /embeddings 向量化器（三级回退的第一级）。"""

    name = "openai_compat"
    is_sentinel = False

    def __init__(self, base_url, api_key, model=_DEFAULT_MODEL, dimension=_DEFAULT_DIMENSION):
        ...
    def embed(self, texts) -> list[list[float]]:
        # 同步 httpx：由调用方经 run_in_threadpool 卸载
        ...
```

- [ ] **Step 4: Extend registry with resolve_embedder**

```python
# 追加到 backend/app/infrastructure/registry.py
EMBED_LEVEL_OPENAI = 0
EMBED_LEVEL_LOCAL = 1
EMBED_LEVEL_HASHING = 2
EMBED_LEVELS = 3


def build_embedder(cfg: ModelConfig, level: int) -> Embedder | None:
    """按级别构建向量化器；该级不可用时返回 None，由调用方降级。"""
    if level <= EMBED_LEVEL_OPENAI:
        if cfg.embedding_provider == "openai_compat" and cfg.api_key_encrypted:
            return OpenAICompatEmbedder(
                base_url=cfg.base_url or "",
                api_key=decrypt_api_key(cfg.api_key_encrypted),
                model=cfg.embedding_model or _DEFAULT_MODEL,
            )
    if level <= EMBED_LEVEL_LOCAL and cfg.embedding_provider != "hashing":
        if local_embed_available():
            return SentenceTransformerEmbedder(cfg.embedding_model or DEFAULT_LOCAL_EMBED_MODEL)
    if level <= EMBED_LEVEL_HASHING:
        return HashingEmbed()
    return None
```

- [ ] **Step 5: Write EmbedderRuntime**

```python
# backend/app/infrastructure/embedder_runtime.py
class EmbedderRuntime:
    """进程级向量化器运行时：三级回退 + 异步后台预热 + 就绪状态。

    级别越低越「真」：0=OpenAI 兼容，1=sentence-transformers，2=HashingEmbed 哨兵。
    运行期任一级失败即降级到下一级并记住当前级别，避免每次请求重复试错。
    """

    def __init__(self, factory, levels: int = EMBED_LEVELS):
        self._factory = factory
        self._levels = levels
        self._level = 0
        self._embedder: Embedder | None = None
        self._ready = False
        self._error: str | None = None

    @property
    def is_ready(self) -> bool: return self._ready

    @property
    def current(self) -> Embedder | None: return self._embedder

    def snapshot(self) -> dict:
        return {"name": ..., "model": ..., "ready": self._ready, "error": self._error}

    def require_ready(self) -> Embedder:
        if not self._ready:
            raise ApiError(5032, "向量模型正在加载，请稍后重试")
        return self._embedder

    async def warmup(self) -> None:
        """异步后台预热：加载模型并完成一次探针编码。禁止阻塞启动流程。"""
        try:
            await self.embed([_WARMUP_PROBE])
        except ApiError:
            pass  # 三级全部失败：保持未就绪，/health 暴露 error

    async def embed(self, texts: list[str]) -> list[list[float]]:
        for level in range(self._level, self._levels):
            emb = self._factory(level)
            if emb is None:
                continue
            try:
                vectors = await run_in_threadpool(emb.embed, texts)
            except Exception as exc:
                logger.warning("向量化器 %s 调用失败，降级到下一级：%s", emb.name, exc)
                continue
            self._level, self._embedder, self._ready, self._error = level, emb, True, None
            return vectors
        self._ready, self._error = False, "所有向量化器均不可用"
        raise ApiError(5032, "向量化服务不可用，知识库功能暂时降级")
```

- [ ] **Step 6: Run test to verify it passes / full suite / Commit**

---

## Task 5: VectorStore 端口与 Chroma 适配器

**Files:**
- Create: `backend/app/infrastructure/ports/vectorstore.py`
- Create: `backend/app/infrastructure/adapters/vectorstore/__init__.py`
- Create: `backend/app/infrastructure/adapters/vectorstore/chroma_store.py`
- Create: `backend/tests/test_chroma_store.py`

**Interfaces:**
- Consumes: 无
- Produces: `VectorStore` Protocol、`ChromaVectorStore(persist_dir)`、`VectorHit`。Task 10–12 使用。

> **spec §3.2 权衡 4**：Chroma **单集合** + `kb_id` 元数据过滤。代价是每次检索必须带过滤条件 —— 因此 `query()` 的 `kb_ids` 为**必填参数**，从签名上防止漏过滤。
> 集合名 `course_chunks`（Chroma 1.x 要求 3–512 字符）。

- [ ] **Step 1: Write the failing test**（用 `tmp_path` 起真实 Chroma，非 mock）

```python
# backend/tests/test_chroma_store.py
import pytest

from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.ports.vectorstore import VectorRecord


@pytest.fixture
def store(tmp_path):
    return ChromaVectorStore(persist_dir=tmp_path / "chroma")


def _rec(vid, kb, doc, vec):
    return VectorRecord(vector_id=vid, kb_id=kb, document_id=doc, embedding=vec, content=vec and "文本")


@pytest.mark.asyncio
async def test_upsert_then_query_filters_by_kb(store):
    await store.upsert([_rec("v1", "kb1", "d1", [1.0, 0.0, 0.0, 0.0])])
    await store.upsert([_rec("v2", "kb2", "d2", [1.0, 0.0, 0.0, 0.0])])

    hits = await store.query([1.0, 0.0, 0.0, 0.0], top_k=5, kb_ids=["kb1"])
    assert [h.vector_id for h in hits] == ["v1"]


@pytest.mark.asyncio
async def test_score_is_cosine_similarity_not_distance(store):
    """Chroma 返回余弦距离，端口必须换算为相似度，否则阈值语义反了。"""
    await store.upsert([
        _rec("same", "kb", "d", [1.0, 0.0, 0.0, 0.0]),
        _rec("orth", "kb", "d", [0.0, 1.0, 0.0, 0.0]),
    ])
    hits = await store.query([1.0, 0.0, 0.0, 0.0], top_k=2, kb_ids=["kb"])
    by_id = {h.vector_id: h.score for h in hits}
    assert by_id["same"] == pytest.approx(1.0, abs=1e-5)
    assert by_id["orth"] == pytest.approx(0.0, abs=1e-5)


@pytest.mark.asyncio
async def test_query_across_multiple_kb_ids(store):
    ...


@pytest.mark.asyncio
async def test_delete_by_kb_and_by_ids(store):
    ...


@pytest.mark.asyncio
async def test_list_ids_for_gc(store):
    """孤儿向量清理需要枚举 Chroma 中某个 kb 的全部向量 id。"""
    ...
```

- [ ] **Step 2–5**：实现端口与适配器，全部 Chroma 调用经 `run_in_threadpool` 卸载；`score = 1 - distance`。
- [ ] **Step 6: full suite → Commit**

---

## Task 6: 领域层切分器（按字符 1200 / 150 重叠）

**Files:**
- Create: `backend/app/domain/knowledge/__init__.py`
- Create: `backend/app/domain/knowledge/status.py`
- Create: `backend/app/domain/knowledge/chunker.py`
- Create: `backend/tests/test_chunker.py`

**Interfaces:**
- Consumes: 无
- Produces: `CHUNK_SIZE=1200`、`CHUNK_OVERLAP=150`、`split_text(text) -> list[str]`。Task 11 使用。

> **spec §8.2**：切分**按字符数计量，不用 token**。中文 token 密度与英文相差 2–3 倍，用 tokenizer 计量会导致切片粒度不可预测。
> 切分策略：先按 Markdown 标题切 section → 段内按空行贪心打包 → 单段超长走固定窗口（步长 = 1200 − 150）→ 相邻切片携带上一片尾部 150 字符。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chunker.py
from app.domain.knowledge.chunker import CHUNK_OVERLAP, CHUNK_SIZE, split_text


def test_chunk_size_and_overlap_match_spec():
    """spec §8.2：1200 字符 / 150 字符重叠。"""
    assert (CHUNK_SIZE, CHUNK_OVERLAP) == (1200, 150)


def test_short_text_yields_single_chunk():
    assert split_text("短文本。") == ["短文本。"]


def test_empty_text_yields_no_chunk():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_long_text_is_split_with_bounded_size():
    text = "这是一段用于验证切分长度的中文文本内容。" * 200  # 3800 字
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_consecutive_chunks_overlap_by_150_chars():
    text = "".join(f"第{i}句话，用于构造连续文本。" for i in range(400))
    chunks = split_text(text)
    assert len(chunks) >= 2
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.startswith(prev[-CHUNK_OVERLAP:])


def test_markdown_headings_start_new_chunks():
    text = "# 第一章\n" + "内容一。" * 20 + "\n\n# 第二章\n" + "内容二。" * 20
    chunks = split_text(text)
    assert any(c.lstrip().startswith("# 第一章") for c in chunks)
    assert any("# 第二章" in c for c in chunks)


def test_no_content_is_lost_except_overlap():
    import re

    text = "".join(f"片段{i}。" for i in range(300))
    joined = "".join(split_text(text))
    assert re.sub(r"\s", "", text) in re.sub(r"\s", "", joined)
```

- [ ] **Step 2–5**：实现 `split_text`。
- [ ] **Step 6: full suite → Commit**

---

## Task 7: 领域层检索规则（阈值 / 相对截断 / 多样性截取）

**Files:**
- Create: `backend/app/domain/knowledge/retrieval.py`
- Create: `backend/tests/test_retrieval_rules.py`

**Interfaces:**
- Consumes: 无
- Produces: `default_score_threshold()`、`resolve_score_threshold()`、`apply_score_threshold()`、`apply_relative_truncation()`、`apply_diversity_truncation()`、`number_chunks()`。Task 12 使用。

> **M1 / spec §3.2 权衡 8**：`score_threshold` 按 embedding 模型分别取默认值 —— OpenAI 兼容 **0.25** / MiniLM **0.35** / 其他 **0.30**；`ModelConfig.score_threshold` 为 `None` 时用模型默认值。
> **spec §7.2 步骤 3–5**：相对截断（与最佳命中分差 > 0.15 丢弃）、多样性截取（单文档最多 3 片段）、片段编号 `[1][2][3]`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retrieval_rules.py
from app.domain.knowledge.retrieval import (
    MAX_CHUNKS_PER_DOCUMENT,
    RELATIVE_TRUNCATION_MARGIN,
    apply_diversity_truncation,
    apply_relative_truncation,
    apply_score_threshold,
    default_score_threshold,
    number_chunks,
    resolve_score_threshold,
)


def _hit(cid, doc, score):
    return {"chunk_id": cid, "document_id": doc, "score": score}


def test_default_threshold_per_embedding_model():
    """M1：spec §3.2 权衡 8 的 0.25 / 0.35 / 0.30。"""
    assert default_score_threshold("openai_compat", "text-embedding-3-small") == 0.25
    assert default_score_threshold(
        "sentence_transformers", "paraphrase-multilingual-MiniLM-L12-v2"
    ) == 0.35
    assert default_score_threshold("hashing", "hashing-256") == 0.30


def test_resolve_threshold_prefers_configured_value():
    assert resolve_score_threshold(0.42, "hashing", "hashing-256") == 0.42
    assert resolve_score_threshold(None, "openai_compat", "m") == 0.25


def test_threshold_drops_low_scores():
    kept = apply_score_threshold([_hit("a", "d", 0.9), _hit("b", "d", 0.1)], 0.35)
    assert [h["chunk_id"] for h in kept] == ["a"]


def test_relative_truncation_drops_hits_far_from_best():
    """spec §7.2 步骤 3：与最佳命中分差 > 0.15 一律丢弃。"""
    hits = [_hit("a", "d1", 0.90), _hit("b", "d2", 0.80), _hit("c", "d3", 0.70)]
    kept = apply_relative_truncation(hits)
    assert [h["chunk_id"] for h in kept] == ["a", "b"]


def test_relative_truncation_keeps_all_when_scores_are_close():
    hits = [_hit("a", "d", 0.5), _hit("b", "d", 0.45), _hit("c", "d", 0.4)]
    assert len(apply_relative_truncation(hits)) == 3


def test_diversity_truncation_caps_three_chunks_per_document():
    """spec §7.2 步骤 4：防止长文档霸占上下文。"""
    assert MAX_CHUNKS_PER_DOCUMENT == 3
    hits = [_hit(f"c{i}", "d1", 0.9 - i * 0.01) for i in range(6)]
    kept = apply_diversity_truncation(hits)
    assert len(kept) == 3


def test_diversity_truncation_spreads_across_documents():
    hits = [_hit("a1", "d1", 0.9), _hit("a2", "d1", 0.88), _hit("b1", "d2", 0.7)]
    kept = apply_diversity_truncation(hits)
    assert {h["document_id"] for h in kept} == {"d1", "d2"}


def test_chunks_are_numbered_from_one():
    assert number_chunks([_hit("a", "d", 0.9), _hit("b", "d", 0.8)])[0] == (1, _hit("a", "d", 0.9))


def test_relative_truncation_margin_matches_spec():
    assert RELATIVE_TRUNCATION_MARGIN == 0.15
```

- [ ] **Step 2–5**：实现纯函数。
- [ ] **Step 6: full suite → Commit**

---

## Task 8: 文档解析适配器与上传校验

**Files:**
- Create: `backend/app/domain/knowledge/upload.py`
- Create: `backend/app/infrastructure/ports/document.py`
- Create: `backend/app/infrastructure/adapters/document/__init__.py`
- Create: `backend/app/infrastructure/adapters/document/parsers.py`
- Create: `backend/tests/test_document_parsers.py`
- Create: `backend/tests/test_upload_validation.py`

**Interfaces:**
- Consumes: 无
- Produces: `parse_document(path, source_type) -> ParsedDocument`、`validate_upload(filename, size) -> str`（返回 `source_type`）。Task 11 使用。

> **spec §8.2**：单文件上限 **10MB**（超出 `413`）；扩展名白名单 `.pdf .md .txt .docx`（不在白名单 `415`）；无文字层的扫描版 PDF 判为解析失败并提示 **不做 OCR**（spec §3.3）。
> 领域异常 `FileTooLargeError` / `UnsupportedFileTypeError` / `EmptyDocumentError` 由服务层映射为 `ApiError`，保持领域层零基础设施依赖。

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_upload_validation.py
import pytest

from app.domain.knowledge.upload import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    FileTooLargeError,
    UnsupportedFileTypeError,
    validate_upload,
)


def test_limits_match_spec():
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert set(ALLOWED_EXTENSIONS) == {".pdf", ".md", ".txt", ".docx"}


def test_extension_whitelist():
    assert validate_upload("a.md", 10) == "md"
    assert validate_upload("a.PDF", 10) == "pdf"
    assert validate_upload("a.docx", 10) == "docx"
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("a.exe", 10)
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("a", 10)


def test_size_limit():
    with pytest.raises(FileTooLargeError):
        validate_upload("a.pdf", MAX_UPLOAD_BYTES + 1)
```

```python
# backend/tests/test_document_parsers.py
import pytest

from app.infrastructure.adapters.document.parsers import EmptyDocumentError, parse_document


def test_plain_text_is_read_directly(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("闭包是函数与其引用环境的组合。", encoding="utf-8")
    parsed = parse_document(p, "txt")
    assert "闭包" in parsed.text


def test_markdown_is_read_directly(tmp_path):
    ...


def test_docx_is_parsed_with_python_docx(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("第一段：列表推导式。")
    d.add_paragraph("第二段：生成器表达式。")
    p = tmp_path / "a.docx"
    d.save(p)
    parsed = parse_document(p, "docx")
    assert "列表推导式" in parsed.text and "生成器表达式" in parsed.text


def test_pdf_without_text_layer_is_rejected(tmp_path):
    """spec §8.2：扫描版 PDF 判为解析失败，不做 OCR。"""
    pdfplumber = pytest.importorskip("pdfplumber")
    from reportlab.pdfgen import canvas  # 仅在可用时执行

    ...


def test_empty_text_raises_empty_document_error(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("   \n\t ", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        parse_document(p, "txt")
```

- [ ] **Step 2–5**：实现 `parsers.py`（pdfplumber 逐页 `extract_text()`，docx 逐段落，md/txt 直读；文本长度 `< MIN_TEXT_CHARS(10)` 抛 `EmptyDocumentError`，错误消息 `"未提取到文本，可能是扫描版 PDF，请先做 OCR"`）。
- [ ] **Step 6: full suite → Commit**

---

## Task 9: 并发控制（知识库锁 + 索引信号量）

**Files:**
- Create: `backend/app/infrastructure/concurrency.py`
- Create: `backend/tests/test_concurrency.py`

**Interfaces:**
- Consumes: 无
- Produces: `kb_lock(kb_id)`、`index_slot()`、`reset_concurrency()`。Task 10–13 使用。

> **CONTEXT.md「知识库锁」**：per-`kb_id` 的 `asyncio.Lock`，保护索引 / 删除 / 重建 / GC；**检索不持锁**。锁对象按 `kb_id` 懒创建并定期清理，防止内存泄漏（spec §8.2）。
> **spec §3.2 权衡 14**：索引全局并发上限 **1**。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_concurrency.py
import asyncio

import pytest

from app.infrastructure.concurrency import index_slot, kb_lock, reset_concurrency


@pytest.fixture(autouse=True)
def _reset():
    reset_concurrency()
    yield
    reset_concurrency()


@pytest.mark.asyncio
async def test_same_kb_shares_one_lock():
    async with kb_lock("kb1") as a:
        async with kb_lock("kb1") as b:
            assert a is b


@pytest.mark.asyncio
async def test_different_kb_have_different_locks():
    async with kb_lock("kb1") as a:
        async with kb_lock("kb2") as b:
            assert a is not b


@pytest.mark.asyncio
async def test_lock_serializes_writes_for_same_kb():
    order = []

    async def worker(tag):
        async with kb_lock("kb1"):
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


@pytest.mark.asyncio
async def test_index_slot_allows_only_one_concurrent():
    """spec §3.2 权衡 14：索引全局并发上限 1。"""
    live = 0
    peak = 0

    async def worker():
        nonlocal live, peak
        async with index_slot():
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*[worker() for _ in range(4)])
    assert peak == 1


def test_locks_are_swept_after_release():
    ...
```

- [ ] **Step 2–5**：实现。
- [ ] **Step 6: full suite → Commit**

---

## Task 10: KnowledgeBaseService（CRUD + 删除顺序 + 孤儿向量 GC）

**Files:**
- Create: `backend/app/services/knowledge_service.py`
- Create: `backend/tests/fakes.py`
- Create: `backend/tests/test_knowledge_service.py`

**Interfaces:**
- Consumes: `VectorStore` 端口（Task 5）、`concurrency`（Task 9）、`AuditService`（P0）、`KnowledgeBase/Document/Chunk`（Task 1）
- Produces: `KnowledgeBaseService`。Task 14 路由使用。

> **spec §8.6**：删除顺序**固定三步、不可颠倒** —— 先删 Chroma 向量 → 再删 `Chunk` 行 → 再删 `Document` / `KnowledgeBase` 行。Chroma 删除失败**仍继续删 DB**，但写 `AuditLog(action=admin_kb_delete, detail={vector_cleanup: "failed"})`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_service.py
import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import AuditLog, Chunk, Document, KnowledgeBase
from app.services.knowledge_service import KnowledgeBaseService
from tests.fakes import ExplodingVectorStore, FakeVectorStore


async def _seed(session, store, *, chunks=2):
    kb = await KnowledgeBaseService(session, vector_store=store).create(
        name="Python 基础", course_code="CS101", owner_id="u1"
    )
    doc = Document(kb_id=kb.id, title="第 1 讲", source_type="md", status="ready")
    session.add(doc)
    await session.flush()
    for i in range(chunks):
        session.add(Chunk(document_id=doc.id, kb_id=kb.id, content=f"c{i}", ordinal=i, char_count=2, vector_id=f"v{i}"))
    await session.commit()
    return kb, doc


@pytest.mark.asyncio
async def test_create_persists_knowledge_base(session):
    svc = KnowledgeBaseService(session, vector_store=FakeVectorStore())
    kb = await svc.create(name="kb", course_code="CS101", owner_id="u1")
    await session.commit()
    assert kb.course_code == "CS101" and kb.status == "ready"


@pytest.mark.asyncio
async def test_list_filters_by_course_code(session):
    ...


@pytest.mark.asyncio
async def test_delete_removes_vectors_before_rows(session):
    """spec §8.6：顺序不可颠倒。"""
    store = FakeVectorStore()
    kb, doc = await _seed(session, store)
    await KnowledgeBaseService(session, vector_store=store).delete(kb.id, user_id="admin", request_id="rid")
    await session.commit()

    # Chroma 侧先删，随后才是 DB 行
    assert store.calls == ["delete_by_kb:kb", ...] or store.deleted_kbs == [kb.id]
    assert (await session.execute(select(Chunk))).scalars().all() == []
    assert (await session.execute(select(Document))).scalars().all() == []
    assert (await session.execute(select(KnowledgeBase))).scalars().all() == []


@pytest.mark.asyncio
async def test_delete_continues_when_vector_cleanup_fails(session):
    """spec §8.6：Chroma 删除失败仍继续删 DB，并落审计告警。"""
    store = ExplodingVectorStore()
    kb, doc = await _seed(session, store)
    await KnowledgeBaseService(session, vector_store=store).delete(kb.id, user_id="admin", request_id="rid")
    await session.commit()

    assert (await session.execute(select(KnowledgeBase))).scalars().all() == []
    row = (await session.execute(select(AuditLog).where(AuditLog.action == "admin_kb_delete"))).scalar_one()
    assert row.detail["vector_cleanup"] == "failed"


@pytest.mark.asyncio
async def test_gc_removes_orphan_vectors_only(session):
    """CONTEXT.md「孤儿向量」：Chroma 中有、Chunk 表中无。"""
    store = FakeVectorStore(preloaded={"kb1": ["v1", "v2", "v3"]})
    kb, doc = await _seed(session, store, chunks=2)  # v0 / v1 有效
    result = await KnowledgeBaseService(session, vector_store=store).gc_orphan_vectors(kb.id)
    assert result["deleted"] == 1  # 仅 v2/v3 中属于该 kb 的部分
```

- [ ] **Step 2–5**：实现服务与 `tests/fakes.py`。
- [ ] **Step 6: full suite → Commit**

---

## Task 11: IndexingService（BackgroundTasks + 阻塞卸载 + 进度可见）

**Files:**
- Create: `backend/app/domain/knowledge/upload.py`（已完成于 Task 8）
- Create: `backend/app/services/document_service.py`
- Create: `backend/app/services/indexing_service.py`
- Create: `backend/tests/test_indexing_service.py`

**Interfaces:**
- Consumes: `EmbedderRuntime`（Task 4）、`VectorStore`（Task 5）、`split_text`（Task 6）、`parse_document`（Task 8）、`concurrency`（Task 9）
- Produces: `DocumentService.accept_upload()`、`IndexingService.index_document()` / `reindex_document()` / `rebuild_knowledge_base()`

> **spec §8.2 / ADR-0002**：整段索引（解析 + embedding 推理）**必须经 `run_in_threadpool` 卸载**，否则单次索引会冻结整个后端。
> **进度可见**：`Document.chunk_indexed / chunk_total` 分批提交，管理端可轮询。
> 后台任务不可复用请求会话 —— 从 `db.SessionFactory`（**调用时**取属性，便于测试替换）新建会话。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_indexing_service.py
import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import Chunk, Document
from app.services.indexing_service import IndexingService
from tests.fakes import FakeEmbedder, FakeVectorStore, SlowEmbedder


async def _mk(session, tmp_path, text="## 标题\n" + "内容。" * 300, name="a.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    doc = Document(kb_id="kb1", title="t", source_type="md", source_uri=str(p), status="pending")
    session.add(doc)
    await session.commit()
    return doc


@pytest.mark.asyncio
async def test_index_document_produces_chunks_and_marks_ready(session, tmp_path):
    doc = await _mk(session, tmp_path)
    await IndexingService(session, embedder=FakeEmbedder(), vector_store=FakeVectorStore()).index_document(doc.id)
    await session.commit()

    got = (await session.execute(select(Document))).scalar_one()
    assert got.status == "ready"
    assert got.chunk_total > 1 and got.chunk_indexed == got.chunk_total
    rows = (await session.execute(select(Chunk))).scalars().all()
    assert len(rows) == got.chunk_total
    assert all(r.vector_id for r in rows)
    assert rows[0].embed_model == "fake-1"


@pytest.mark.asyncio
async def test_progress_is_committed_incrementally(session, tmp_path):
    """进度可见：索引过程中 chunk_indexed 逐步增长，而非一次性跳到 total。"""
    ...


@pytest.mark.asyncio
async def test_parse_failure_marks_document_failed_with_error_msg(session, tmp_path):
    doc = await _mk(session, tmp_path, text="   ", name="empty.md")
    await IndexingService(session, embedder=FakeEmbedder(), vector_store=FakeVectorStore()).index_document(doc.id)
    got = (await session.execute(select(Document))).scalar_one()
    assert got.status == "failed"
    assert got.error_msg


@pytest.mark.asyncio
async def test_missing_file_marks_document_failed(session):
    ...


@pytest.mark.asyncio
async def test_indexing_runs_outside_event_loop_blocking_path(session, tmp_path):
    """ADR-0002：embedding 推理不得在事件循环上执行。"""
    ...
```

- [ ] **Step 2–5**：实现。索引分批（32 段/批），每批 embed → upsert → 落 Chunk 行 → 更新 `chunk_indexed` → commit。
- [ ] **Step 6: full suite → Commit**

---

## Task 12: RetrievalService（spec §7.2 七步装配链路）

**Files:**
- Create: `backend/app/services/retrieval_service.py`
- Create: `backend/tests/test_retrieval_service.py`

**Interfaces:**
- Consumes: `EmbedderRuntime`（Task 4）、`VectorStore`（Task 5）、领域检索规则（Task 7）、`ModelConfig`
- Produces: `RetrievalService.search()` → `SearchResult(rag_hit, degraded, fallback_reason, citations, threshold, embedder)`。Task 14 与 P2 使用。

> **spec §7.2 七步**：embed → 阈值过滤 → 相对截断 → 多样性截取 → 编号 → 写 citations → 零命中明确降级。
> **ADR-0004**：实际生效的 Embedder 为 HashingEmbed 时，**结果一律不注入 prompt**，强制 `rag_hit=false + degraded=true + fallback_reason=hashing_embed_no_semantics`。
> **spec §9**：KB 不存在 → `4040`；未就绪 → `5032`；Embedder 未就绪 → `5032`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retrieval_service.py
import pytest

from app.core.errors import ApiError
from app.infrastructure.persistence.models import KnowledgeBase
from app.services.retrieval_service import RetrievalService
from tests.fakes import FakeEmbedder, FakeVectorStore, SentinelEmbedder, StubVectorStore


@pytest.mark.asyncio
async def test_unknown_kb_returns_4040(session):
    with pytest.raises(ApiError) as exc:
        await RetrievalService(session, embedder=FakeEmbedder(), vector_store=FakeVectorStore()).search(
            "问题", kb_ids=["nope"]
        )
    assert exc.value.code == 4040


@pytest.mark.asyncio
async def test_reindexing_kb_returns_5032(session):
    session.add(KnowledgeBase(id="kb1", name="kb", status="reindexing"))
    await session.commit()
    with pytest.raises(ApiError) as exc:
        await RetrievalService(session, embedder=FakeEmbedder(), vector_store=FakeVectorStore()).search(
            "问题", kb_ids=["kb1"]
        )
    assert exc.value.code == 5032


@pytest.mark.asyncio
async def test_sentinel_embedder_forces_rag_hit_false(session):
    """ADR-0004：哨兵级降级的产出不参与业务逻辑。"""
    session.add(KnowledgeBase(id="kb1", name="kb", status="ready"))
    await session.commit()
    result = await RetrievalService(
        session, embedder=SentinelEmbedder(), vector_store=StubVectorStore([...])
    ).search("问题", kb_ids=["kb1"])
    assert result.rag_hit is False
    assert result.degraded is True
    assert result.fallback_reason == "hashing_embed_no_semantics"
    assert result.citations == []


@pytest.mark.asyncio
async def test_relative_truncation_and_diversity_are_applied(session):
    ...


@pytest.mark.asyncio
async def test_zero_hit_reports_rag_hit_false(session):
    ...


@pytest.mark.asyncio
async def test_course_code_scopes_the_search(session):
    """course_code 为空表示不限课程（spec §6.2）。"""
    ...


@pytest.mark.asyncio
async def test_embedder_not_ready_returns_5032(session):
    ...
```

- [ ] **Step 2–5**：实现。
- [ ] **Step 6: full suite → Commit**

---

## Task 13: Embedding 配置变更 409 与强制重建

**Files:**
- Create: `backend/app/services/model_config_service.py`
- Create: `backend/app/services/rebuild_service.py`
- Create: `backend/tests/test_embedding_switch.py`

**Interfaces:**
- Consumes: `get_or_create_singleton()`（P0）、`Chunk`（Task 1）、`IndexingService`（Task 11）、`concurrency`（Task 9）
- Produces: `ModelConfigService.update_embedding()`（409 + `need_rebuild`）、`RebuildService.rebuild()`

> **spec §8.7**：切换即强制全量重建，不允许边用边切。已存在 `Chunk` 行 → `409 + need_rebuild: true`；二次确认后触发重建，KB 置 `reindexing`，期间检索返回 `5032`；`Chunk.embed_model` 记录实际索引所用模型。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_embedding_switch.py
import pytest
from sqlalchemy import select

from app.core.errors import ApiError
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.services.model_config_service import ModelConfigService
from app.services.rebuild_service import RebuildService
from tests.fakes import FakeEmbedder, FakeVectorStore


async def _kb_with_chunks(session, model="old-model"):
    session.add(KnowledgeBase(id="kb1", name="kb", embed_model=model, embed_provider="p"))
    doc = Document(id="d1", kb_id="kb1", title="t", source_type="md", status="ready")
    session.add(doc)
    session.add(Chunk(document_id="d1", kb_id="kb1", content="c", ordinal=0, char_count=1, embed_model=model, vector_id="v0"))
    await session.commit()


@pytest.mark.asyncio
async def test_switching_embedding_with_existing_chunks_returns_409(session):
    await _kb_with_chunks(session)
    with pytest.raises(ApiError) as exc:
        await ModelConfigService(session).update_embedding(
            provider="sentence_transformers", model="paraphrase-multilingual-MiniLM-L12-v2", confirm=False
        )
    assert exc.value.code == 4090
    assert exc.value.payload["need_rebuild"] is True


@pytest.mark.asyncio
async def test_confirmed_switch_persists_and_keeps_need_rebuild(session):
    """409 + 二次确认：保存配置，返回待重建的知识库清单。"""
    ...


@pytest.mark.asyncio
async def test_switch_without_existing_chunks_succeeds(session):
    ...


@pytest.mark.asyncio
async def test_rebuild_reindexes_every_chunk_with_new_model(session, tmp_path):
    ...


@pytest.mark.asyncio
async def test_rebuild_sets_kb_reindexing_then_ready(session, tmp_path):
    ...
```

- [ ] **Step 2–5**：实现。
- [ ] **Step 6: full suite → Commit**

---

## Task 14: 路由层（学生端 + 管理端全部端点）

**Files:**
- Create: `backend/app/schemas/knowledge.py`
- Create: `backend/app/routers/knowledge.py`
- Create: `backend/app/routers/admin_knowledge.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_knowledge_api.py`

**Interfaces:**
- Consumes: Task 10–13 全部服务、`require_admin`、`CurrentRidDep`、`AuditService`
- Produces: spec §6.2 `knowledge` 行 2 个端点 + `admin·kb` 行 10 个端点

> **H3**：所有端点注入 `CurrentRidDep`，禁止硬编码 `request_id=""`。
> 上传超限 `413`（`code=4130`）、类型不支持 `415`（`code=4150`），需同步扩充 `core/errors.py` 的 `CODE_STATUS`。

- [ ] **Step 1: Write the failing test**（`httpx.AsyncClient` + 内存 SQLite，`dependency_overrides`）

```python
# backend/tests/test_knowledge_api.py
import pytest

STUDENT = {"username": "stu", "password": "Secret123!"}


async def _login_as(client, username, password):
    ...


@pytest.mark.asyncio
async def test_student_can_list_and_search(client):
    ...
@pytest.mark.asyncio
async def test_search_on_unknown_kb_returns_4040(client):
    ...
@pytest.mark.asyncio
async def test_admin_only_endpoints_reject_student(client):
    ...
@pytest.mark.asyncio
async def test_upload_rejects_oversized_file_with_413(client):
    ...
@pytest.mark.asyncio
async def test_upload_rejects_bad_extension_with_415(client):
    ...
@pytest.mark.asyncio
async def test_upload_then_list_documents_then_chunks(client, tmp_path):
    ...
@pytest.mark.asyncio
async def test_reindex_and_delete_document(client, tmp_path):
    ...
@pytest.mark.asyncio
async def test_rebuild_vector_and_gc_orphan_vectors(client, tmp_path):
    ...
```

- [ ] **Step 2–6**：实现路由、schema、main 注册；全量测试；commit。

---

## Task 15: 启动预热、/health 就绪状态、ADR 补充与全量验收

**Files:**
- Modify: `backend/app/main.py`（lifespan）
- Modify: `backend/app/core/errors.py`（扩充 4130/4150）
- Modify: `backend/app/infrastructure/embedder_runtime.py`（进程级单例与访问器）
- Create: `docs/adr/0007-chroma-single-collection-metadata-filter.md`
- Create: `docs/adr/0008-char-based-chunking.md`
- Create: `docs/adr/0009-relative-truncation-over-absolute-threshold.md`
- Create: `docs/adr/0010-weak-knowledge-point-realtime-aggregation.md`
- Create: `backend/tests/test_health_ready.py`
- Modify: `backend/app/infrastructure/persistence/models.py`（无结构变更则跳过）

> **决策（用户拍板 1）**：启动时**异步后台预热**，不阻塞对外服务；`/health` 返回模型就绪状态；未就绪期间检索返回 `5032`。
> **L1**：补齐 4 篇 ADR（Chroma 单集合 / 按字符切分 / 相对截断 / 薄弱知识点实时聚合）。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_health_ready.py
def test_health_reports_embedder_readiness():
    body = client.get("/health").json()["data"]
    assert "embedder" in body
    assert body["embedder"]["ready"] in (True, False)


@pytest.mark.asyncio
async def test_search_before_ready_returns_5032(client):
    ...
```

- [ ] **Step 2–7**：实现 lifespan（建表 → 一致性校验告警 → `asyncio.create_task(warmup())`）、/health 载荷、4 篇 ADR；跑全量测试；commit。

---

## 验收清单（P1 完成标准）

- [ ] `make test` 全绿，且无 P0 回归（基线 64 passed）
- [ ] 上传 `.md` / `.txt` / `.docx` / `.pdf` 四类文件均可完成索引；扫描版 PDF 判为 `failed` 并给出 OCR 提示
- [ ] 上传 >10MB 返回 413；非白名单扩展名返回 415
- [ ] 检索能把语义相近句（实测 ≈0.92）与无关句（实测 ≈0.02）明显分开
- [ ] 无 API Key 且有本地模型 → 走 `sentence_transformers`，检索可用
- [ ] 无 API Key 且无本地模型 → 走 HashingEmbed 哨兵，`rag_hit=false` + `degraded=true` + `fallback_reason=hashing_embed_no_semantics`
- [ ] 切换 embedding 配置且已有切片 → `409` + `need_rebuild:true`；确认后重建，期间检索 `5032`
- [ ] 删除知识库时 Chroma 删除失败仍继续删 DB，并落 `AuditLog(action=admin_kb_delete, detail={vector_cleanup:"failed"})`
- [ ] `gc-orphan-vectors` 能清掉孤儿向量且不动有效向量
- [ ] `/health` 暴露 embedding 模型就绪状态；未就绪时检索返回 `5032` 且提示明确
- [ ] 索引期间不冻结事件循环（阻塞卸载生效），`chunk_indexed / chunk_total` 进度可见
- [ ] 所有端点注入 `CurrentRidDep`，响应体 `request_id` 与响应头一致
- [ ] 所有 datetime 列使用 `UTCDateTime`
- [ ] 新增 4 篇 ADR（0007–0010）

## 待处理项（留到后续批次）

M2 `backend/seeds/` 目录（P5）· M3 `response_model=ApiResponse[T]`（P6）· M4 契约测试补全同组断言（P2）· M6 bcrypt 走线程池（P2）· L2 功能点语义重叠口径 · L4 `core/logging.py`
