"""管理端统计与查询端点（spec §6.2 admin 行，P6 Task 5/6）。

- `GET /admin/anti-plagiarism/stats`（P2 交付）：各档位拦截率，口径只数 role=user；
- `GET /admin/logs`（Task 5）：审计日志查询；
- `GET /admin/overview`（Task 6）：仪表盘聚合。
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, require_admin
from app.core.errors import ApiError
from app.core.responses import ok
from app.infrastructure.persistence.models import AuditLog, User
from app.schemas.common import ApiResponse
from app.services.anti_plagiarism_stats import AntiPlagiarismStatsService
from app.services.audit_service import AuditService
from app.services.overview_service import OverviewService

router = APIRouter(prefix="/api/v1/admin", tags=["admin·stats"])

AdminDep = Annotated[User, Depends(require_admin)]


def _parse_dt_bound(value: str, *, is_end: bool) -> datetime:
    """解析 start/end 参数：ISO 日期或日期时间，非法一律 422。

    纯日期按当日闭合区间处理：start → 当日 00:00:00，end → 当日 23:59:59。
    """
    raw = value.strip()
    try:
        if len(raw) == 10:
            raw = f"{raw}T{'23:59:59' if is_end else '00:00:00'}"
        dt = datetime.fromisoformat(raw)
        # 无时区输入按 UTC 解释（UTCDateTime 落库前强制转 naive UTC，
        # 混入本地时区解释会让区间偏移）
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError as exc:
        raise ApiError(4220, "start/end 必须是 ISO 8601 日期或日期时间") from exc


def _log_out(row: AuditLog) -> dict:
    """审计行全字段回显（管理页就是给管理员看的）。"""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": row.detail,
        "ip": row.ip,
        "request_id": row.request_id,
        "created_at": row.created_at,
    }


@router.get("/logs", response_model=ApiResponse[Any])
async def list_logs(
    session: SessionDep,
    rid: CurrentRidDep,
    user: AdminDep,
    action: str | None = None,
    user_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """审计日志查询（spec §6.2）：action/user_id 精确 + start/end 时间区间 + 分页。

    **说明（裁定 8）**：审计日志记录管理操作与关键行为留痕，仅可查询、
    不可修改或删除。
    """
    items, total = await AuditService(session).list_logs(
        action=action,
        user_id=user_id,
        start=_parse_dt_bound(start, is_end=False) if start else None,
        end=_parse_dt_bound(end, is_end=True) if end else None,
        page=page,
        page_size=page_size,
    )
    return ok(
        {"items": [_log_out(r) for r in items], "total": total}, request_id=rid
    )


@router.get("/overview", response_model=ApiResponse[Any])
async def overview(session: SessionDep, rid: CurrentRidDep, user: AdminDep):
    """仪表盘聚合（裁定 3：最小集，实际响应为超集）。"""
    data = await OverviewService(session).overview()
    return ok(data, request_id=rid)


@router.get("/anti-plagiarism/stats", response_model=ApiResponse[Any])
async def anti_plagiarism_stats(
    session: SessionDep, rid: CurrentRidDep, user: AdminDep
):
    """spec §7.4：各档位下的「触发底线次数 / 总请求数」。

    **这是度量口径，不是检测能力** —— 分子来自确定性关键词规则，不代表抄袭检出数。
    """
    data = await AntiPlagiarismStatsService(session).stats()
    return ok(data, request_id=rid)
