"""习题用例编排（spec §5.1 判题四路 / §8.5 错题归集 / §6.2 exercise 行）。

`submit()` 的链路：

1. 取 published 习题（不存在 / 未发布一律 `4040` —— 不泄露「存在但未发布」）
2. 按题型判分：
   - choice / blank / multi：领域层纯规则即时判分（`domain/exercise/judging.py`）
   - coding：逐用例经 `execution_slot()` + `run_in_threadpool` 调 CodeExecutor，
     **服务层自计 15s 累计预算**（端口无 per-call 超时，已裁定），超预算中止
     剩余用例并按已通过比例判分
   - short：转 AI 评分（内部 Judging 意图，完全豁免防抄袭；prompt 不走
     PromptAssembler，见 `domain/exercise/short_scoring.py`）；Mock 判定取
     配置层（同 spec §8.4 口径），解析失败 → `5021` **不落库不入错题本**
3. `attempt_no` 递增 → 落 Submission → `is_correct == false` 即入错题本
4. 写 `AuditLog(action="exercise_submit")`

hint 的 AI 辅导链路在 Task 10 追加（`stream_hint`）。
"""

import logging
import time
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.code.execution import STATUS_ACCEPTED
from app.domain.exercise.judging import (
    JUDGING_BUDGET_S,
    METHOD_EXECUTED,
    TYPE_BLANK,
    TYPE_CODING,
    TYPE_MULTI,
    TYPE_SHORT,
    JudgeOutcome,
    judge_blank,
    judge_choice,
    judge_coding,
    judge_multi,
)
from app.domain.exercise.short_scoring import (
    SHORT_JUDGE_SYSTEM_PROMPT,
    ShortJudgeParseError,
    build_short_judge_user_prompt,
    mock_short_score,
    parse_judge_json,
)
from app.infrastructure.concurrency import execution_slot
from app.infrastructure.persistence.models import Exercise, Submission
from app.infrastructure.ports.code_executor import CodeExecutor, ExecutionResult
from app.infrastructure.ports.llm import ChatMessage
from app.infrastructure.registry import (
    LLM_PROVIDER_OPENAI,
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
from app.services.mistake_service import MistakeBookService

logger = logging.getLogger(__name__)


class ExerciseService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        executor: CodeExecutor | None = None,
        llm=None,
        mistakes: MistakeBookService | None = None,
        budget_seconds: float | None = None,
    ):
        self._session = session
        # 服务层只依赖端口；执行器不随 ModelConfig revision 变化，注入即生效
        self._executor = executor or get_code_executor()
        self._llm = llm or get_llm_runtime()
        # 与 ChatService / CodeService 同理：只有共享运行时才按 revision 重绑
        self._shared_llm = llm is None
        self._mistakes = mistakes or MistakeBookService(session)
        # 15s 累计预算缺省取领域常量；构造参数仅供测试注入小值（已裁定语义）
        self._budget_seconds = budget_seconds if budget_seconds is not None else JUDGING_BUDGET_S

    # ------------------------------------------------------------ 查询

    async def get_published(self, exercise_id: str) -> Exercise:
        """学生端可见的习题；不存在与未发布一律 `4040`（spec §6.2）。"""
        row = await self._session.get(Exercise, exercise_id)
        if row is None or row.status != "published":
            raise ApiError(4040, "习题不存在")
        return row

    async def list_exercises(
        self,
        *,
        type: str | None = None,
        difficulty: int | None = None,
        knowledge_tag: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Exercise], int, list[str]]:
        """学生端列表：只暴露 published（spec §6.2）。

        返回 `(items, total, facets)`；facets.knowledge_tags 供前端筛选下拉，
        不受 knowledge_tag 过滤影响（契约定稿 11）。knowledge_tag 是 JSON 列，
        Python 层过滤（spec §3.2 权衡 3：声明规模下聚合成本可忽略）。
        """
        stmt = select(Exercise).where(Exercise.status == "published")
        if type:
            stmt = stmt.where(Exercise.type == type)
        if difficulty:
            stmt = stmt.where(Exercise.difficulty == difficulty)
        rows = list(
            (
                await self._session.execute(
                    stmt.order_by(Exercise.difficulty, Exercise.created_at, Exercise.id)
                )
            )
            .scalars()
            .all()
        )
        facets = sorted({tag for row in rows for tag in (row.knowledge_tags or [])})
        if knowledge_tag:
            rows = [row for row in rows if knowledge_tag in (row.knowledge_tags or [])]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total, facets

    # ------------------------------------------------------------ 判题提交

    async def submit(
        self, *, user_id: str, exercise_id: str, answer: object, request_id: str
    ) -> Submission:
        exercise = await self.get_published(exercise_id)

        if exercise.type == TYPE_CODING:
            outcome = await self._judge_coding(exercise, answer)
        elif exercise.type == TYPE_SHORT:
            outcome = await self._judge_short(exercise, answer)
        elif exercise.type == TYPE_MULTI:
            outcome = judge_multi(exercise.answer, answer)
        elif exercise.type == TYPE_BLANK:
            outcome = judge_blank(exercise.answer, answer)
        else:
            outcome = judge_choice(exercise.answer, answer)

        attempt_no = (
            await self._session.execute(
                select(func.count())
                .select_from(Submission)
                .where(Submission.user_id == user_id, Submission.exercise_id == exercise_id)
            )
        ).scalar_one() + 1

        submission = Submission(
            user_id=user_id,
            exercise_id=exercise_id,
            answer=answer,
            is_correct=outcome.is_correct,
            score=outcome.score,
            judge_detail=outcome.detail,
            # 简答题的 AI 点评同时进 feedback 列，列表页免解 JSON
            feedback=outcome.detail.get("feedback") if exercise.type == TYPE_SHORT else None,
            attempt_no=attempt_no,
        )
        self._session.add(submission)
        await self._session.flush()

        # 统一规则（spec §5.1）：is_correct == false 即入错题本；
        # 答对也要推进已存在条目的连续计数（推进逻辑在 MistakeBookService）
        await self._mistakes.record_result(
            user_id=user_id,
            exercise=exercise,
            is_correct=outcome.is_correct,
            wrong_answer=None if outcome.is_correct else answer,
            now=datetime.now(UTC),
        )

        await AuditService(self._session).record(
            "exercise_submit",
            user_id=user_id,
            target_type="exercise",
            target_id=exercise.id,
            detail={
                "type": exercise.type,
                "score": outcome.score,
                "is_correct": outcome.is_correct,
                "attempt_no": attempt_no,
            },
            request_id=request_id,
        )
        return submission

    # ------------------------------------------------------------ 编程判分

    async def _judge_coding(self, exercise: Exercise, answer: object) -> JudgeOutcome:
        """逐用例受限执行 + 15s 累计预算（spec §5.1 路 3，已裁定语义）。"""
        if not isinstance(answer, dict) or not isinstance(answer.get("source"), str) or not answer["source"].strip():
            raise ApiError(4220, "编程题作答需提供 source 源码")

        test_cases = exercise.test_cases or {}
        language = test_cases.get("language") or "python"
        cases = test_cases.get("cases") or []
        if not cases:
            return JudgeOutcome(
                0,
                False,
                {
                    "method": METHOD_EXECUTED,
                    "language": language,
                    "budget_exceeded": False,
                    "budget_limit_s": self._budget_seconds,
                    "cases": [],
                    "error": "习题缺少执行用例",
                },
            )

        source = answer["source"]
        started = time.monotonic()
        passed = 0
        budget_exceeded = False
        cases_detail: list[dict] = []
        for index, case in enumerate(cases):
            if budget_exceeded or time.monotonic() - started >= self._budget_seconds:
                # 跨用例累计超预算：中止剩余用例，按已通过比例判分（已裁定）
                budget_exceeded = True
                cases_detail.append(self._skipped_case(index, case))
                continue
            result = await self._run_case(language, source, case.get("stdin", ""))
            expected = case.get("expected_stdout", "")
            case_passed = result.status == STATUS_ACCEPTED and result.stdout.strip() == expected.strip()
            if case_passed:
                passed += 1
            cases_detail.append(
                {
                    "index": index,
                    "stdin": case.get("stdin", ""),
                    "expected_stdout": expected,
                    "actual_stdout": result.stdout,
                    "passed": case_passed,
                    "duration_ms": result.duration_ms,
                    "status": result.status,
                }
            )

        outcome = judge_coding(
            passed=passed,
            total=len(cases),
            budget_exceeded=budget_exceeded,
            cases=cases_detail,
        )
        detail = dict(outcome.detail)
        detail["language"] = language
        detail["budget_limit_s"] = self._budget_seconds
        return JudgeOutcome(outcome.score, outcome.is_correct, detail)

    async def _run_case(self, language: str, source: str, stdin: str) -> ExecutionResult:
        """单用例执行：先抢执行位再卸载到线程池（ADR-0002 / spec §3.2 权衡 14）。"""
        async with execution_slot():
            return await run_in_threadpool(
                self._executor.execute, language=language, source=source, stdin=stdin
            )

    @staticmethod
    def _skipped_case(index: int, case: dict) -> dict:
        return {
            "index": index,
            "stdin": case.get("stdin", ""),
            "expected_stdout": case.get("expected_stdout", ""),
            "actual_stdout": None,
            "passed": False,
            "duration_ms": 0,
            "status": "skipped",
            "skipped": True,
            "skip_reason": "budget_exceeded",
        }

    # ------------------------------------------------------------ 简答评分

    async def _judge_short(self, exercise: Exercise, answer: object) -> JudgeOutcome:
        """AI 评分（spec §5.1 路 4）：Mock 走确定性启发式，真提供方走 complete()。"""
        student_answer = answer if isinstance(answer, str) else ""
        reference = exercise.answer if isinstance(exercise.answer, str) else ""

        cfg_row = await get_or_create_singleton(self._session)
        if self._shared_llm:
            # spec §4.2 硬约束 4：按 revision 重绑降级链，管理员改配置即时生效
            await refresh_llm_config(self._session)
        cfg = llm_config(cfg_row)
        real_provider = cfg.provider == LLM_PROVIDER_OPENAI and bool(cfg.api_key)
        if not real_provider:
            verdict = mock_short_score(reference, exercise.explanation, student_answer)
            return JudgeOutcome(
                verdict.score,
                verdict.is_correct,
                {
                    "ai_scored": True,
                    "judge_mode": "mock_heuristic",
                    "model": None,
                    "provider": "mock",
                    "token_usage": None,
                    "feedback": verdict.feedback,
                },
            )

        messages = [
            ChatMessage(role="system", content=SHORT_JUDGE_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=build_short_judge_user_prompt(
                    exercise.stem, reference, exercise.explanation, student_answer
                ),
            ),
        ]
        params = llm_params(cfg)
        completion = await self._llm.complete(messages, params)
        try:
            score, is_correct, feedback = parse_judge_json(completion.text)
        except ShortJudgeParseError as exc:
            # 「模型故障」不能记成「学生答错」：不落 Submission、不入错题本
            logger.warning("简答评分输出无法解析：%s", completion.text[:120])
            raise ApiError(5021, "AI 评分暂不可用，请稍后重试") from exc

        usage = completion.usage
        return JudgeOutcome(
            score,
            is_correct,
            {
                "ai_scored": True,
                "judge_mode": "model",
                "model": params.model,
                "provider": self._llm.snapshot().provider,
                "token_usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
                if usage
                else None,
                "feedback": feedback,
            },
        )
