from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=128)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    # 引用：spec §7.2 步骤 6，前端点击可溯源
    citations: list[dict] | None = None
    token_usage: dict | None = None
    model: str | None = None
    provider: str | None = None
    truncated: bool = False
    anti_plagiarism_mode: str | None = None
    blocked_by_policy: bool = False
    created_at: datetime


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    use_rag: bool = True
    kb_ids: list[str] | None = None
    course_code: str | None = None
    top_k: int | None = None


class StopIn(BaseModel):
    """spec §6.2 `POST /chat/conversations/{id}/stop`。

    `request_id` 缺省时取消该会话的全部进行中流 —— 前端若丢了 request_id
    （例如刷新页面），仍能止损。
    """

    request_id: str | None = None


class StopOut(BaseModel):
    cancelled: bool
