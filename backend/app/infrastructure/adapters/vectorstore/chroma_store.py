"""Chroma 向量库适配器。

**单集合 + 元数据过滤**（spec §3.2 权衡 4）：Chroma 单个集合即可容纳全部切片，
按 `kb_id` 元数据过滤；代价是每次检索必须带过滤条件 —— 因此端口把 `kb_ids`
设计成必填参数。

所有 Chroma 调用都是同步阻塞的，统一经 `run_in_threadpool` 卸载（ADR-0002）。
"""

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from fastapi.concurrency import run_in_threadpool

from app.infrastructure.ports.vectorstore import VectorHit, VectorRecord

# Chroma 1.x 要求集合名 3–512 字符
COLLECTION_NAME = "course_chunks"
_METADATA_KEYS = ("kb_id", "document_id")


class ChromaVectorStore:
    def __init__(self, persist_dir: Path | str):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            COLLECTION_NAME,
            # 余弦空间：与 Embedder 的 normalize_embeddings=True 口径一致
            metadata={"hnsw:space": "cosine"},
        )

    async def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        await run_in_threadpool(self._upsert, records)

    async def query(self, embedding: list[float], top_k: int, kb_ids: list[str]) -> list[VectorHit]:
        if not kb_ids:
            # 单集合下漏过滤等于跨库检索，直接返回空而非「全部命中」
            return []
        return await run_in_threadpool(self._query, embedding, top_k, kb_ids)

    async def delete_ids(self, vector_ids: list[str]) -> None:
        if not vector_ids:
            return
        await run_in_threadpool(self._collection.delete, ids=list(vector_ids))

    async def delete_by_kb(self, kb_id: str) -> None:
        await run_in_threadpool(self._collection.delete, where={"kb_id": kb_id})

    async def list_ids(self, kb_id: str) -> list[str]:
        return await run_in_threadpool(self._list_ids, kb_id)

    # --- 同步实现（在线程池中执行） ---

    def _upsert(self, records: list[VectorRecord]) -> None:
        self._collection.upsert(
            ids=[r.vector_id for r in records],
            embeddings=[r.embedding for r in records],
            documents=[r.content for r in records],
            metadatas=[_metadata(r) for r in records],
        )

    def _query(self, embedding: list[float], top_k: int, kb_ids: list[str]) -> list[VectorHit]:
        where = {"kb_id": {"$in": list(kb_ids)}} if len(kb_ids) > 1 else {"kb_id": kb_ids[0]}
        raw = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=where,
        )
        ids = (raw.get("ids") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]

        hits = []
        for vid, distance, meta in zip(ids, distances, metadatas):
            # Chroma 的 cosine 空间返回余弦*距离*，端口契约是相似度
            hits.append(VectorHit(vector_id=vid, score=1.0 - float(distance), metadata=meta or {}))
        return hits

    def _list_ids(self, kb_id: str) -> list[str]:
        raw = self._collection.get(where={"kb_id": kb_id})
        return list(raw.get("ids") or [])


def _metadata(record: VectorRecord) -> dict[str, Any]:
    meta = {"kb_id": record.kb_id, "document_id": record.document_id}
    for key, value in (record.metadata or {}).items():
        if key in _METADATA_KEYS:
            continue
        # Chroma 只接受 str / int / float / bool，其余一律字符串化
        meta[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    return meta
