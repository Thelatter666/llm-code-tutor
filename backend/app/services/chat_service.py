"""答疑对话用例编排（spec §8.1）。

`stream_reply()` 的完整链路：

1. 落 user message（含当次生效的防抄袭档位与底线拦截标记）
2. 装配 RAG → 先发 `citation` 事件（spec §7.2 七步链路复用 P1 的 RetrievalService）
3. 渲染 prompt（档位 + 底线 + 引用上下文 + 截断后的历史）
4. 流式转发 `token`，每次 yield 前检查 per-call 的中断 Event
5. 落 assistant message（citations / token_usage / model / provider / truncated / 档位 / 底线拦截）
6. 发 `done`（或中断 / 异常时发 `error`）
7. 写 `AuditLog(action=chat)` —— **在 `finally` 中**，无论正常结束还是异常中断

**聊天入口固定 `seek_answer`**（ADR-0005）：本服务是答疑对话入口，不做任何
意图推断。豁免只发生在显式传入 `review_my_code` / `judging` 的其它入口
（P3 代码辅导、P5 习题辅导）。
"""

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.errors import ApiError
from app.domain.chat.history import truncate_history
from app.domain.chat.policy import (
    ACTION_CHAT,
    DEFAULT_CONVERSATION_TITLE,
    ROLE_ASSISTANT,
    ROLE_USER,
    SEEK_ANSWER,
    TITLE_MAX_CHARS,
    detect_floor_violation,
    resolve_mode,
)
from app.infrastructure.cancellation import get_cancellation_registry
from app.infrastructure.persistence.models import Conversation, Message
from app.infrastructure.ports.llm import LLMParams, TextDelta, Usage
from app.infrastructure.prompt_assembler import PromptAssembler
from app.infrastructure.registry import get_or_create_singleton, llm_config, llm_params
from app.infrastructure.runtime import get_llm_runtime, refresh_llm_config
from app.infrastructure.sse import (
    CANCELLED_CODE,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_TOKEN,
    StreamEvent,
    citation_event,
)
from app.services.audit_service import AuditService
from app.services.retrieval_service import RetrievalService, SearchResult

logger = logging.getLogger(__name__)

_NO_RAG = "rag_qa"


