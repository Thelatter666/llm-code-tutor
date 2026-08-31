"""管理端用户 CRUD（spec §6.2 admin 行 / §8.9，P6 Task 1）。

写操作落 `admin_user_*` 命名族审计（照 `admin_kb_*` / `admin_exercise_*` 先例）。
软删除（`status:"disabled"` 停用）是日常路径，保留全部数据；硬删除级联见
`UserService.delete`（Task 2）。出参不含 `hashed_password`（裁定 4）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.admin import ROLE_PATTERN, STATUS_PATTERN, UserIn, UserOut, UserPatch
from app.services.user_service import UserService

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin·user"])

AdminDep = Annotated[User, Depends(require_admin)]


@router.get("")
async def list_users(
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
    q: str | None = None,
    role: Annotated[str | None, Query(pattern=ROLE_PATTERN)] = None,
    status: Annotated[str | None, Query(pattern=STATUS_PATTERN)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """`{items, total}`（spec §6.2 分页约定），按创建时间倒序。"""
    items, total = await UserService(session).list_all(
        q=q, role=role, status=status, page=page, page_size=page_size
    )
    return ok(
        {"items": [UserOut.model_validate(r).model_dump() for r in items], "total": total},
        request_id=rid,
    )


@router.post("")
async def create_user(
    body: UserIn, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """管理员新建用户；重复账号 4090（与注册同口径）。"""
    row = await UserService(session).create(
        username=body.username,
        email=body.email,
        password=body.password,
        role=body.role,
        status=body.status,
        admin_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(UserOut.model_validate(row).model_dump(), request_id=rid)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str, session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """硬删除 + 手工级联（spec §8.9）；级联计数进审计 detail。

    非日常路径 —— 日常停用走 PATCH `status:"disabled"`（保留全部数据）。
    """
    counts = await UserService(session).delete(
        user_id, admin_id=user.id, request_id=rid
    )
    await session.commit()
    return ok({"deleted": True, **counts}, request_id=rid)


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    body: UserPatch,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
):
    """全部字段可选更新；`status:"disabled"` 即软删除（spec §8.9 日常路径）。"""
    row = await UserService(session).update(
        user_id,
        fields=body.model_dump(exclude_unset=True),
        admin_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(UserOut.model_validate(row).model_dump(), request_id=rid)
