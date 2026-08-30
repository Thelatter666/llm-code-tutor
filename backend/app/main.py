from fastapi import APIRouter, Depends, FastAPI

from app.core.deps import CurrentRidDep, require_admin
from app.core.errors import install_exception_handlers
from app.core.responses import install_request_id, ok
from app.routers import auth as auth_router

app = FastAPI(title="LLM Programming Tutor")

install_request_id(app)
install_exception_handlers(app)

app.include_router(auth_router.router)

_admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@_admin.get("/ping")
async def admin_ping(rid: CurrentRidDep, user=Depends(require_admin)):
    """P0 占位：用于验证角色拦截。P6 将被真实管理端点取代。"""
    return ok({"role": user.role}, request_id=rid)


app.include_router(_admin)


@app.get("/health")
async def health(rid: CurrentRidDep):
    return ok({"status": "ok"}, request_id=rid)
