"""切分器：把文档文本切成切片（Chunk 的内容），零 IO。

**按字符数计量，不用 token**（spec §8.2）：中文场景下 token 密度与英文相差
2–3 倍，用 tokenizer 计量会导致切片粒度不可预测；按字符计量可预测且免引入
tiktoken 依赖。默认 **1200 字符 / 150 字符重叠**。

切分策略（先结构、后窗口）：
1. 归一化换行；
2. 按 Markdown 标题切成小节，保留标题与其正文；
3. 小节内按空行（段落）贪心打包，单包不超过 chunk_size；
   打包时把上一包的尾部 `overlap` 字符作为下一包的开头，实现重叠；
4. 仍超过 chunk_size 的单个段落走固定窗口切分，步长 = chunk_size - overlap。
"""

import re

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

# Markdown 标题行（# 到 ######），按整行匹配，避免把正文里的 # 当标题
_HEADING_RE = re.compile(r"^(#{1,6})\s+.*$", re.MULTILINE)
# 一个或多个空行，作为段落边界
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")


def split_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap 必须小于 chunk_size，否则窗口不会前进")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks: list[str] = []
    for section in _split_sections(normalized):
        chunks.extend(_split_section(section, chunk_size, overlap))
    return chunks


def _split_sections(text: str) -> list[str]:
    """按 Markdown 标题切小节；无标题时整篇作为一个小节。"""
    starts = [m.start() for m in _HEADING_RE.finditer(text)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)

    sections = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)
    return sections


def _split_section(section: str, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(section) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    # carry 是上一片的尾部，作为下一片的开头 —— 重叠在打包阶段完成，
    # 这样每片长度始终不超过 chunk_size，不会出现「越切越长」
    carry = ""
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n{para}".strip() if current else para
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        # 当前包已满，先吐出
        if current:
            chunks.append(current)
            carry = current[-overlap:]

        if len(para) <= chunk_size:
            current = f"{carry}\n{para}".strip() if carry else para
            carry = ""
        else:
            # 单个段落就超过 chunk_size：固定窗口切分
            chunks.extend(_window(para, chunk_size, overlap, carry))
            current = ""
            carry = ""

    if current:
        chunks.append(current)
    return chunks


def _window(text: str, chunk_size: int, overlap: int, prefix: str = "") -> list[str]:
    """固定窗口切分，步长 = chunk_size - overlap。"""
    step = chunk_size - overlap
    out: list[str] = []
    start = 0
    while start < len(text):
        piece = text[start : start + chunk_size]
        if prefix and not out:
            piece = f"{prefix}\n{piece}".strip()
        out.append(piece)
        if start + chunk_size >= len(text):
            break
        start += step
    return out
