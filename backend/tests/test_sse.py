import json

from app.infrastructure.sse import (
    CANCELLED_CODE,
    EVENT_DONE,
    EVENT_TOKEN,
    StreamEvent,
    citation_event,
    format_sse,
)
from app.services.retrieval_service import Citation


def test_frame_shape_is_event_then_data_then_blank_line():
    frame = format_sse(StreamEvent(EVENT_TOKEN, {"delta": "闭"}))
    assert frame == 'event: token\ndata: {"delta": "闭"}\n\n'


def test_chinese_is_not_escaped():
    """ensure_ascii=False：中文增量不该被转义成 \\uXXXX，否则前端要做二次解码。"""
    assert "闭包" in format_sse(StreamEvent(EVENT_TOKEN, {"delta": "闭包"}))


def test_frame_is_parseable_by_a_plain_sse_reader():
    """前端是手写的 SSE 解析器（EventSource 带不了 Authorization 头），
    这里按它的解析方式反解一遍，确保格式对得上。"""
    frame = format_sse(StreamEvent(EVENT_DONE, {"message_id": "m1", "degraded": False}))
    lines = frame.rstrip("\n").split("\n")
    assert lines[0] == "event: done"
    assert json.loads(lines[1][6:]) == {"message_id": "m1", "degraded": False}


def test_citation_event_carries_traceable_fields():
    event = citation_event(
        Citation(
            chunk_id="c1",
            document_id="d1",
            doc_title="第1讲",
            kb_id="kb1",
            snippet="排序有三大类",
            score=0.72,
            number=1,
        )
    )
    assert event.event == "citation"
    assert event.data["chunk_id"] == "c1"
    assert event.data["doc_title"] == "第1讲"
    assert event.data["score"] == 0.72
    assert event.data["number"] == 1


def test_cancelled_code_is_distinct_from_server_errors():
    """4990 表示「学生主动停止」，前端据此不弹红色错误提示。"""
    assert CANCELLED_CODE == 4990
    assert CANCELLED_CODE != 5021
