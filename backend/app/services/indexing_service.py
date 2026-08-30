"""索引流水线：解析 → 切分 → 向量化 → 落库（spec §8.2）。

**整段必须经 `run_in_threadpool` 卸载**（ADR-0002）：解析与 embedding 推理都是
同步阻塞调用，500 份文档按每份 50 片估算纯编码就要数分钟，在事件循环上执行会
冻结整个后端。

**进度可见**：`Document.chunk_indexed / chunk_total` 分批提交，管理端可轮询。

索引任务由 `BackgroundTasks` 拉起，**不可复用请求会话**（响应返回时会话已关），
因此本服务从 `db.SessionFactory` 新建会话 —— 取属性而非 import 绑定，便于测试替换。
"""

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge.chunker import split_text
from app.domain.knowledge.errors import EmptyDocumentError
from app.domain.knowledge.status import (
    DOC_FAILED,
    DOC_INDEXING,
    DOC_READY,
    DOC_REINDEXING,
)
from app.infrastructure.adapters.document.parsers import parse_document
from app.infrastructure.concurrency import index_slot, kb_lock
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence import db
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.infrastructure.ports.vectorstore import VectorRecord, VectorStore
from app.infrastructure.runtime import get_embedder_runtime, get_vector_store

logger = logging.getLogger(__name__)

# 每批切片数：实测 64 段批量编码约 0.8–1.2 秒，取 32 让进度条更细
EMBED_BATCH_SIZE = 32


class IndexingService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbedderRuntime | None = None,
        vector_store: VectorStore | None = None,
        session_factory: Callable | None = None,
    ):
        self._session = session
        self._embedder = embedder or get_embedder_runtime()
        self._vectors = vector_store or get_vector_store()
        self._factory = session_factory

    async def index_document(self, document_id: str) -> None:
        """索引一份文档；失败置 `status=failed` + `error_msg`，不影响其余文档。"""
        async with self._new_session() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                # 后台任务可能落在已被删除的文档上，静默返回好过抛错
                return
            async with index_slot(), kb_lock(doc.kb_id):
                await self._run(session, doc, is_reindex=False)

    async def reindex_document(self, document_id: str) -> None:
        doc = await self._session.get(Document, document_id)
        if doc is None:
            raise _not_found("文档不存在")
        kb_id, source_uri = doc.kb_id, doc.source_uri

        async with index_slot(), kb_lock(kb_id), self._new_session() as session:
            target = await session.get(Document, document_id)
            if target is None:
                return
            await self._clear(session, document_id, kb_id)
            await self._run(session, target, is_reindex=True, forced_uri=source_uri)

    async def rebuild_knowledge_base(self, kb_id: str) -> None:
        """全量重建：清掉该 KB 的全部向量与 Chunk 行，再逐份文档重建（spec §8.7）。"""
        async with index_slot(), kb_lock(kb_id), self._new_session() as session:
            docs = list(
                (
                    await session.execute(
                        select(Document).where(Document.kb_id == kb_id)
                    )
                ).scalars().all()
            )
            await self._clear_many(session, [d.id for d in docs], kb_id)

            for doc in docs:
                await self._run(session, doc, is_reindex=True)

            kb = await session.get(KnowledgeBase, kb_id)
            if kb is not None:
                kb.status = "ready"
                embedder = self._embedder.current
                if embedder is not None:
                    kb.embed_provider = embedder.name
                    kb.embed_model = embedder.model
                await session.commit()

    # --- 内部实现 ---

    def _new_session(self) -> AsyncSession:
        """后台任务用的独立会话（请求响应返回时，请求会话已关闭）。

        `db.SessionFactory` 在**调用时**取属性而非 import 时绑定，测试因此能通过
        monkeypatch 替换（conftest 的 `_bind_session_factory` 就是这么做的）。
        注意：`AsyncSession.bind` 返回的是每次新构造的 AsyncEngine 包装，
        拿它建会话会落到另一个库上，不可用于此。
        """
        factory = self._factory or db.SessionFactory
        return factory()

    async def _run(
        self,
        session: AsyncSession,
        doc: Document,
        *,
        is_reindex: bool,
        forced_uri: str | None = None,
    ) -> None:
        doc.status = DOC_REINDEXING if is_reindex else DOC_INDEXING
        doc.error_msg = None
        doc.chunk_indexed = 0
        doc.chunk_total = 0
        await session.commit()

        try:
            uri = forced_uri or doc.source_uri
            if not uri:
                raise FileNotFoundError("源文件路径缺失")

            parsed = await run_in_threadpool(parse_document, Path(uri), doc.source_type)
            chunks = await run_in_threadpool(split_text, parsed.text)

            doc.chunk_total = len(chunks)
            doc.chunk_indexed = 0
            await session.commit()

            # 实际生效的模型要等第一次 embed 之后才确定：预热是异步的，且运行期
            # 还可能降级。Chunk.embed_model 必须记录真正用来编码的那个（spec §8.7）
            embed_model = None

            for start in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[start : start + EMBED_BATCH_SIZE]
                vectors = await self._embedder.embed(batch)
                if embed_model is None and self._embedder.current is not None:
                    embed_model = self._embedder.current.model

                records = []
                rows = []
                for offset, (content, vector) in enumerate(zip(batch, vectors)):
                    chunk_id = _chunk_id(doc.id, start + offset)
                    rows.append(
                        Chunk(
                            id=chunk_id,
                            document_id=doc.id,
                            kb_id=doc.kb_id,
                            content=content,
                            ordinal=start + offset,
                            char_count=len(content),
                            embed_model=embed_model,
                            vector_id=chunk_id,
                        )
                    )
                    records.append(
                        VectorRecord(
                            vector_id=chunk_id,
                            kb_id=doc.kb_id,
                            document_id=doc.id,
                            embedding=vector,
                            content=content,
                        )
                    )

                await self._vectors.upsert(records)
                session.add_all(rows)

                doc.chunk_indexed = start + len(batch)
                await session.commit()  # 分批提交 → 进度对外可见

            doc.status = DOC_READY
            await session.commit()
        except (EmptyDocumentError, FileNotFoundError) as exc:
            await self._fail(session, doc, str(exc) or "文档解析失败")
        except Exception as exc:
            logger.exception("索引失败 document=%s", doc.id)
            await self._fail(session, doc, f"索引失败：{exc}")

    async def _fail(self, session: AsyncSession, doc: Document, message: str) -> None:
        await session.rollback()
        doc = await session.get(Document, doc.id)
        if doc is not None:
            doc.status = DOC_FAILED
            doc.error_msg = message
            await session.commit()

    async def _clear(self, session: AsyncSession, document_id: str, kb_id: str) -> None:
        await self._clear_many(session, [document_id], kb_id)

    async def _clear_many(
        self, session: AsyncSession, document_ids: list[str], kb_id: str
    ) -> None:
        """清掉切片与其向量；向量删除失败只告警，不阻断重建。"""
        if not document_ids:
            return
        vector_ids = [
            v
            for v in (
                await session.execute(
                    select(Chunk.vector_id).where(Chunk.document_id.in_(document_ids))
                )
            ).scalars().all()
            if v
        ]
        if vector_ids:
            try:
                await self._vectors.delete_ids(vector_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("重建前清理向量失败 kb=%s：%s", kb_id, exc)
        await session.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
        await session.commit()


def _chunk_id(document_id: str, ordinal: int) -> str:
    """切片 id 直接作为 vector_id：省掉一张映射表，也便于孤儿向量比对。"""
    return f"{document_id}:{ordinal}"


def _not_found(message: str):
    from app.core.errors import ApiError

    return ApiError(4040, message)
