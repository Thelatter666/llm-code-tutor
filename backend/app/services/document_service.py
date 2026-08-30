"""文档接入：校验 → 落盘 → 建 Document 行 → 挂后台索引任务。

索引本身由 `IndexingService` 在 `BackgroundTasks` 中执行，本服务只负责把
「文件已收下」这件事落定，好让上传请求立刻返回（spec §3.2 权衡 6）。
"""

from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.domain.knowledge.errors import FileTooLargeError, UnsupportedFileTypeError
from app.domain.knowledge.status import ACTION_KB_DOCUMENT_UPLOAD, DOC_PENDING
from app.domain.knowledge.upload import validate_upload
from app.infrastructure.persistence.models import Document
from app.services.audit_service import AuditService


def default_upload_dir() -> Path:
    raw = Path(get_settings().upload_dir)
    return raw if raw.is_absolute() else Path.cwd() / raw


class DocumentService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def accept_upload(
        self,
        kb_id: str,
        upload: UploadFile,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> Document:
        """收下一个上传文件；校验不通过直接抛 413 / 415。"""
        filename = upload.filename or ""
        size = await _size_of(upload)

        try:
            source_type = validate_upload(filename, size)
        except UnsupportedFileTypeError as exc:
            raise ApiError(4150, str(exc), status=415) from exc
        except FileTooLargeError as exc:
            raise ApiError(4130, str(exc), status=413) from exc

        doc = Document(
            kb_id=kb_id,
            title=Path(filename).name or "未命名文档",
            source_type=source_type,
            status=DOC_PENDING,
        )
        self._session.add(doc)
        await self._session.flush()

        target = default_upload_dir() / kb_id / f"{doc.id}.{source_type}"
        target.parent.mkdir(parents=True, exist_ok=True)
        await _save(upload, target)

        doc.source_uri = str(target)
        await self._session.flush()

        await AuditService(self._session).record(
            ACTION_KB_DOCUMENT_UPLOAD,
            user_id=user_id,
            target_type="document",
            target_id=doc.id,
            detail={"kb_id": kb_id, "title": doc.title, "size": size},
            request_id=request_id,
        )
        return doc


async def _size_of(upload: UploadFile) -> int:
    """取文件大小：优先用 spooled 内容的长度，否则落临时文件后取 stat。"""
    if upload.size is not None:
        return upload.size
    current = await upload.read()
    await upload.seek(0)
    return len(current)


async def _save(upload: UploadFile, target: Path) -> None:
    await upload.seek(0)
    data = await upload.read()
    target.write_bytes(data)
