"""管理端模型配置（spec §6.2 / §8.7 / §8.8 / §4.2 硬约束 4，P6 Task 3/4）。

- embedding 切换仍走 `/model-config/embedding` 的 409 + 强制重建流程（P1 三道闸），
  本批不动；
- 本批补齐 LLM 配置的 GET / PUT / test 三端点：PUT 保存即 `revision += 1`，
  运行时按下一次调用按 revision 重绑 —— 无需重启（裁定 2 字段面见 schemas/admin.py）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.crypto import decrypt_api_key, mask_api_key
from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.infrastructure.registry import get_or_create_singleton
from app.infrastructure.runtime import get_embedder_runtime, refresh_embedder_config
from app.schemas.admin import ModelConfigPut
from app.schemas.knowledge import EmbeddingConfigIn
from app.services.model_config_service import ModelConfigService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

AdminDep = Annotated[User, Depends(require_admin)]


def _model_config_out(cfg) -> dict:
    """LLM 配置出参：api_key 只出掩码（spec §8.8 / CONTEXT.md「API Key 掩码」）。

    明文只存在于加密列与运行时内存；读取接口一律掩码显示。
    """
    plain = decrypt_api_key(cfg.api_key_encrypted) if cfg.api_key_encrypted else None
    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "api_key": mask_api_key(plain),
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "max_tokens": cfg.max_tokens,
        "anti_plagiarism_mode": cfg.anti_plagiarism_mode,
        "score_threshold": cfg.score_threshold,
        "top_k": cfg.top_k,
        # embedding 配置只读回显；修改仍走 /model-config/embedding 409 流程
        "embedding_provider": cfg.embedding_provider,
        "embedding_model": cfg.embedding_model,
        "revision": cfg.revision,
        "updated_by": cfg.updated_by,
        "updated_at": cfg.updated_at,
    }


@router.get("/model-config")
async def get_model_config(session: SessionDep, rid: CurrentRidDep, user: AdminDep):
    """当前 LLM 配置（含掩码 api_key 与 revision，供管理页回显）。"""
    cfg = await get_or_create_singleton(session)
    return ok(_model_config_out(cfg), request_id=rid)


@router.put("/model-config")
async def put_model_config(
    body: ModelConfigPut,
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
):
    """LLM 配置全量更新（字段面与 api_key 语义见 schemas/admin.py::ModelConfigPut）。

    保存即 `revision += 1`，下一次调用即用新值（spec §4.2 硬约束 4，无需重启）。
    只改库不够 —— 服务侧在**下一次请求**经 `refresh_llm_config` 按 revision 重绑，
    本端点不主动刷新（避免与在途请求抢运行时）。
    """
    cfg = await ModelConfigService(session).update_llm_config(
        fields=body.model_dump(exclude_unset=True),
        user_id=user.id,
        request_id=rid,
    )
    await session.commit()
    return ok(_model_config_out(cfg), request_id=rid)


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
