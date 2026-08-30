from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.deps import CurrentRidDep, require_admin
from app.core.errors import ApiError, install_exception_handlers
from app.core.responses import install_request_id, ok
from app.routers import auth as auth_router

DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

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


def install_spa_fallback(app: FastAPI, dist: Path = DIST_DIR) -> None:
    """挂载前端构建产物并提供 SPA fallback。

    dist 不存在时完全不挂载（开发模式走 Vite dev server）。
    必须在所有 API 路由注册之后调用，否则 catch-all 会吞掉 /api/*。
    """
    if not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def _spa(full_path: str):
        # 未注册的 /api/* 与 /health 会落到这里，返回业务错误码而非 index.html
        if full_path.startswith(("api/", "health")):
            raise ApiError(4040, "资源不存在")
        index = dist / "index.html"
        if not index.exists():
            raise ApiError(4040, "资源不存在")
        return FileResponse(index)


install_spa_fallback(app)
