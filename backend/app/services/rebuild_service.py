"""知识库全量重建（spec §8.7 步骤 3）。

切换 embedding 配置后，必须把所有切片用新模型重新编码一遍：不同模型维度不同，
混合会让 Chroma 查询直接抛错。重建期间 KB 置 `reindexing`，检索返回 `5032`。
"""

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.knowledge.status import (
    ACTION_KB_REBUILD,
    KB_READY,
    KB_REINDEXING,
)
from app.infrastructure.concurrency import kb_lock
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import KnowledgeBase
from app.infrastructure.ports.vectorstore import VectorStore
from app.infrastructure.runtime import get_embedder_runtime, get_vector_store
from app.services.audit_service import AuditService
from app.services.indexing_service import IndexingService

logger = logging.getLogger(__name__)


class RebuildService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbedderRuntime | None = None,
        vector_store: VectorStore | None = None,
        indexing: IndexingService | None = None,
    ):
        self._session = session
        self._indexing = indexing or IndexingService(
            session,
            embedder=embedder or get_embedder_runtime(),
            vector_store=vector_store or get_vector_store(),
        )

    async def rebuild(
        self,
        kb_id: str,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> dict:
        kb = await self._session.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ApiError(4040, "知识库不存在")

        await self._set_status(kb_id, KB_REINDEXING, on_status)
        try:
            await self._indexing.rebuild_knowledge_base(kb_id)
        except Exception as exc:
            logger.exception("知识库重建失败 kb=%s", kb_id)
            # 失败也要放开：卡在 reindexing 会让检索永久不可用，
            # 具体失败原因由各文档的 status=failed + error_msg 承载
            await self._set_status(kb_id, KB_READY, on_status)
            await AuditService(self._session).record(
                ACTION_KB_REBUILD,
                user_id=user_id,
                target_type="knowledge_base",
                target_id=kb_id,
                detail={"result": "failed", "error": str(exc)},
                request_id=request_id,
            )
            raise ApiError(5000, f"知识库重建失败：{exc}") from exc

        await self._set_status(kb_id, KB_READY, on_status)
        await AuditService(self._session).record(
            ACTION_KB_REBUILD,
            user_id=user_id,
            target_type="knowledge_base",
            target_id=kb_id,
            detail={"result": "ok"},
            request_id=request_id,
        )
        return {"kb_id": kb_id, "status": KB_READY}

    async def _set_status(
        self, kb_id: str, status: str, on_status: Callable[[str], None] | None
    ) -> None:
        async with kb_lock(kb_id):
            kb = await self._session.get(KnowledgeBase, kb_id)
            if kb is None:
                return
            kb.status = status
            await self._session.commit()
        if on_status is not None:
            on_status(status)
