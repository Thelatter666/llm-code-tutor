"""学生端习题端点（spec §6.2 exercise 行）。

路由不含业务逻辑，判分与编排在 `ExerciseService`。学生视图不含 answer /
explanation / test_cases —— 揭示只发生在提交之后（`SubmitOut`）。

`POST /exercises/{id}/hint` 是 SSE 端点（Task 10），事件契约见 spec §6.1。
**本端点没有配套的 /stop**：中断由前端 `AbortController` 断连承担（裁定 10），
服务端保留 per-call cancel Event 与 4990 语义，与 chat 同构。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.infrastructure.sse import format_sse
from app.schemas.exercise import (
    TYPE_PATTERN,
    ExerciseDetail,
    ExerciseListItem,
    HintIn,
    SubmitIn,
    SubmitOut,
)
from app.services.exercise_service import ExerciseService

router = APIRouter(prefix="/api/v1/exercises", tags=["exercise"])

UserDep = Annotated[User, Depends(get_current_user)]


@router.get("")
async def list_exercises(
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
    type: Annotated[str | None, Query(pattern=TYPE_PATTERN)] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    knowledge_tag: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """`{items, total, facets.knowledge_tags}`；facets 供筛选下拉（契约定稿 11）。"""
    items, total, facets = await ExerciseService(session).list_exercises(
        type=type,
        difficulty=difficulty,
        knowledge_tag=knowledge_tag,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [ExerciseListItem.model_validate(r).model_dump() for r in items],
            "total": total,
            "facets": {"knowledge_tags": facets},
        },
        request_id=rid,
    )


@router.get("/{exercise_id}")
async def get_exercise(
    exercise_id: str, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    row = await ExerciseService(session).get_published(exercise_id)
    data = ExerciseDetail.model_validate(row).model_dump()
    if row.type == "coding":
        data["language"] = (row.test_cases or {}).get("language")
    return ok(data, request_id=rid)


@router.post("/{exercise_id}/submit")
async def submit_exercise(
    exercise_id: str,
    body: SubmitIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
):
    """判分四路入口（spec §5.1）；提交即揭示正确答案与解析。"""
    svc = ExerciseService(session)
    row = await svc.submit(
        user_id=user.id, exercise_id=exercise_id, answer=body.answer, request_id=rid
    )
    await session.commit()
    exercise = await svc.get_published(exercise_id)
    return ok(
        SubmitOut(
            submission_id=row.id,
            exercise_id=row.exercise_id,
            answer=row.answer,
            is_correct=row.is_correct,
            score=row.score,
            judge_detail=row.judge_detail,
            feedback=row.feedback,
            attempt_no=row.attempt_no,
            created_at=row.created_at,
            correct_answer=exercise.answer,
            explanation=exercise.explanation,
            ai_scored=bool((row.judge_detail or {}).get("ai_scored")),
        ).model_dump(),
        request_id=rid,
    )


@router.post("/{exercise_id}/hint")
async def stream_hint(
    exercise_id: str,
    body: HintIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
):
    """习题 AI 辅导（SSE，spec §6.1 / §6.2）。

    `intent` 由前端入口按钮**显式传入**（ADR-0005）：「获取思路」= `seek_answer`
    受防抄袭档位约束；「批改我的作答」= `review_my_code` 豁免档位（不豁免底线）。

    published 校验在返回 `StreamingResponse` **之前**完成（chat 同构）—— 否则
    HTTP 200 已发出，「不存在或未发布」只能靠流里的 error 事件表达，前端与日志
    都更难处理。
    """
    svc = ExerciseService(session)
    await svc.get_published(exercise_id)

    async def _events():
        async for event in svc.stream_hint(
            exercise_id=exercise_id,
            user_id=user.id,
            intent=body.intent,
            answer=body.answer,
            request_id=rid,
        ):
            yield format_sse(event)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        # X-Accel-Buffering：经反代时不得缓冲，否则流式退化成一次性返回
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
