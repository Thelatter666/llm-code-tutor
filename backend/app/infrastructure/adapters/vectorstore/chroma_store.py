"""Chroma 向量库适配器。

**单集合 + 元数据过滤**（spec §3.2 权衡 4）：Chroma 单个集合即可容纳全部切片，
按 `kb_id` 元数据过滤；代价是每次检索必须带过滤条件 —— 因此端口把 `kb_ids`
设计成必填参数。

**集合按向量维度分区**（`course_chunks_d{维度}`）：实测发现 Chroma 集合在被
`get_or_create` 首次写入后就把维度固定下来了，**把所有记录删光也不会重置**
—— 于是切换 embedding 模型（1536 / 384 / 256 维）后即便按 spec §8.7 做了全量
重建，新维度的 upsert 仍会被拒（`Collection expecting embedding with dimension
of 384, got 256`）。按维度分区后，维度不同的向量天然落在不同集合里，
「查询用了与索引时不同的模型」在结构上就不可能发生。

所有 Chroma 调用都是同步阻塞的，统一经 `run_in_threadpool` 卸载（ADR-0002）。
"""

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from fastapi.concurrency import run_in_threadpool

from app.infrastructure.ports.vectorstore import VectorHit, VectorRecord

logger = logging.getLogger(__name__)

# Chroma 1.x 要求集合名 3–512 字符；维度后缀见文件头说明
COLLECTION_PREFIX = "course_chunks"
_METADATA_KEYS = ("kb_id", "document_id")


def collection_name(dimension: int) -> str:
    return f"{COLLECTION_PREFIX}_d{dimension}"


def is_owned_collection(name: str) -> bool:
    prefix = f"{COLLECTION_PREFIX}_d"
    return name.startswith(prefix) and name[len(prefix) :].isdigit()


class ChromaVectorStore:
    def __init__(self, persist_dir: Path | str):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collections: dict[int, Any] = {}

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
        await run_in_threadpool(self._delete_ids, list(vector_ids))

    async def delete_by_kb(self, kb_id: str) -> None:
        await run_in_threadpool(self._delete_by_kb, kb_id)

    async def list_ids(self, kb_id: str) -> list[str]:
        return await run_in_threadpool(self._list_ids, kb_id)

    # --- 同步实现（在线程池中执行） ---

    def _collection(self, dimension: int):
        if dimension not in self._collections:
            self._collections[dimension] = self._client.get_or_create_collection(
                collection_name(dimension),
                # 余弦空间：与 Embedder 的 normalize_embeddings=True 口径一致
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[dimension]

    def list_collection_names(self) -> list[str]:
        """当前存在的集合名（运维排查用）。"""
        return [getattr(c, "name", "") for c in self._client.list_collections()]

    def _existing(self) -> list[tuple[int, Any]]:
        """已存在的维度分区集合（不创建新的）。"""
        found: list[tuple[int, Any]] = []
        for collection in self._client.list_collections():
            name = getattr(collection, "name", "")
            if not is_owned_collection(name):
                continue
            dimension = int(name[len(f"{COLLECTION_PREFIX}_d") :])
            found.append((dimension, self._collection(dimension)))
        return found

    def _upsert(self, records: list[VectorRecord]) -> None:
        by_dimension: dict[int, list[VectorRecord]] = {}
        for record in records:
            by_dimension.setdefault(len(record.embedding), []).append(record)

        for dimension, group in by_dimension.items():
            self._collection(dimension).upsert(
                ids=[r.vector_id for r in group],
                embeddings=[r.embedding for r in group],
                documents=[r.content for r in group],
                metadatas=[_metadata(r) for r in group],
            )

    def _query(self, embedding: list[float], top_k: int, kb_ids: list[str]) -> list[VectorHit]:
        dimension = len(embedding)
        if collection_name(dimension) not in self.list_collection_names():
            # 该维度下还没有任何向量 —— 通常意味着还没用当前模型重建过
            return []

        where = {"kb_id": {"$in": list(kb_ids)}} if len(kb_ids) > 1 else {"kb_id": kb_ids[0]}
        raw = self._collection(dimension).query(
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

    def _delete_ids(self, vector_ids: list[str]) -> None:
        for _dimension, collection in self._existing():
            collection.delete(ids=vector_ids)
        self._prune_empty_collections()

    def _delete_by_kb(self, kb_id: str) -> None:
        for _dimension, collection in self._existing():
            collection.delete(where={"kb_id": kb_id})
        self._prune_empty_collections()

    def _list_ids(self, kb_id: str) -> list[str]:
        """跨维度分区枚举：未重建的知识库其向量可能还留在旧维度的集合里。"""
        ids: list[str] = []
        for _dimension, collection in self._existing():
            ids.extend(collection.get(where={"kb_id": kb_id}).get("ids") or [])
        return ids

    def _prune_empty_collections(self) -> None:
        """删空后清掉空集合，避免维度切换留下无法再使用的空壳。

        永远保留至少一个 —— 否则下次 upsert 会重建一个维度已被前一次写死的集合。
        """
        existing = self._existing()
        empties = [(d, c) for d, c in existing if not (c.get().get("ids") or [])]
        if len(empties) == len(existing):
            empties = empties[:-1]  # 至少留一个
        for dimension, _collection in empties:
            try:
                self._client.delete_collection(collection_name(dimension))
            except Exception as exc:  # noqa: BLE001 - 清理失败不影响主流程，但必须留痕
                logger.warning("删除空集合失败 dimension=%s：%s", dimension, exc)
                continue
            self._collections.pop(dimension, None)


def _metadata(record: VectorRecord) -> dict[str, Any]:
    meta = {"kb_id": record.kb_id, "document_id": record.document_id}
    for key, value in (record.metadata or {}).items():
        if key in _METADATA_KEYS:
            continue
        # Chroma 只接受 str / int / float / bool，其余一律字符串化
        meta[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    return meta
