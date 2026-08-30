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

## `run()`（P4，spec §8.3）

1. 先抢执行位（`execution_slot()`），拿不到就 `429` —— **不无限排队**（spec §9）
2. 整段执行经 `run_in_threadpool` 卸载（ADR-0002）：它含 psutil 轮询，是同步阻塞调用
3. 落 `CodeRun`（含 `limit_detail`）→ 写 `AuditLog(action=code_run)`

命中黑名单时**执行器内部**就直接返回了（`status=blocked`），但本服务仍然照常
落库与审计 —— 「谁在反复尝试危险调用」这件事本身需要可见性。

**草稿（`CodeSession`）与运行（`CodeRun`）没有外键**：删草稿不该连带删掉运行
历史（spec §5 未要求外键，两者按 user_id 各自隔离）。
"""

import logging
from dataclasses import asdict

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.code.analysis import (
    ACTION_CODE_ANALYZE,
    StaticReport,
    analyze,
    source_hash,
)
from app.domain.code.execution import ACTION_CODE_RUN
from app.domain.code.review import build_review_question, render_mock_review
from app.infrastructure.concurrency import execution_slot
from app.infrastructure.llm_runtime import FALLBACK_TO_MOCK
from app.infrastructure.persistence.models import CodeAnalysis, CodeRun, CodeSession
from app.infrastructure.ports.code_executor import CodeExecutor, ExecutionResult
from app.infrastructure.ports.llm import LLMParams, TextDelta, Usage
from app.infrastructure.prompt_assembler import PromptAssembler
from app.infrastructure.registry import (
    LLM_PROVIDER_OPENAI,
    LLMConfig,
    get_or_create_singleton,
    llm_config,
    llm_params,
)
from app.infrastructure.runtime import (
    get_code_executor,
    get_llm_runtime,
    refresh_llm_config,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

_CODE_REVIEW = "code_review"


class CodeService:
    def __init__(
        self,
        session: AsyncSession,
        llm=None,
        prompts: PromptAssembler | None = None,
        executor: CodeExecutor | None = None,
    ):
        self._session = session
        # 与 ChatService 同理：只有共享运行时才按 revision 重绑（配置热生效），
        # 注入替身的测试不被 rebind 顶掉。
        self._llm = llm or get_llm_runtime()
        self._shared_llm = llm is None
        self._prompts = prompts or PromptAssembler()
        # 服务层只依赖端口；执行器不像 LLM 那样随配置 revision 变化，故不需要
        # 「共享 / 注入」的区分，注入即生效。
        self._executor = executor or get_code_executor()

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

    # ------------------------------------------------------------ 代码运行（P4）

    async def run(
        self,
        *,
        user_id: str,
        language: str,
        source: str,
        stdin: str = "",
        request_id: str = "",
    ) -> CodeRun:
        """执行一次代码并落 `CodeRun`（spec §8.3）。

        执行位与 `run_in_threadpool` 的先后刻意如此：**先抢位再卸载** —— 否则
        超限的请求会先占上线程池线程再被退回，白白消耗并发资源。
        """
        async with execution_slot():
            result: ExecutionResult = await run_in_threadpool(
                self._executor.execute, language=language, source=source, stdin=stdin
            )

        row = CodeRun(
            user_id=user_id,
            language=language,
            source_code=source,
            stdin=stdin,
            status=result.status,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            limit_detail=result.limit_detail,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit_run(row, user_id=user_id, request_id=request_id)
        return row

    async def list_runs(
        self, *, user_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[CodeRun], int]:
        """运行历史，按最近运行在前。"""
        total = (
            await self._session.execute(
                select(func.count()).select_from(CodeRun).where(CodeRun.user_id == user_id)
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                select(CodeRun)
                .where(CodeRun.user_id == user_id)
                .order_by(CodeRun.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    # ------------------------------------------------------------ 草稿（CodeSession）

    async def create_draft(
        self, *, user_id: str, language: str, title: str = "未命名草稿", source_code: str = ""
    ) -> CodeSession:
        row = CodeSession(
            user_id=user_id, language=language, title=title, source_code=source_code
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_drafts(self, *, user_id: str) -> list[CodeSession]:
        rows = (
            await self._session.execute(
                select(CodeSession)
                .where(CodeSession.user_id == user_id)
                .order_by(CodeSession.updated_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def update_draft(
        self,
        *,
        user_id: str,
        draft_id: str,
        title: str | None = None,
        source_code: str | None = None,
        language: str | None = None,
    ) -> CodeSession:
        row = await self._own_draft(user_id=user_id, draft_id=draft_id)
        if title is not None:
            row.title = title
        if source_code is not None:
            row.source_code = source_code
        if language is not None:
            row.language = language
        await self._session.flush()
        return row

    async def delete_draft(self, *, user_id: str, draft_id: str) -> None:
        row = await self._own_draft(user_id=user_id, draft_id=draft_id)
        await self._session.delete(row)
        await self._session.flush()

    async def _own_draft(self, *, user_id: str, draft_id: str) -> CodeSession:
        """取草稿并校验归属 —— 越权一律 `4040`（不泄露「存在但属于别人」）。"""
        row = (
            await self._session.execute(
                select(CodeSession).where(
                    CodeSession.id == draft_id, CodeSession.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApiError(4040, "草稿不存在")
        return row

    # ------------------------------------------------------------ 内部辅助

    async def _audit_run(self, row: CodeRun, *, user_id: str, request_id: str) -> None:
        detail = row.limit_detail or {}
        memory = detail.get("memory") or {}
        await AuditService(self._session).record(
            ACTION_CODE_RUN,
            user_id=user_id,
            target_type="code_run",
            target_id=row.id,
            detail={
                "language": row.language,
                "status": row.status,
                "duration_ms": row.duration_ms,
                "exit_code": row.exit_code,
                "blocked_by_blacklist": (detail.get("blacklist") or {}).get("rule"),
                "memory_peak_bytes": memory.get("peak_bytes"),
                "degraded_layers": detail.get("degraded_layers", []),
            },
            request_id=request_id,
        )

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
