from pathlib import Path

import pytest

from app.domain.knowledge.errors import EmptyDocumentError
from app.domain.knowledge.status import SOURCE_DOCX, SOURCE_MD, SOURCE_PDF, SOURCE_TXT
from app.infrastructure.adapters.document.parsers import (
    NO_TEXT_HINT,
    parse_document,
)
from app.infrastructure.adapters.document.parsers import (
    EmptyDocumentError as ParserEmptyError,
)
from app.infrastructure.ports.document import DocumentParser

# --- 最小的 PDF 构造器：不引入 reportlab 之类的额外依赖，也能造出
#     有文字层 / 无文字层两种 PDF 用于验证扫描版判定 -------------------------


def _build_pdf(path: Path, content_stream: bytes) -> Path:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length "
        + str(len(content_stream)).encode()
        + b" >>\nstream\n"
        + content_stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
    out += str(xref_pos).encode() + b"\n%%EOF"
    path.write_bytes(bytes(out))
    return path


def _text_pdf(path: Path) -> Path:
    return _build_pdf(path, b"BT /F1 12 Tf 20 100 Td (Hello PDF text layer) Tj ET")


def _scanned_pdf(path: Path) -> Path:
    """只有图形、没有文字算子的 PDF —— 等价于扫描版。"""
    return _build_pdf(path, b"0 0 0 rg 0 0 100 100 re f")


def test_parsers_satisfy_port(tmp_path):
    from app.infrastructure.adapters.document.parsers import (
        DocxParser,
        PdfParser,
        PlainTextParser,
    )

    for parser in (PlainTextParser(), DocxParser(), PdfParser()):
        assert isinstance(parser, DocumentParser)


def test_txt_is_read_directly(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("闭包是函数与其引用环境的组合。", encoding="utf-8")
    parsed = parse_document(p, SOURCE_TXT)
    assert "闭包" in parsed.text
    assert parsed.meta["source_type"] == SOURCE_TXT


def test_md_is_read_directly(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# 标题\n\n正文内容。", encoding="utf-8")
    parsed = parse_document(p, SOURCE_MD)
    assert "# 标题" in parsed.text


def test_utf8_without_bom_is_decoded(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("中文内容测试".encode())
    assert "中文内容测试" in parse_document(p, SOURCE_TXT).text


def test_docx_is_parsed_with_python_docx(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("第一段：列表推导式。")
    d.add_paragraph("第二段：生成器表达式。")
    p = tmp_path / "a.docx"
    d.save(p)

    parsed = parse_document(p, SOURCE_DOCX)
    assert "列表推导式" in parsed.text
    assert "生成器表达式" in parsed.text


def test_docx_tables_are_included(tmp_path):
    """讲义常见结构：表格里的文字也必须进文本，否则整段内容会丢。"""
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("段落内容。")
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "知识点"
    table.cell(0, 1).text = "切片"
    p = tmp_path / "b.docx"
    d.save(p)

    text = parse_document(p, SOURCE_DOCX).text
    assert "段落内容。" in text
    assert "知识点" in text
    assert "切片" in text


def test_pdf_with_text_layer_is_parsed(tmp_path):
    pytest.importorskip("pdfplumber")
    p = _text_pdf(tmp_path / "text.pdf")
    assert "Hello PDF text layer" in parse_document(p, SOURCE_PDF).text


def test_scanned_pdf_is_rejected_with_ocr_hint(tmp_path):
    """spec §8.2：无文字层的扫描版 PDF 判为解析失败并提示，不做 OCR（§3.3）。"""
    pytest.importorskip("pdfplumber")
    p = _scanned_pdf(tmp_path / "scan.pdf")

    with pytest.raises(EmptyDocumentError) as exc:
        parse_document(p, SOURCE_PDF)
    assert NO_TEXT_HINT in str(exc.value)


def test_whitespace_only_text_is_rejected(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("   \n\t 　", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        parse_document(p, SOURCE_TXT)


def test_short_pdf_text_is_rejected_as_no_text_layer(tmp_path):
    """spec §8.2：PDF 文本为空或**极短**即判定为无文字层。"""
    pytest.importorskip("pdfplumber")
    p = _build_pdf(tmp_path / "tiny.pdf", b"BT /F1 12 Tf 20 100 Td (ab) Tj ET")
    with pytest.raises(EmptyDocumentError):
        parse_document(p, SOURCE_PDF)


def test_short_txt_is_still_accepted(tmp_path):
    """长度阈值只对 PDF 生效：txt 的正文就是全部内容，误杀代价太高。"""
    p = tmp_path / "a.txt"
    p.write_text("闭包。", encoding="utf-8")
    assert parse_document(p, SOURCE_TXT).text == "闭包。"


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_document(tmp_path / "nope.pdf", SOURCE_PDF)


def test_unknown_source_type_is_rejected(tmp_path):
    p = tmp_path / "a.bin"
    p.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(ValueError):
        parse_document(p, "bin")


def test_empty_document_error_is_the_domain_one():
    """解析适配器抛的必须是领域异常，服务层才能统一映射。"""
    assert ParserEmptyError is EmptyDocumentError


def test_multi_format_class_is_equivalent_to_function(tmp_path):
    """A5（裁定 R4）：类化外壳与 parse_document 行为等价，不是只过 isinstance。"""
    from app.infrastructure.adapters.document.parsers import (
        MultiFormatDocumentParser,
    )

    p = tmp_path / "x.txt"
    p.write_text("闭包。", encoding="utf-8")
    parser = MultiFormatDocumentParser()
    assert parser.parse(p, SOURCE_TXT) == parse_document(p, SOURCE_TXT)

    with pytest.raises(ValueError):
        parser.parse(p, "bin")
    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path / "nope.pdf", SOURCE_PDF)
