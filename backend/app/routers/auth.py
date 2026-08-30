from fastapi import APIRouter, Depends, Request

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.core.security import create_access_token, decode_token
from app.infrastructure.persistence.models import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, UserOut
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register")
async def register(body: RegisterIn, request: Request, session: SessionDep, rid: CurrentRidDep):
    user = await AuthService(session).register(body.username, body.email, body.password)
    await AuditService(session).record(
        "register",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=_ip(request),
        request_id=rid,
    )
    await session.commit()
    return ok(UserOut.model_validate(user).model_dump(), request_id=rid)


@router.post("/login")
async def login(body: LoginIn, request: Request, session: SessionDep, rid: CurrentRidDep):
    user, access, refresh = await AuthService(session).login(body.username, body.password)
    await AuditService(session).record(
        "login", user_id=user.id, ip=_ip(request), request_id=rid
    )
    await session.commit()
    return ok({"access_token": access, "refresh_token": refresh}, request_id=rid)


@router.post("/refresh")
async def refresh(body: RefreshIn, session: SessionDep, rid: CurrentRidDep):
    payload = decode_token(body.refresh_token, expect="refresh")
    user = await AuthService(session).get_by_id(payload["sub"])
    return ok(
        {
            "access_token": create_access_token(user.id, user.role),
            "refresh_token": body.refresh_token,
        },
        request_id=rid,
    )


@router.get("/me")
async def me(rid: CurrentRidDep, user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump(), request_id=rid)


@router.post("/logout")
async def logout(
    session: SessionDep, rid: CurrentRidDep, user: User = Depends(get_current_user)
):
    await AuditService(session).record("logout", user_id=user.id, request_id=rid)
    await session.commit()
    return ok({"logged_out": True}, request_id=rid)
