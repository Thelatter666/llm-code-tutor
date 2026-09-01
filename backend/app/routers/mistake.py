"""学生端错题本端点（spec §6.2 mistake 行，P5 Task 9）。

四个端点全部挂 `CurrentRidDep` + 登录用户；条目归属与「非本人一律 `4040`」的
判定在 `MistakeBookService`，本文件只把 `(entry, exercise)` 对组装成出参。

`GET /mistakes` 返回裸数组：单个学生的错题条目上限就是题库规模（spec §3.1 假设 1
的声明规模），无需分页；与学生端其它列表端点（会话列表、知识库列表）同构。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.errors import ApiError
from app.core.responses import ok
from app.infrastructure.persistence.models import Exercise, MistakeBookEntry, User
from app.schemas.common import ApiResponse
from app.schemas.exercise import (
    ExerciseListItem,
    MistakeEntryOut,
    RecommendationItemOut,
    WeakKnowledgePointOut,
)
from app.services.audit_service import AuditService
from app.services.mistake_service import MistakeBookService

router = APIRouter(prefix="/api/v1/mistakes", tags=["mistake"])

UserDep = Annotated[User, Depends(get_current_user)]


def _entry_out(entry: MistakeBookEntry, exercise: Exercise) -> dict:
    """错题条目出参；嵌套的习题走学生视图（不含 answer / explanation）。"""
    return MistakeEntryOut(
        id=entry.id,
        exercise_id=entry.exercise_id,
        wrong_count=entry.wrong_count,
        consecutive_correct=entry.consecutive_correct,
        last_wrong_answer=entry.last_wrong_answer,
        last_wrong_at=entry.last_wrong_at,
        mastered=bool(entry.mastered),
        mastered_at=entry.mastered_at,
        exercise=ExerciseListItem.model_validate(exercise),
    ).model_dump()


@router.get("", response_model=ApiResponse[Any])
async def list_mistakes(
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
    mastered: bool | None = None,
):
    """`?mastered=` 三态：不传全返回、`true` 只已掌握、`false` 只未掌握。"""
    pairs = await MistakeBookService(session).list_entries(user.id, mastered=mastered)
    return ok([_entry_out(entry, exercise) for entry, exercise in pairs], request_id=rid)


@router.get("/profile", response_model=ApiResponse[Any])
async def get_profile(session: SessionDep, rid: CurrentRidDep, user: UserDep):
    """薄弱知识点画像（spec §8.5）：按 tag 聚合 wrong_count，排除已掌握，降序。"""
    rows = await MistakeBookService(session).profile(user.id)
    return ok(
        [WeakKnowledgePointOut(**row).model_dump() for row in rows],
        request_id=rid,
    )


@router.get("/recommendations", response_model=ApiResponse[Any])
async def get_recommendations(
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
):
    """定向推荐：top-3 薄弱 tag → 难度升序 → 不足时随机补足并标 `filled_by=random`。"""
    result = await MistakeBookService(session).recommendations(user.id, limit=limit)
    return ok(
        {
            "items": [
                RecommendationItemOut(
                    exercise=ExerciseListItem.model_validate(item["exercise"]),
                    filled_by=item["filled_by"],
                ).model_dump()
                for item in result["items"]
            ],
            "weak_tags": result["weak_tags"],
        },
        request_id=rid,
    )


@router.delete("/{entry_id}/mastered", response_model=ApiResponse[Any])
async def reset_mastered(
    entry_id: str, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    """手动重置掌握度（裁定 2）：开启新一轮练习周期，返回重置后的条目。

    `wrong_count` 与 `last_wrong_*` 是历史，保留；`consecutive_correct` 是状态机
    状态而非历史，清零 —— 否则重置后答对一次即重新掌握，按钮形同虚设。
    """
    svc = MistakeBookService(session)
    entry = await svc.reset_mastered(user.id, entry_id)
    exercise = await svc.published_exercise(entry.exercise_id)
    if exercise is None:
        # 习题已下架或被删走（无 FK 现状下的脏数据）：条目出不了完整视图，
        # 与 `list_entries` 丢弃无主条目同口径 —— 不返回半截数据，也不泄未发布题干
        raise ApiError(4040, "错题条目不存在")
    await AuditService(session).record(
        "mistake_reset_mastered",
        user_id=user.id,
        target_type="mistake_book_entry",
        target_id=entry.id,
        detail={"exercise_id": entry.exercise_id, "wrong_count": entry.wrong_count},
        request_id=rid,
    )
    await session.commit()
    return ok(_entry_out(entry, exercise), request_id=rid)
