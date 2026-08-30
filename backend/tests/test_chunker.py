import re
from itertools import pairwise

from app.domain.knowledge.chunker import CHUNK_OVERLAP, CHUNK_SIZE, split_text


def _norm(s: str) -> str:
    return re.sub(r"\s", "", s)


def test_chunk_size_and_overlap_match_spec():
    """spec §8.2：1200 字符 / 150 字符重叠。"""
    assert (CHUNK_SIZE, CHUNK_OVERLAP) == (1200, 150)


def test_short_text_yields_single_chunk():
    assert split_text("短文本。") == ["短文本。"]


def test_empty_text_yields_no_chunk():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_long_text_is_split_with_bounded_size():
    text = "这是一段用于验证切分长度的中文文本内容。" * 200  # 约 3800 字
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_consecutive_chunks_overlap_by_150_chars():
    text = "".join(f"第{i}句话，用于构造连续文本。" for i in range(400))
    chunks = split_text(text)
    assert len(chunks) >= 2
    for prev, nxt in pairwise(chunks):
        assert nxt.startswith(prev[-CHUNK_OVERLAP:])


def test_markdown_headings_start_new_chunks():
    text = "# 第一章\n" + "内容一。" * 20 + "\n\n# 第二章\n" + "内容二。" * 20
    chunks = split_text(text)
    assert any(c.lstrip().startswith("# 第一章") for c in chunks)
    assert any("# 第二章" in c for c in chunks)


def test_every_part_of_the_text_is_covered():
    """重叠必然带来重复，所以「无内容丢失」的正确表述是**覆盖**而非子串。

    每个切片编号都必须在拼接结果中出现至少一次。
    """
    markers = [f"[{i:04d}]" for i in range(120)]
    text = "".join(f"{m}" + "正文内容。" * 20 for m in markers)
    joined = "".join(split_text(text))
    missing = [m for m in markers if m not in joined]
    assert missing == []


def test_multiple_headings_are_not_merged_into_one_chunk():
    """标题分段的意义：不同小节不应被拼进同一个切片（除非它们都很短）。"""
    text = "\n\n".join(
        f"## 小节{i}\n" + f"第{i}节的正文内容。" * 30 for i in range(5)
    )
    chunks = split_text(text)
    assert len(chunks) >= 5


def test_single_huge_paragraph_is_window_split():
    text = "字" * 5000
    chunks = split_text(text)
    assert len(chunks) >= 5
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
    for prev, nxt in pairwise(chunks):
        assert nxt.startswith(prev[-CHUNK_OVERLAP:])


def test_crlf_is_normalized():
    text = "第一段内容。\r\n\r\n第二段内容。"
    chunks = split_text(text)
    assert "\r" not in "".join(chunks)


def test_chunk_size_is_configurable_for_tests():
    assert len(split_text("字" * 500, chunk_size=100, overlap=10)) >= 5
