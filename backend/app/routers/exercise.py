"""学生端习题端点（spec §6.2 exercise 行）。

hint 端点在 Task 10 追加（SSE）。路由不含业务逻辑，判分与编排都在
`ExerciseService`。学生视图不含 answer / explanation / test_cases —— 揭示
只发生在提交之后（`SubmitOut`）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.domain.exercise.judging import EXERCISE_TYPES
from app.infrastructure.persistence.models import User
from app.schemas.exercise import (
    ExerciseDetail,
    ExerciseListItem,
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
    type: Annotated[str | None, Query(pattern=f"^({'|'.join(EXERCISE_TYPES)})$")] = None,
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