class ChatService:
    def __init__(
        self,
        session,
        llm=None,
        retrieval=None,
        prompts: PromptAssembler | None = None,
        cancels=None,
    ):
        self._session = session
        self._llm = llm or get_llm_runtime()
        # 只有用共享运行时时才按 revision 重新绑定（见 stream_reply）。
        # 注入替身的测试若也被 rebind，替身会被真实的 factory 顶掉。
        self._shared_llm = llm is None
        self._retrieval = retrieval or RetrievalService(session)
        self._prompts = prompts or PromptAssembler()
        self._cancels = cancels or get_cancellation_registry()

    # ------------------------------------------------------------ 会话 CRUD

    async def create_conversation(self, user_id: str, title: str | None = None) -> Conversation:
        conv = Conversation(user_id=user_id, title=title or DEFAULT_CONVERSATION_TITLE)
        self._session.add(conv)
        await self._session.flush()
        return conv

    async def list_conversations(self, user_id: str) -> list[Conversation]:
        rows = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
        )
        return list(rows.scalars().all())

    async def get_conversation(self, conversation_id: str, user_id: str) -> Conversation:
        """取会话并校验归属；不存在或不属于当前用户一律 `4040`。

        不返回 `4030` 是刻意的：返回「无权限」等于替攻击者确认了该会话存在。
        """
        conv = await self._session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            raise ApiError(4040, "会话不存在")
        return conv

    async def delete_conversation(
        self, conversation_id: str, user_id: str, request_id: str
    ) -> None:
        conv = await self.get_conversation(conversation_id, user_id)
        await self._session.execute(
            Message.__table__.delete().where(Message.conversation_id == conv.id)
        )
        await self._session.delete(conv)
        await self._session.flush()
        await AuditService(self._session).record(
            "chat_conversation_delete",
            user_id=user_id,
            target_type="conversation",
            target_id=conversation_id,
            request_id=request_id,
        )

    async def list_messages(self, conversation_id: str, user_id: str) -> list[Message]:
        await self.get_conversation(conversation_id, user_id)
        rows = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(rows.scalars().all())

    # ------------------------------------------------------------ 流式答疑

    async def stream_reply(
        self,
        conversation_id: str,
        content: str,
        *,
        user_id: str,
        request_id: str,
        use_rag: bool = True,
        kb_ids: list[str] | None = None,
        course_code: str | None = None,
        top_k: int | None = None,
    ):
        """产出 `StreamEvent`：`citation* → token* → done`（或 `error`）。"""
        conv = await self.get_conversation(conversation_id, user_id)
        # spec §4.2 硬约束 4「配置热生效」：按 ModelConfig.revision 重新绑定降级链。
        # 只在启动时绑一次的话，管理员改了 base_url / Key 之后必须重启才生效。
        if self._shared_llm:
            await refresh_llm_config(self._session)
        cfg = await get_or_create_singleton(self._session)
        mode = resolve_mode(SEEK_ANSWER, cfg.anti_plagiarism_mode)
        floor_hit = detect_floor_violation(content)

        # 先落 user message：即便随后中断或异常，学生的提问也不该丢
        user_message = Message(
            conversation_id=conversation_id,
            role=ROLE_USER,
            content=content,
            anti_plagiarism_mode=mode,
            blocked_by_policy=floor_hit is not None,
        )
        self._session.add(user_message)
        await self._session.flush()

        params = llm_params(llm_config(cfg))
        cancel = self._cancels.create(conversation_id, request_id)
        result = SearchResult(rag_hit=False, degraded=False, fallback_reason=None, threshold=0.0)
        texts: list[str] = []
        usage: Usage | None = None
        error: ApiError | None = None

        try:
            try:
                if use_rag:
                    result = await self._retrieval.search(
                        content, kb_ids=kb_ids, course_code=course_code, top_k=top_k
                    )
                # spec §6.1：citation 先于 token，前端得以在答案出现前展示引用来源
                for citation in result.citations:
                    yield citation_event(citation)

                history = truncate_history(
                    await self._history_dicts(conversation_id, exclude=user_message.id)
                )
                messages = self._prompts.assemble(
                    _NO_RAG,
                    question=content,
                    mode=cfg.anti_plagiarism_mode,
                    intent=SEEK_ANSWER,
                    citations=[asdict(c) for c in result.citations],
                    history=history,
                    floor_hit=floor_hit,
                )
                async for chunk in self._llm.stream(messages, params, cancel=cancel):
                    if isinstance(chunk, TextDelta):
                        texts.append(chunk.text)
                        yield StreamEvent(EVENT_TOKEN, {"delta": chunk.text})
                    else:
                        usage = chunk  # 用量是流的最后一个元素（B1）
            except ApiError as exc:
                error = exc
            except Exception:
                logger.exception("答疑流式生成异常 conversation=%s", conversation_id)
                error = ApiError(5000, "生成失败，请稍后重试")

            if error is None and cancel.is_set():
                # spec §8.1：流中断发 error，已生成内容仍落库并标记 truncated
                error = ApiError(CANCELLED_CODE, "已中断生成")

            truncated = error is not None
            assistant = await self._persist_assistant(
                conversation_id=conversation_id,
                text="".join(texts),
                citations=result.citations,
                usage=usage,
                params=params,
                mode=mode,
                blocked=floor_hit is not None,
                truncated=truncated,
            )
            self._touch(conv, content)

            if error is None:
                yield StreamEvent(EVENT_DONE, self._done_payload(assistant, usage, params, result))
            else:
                yield StreamEvent(
                    EVENT_ERROR, {"code": error.code, "message": error.message}
                )
        finally:
            self._cancels.discard(conversation_id, request_id)
            await self._write_audit(
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                mode=mode,
                floor_hit=floor_hit,
                result=result,
                texts=texts,
                error=error,
            )

    # ------------------------------------------------------------ 内部辅助

    async def _history_dicts(self, conversation_id: str, *, exclude: str) -> list[dict]:
        rows = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != exclude)
            .order_by(Message.created_at, Message.id)
        )
        return [{"role": m.role, "content": m.content} for m in rows.scalars().all()]

    async def _persist_assistant(
        self,
        *,
        conversation_id: str,
        text: str,
        citations,
        usage: Usage | None,
        params: LLMParams,
        mode: str | None,
        blocked: bool,
        truncated: bool,
    ) -> Message:
        # 流末没拿到用量（提供方违约）时按估算用量补齐，不让 done 缺字段
        if usage is None:
            usage = Usage(0, len(text) // 4, len(text) // 4, estimated=True)
        message = Message(
            conversation_id=conversation_id,
            role=ROLE_ASSISTANT,
            content=text,
            citations=[asdict(c) for c in citations] or None,
            token_usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "estimated": usage.estimated,
            },
            model=params.model,
            provider=self._llm.snapshot().provider,
            truncated=truncated,
            anti_plagiarism_mode=mode,
            blocked_by_policy=blocked,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    def _done_payload(
        self, assistant: Message, usage: Usage | None, params: LLMParams, result: SearchResult
    ) -> dict:
        """spec §6.1 的 `done` 载荷，八个字段一个都不能少。"""
        snapshot = self._llm.snapshot()
        token_usage = assistant.token_usage or {}
        return {
            "message_id": assistant.id,
            "token_usage": {
                "prompt_tokens": token_usage.get("prompt_tokens", 0),
                "completion_tokens": token_usage.get("completion_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
            },
            "usage_estimated": bool(token_usage.get("estimated", False)),
            "model": params.model,
            "provider": snapshot.provider,
            "rag_hit": result.rag_hit,
            # 检索降级与提供方降级可能同时发生；先报检索的，它是学生更可感知的那个
            "degraded": result.degraded or snapshot.degraded,
            "fallback_reason": result.fallback_reason or snapshot.fallback_reason,
        }

    def _touch(self, conv: Conversation, content: str) -> None:
        """推进 `updated_at`；仍是默认标题时用首条提问生成标题。

        `onupdate` 只在列值变化时触发，故显式赋值，否则会话列表的「最近活动」
        排序会一直停在创建时间。
        """
        if conv.title == DEFAULT_CONVERSATION_TITLE and content.strip():
            conv.title = content.strip()[:TITLE_MAX_CHARS]
        # 与 models.py / auth_service.py 保持一致用 timezone.utc —— ruff 的 UP017
        # 建议 `datetime.UTC`，但那是 **模块** 级别名，本文件导入的是 datetime 类
        conv.updated_at = datetime.now(timezone.utc)

    async def _write_audit(
        self,
        *,
        user_id: str,
        conversation_id: str,
        request_id: str,
        mode: str | None,
        floor_hit: str | None,
        result: SearchResult,
        texts: list[str],
        error: ApiError | None,
    ) -> None:
        """spec §8.1：无论正常结束还是异常中断，`AuditLog(action=chat)` 都要写。

        本方法在 `finally` 中调用，因此自身不得抛出 —— 否则会掩盖真正的异常。
        """
        try:
            await AuditService(self._session).record(
                ACTION_CHAT,
                user_id=user_id,
                target_type="conversation",
                target_id=conversation_id,
                detail={
                    "mode": mode,
                    "blocked_by_policy": floor_hit is not None,
                    "floor_hit": floor_hit,
                    "rag_hit": result.rag_hit,
                    "citations": len(result.citations),
                    "chars": len("".join(texts)),
                    "error_code": error.code if error else None,
                },
                request_id=request_id,
            )
            await self._session.commit()
        except Exception:
            logger.exception("写入答疑审计日志失败 conversation=%s", conversation_id)
