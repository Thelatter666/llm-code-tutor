"""知识库用例编排：CRUD、删除与孤儿向量 GC。

**删除顺序固定三步、不可颠倒**（spec §8.6）：
先删 Chroma 向量 → 再删 `Chunk` 行 → 再删 `Document` / `KnowledgeBase` 行。
Chroma 删除失败时**仍继续删 DB**，但写 `AuditLog(action=admin_kb_delete,
detail={vector_cleanup: "failed"})` 告警 —— 牺牲向量层一致性，换取记录不残留为
无法清理的死数据。
"""

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.knowledge.status import (
    ACTION_KB_CREATE,
    ACTION_KB_DELETE,
    ACTION_KB_DOCUMENT_DELETE,
    ACTION_KB_GC,
    ACTION_KB_UPDATE,
    KB_READY,
)
from app.infrastructure.concurrency import kb_lock
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.infrastructure.ports.vectorstore import VectorStore
from app.infrastructure.runtime import get_vector_store
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession, vector_store: VectorStore | None = None):
        self._session = session
        self._vectors = vector_store or get_vector_store()

    async def create(
        self,
        name: str,
        owner_id: str | None = None,
        description: str | None = None,
        course_code: str | None = None,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> KnowledgeBase:
        kb = KnowledgeBase(
            name=name,
            description=description,
            owner_id=owner_id,
            course_code=course_code,
            status=KB_READY,
        )
        self._session.add(kb)
        await self._session.flush()
        await AuditService(self._session).record(
            ACTION_KB_CREATE,
            user_id=user_id,
            target_type="knowledge_base",
            target_id=kb.id,
            detail={"name": name},
            request_id=request_id,
        )
        return kb

    async def get(self, kb_id: str) -> KnowledgeBase:
        kb = await self._session.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ApiError(4040, "知识库不存在")
        return kb

    async def list_bases(self, course_code: str | None = None) -> list[KnowledgeBase]:
        """`course_code` 为空表示不限课程（spec §6.2）。"""
        stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        if course_code:
            stmt = stmt.where(KnowledgeBase.course_code == course_code)
        return list((await self._session.execute(stmt)).scalars().all())

    async def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        course_code: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> KnowledgeBase:
        kb = await self.get(kb_id)
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        if course_code is not None:
            kb.course_code = course_code
        await self._session.flush()
        await AuditService(self._session).record(
            ACTION_KB_UPDATE,
            user_id=user_id,
            target_type="knowledge_base",
            target_id=kb.id,
            detail={"name": kb.name},
            request_id=request_id,
        )
        return kb

    async def set_status(self, kb_id: str, status: str) -> KnowledgeBase:
        kb = await self.get(kb_id)
        kb.status = status
        await self._session.flush()
        return kb

    async def list_documents(self, kb_id: str, status: str | None = None) -> list[Document]:
        stmt = select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        if status:
            stmt = stmt.where(Document.status == status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_document(self, document_id: str) -> Document:
        doc = await self._session.get(Document, document_id)
        if doc is None:
            raise ApiError(4040, "文档不存在")
        return doc

    async def delete(
        self,
        kb_id: str,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """删除知识库：先向量，再 Chunk 行，最后 Document / KnowledgeBase 行。"""
        async with kb_lock(kb_id):
            kb = await self.get(kb_id)
            vector_cleanup = await self._delete_vectors(kb_id=kb_id)

            await self._session.execute(delete(Chunk).where(Chunk.kb_id == kb_id))
            await self._session.execute(delete(Document).where(Document.kb_id == kb_id))
            await self._session.delete(kb)
            await self._session.flush()

            await AuditService(self._session).record(
                ACTION_KB_DELETE,
                user_id=user_id,
                target_type="knowledge_base",
                target_id=kb_id,
                detail={"name": kb.name, "vector_cleanup": vector_cleanup},
                request_id=request_id,
            )

    async def delete_document(
        self,
        document_id: str,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        doc = await self.get_document(document_id)
        async with kb_lock(doc.kb_id):
            # 索引中途失败的 Chunk 行没有 vector_id，必须过滤掉 ——
            # 把 None 传给 Chroma 会直接报错
            vector_ids = [
                v
                for v in (
                    await self._session.execute(
                        select(Chunk.vector_id).where(Chunk.document_id == document_id)
                    )
                ).scalars().all()
                if v
            ]
            vector_cleanup = await self._delete_vectors(vector_ids=vector_ids)

            await self._session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            await self._session.delete(doc)
            await self._session.flush()

            await AuditService(self._session).record(
                ACTION_KB_DOCUMENT_DELETE,
                user_id=user_id,
                target_type="document",
                target_id=document_id,
                detail={"title": doc.title, "vector_cleanup": vector_cleanup},
                request_id=request_id,
            )

    async def gc_orphan_vectors(
        self,
        kb_id: str,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """清理孤儿向量：Chroma 中有、Chunk 表中无（CONTEXT.md「孤儿向量」）。"""
        await self.get(kb_id)
        async with kb_lock(kb_id):
            known = set(
                (
                    await self._session.execute(
                        select(Chunk.vector_id).where(
                            Chunk.kb_id == kb_id, Chunk.vector_id.is_not(None)
                        )
                    )
                ).scalars().all()
            )
            listed = set(await self._vectors.list_ids(kb_id))
            orphans = sorted(listed - known)

            deleted = 0
            if orphans:
                try:
                    await self._vectors.delete_ids(orphans)
                    deleted = len(orphans)
                except Exception as exc:  # noqa: BLE001 - GC 失败只告警，不影响业务
                    logger.warning("孤儿向量清理失败 kb=%s：%s", kb_id, exc)

            result = {"scanned": len(listed), "orphans": len(orphans), "deleted": deleted}
            await AuditService(self._session).record(
                ACTION_KB_GC,
                user_id=user_id,
                target_type="knowledge_base",
                target_id=kb_id,
                detail=result,
                request_id=request_id,
            )
            return result

    async def _delete_vectors(
        self,
        *,
        kb_id: str | None = None,
        vector_ids: list[str] | None = None,
    ) -> str:
        """删除向量；失败返回 "failed" 而非抛出 —— 调用方须继续删 DB（spec §8.6）。"""
        try:
            if kb_id is not None:
                await self._vectors.delete_by_kb(kb_id)
            elif vector_ids:
                await self._vectors.delete_ids(vector_ids)
        except Exception as exc:  # noqa: BLE001 - 向量层失败不得阻断 DB 清理
            logger.warning("Chroma 删除失败（仍继续删 DB）：%s", exc)
            return "failed"
        return "ok"
