"""管理端统计端点。

spec §6.2 把 `GET /admin/anti-plagiarism/stats` 与 `GET /admin/overview` 一起
列在 admin 行；overview（仪表盘聚合）归 P6，本批只落地防抄袭统计。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.services.anti_plagiarism_stats import AntiPlagiarismStatsService

router = APIRouter(prefix="/api/v1/admin", tags=["admin·stats"])

AdminDep = Annotated[User, Depends(require_admin)]


@router.get("/anti-plagiarism/stats")
async def anti_plagiarism_stats(
    session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """spec §7.4：各档位下的「触发底线次数 / 总请求数」。

    **这是度量口径，不是检测能力** —— 分子来自确定性关键词规则，不代表抄袭检出数。
    """
    data = await AntiPlagiarismStatsService(session).stats()
    return ok(data, request_id=rid)
