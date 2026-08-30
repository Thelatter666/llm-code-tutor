"""管理端模型配置：本批次只承载 embedding 切换的 409 流程（spec §8.7）。

`PUT /admin/model-config` 在 spec §6.2 的 admin 行，本批次只实现其中的
embedding 部分 —— §8.7 的 409 + 强制重建归 P1，需要一个可调用的入口才能验证。
其余配置项（LLM provider、防抄袭档位、top_k 等）由 P6 在本文件上补齐。
"""

from fastapi import APIRouter, Depends

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.infrastructure.runtime import get_embedder_runtime, refresh_embedder_config
from app.schemas.knowledge import EmbeddingConfigIn
from app.services.model_config_service import ModelConfigService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.put("/model-config/embedding")
async def update_embedding(
    body: EmbeddingConfigIn,
    session: SessionDep,
    rid: CurrentRidDep,
    user: User = Depends(require_admin),
):
    """切换 embedding 配置。

    已有切片且未确认 → `409` + `need_rebuild: true`（spec §8.7 步骤 2），
    前端弹二次确认；确认后保存配置，并**同步触发全量重建**。

    重建与切换是同一个单元：任一知识库重建失败就回滚配置（见
    `ModelConfigService.switch_embedding_with_rebuild`）—— 否则查询会拿新模型的
    新维度向量去查空的 `course_chunks_d{新维度}` 集合，静默零命中。
    """
    try:
        result = await ModelConfigService(session).switch_embedding_with_rebuild(
            provider=body.provider,
            model=body.model,
            confirm=body.confirm,
            user_id=user.id,
            request_id=rid,
        )
        await session.commit()
    finally:
        # 成功与回滚都必须让运行时与库内配置一致：重建失败时上一步已把配置改回旧值，
        # 不刷新的话运行时还停在新模型上，等于回滚只做了一半
        await refresh_embedder_config(session)

    return ok(result, request_id=rid)


@router.get("/model-config/embedding-consistency")
async def embedding_consistency(
    session: SessionDep, rid: CurrentRidDep, user: User = Depends(require_admin)
):
    """spec §8.7 步骤 4：比对配置里的模型与切片上记的模型，供启动/巡检告警。"""
    current = get_embedder_runtime().current
    warnings = await ModelConfigService(session).check_embedding_consistency(
        current.model if current is not None else None
    )
    return ok(warnings, request_id=rid)
