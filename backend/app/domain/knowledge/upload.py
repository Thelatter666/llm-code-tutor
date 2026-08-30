"""上传校验规则（spec §8.2），零 IO。

- 单文件上限 **10MB**，超出直接拒绝（`413`）
- 扩展名白名单 `.pdf` `.md` `.txt` `.docx`，不在其内直接拒绝（`415`）
"""

from pathlib import PurePath

from app.domain.knowledge.errors import FileTooLargeError, UnsupportedFileTypeError
from app.domain.knowledge.status import SOURCE_DOCX, SOURCE_MD, SOURCE_PDF, SOURCE_TXT

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 扩展名 → source_type
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": SOURCE_PDF,
    ".md": SOURCE_MD,
    ".txt": SOURCE_TXT,
    ".docx": SOURCE_DOCX,
}


def detect_source_type(filename: str) -> str:
    """按扩展名判定来源类型；不在白名单内抛 UnsupportedFileTypeError。"""
    suffix = PurePath(filename).suffix.lower()
    try:
        return ALLOWED_EXTENSIONS[suffix]
    except KeyError as exc:
        allowed = " / ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsupportedFileTypeError(
            f"不支持的文件类型：{suffix or filename}，仅支持 {allowed}"
        ) from exc


def validate_upload(filename: str, size: int) -> str:
    """校验上传文件，返回 source_type；不合规抛领域异常。"""
    if size > MAX_UPLOAD_BYTES:
        raise FileTooLargeError(
            f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限：{size} 字节"
        )
    return detect_source_type(filename)
