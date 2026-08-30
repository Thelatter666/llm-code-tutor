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
