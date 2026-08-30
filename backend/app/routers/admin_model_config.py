"""管理端模型配置：本批次只承载 embedding 切换的 409 流程（spec §8.7）。

`PUT /admin/model-config` 在 spec §6.2 的 admin 行，本批次只实现其中的
embedding 部分 —— §8.7 的 409 + 强制重建归 P1，需要一个可调用的入口才能验证。
其余配置项（LLM provider、防抄袭档位、top_k 等）由 P6 在本文件上补齐。
"""

from fastapi import APIRouter, Depends

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.infrastructure.runtime import refresh_embedder_config
from app.schemas.knowledge import EmbeddingConfigIn
from app.services.model_config_service import ModelConfigService
from app.services.rebuild_service import RebuildService

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
    """
    result = await ModelConfigService(session).update_embedding(
        provider=body.provider,
        model=body.model,
        confirm=body.confirm,
        user_id=user.id,
        request_id=rid,
    )
    await session.commit()

    # 配置变更后必须换掉运行时的 factory，否则新模型永远不生效
    await refresh_embedder_config(session)

    rebuilt: list[str] = []
    if body.confirm and result["knowledge_base_ids"]:
        for kb_id in result["knowledge_base_ids"]:
            await RebuildService(session).rebuild(kb_id, user_id=user.id, request_id=rid)
            rebuilt.append(kb_id)
        await session.commit()

    return ok({**result, "rebuilt": rebuilt}, request_id=rid)


@router.get("/model-config/embedding-consistency")
async def embedding_consistency(
    session: SessionDep, rid: CurrentRidDep, user: User = Depends(require_admin)
):
    """spec §8.7 步骤 4：比对配置里的模型与切片上记的模型，供启动/巡检告警。"""
    warnings = await ModelConfigService(session).check_embedding_consistency()
    return ok(warnings, request_id=rid)
