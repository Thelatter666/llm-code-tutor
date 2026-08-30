import pytest

from app.domain.knowledge.errors import FileTooLargeError, UnsupportedFileTypeError
from app.domain.knowledge.upload import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    detect_source_type,
    validate_upload,
)


def test_limits_match_spec():
    """spec §8.2：单文件上限 10MB。"""
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert set(ALLOWED_EXTENSIONS) == {".pdf", ".md", ".txt", ".docx"}


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("a.md", "md"),
        ("a.txt", "txt"),
        ("a.pdf", "pdf"),
        ("a.docx", "docx"),
        ("A.PDF", "pdf"),  # 扩展名大小写不敏感
        ("dir/with.dots/a.MD", "md"),
    ],
)
def test_extension_whitelist(filename, expected):
    assert detect_source_type(filename) == expected


@pytest.mark.parametrize("filename", ["a.exe", "a", "a.pdf.exe", "a.png", "a.doc"])
def test_unsupported_extension_is_rejected(filename):
    with pytest.raises(UnsupportedFileTypeError):
        detect_source_type(filename)


def test_size_limit_is_enforced():
    assert validate_upload("a.pdf", MAX_UPLOAD_BYTES) == "pdf"
    with pytest.raises(FileTooLargeError):
        validate_upload("a.pdf", MAX_UPLOAD_BYTES + 1)


def test_size_is_checked_before_extension():
    """两个都不合规时先报 413 —— 体积是更硬的限制，也更省事。"""
    with pytest.raises(FileTooLargeError):
        validate_upload("a.exe", MAX_UPLOAD_BYTES + 1)
