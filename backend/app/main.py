import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.deps import CurrentRidDep, require_admin
from app.core.errors import ApiError, install_exception_handlers
from app.core.responses import install_request_id, ok
from app.infrastructure.persistence.db import SessionFactory, init_db
from app.infrastructure.runtime import get_embedder_runtime, refresh_embedder_config
from app.routers import admin_knowledge, admin_model_config, auth as auth_router, knowledge
from app.services.model_config_service import ModelConfigService

logger = logging.getLogger(__name__)

DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def warmup_embedder() -> None:
    """异步后台预热向量化器（用户拍板决策 1）。

    模型加载实测 13–20 秒，**不得**在启动路径上同步等待 —— 那样演示环境启动后会
    长时间无响应。这里由 lifespan 用 `create_task` 拉起，服务立刻对外可用；
    未就绪期间检索返回 5032（spec §9），/health 暴露就绪状态供前端提示。
    """
    try:
        await get_embedder_runtime().warmup()
        logger.info("向量化器预热完成：%s", get_embedder_runtime().snapshot())
    except Exception:  # noqa: BLE001 - 预热失败只告警，服务继续可用
        logger.exception("向量化器预热失败，知识库功能将降级")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 建表走 create_all，不做迁移（ADR-0006）
    await init_db()

    async with SessionFactory() as session:
        await refresh_embedder_config(session)
        # spec §8.7 步骤 4：启动时校验「配置与索引不一致」并告警
        for warning in await ModelConfigService(session).check_embedding_consistency():
            logger.warning(
                "知识库 %s 的索引模型与配置不一致：索引=%s 配置=%s，请执行重建",
                warning["kb_id"],
                warning["indexed_model"],
                warning["configured_model"],
            )

    asyncio.create_task(warmup_embedder())
    yield


app = FastAPI(title="LLM Programming Tutor", lifespan=lifespan)

install_request_id(app)
install_exception_handlers(app)

app.include_router(auth_router.router)
app.include_router(knowledge.router)
app.include_router(admin_knowledge.router)
app.include_router(admin_model_config.router)

_admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@_admin.get("/ping")
async def admin_ping(rid: CurrentRidDep, user=Depends(require_admin)):
    """P0 占位：用于验证角色拦截。P6 将被真实管理端点取代。"""
    return ok({"role": user.role}, request_id=rid)


app.include_router(_admin)


@app.get("/health")
async def health(rid: CurrentRidDep):
    """健康检查；`embedder.ready` 即模型就绪状态（前端可据此显示「模型加载中」）。"""
    return ok(
        {"status": "ok", "embedder": get_embedder_runtime().snapshot()},
        request_id=rid,
    )


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
