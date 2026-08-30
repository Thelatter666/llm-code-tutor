"""SSE 事件契约（spec §6.1）。

| 事件 | 载荷 | 时机 |
|---|---|---|
| `citation` | `{chunk_id, doc_title, snippet, score}` | 检索完成后、生成开始前，可多次 |
| `token` | `{delta}` | 逐字增量 |
| `done` | `{message_id, token_usage, usage_estimated, model, provider, rag_hit, degraded, fallback_reason}` | 生成结束 |
| `error` | `{code, message}` | 流中异常 |

`citation` 先于 `token` 发出，前端得以在答案出现前展示「引用了哪几段」。
"""

import json
from dataclasses import dataclass, field

EVENT_CITATION = "citation"
EVENT_TOKEN = "token"
EVENT_DONE = "done"
EVENT_ERROR = "error"

# 学生主动点「停止」不是服务端故障，故不与 5021 混用 —— 前端据此只结束打字机、
# 不弹红色错误提示。4990 只出现在 SSE 载荷里，不进 HTTP 状态码映射。
CANCELLED_CODE = 4990


@dataclass(frozen=True)
class StreamEvent:
    """服务层产出的事件对象。

    服务层因此不依赖 SSE 的字节格式（那是接口层的事），可以脱离 HTTP 单测。
    """

    event: str
    data: dict = field(default_factory=dict)


def format_sse(event: StreamEvent) -> str:
    """序列化为 SSE 帧；`ensure_ascii=False` 保证中文增量不被转义成一堆 \\uXXXX。"""
    payload = json.dumps(event.data, ensure_ascii=False)
    return f"event: {event.event}\ndata: {payload}\n\n"


def citation_event(citation) -> StreamEvent:
    """`citation` 事件载荷；`number` 是 spec 之外的增量，供前端对齐内联引用编号。"""
    return StreamEvent(
        EVENT_CITATION,
        {
            "chunk_id": citation.chunk_id,
            "document_id": citation.document_id,
            "doc_title": citation.doc_title,
            "kb_id": citation.kb_id,
            "snippet": citation.snippet,
            "score": citation.score,
            "number": citation.number,
        },
    )
