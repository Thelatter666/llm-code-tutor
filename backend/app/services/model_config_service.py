"""模型配置用例：embedding 切换的 409 流程与启动一致性校验（spec §8.7）。

**切换即强制全量重建，不允许边用边切** —— 不同 embedding 模型维度不同
（OpenAI 1536 / MiniLM 384 / Hash 256），混合会让 Chroma 查询直接抛错。
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.infrastructure.adapters.embedding.hashing_embed import HashingEmbed
from app.infrastructure.adapters.embedding.openai_compat_embed import (
    DEFAULT_OPENAI_EMBED_MODEL,
)
from app.infrastructure.adapters.embedding.sentence_transformer import (
    DEFAULT_LOCAL_EMBED_MODEL,
)
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import Chunk, KnowledgeBase
from app.infrastructure.registry import (
    EMBEDDING_PROVIDER_HASHING,
    EMBEDDING_PROVIDER_OPENAI,
    get_or_create_singleton,
)
from app.infrastructure.runtime import get_embedder_runtime, refresh_embedder_config
from app.services.rebuild_service import RebuildService

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

    async def switch_embedding_with_rebuild(
        self,
        *,
        provider: str,
        model: str,
        confirm: bool = False,
        user_id: str | None = None,
        request_id: str | None = None,
        rebuild: Callable[[str], Awaitable[object]] | None = None,
        refresh_runtime: Callable[[], Awaitable[bool]] | None = None,
        runtime: EmbedderRuntime | None = None,
    ) -> dict[str, Any]:
        """切换 embedding 配置并强制全量重建；**任何一步不成立就整体回滚配置**。

        **「配置 ↔ 向量维度」必须始终一致。** 若配置先落库而重建失败，查询会拿
        新模型产生的新维度向量去查 `course_chunks_d{新维度}` —— 该集合是空的
        （按维度分区，见 ADR-0007），于是检索静默零命中，既没有错误码也没有
        `degraded` 之外的任何痕迹。这违反 spec §9 的「降级必须可见」：此处的降级
        对**学生端完全不可见**，管理员只有主动调 `embedding-consistency` 才发现。

        因此切换与重建必须绑成一个「要么全成、要么回滚」的单元。全流程有三道闸，
        任一不过就回滚：

        1. **新配置是否真能取到可用的向量化器**（`_falls_back_to_sentinel`）
        2. 重建是否抛异常
        3. **重建是否真的换掉了切片**（`_rebuild_did_not_take_effect`）

        第 1、3 道不是多余的保险，而是各挡住一类**实测踩到过的**静默失败：

        - 填一个不存在的模型名，运行时会一路降级到 HashingEmbed 哨兵，于是一声不吭
          地把全部切片用无语义的哈希向量重写一遍，还返回「重建成功」；
        - 逐份文档的索引失败会被 `IndexingService._run` 各自吞掉并置 failed，
          于是「全部失败」也不会抛异常。

        `rebuild` / `refresh_runtime` / `runtime` 均可注入，便于测试构造这些路径。
        """
        cfg = await get_or_create_singleton(self._session)
        old = {"provider": cfg.embedding_provider, "model": cfg.embedding_model}
        # 旧模型名可能为空（从未显式配置），比对时要按 provider 解析出实际用的那个
        old_model = old["model"] or default_embedding_model(old["provider"])

        result = await self.update_embedding(
            provider=provider,
            model=model,
            confirm=confirm,
            user_id=user_id,
            request_id=request_id,
        )
        refresh = refresh_runtime or (lambda: refresh_embedder_config(self._session))
        effective = runtime if runtime is not None else get_embedder_runtime()
        # 必须用新配置下的运行时去重建 —— 晚一步刷新就是在拿旧模型写新维度的切片
        await refresh()

        kb_ids = result["knowledge_base_ids"]
        if not (confirm and kb_ids):
            return {**result, "rebuilt": [], "failed": []}

        # 闸 1：重建会先删旧向量，一旦开始就没有回头路，所以先确认新配置真能用
        if await self._falls_back_to_sentinel(provider, model, effective):
            await self._roll_back(old, refresh, effective)
            raise ApiError(
                5000,
                f"配置的 embedding 模型不可用（{provider}/{model}），"
                f"已回滚到切换前：{old['provider']}/{old['model']}",
                data={
                    "need_rebuild": True,
                    "knowledge_base_ids": kb_ids,
                    "rebuilt": [],
                    "failed": kb_ids,
                    "rolled_back_to": old,
                    "reason": "embedding_unavailable_falls_back_to_sentinel",
                },
            )

        runner = rebuild or (
            lambda kb_id: RebuildService(self._session).rebuild(
                kb_id, user_id=user_id, request_id=request_id
            )
        )
        rebuilt: list[str] = []
        failed: list[str] = []
        for kb_id in kb_ids:
            # 闸 2
            try:
                await runner(kb_id)
            except Exception:
                logger.exception("知识库重建失败 kb=%s", kb_id)
                failed.append(kb_id)
                continue
            # 闸 3：不抛异常不等于重建成功，按结果再验一次
            if await self._rebuild_did_not_take_effect(kb_id, old_model):
                failed.append(kb_id)
            else:
                rebuilt.append(kb_id)

        if failed:
            await self._roll_back(old, refresh, effective)
            raise ApiError(
                5000,
                f"以下知识库重建失败，已回滚 embedding 配置：{'、'.join(failed)}",
                data={
                    "need_rebuild": True,
                    "knowledge_base_ids": kb_ids,
                    "rebuilt": rebuilt,
                    "failed": failed,
                    "rolled_back_to": old,
                },
            )
        return {**result, "rebuilt": rebuilt, "failed": failed}

    async def _roll_back(
        self,
        old: dict[str, Any],
        refresh: Callable[[], Awaitable[bool]],
        runtime: EmbedderRuntime,
    ) -> None:
        """回滚配置并让运行时重新就绪。

        只改库不够 —— 运行时还停在新模型上，等于回滚只做了一半；而
        `refresh_embedder_config` 会把 `_ready` 置回 False，不重新预热的话
        检索会一直返回 5032。三步缺一不可。
        """
        cfg = await get_or_create_singleton(self._session)
        cfg.embedding_provider = old["provider"]
        cfg.embedding_model = old["model"]
        # 再自增一次：revision 是运行时缓存的失效键
        cfg.revision += 1
        await self._session.commit()
        await refresh()
        await runtime.warmup()

    async def _falls_back_to_sentinel(
        self, provider: str, model: str, runtime: EmbedderRuntime
    ) -> bool:
        """新配置是否只能落到 HashingEmbed 哨兵。

        哨兵**不是可用降级**（ADR-0004）：它的向量无语义，重建等于把好向量换成一堆
        噪声，而响应还会说「重建成功」—— 学生端拿到的仍是零命中，且
        `embedding-consistency` 看不出问题（切片上记的确实是哨兵模型）。

        管理员显式选 hashing 是唯一例外：那时哨兵就是要的效果，且检索端会以
        `hashing_embed_no_semantics` 显式降级，属于「可见降级」。
        """
        if provider == EMBEDDING_PROVIDER_HASHING or model == HashingEmbed.model:
            return False
        await runtime.warmup()
        current = runtime.current
        return current is not None and current.is_sentinel

    async def _rebuild_did_not_take_effect(self, kb_id: str, old_model: str) -> bool:
        """重建后是否仍残留旧模型的切片，或把知识库清空了。

        用 `count` 标量查询而非 ORM 对象：重建在别处提交过，本会话的身份映射可能
        是陈旧的，而标量查询直接落库取数。
        """
        stale = (
            await self._session.execute(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.kb_id == kb_id, Chunk.embed_model == old_model)
            )
        ).scalar_one()
        if stale:
            return True

        total = (
            await self._session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.kb_id == kb_id)
            )
        ).scalar_one()
        # 进这个列表的知识库重建前都有切片（来自 knowledge_bases_with_chunks），
        # 重建后一片不剩说明重建没干成活 —— 不能算切换成功
        return total == 0

    async def knowledge_bases_with_chunks(self) -> list[str]:
        """已存在切片的知识库 —— 它们才是必须重建的对象。"""
        rows = (
            await self._session.execute(select(Chunk.kb_id).distinct())
        ).scalars().all()
        return [kb_id for kb_id in rows if kb_id]

    async def check_embedding_consistency(
        self, expected_model: str | None = None
    ) -> list[dict[str, Any]]:
        """spec §8.7 步骤 4：比对「配置里的模型」与「切片上记的模型」。

        不一致通常来自手动改库或改 `.env` 绕过 409 流程。这里只告警不自动修复 ——
        自动重建可能在无人值守时吃掉几分钟 CPU。

        `expected_model` 为空时按配置解析出**实际会用的模型**：管理员从未显式配置过
        embedding 模型是常态，此时 `embedding_model` 为 NULL，直接拿 NULL 去比对
        会把「一切正常」误报成不一致。
        """
        cfg = await get_or_create_singleton(self._session)
        if expected_model is None:
            expected_model = cfg.embedding_model or default_embedding_model(
                cfg.embedding_provider
            )
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
            if indexed_model == expected_model:
                continue
            warnings.append(
                {
                    "kb_id": kb_id,
                    "kb_name": titles.get(kb_id, ""),
                    "indexed_model": indexed_model,
                    "configured_model": expected_model,
                }
            )
        return warnings


def default_embedding_model(provider: str | None) -> str:
    """未显式配置模型时，各 provider 实际会用的模型（与 registry.build_embedder 对齐）。"""
    if provider == EMBEDDING_PROVIDER_OPENAI:
        return DEFAULT_OPENAI_EMBED_MODEL
    if provider == EMBEDDING_PROVIDER_HASHING:
        return HashingEmbed.model
    return DEFAULT_LOCAL_EMBED_MODEL
