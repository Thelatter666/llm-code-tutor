"""管理端知识库端点（spec §6.2 admin·kb 行，共 10 个）。

删除顺序、孤儿向量 GC、embedding 切换 409 的具体规则分别在
`KnowledgeBaseService`（§8.6）与 `ModelConfigService`（§8.7）里。
"""

import logging
from typing import Annotated

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.knowledge import (
    ChunkOut,
    DocumentOut,
    GcOut,
    KnowledgeBaseIn,
    KnowledgeBaseOut,
    KnowledgeBasePatch,
    RebuildOut,
)
from app.services.document_service import DocumentService
from app.services.indexing_service import IndexingService
from app.services.knowledge_service import KnowledgeBaseService
from app.services.rebuild_service import RebuildService

router = APIRouter(prefix="/api/v1/admin/knowledge", tags=["admin·kb"])

AdminDep = Annotated[User, Depends(require_admin)]


@router.post("/bases")
async def create_base(
    body: KnowledgeBaseIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
):
    kb = await KnowledgeBaseService(session).create(
        name=body.name,
        description=body.description,
        course_code=body.course_code,
        owner_id=user.id,
        user_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(KnowledgeBaseOut.model_validate(kb).model_dump(), request_id=rid)


@router.patch("/bases/{kb_id}")
async def update_base(
    kb_id: str,
    body: KnowledgeBasePatch,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
):
    kb = await KnowledgeBaseService(session).update(
        kb_id,
        name=body.name,
        description=body.description,
        course_code=body.course_code,
        user_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(KnowledgeBaseOut.model_validate(kb).model_dump(), request_id=rid)


@router.delete("/bases/{kb_id}")
async def delete_base(kb_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep):
    """spec §8.6：先删向量 → 再删 Chunk 行 → 再删 Document/KB 行。"""
    await KnowledgeBaseService(session).delete(kb_id, user_id=user.id, request_id=rid)
    await session.commit()
    return ok({"deleted": True}, request_id=rid)


@router.post("/bases/{kb_id}/documents")
async def upload_document(
    kb_id: str,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
    tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
):
    """上传 → 落盘 → 建 Document 行；索引在响应返回后由后台任务执行。

    索引用 BackgroundTasks 而非 Celery（spec §3.2 权衡 6）：代价是重启丢任务、
    无重试队列，由 `reindex` 端点人工补偿。

    超限 413 / 类型不支持 415（spec §8.2）。
    """
    await KnowledgeBaseService(session).get(kb_id)  # 不存在 → 4040
    doc = await DocumentService(session).accept_upload(
        kb_id, file, user_id=user.id, request_id=rid
    )
    await session.commit()

    document_id = doc.id
    # 后台任务自带会话，不复用已提交的请求会话
    tasks.add_task(_index_in_background, document_id)
    return ok(DocumentOut.model_validate(doc).model_dump(), request_id=rid)


async def _index_in_background(document_id: str) -> None:
    from app.infrastructure.persistence import db

    async with db.SessionFactory() as session:
        try:
            await IndexingService(session).index_document(document_id)
        except Exception:
            logger.exception("后台索引任务异常 document=%s", document_id)


@router.get("/bases/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
    status: str | None = None,
):
    await KnowledgeBaseService(session).get(kb_id)
    docs = await KnowledgeBaseService(session).list_documents(kb_id, status)
    return ok([DocumentOut.model_validate(d).model_dump() for d in docs], request_id=rid)


@router.post("/documents/{document_id}/reindex")
async def reindex_document(
    document_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    await IndexingService(session).reindex_document(document_id)
    await session.commit()
    doc = await KnowledgeBaseService(session).get_document(document_id)
    return ok(DocumentOut.model_validate(doc).model_dump(), request_id=rid)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    await KnowledgeBaseService(session).delete_document(
        document_id, user_id=user.id, request_id=rid
    )
    await session.commit()
    return ok({"deleted": True}, request_id=rid)


@router.get("/documents/{document_id}/chunks")
async def list_chunks(
    document_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """切片预览，供服务答辩演示（spec §6.2）。"""
    svc = KnowledgeBaseService(session)
    await svc.get_document(document_id)
    chunks = await svc.list_chunks(document_id)
    return ok([ChunkOut.model_validate(c).model_dump() for c in chunks], request_id=rid)


@router.post("/bases/{kb_id}/rebuild-vector")
async def rebuild_vector(kb_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep):
    """spec §8.7 步骤 3：切换 embedding 配置后的强制全量重建。"""
    result = await RebuildService(session).rebuild(kb_id, user_id=user.id, request_id=rid)
    await session.commit()
    return ok(RebuildOut(**result).model_dump(), request_id=rid)


@router.post("/bases/{kb_id}/gc-orphan-vectors")
async def gc_orphan_vectors(
    kb_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """清理孤儿向量：Chroma 中有、Chunk 表中无（CONTEXT.md「孤儿向量」）。"""
    result = await KnowledgeBaseService(session).gc_orphan_vectors(
        kb_id, user_id=user.id, request_id=rid
    )
    await session.commit()
    return ok(GcOut(**result).model_dump(), request_id=rid)
