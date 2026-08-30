"""代码解析与辅导用例编排（spec §8.4）。

`analyze()` 的链路：

1. `source_hash` 命中历史则直接复用已有 CodeAnalysis，不重复解析、不重复生成
   （唯一约束在库层兜底；复用按 user 隔离，不跨账号共享）
2. 静态解析是同步 CPU 调用，经 `run_in_threadpool` 卸载（ADR-0002）
3. AI 报告分两路（spec §8.4）：
   - **Mock 模式**（配置无真提供方）：由 static_report 模板化生成，不发起
     LLM 调用 —— 与 P2「无 API Key → Mock 模式，不算降级」同口径
   - **真提供方**：经 `LLMRuntime` 流式生成并服务端收集，`token_usage` 逐字
     取自流末 Usage 元素（拍板决策 5）
4. 真提供方调用失败（LLMRuntime 全链失败抛 5021）→ 改用模板生成，并置
   `degraded=true` + `fallback_reason=llm_fallback_to_mock`（spec §9 降级可见）
5. 写 `AuditLog(action=code_analyze)`

**意图固定 `review_my_code`**（ADR-0005）：豁免防抄袭档位约束是显式契约，
本服务不做任何内容推断。**不做 RAG**（spec §7.2：该链路只服务答疑对话与
习题辅导）；**不做底线检测**（输入是代码不是自然语言请求，关键词误判率高；
底线条文仍由模板无条件注入，装配器无跳过开关 —— spec §3.2 权衡 10）。
"""

import logging
from dataclasses import asdict

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.code.analysis import (
    ACTION_CODE_ANALYZE,
    LANGUAGE_PYTHON,
    StaticReport,
    analyze,
    source_hash,
)
from app.domain.code.review import build_review_question, render_mock_review
from app.infrastructure.llm_runtime import FALLBACK_TO_MOCK
from app.infrastructure.persistence.models import AuditLog, CodeAnalysis
from app.infrastructure.ports.llm import LLMParams, TextDelta, Usage
from app.infrastructure.prompt_assembler import PromptAssembler
from app.infrastructure.registry import (
    LLM_PROVIDER_OPENAI,
    LLMConfig,
    get_or_create_singleton,
    llm_config,
    llm_params,
)
from app.infrastructure.runtime import get_llm_runtime, refresh_llm_config
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

_CODE_REVIEW = "code_review"


class CodeService:
    def __init__(self, session: AsyncSession, llm=None, prompts: PromptAssembler | None = None):
        self._session = session
        # 与 ChatService 同理：只有共享运行时才按 revision 重绑（配置热生效），
        # 注入替身的测试不被 rebind 顶掉。
        self._llm = llm or get_llm_runtime()
        self._shared_llm = llm is None
        self._prompts = prompts or PromptAssembler()

    async def analyze(
        self, *, user_id: str, language: str, source: str, request_id: str
    ) -> tuple[CodeAnalysis, bool]:
        """返回 `(CodeAnalysis, reused)`。"""
        digest = source_hash(language, source)
        existing = (
            await self._session.execute(
                select(CodeAnalysis).where(
                    CodeAnalysis.user_id == user_id,
                    CodeAnalysis.language == language,
                    CodeAnalysis.source_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await self._audit(existing, user_id=user_id, reused=True, request_id=request_id)
            return existing, True

        if self._shared_llm:
            await refresh_llm_config(self._session)
        cfg_row = await get_or_create_singleton(self._session)

        # ADR-0002：ast.parse / 正则解析都是同步阻塞调用，卸载到线程池
        report = await run_in_threadpool(analyze, language, source)
        ai_report = await self._build_ai_report(cfg_row, language, source, report)

        row = CodeAnalysis(
            user_id=user_id,
            language=language,
            source_hash=digest,
            static_report=asdict(report),
            ai_report=ai_report,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(row, user_id=user_id, reused=False, request_id=request_id)
        return row, False

    # ------------------------------------------------------------ 内部辅助

    async def _build_ai_report(
        self, cfg_row, language: str, source: str, report: StaticReport
    ) -> dict:
        """Mock 模式模板化；真提供方流式收集；失败降级回模板并显式标记。"""
        cfg = llm_config(cfg_row)
        real_provider = cfg.provider == LLM_PROVIDER_OPENAI and bool(cfg.api_key)
        if not real_provider:
            return self._templated(cfg, report, degraded=False, fallback_reason=None)

        params = llm_params(cfg)
        messages = self._prompts.assemble(
            _CODE_REVIEW,
            question=build_review_question(language, source, report),
            mode=cfg_row.anti_plagiarism_mode,
            intent="review_my_code",  # ADR-0005：显式契约，不推断
        )
        try:
            content, usage = await self._collect(messages, params)
        except ApiError as exc:
            logger.warning("代码讲解生成失败（code=%s），降级为静态模板", exc.code)
            return self._templated(cfg, report, degraded=True, fallback_reason=FALLBACK_TO_MOCK)

        snapshot = self._llm.snapshot()
        if usage is None:
            # 提供方违约没给用量：按估算用量补齐，不让字段缺失
            usage = Usage(0, len(content) // 4, len(content) // 4, estimated=True)
        return {
            "content": content,
            "provider": snapshot.provider,
            "model": params.model,
            "token_usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "usage_estimated": usage.estimated,
            "degraded": snapshot.degraded,
            "fallback_reason": snapshot.fallback_reason,
        }

    async def _collect(
        self, messages, params: LLMParams
    ) -> tuple[str, Usage | None]:
        """消费流：收集 TextDelta，用量取流末 Usage 元素。"""
        texts: list[str] = []
        usage: Usage | None = None
        async for chunk in self._llm.stream(messages, params):
            if isinstance(chunk, TextDelta):
                texts.append(chunk.text)
            else:
                usage = chunk
        return "".join(texts), usage

    def _templated(
        self, cfg: LLMConfig, report: StaticReport, *, degraded: bool, fallback_reason: str | None
    ) -> dict:
        """spec §8.4：Mock 模式下 ai_report 由 static_report 模板化生成。"""
        content = render_mock_review(report)
        completion = len(content) // 4
        return {
            "content": content,
            "provider": "mock",
            "model": cfg.model,
            "token_usage": {
                "prompt_tokens": 0,
                "completion_tokens": completion,
                "total_tokens": completion,
            },
            "usage_estimated": True,
            "degraded": degraded,
            "fallback_reason": fallback_reason,
        }

    async def _audit(
        self, row: CodeAnalysis, *, user_id: str, reused: bool, request_id: str
    ) -> None:
        ai = row.ai_report or {}
        await AuditService(self._session).record(
            ACTION_CODE_ANALYZE,
            user_id=user_id,
            target_type="code_analysis",
            target_id=row.id,
            detail={
                "language": row.language,
                "reused": reused,
                "provider": ai.get("provider"),
                "degraded": ai.get("degraded", False),
                "fallback_reason": ai.get("fallback_reason"),
                "usage_estimated": ai.get("usage_estimated", False),
            },
            request_id=request_id,
        )
