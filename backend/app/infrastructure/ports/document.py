"""文档解析端口（CONTEXT.md：文档 Document）。

spec §4.3 的端口清单（LLMProvider / Embedder / VectorStore / CodeExecutor /
CodeParser）里没有文档解析这一项 —— 但它是知识库接入的第一个环节，同样需要
「真实实现与测试实现同签名」的接缝，因此按同一范式补在这里。

`parse()` 为同步方法：pdfplumber 与 python-docx 都是同步阻塞库，由调用方
（IndexingService）经 `run_in_threadpool` 卸载（ADR-0002）。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    meta: dict = field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...
