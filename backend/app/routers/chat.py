"""答疑对话端点（spec §6.2 chat 行）。

`POST /chat/conversations/{id}/messages` 是 SSE 端点，事件契约见 spec §6.1。

**为什么 `request_id` 要由前端传**：中断注册表的键是
`(conversation_id, request_id)`，前端必须能拿到它才能调 `/stop`。P0 的
`install_request_id` 中间件已支持调用方自带 `x-request-id`
（`request.headers.get("x-request-id") or uuid4()`），因此前端在发起 SSE 前生成
UUID 放进请求头，SSE 响应头会原样回传。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.infrastructure.cancellation import get_cancellation_registry
from app.infrastructure.persistence.models import User
from app.infrastructure.sse import format_sse
from app.schemas.chat import (
    ChatMessageIn,
    ConversationIn,
    ConversationOut,
    MessageOut,
    StopIn,
    StopOut,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

UserDep = Annotated[User, Depends(get_current_user)]


@router.post("/conversations")
async def create_conversation(
    body: ConversationIn, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    conv = await ChatService(session).create_conversation(user.id, body.title)
    await session.commit()
    return ok(ConversationOut.model_validate(conv).model_dump(), request_id=rid)


@router.get("/conversations")
async def list_conversations(session: SessionDep, rid: CurrentRidDep, user: UserDep):
    rows = await ChatService(session).list_conversations(user.id)
    return ok([ConversationOut.model_validate(r).model_dump() for r in rows], request_id=rid)


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    rows = await ChatService(session).list_messages(conversation_id, user.id)
    return ok([MessageOut.model_validate(r).model_dump() for r in rows], request_id=rid)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    await ChatService(session).delete_conversation(conversation_id, user.id, rid)
    await session.commit()
    return ok({"deleted": True}, request_id=rid)


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: str,
    body: ChatMessageIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
):
    """主答疑链路（SSE）：`citation* → token* → done`，中断或异常发 `error`。

    ADR-0005：本端点固定 `seek_answer` 意图，不做任何语义推断。

    归属校验在返回 `StreamingResponse` **之前**完成 —— 否则 HTTP 200 已经发出，
    越权只能靠流里的 error 事件表达，前端与日志都更难处理。
    """
    svc = ChatService(session)
    await svc.get_conversation(conversation_id, user.id)

    async def _events():
        async for event in svc.stream_reply(
            conversation_id,
            body.content,
            user_id=user.id,
            request_id=rid,
            use_rag=body.use_rag,
            kb_ids=body.kb_ids,
            course_code=body.course_code,
            top_k=body.top_k,
        ):
            yield format_sse(event)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        # X-Accel-Buffering：经 Nginx 反代时不得缓冲，否则流式退化成一次性返回
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/stop")
async def stop_generation(
    conversation_id: str,
    body: StopIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
):
    """spec §8.1：置位该请求的中断 Event。

    幂等：流已结束时返回 `cancelled=false`，而不是报错 —— 前端的「停止」按钮
    可能在流刚结束时被点到。
    """
    await ChatService(session).get_conversation(conversation_id, user.id)
    registry = get_cancellation_registry()
    cancelled = (
        registry.cancel(conversation_id, body.request_id)
        if body.request_id
        else registry.cancel_conversation(conversation_id) > 0
    )
    return ok(StopOut(cancelled=cancelled).model_dump(), request_id=rid)
