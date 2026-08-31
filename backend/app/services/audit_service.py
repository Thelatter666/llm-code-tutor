from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.models import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        action: str,
        *,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict | None = None,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=ip,
            request_id=request_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_logs(
        self,
        *,
        action: str | None = None,
        user_id: str | None = None,
        start=None,
        end=None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:
        """审计日志查询（spec §6.2 admin 行，P6 Task 5）。

        按 `created_at` 倒序；action / user_id 精确匹配（两列均有索引）；
        start / end 为日期时间闭合区间。返回 `{items, total}` 分页。
        """
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if start is not None:
            stmt = stmt.where(AuditLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(AuditLog.created_at <= end)
        rows = list((await self._session.execute(stmt)).scalars().all())
        total = len(rows)
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], total
