"""检索装配链路（spec §7.2 七步）。

1. `Embedder.embed(query)` → `VectorStore.query(top_k, filter={kb_id ∈ ...})`
2. 相关度低于 `score_threshold` 的命中直接丢弃（默认值按 embedding 模型分别取）
3. **相对截断兜底**：与最佳命中分差 > 0.15 的命中一律丢弃
4. 按 `document_id` 聚合做**多样性截取**（单文档最多 3 片段）
5. 片段编号 `[1][2][3]` 注入 prompt，要求模型内联引用编号
6. 命中的 `chunk_id` 写入 `Message.citations`（P2 落库；本批次先在此产出）
7. 零命中或命中被全部截断时明确降级

**ADR-0004**：实际生效的 Embedder 为 HashingEmbed 时，结果一律不注入 prompt，
强制 `rag_hit=false` + `degraded=true` + `fallback_reason=hashing_embed_no_semantics`。

**检索不持锁**（spec §3.2 权衡 16）—— 允许读到索引中间态。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.knowledge.retrieval import (
    apply_diversity_truncation,
    apply_relative_truncation,
    apply_score_threshold,
    number_chunks,
    resolve_score_threshold,
)
from app.domain.knowledge.status import KB_READY
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.infrastructure.ports.vectorstore import VectorStore
from app.infrastructure.registry import get_or_create_singleton
from app.infrastructure.runtime import get_embedder_runtime, get_vector_store

logger = logging.getLogger(__name__)

FALLBACK_SENTINEL = "hashing_embed_no_semantics"
FALLBACK_NO_HIT = "no_relevant_chunk"

DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class Citation:
    """引用：模型回答所依据的切片来源（CONTEXT.md「引用」）。"""

    chunk_id: str
    document_id: str
    doc_title: str
    kb_id: str
    snippet: str
    score: float
    number: int


@dataclass(frozen=True)
class SearchResult:
    rag_hit: bool
    degraded: bool
    fallback_reason: str | None
    citations: list[Citation] = field(default_factory=list)
    threshold: float = 0.0
    embedder: str | None = None

    def as_payload(self) -> dict:
        return {
            "rag_hit": self.rag_hit,
            "degraded": self.degraded,
            "fallback_reason": self.fallback_reason,
            "threshold": self.threshold,
            "embedder": self.embedder,
            "citations": [c.__dict__ for c in self.citations],
        }


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbedderRuntime | None = None,
        vector_store: VectorStore | None = None,
    ):
        self._session = session
        self._embedder = embedder or get_embedder_runtime()
        self._vectors = vector_store or get_vector_store()

    async def search(
        self,
        query: str,
        *,
        kb_ids: list[str] | None = None,
        course_code: str | None = None,
        top_k: int | None = None,
    ) -> SearchResult:
        """执行 §7.2 的七步装配，返回命中结果与降级状态。"""
        cfg = await get_or_create_singleton(self._session)
        target_ids = await self._resolve_scope(kb_ids, course_code)

        # 没有任何知识库时不应 404 —— 空库是合法状态，按零命中处理
        if not target_ids:
            return _miss(resolve_score_threshold(cfg.score_threshold, None, None))

        # 未就绪：spec §9 的知识库功能降级码 5032（用户拍板决策 1）
        embedder = self._embedder.require_ready()
        query_vector = (await self._embedder.embed([query]))[0]

        k = top_k or cfg.top_k or DEFAULT_TOP_K
        raw_hits = await self._vectors.query(query_vector, top_k=k, kb_ids=target_ids)

        # ADR-0004：哨兵的产出不参与业务逻辑，连阈值判定都不必做
        if embedder.is_sentinel:
            return SearchResult(
                rag_hit=False,
                degraded=True,
                fallback_reason=FALLBACK_SENTINEL,
                threshold=resolve_score_threshold(cfg.score_threshold, embedder.name, embedder.model),
                embedder=embedder.name,
            )

        threshold = resolve_score_threshold(
            cfg.score_threshold, embedder.name, embedder.model
        )
        # 领域规则只认 dict —— 向量库的类型（VectorHit）不得渗进领域层，
        # 故在此转一次。转出来的 key 与 domain/knowledge/retrieval.py 的契约一致。
        candidates = [
            {
                "vector_id": h.vector_id,
                "score": h.score,
                "document_id": h.metadata.get("document_id", ""),
            }
            for h in raw_hits
        ]
        # 步骤 2 → 3 → 4
        hits = apply_diversity_truncation(
            apply_relative_truncation(apply_score_threshold(candidates, threshold))
        )
        citations = await self._to_citations(hits)

        if not citations:
            # 步骤 7：零命中或命中被全部截断 → 明确降级，改走通用回答
            return SearchResult(
                rag_hit=False,
                degraded=True,
                fallback_reason=FALLBACK_NO_HIT,
                threshold=threshold,
                embedder=embedder.name,
            )

        return SearchResult(
            rag_hit=True,
            degraded=False,
            fallback_reason=None,
            citations=citations,
            threshold=threshold,
            embedder=embedder.name,
        )

    async def _resolve_scope(
        self, kb_ids: list[str] | None, course_code: str | None
    ) -> list[str]:
        """确定检索作用域；不存在的 KB → 4040，未就绪 → 5032（spec §9）。"""
        if kb_ids:
            for kb_id in kb_ids:
                kb = await self._session.get(KnowledgeBase, kb_id)
                if kb is None:
                    raise ApiError(4040, "知识库不存在")
                if kb.status != KB_READY:
                    raise ApiError(5032, "知识库正在重建索引，请稍后重试")
            return list(kb_ids)

        stmt = select(KnowledgeBase.id)
        if course_code:
            stmt = stmt.where(KnowledgeBase.course_code == course_code)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _to_citations(self, hits: list) -> list[Citation]:
        """把向量命中转成可溯源引用；查不到 Chunk 行的命中一律丢弃。"""
        if not hits:
            return []

        rows = {
            r.vector_id: r
            for r in (
                await self._session.execute(
                    select(Chunk).where(Chunk.vector_id.in_([h["vector_id"] for h in hits]))
                )
            ).scalars().all()
        }
        doc_ids = {r.document_id for r in rows.values()}
        titles = {}
        if doc_ids:
            titles = {
                d.id: d.title
                for d in (
                    await self._session.execute(
                        select(Document).where(Document.id.in_(doc_ids))
                    )
                ).scalars().all()
            }

        citations: list[Citation] = []
        for number, hit in number_chunks(hits):
            chunk = rows.get(hit["vector_id"])
            if chunk is None:
                # 孤儿向量：有向量无 Chunk 行，点击溯源会 404，宁可丢弃
                logger.warning("命中孤儿向量，已丢弃：%s", hit["vector_id"])
                continue
            citations.append(
                Citation(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    doc_title=titles.get(chunk.document_id, ""),
                    kb_id=chunk.kb_id,
                    snippet=chunk.content,
                    score=hit["score"],
                    number=number,
                )
            )
        return citations


def _miss(threshold: float) -> SearchResult:
    return SearchResult(
        rag_hit=False,
        degraded=True,
        fallback_reason=FALLBACK_NO_HIT,
        threshold=threshold,
    )
