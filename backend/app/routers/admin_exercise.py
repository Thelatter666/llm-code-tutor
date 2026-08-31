"""管理端习题 CRUD（spec §6.2 缺口补全，P5 Task 11）。

五端点照 `admin_knowledge.py` 风格：挂 `AdminDep`，三个写操作各落一条 `AuditLog`
（action 对齐 `admin_kb_*` 命名族 → `admin_exercise_create/update/delete`）。

`source` 与 `created_by` 都不由请求体决定：前者服务端写死 `admin`，后者取当前
管理员。PATCH 的 schema 外字段（含 `source`）一律 **422 显式拒绝** —— 见
`schemas/exercise.py::ExercisePatch` 与裁定 1 修订。

管理端出参回完整字段（含 answer / explanation / test_cases 与 draft）：学生端
看不到的东西，出题人必须看得到。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.exercise import (
    STATUS_PATTERN,
    TYPE_PATTERN,
    ExerciseIn,
    ExerciseOut,
    ExercisePatch,
)
from app.services.exercise_service import ExerciseService

router = APIRouter(prefix="/api/v1/admin/exercises", tags=["admin·exercise"])

AdminDep = Annotated[User, Depends(require_admin)]


@router.post("")
async def create_exercise(
    body: ExerciseIn, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    row = await ExerciseService(session).create(
        type=body.type,
        stem=body.stem,
        answer=body.answer,
        difficulty=body.difficulty,
        options=body.options,
        test_cases=body.test_cases,
        explanation=body.explanation,
        knowledge_tags=body.knowledge_tags,
        status=body.status,
        admin_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(ExerciseOut.model_validate(row).model_dump(), request_id=rid)


@router.get("")
async def list_exercises(
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
    type: Annotated[str | None, Query(pattern=TYPE_PATTERN)] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    knowledge_tag: str | None = None,
    status: Annotated[str | None, Query(pattern=STATUS_PATTERN)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """`{items, total}`（spec §6.2 分页约定）；含 draft。"""
    items, total = await ExerciseService(session).list_all(
        type=type,
        difficulty=difficulty,
        knowledge_tag=knowledge_tag,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [ExerciseOut.model_validate(r).model_dump() for r in items],
            "total": total,
        },
        request_id=rid,
    )


@router.get("/{exercise_id}")
async def get_exercise(exercise_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep):
    svc = ExerciseService(session)
    row = await svc.get_any(exercise_id)
    return ok(ExerciseOut.model_validate(row).model_dump(), request_id=rid)


@router.patch("/{exercise_id}")
async def update_exercise(
    exercise_id: str,
    body: ExercisePatch,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
):
    """全部字段可选更新（含 status 发布/下架）；`source` 不可改。"""
    svc = ExerciseService(session)
    row = await svc.update(
        exercise_id,
        fields=body.model_dump(exclude_unset=True),
        admin_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(ExerciseOut.model_validate(row).model_dump(), request_id=rid)


@router.delete("/{exercise_id}")
async def delete_exercise(
    exercise_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """手工级联删 Submission 与错题条目（M-2 无 FK 现状）；删除计数进审计。"""
    counts = await ExerciseService(session).delete(
        exercise_id, admin_id=user.id, request_id=rid
    )
    await session.commit()
    return ok({"deleted": True, **counts}, request_id=rid)
