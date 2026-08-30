"""模型配置用例：embedding 切换的 409 流程与启动一致性校验（spec §8.7）。

**切换即强制全量重建，不允许边用边切** —— 不同 embedding 模型维度不同
（OpenAI 1536 / MiniLM 384 / Hash 256），混合会让 Chroma 查询直接抛错。
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.infrastructure.persistence.models import Chunk, KnowledgeBase
from app.infrastructure.registry import get_or_create_singleton

logger = logging.getLogger(__name__)


class ModelConfigService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def update_embedding(
        self,
        *,
        provider: str,
        model: str,
        confirm: bool = False,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """更新 embedding 配置。

        已存在切片且未经二次确认 → `409` + `need_rebuild: true`（spec §8.7 步骤 2）。
        确认后保存配置并返回待重建的知识库清单，由调用方触发重建。
        """
        cfg = await get_or_create_singleton(self._session)
        old = {"provider": cfg.embedding_provider, "model": cfg.embedding_model}

        if (provider, model) == (old["provider"], old["model"]):
            return {"need_rebuild": False, "knowledge_base_ids": []}

        kb_ids = await self.knowledge_bases_with_chunks()
        if kb_ids and not confirm:
            raise ApiError(
                4090,
                "切换 embedding 配置需要全量重建向量，请确认后重试",
                data={
                    "need_rebuild": True,
                    "knowledge_base_ids": kb_ids,
                    "from": old,
                    "to": {"provider": provider, "model": model},
                },
            )

        cfg.embedding_provider = provider
        cfg.embedding_model = model
        # revision 是 ProviderRegistry / EmbedderRuntime 的缓存失效键（spec §4.2 硬约束 4）
        cfg.revision += 1
        await self._session.flush()

        return {"need_rebuild": bool(kb_ids), "knowledge_base_ids": kb_ids}

    async def knowledge_bases_with_chunks(self) -> list[str]:
        """已存在切片的知识库 —— 它们才是必须重建的对象。"""
        rows = (
            await self._session.execute(select(Chunk.kb_id).distinct())
        ).scalars().all()
        return [kb_id for kb_id in rows if kb_id]

    async def check_embedding_consistency(self) -> list[dict[str, Any]]:
        """spec §8.7 步骤 4：比对「配置里的模型」与「切片上记的模型」。

        不一致通常来自手动改库或改 `.env` 绕过 409 流程。这里只告警不自动修复 ——
        自动重建可能在无人值守时吃掉几分钟 CPU。
        """
        cfg = await get_or_create_singleton(self._session)
        rows = (
            await self._session.execute(
                select(Chunk.kb_id, Chunk.embed_model).distinct()
            )
        ).all()

        titles = {
            kb.id: kb.name
            for kb in (
                await self._session.execute(select(KnowledgeBase))
            ).scalars().all()
        }

        warnings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for kb_id, indexed_model in rows:
            if not kb_id or kb_id in seen:
                continue
            seen.add(kb_id)
            if indexed_model == cfg.embedding_model:
                continue
            warnings.append(
                {
                    "kb_id": kb_id,
                    "kb_name": titles.get(kb_id, ""),
                    "indexed_model": indexed_model,
                    "configured_model": cfg.embedding_model,
                }
            )
        return warnings
