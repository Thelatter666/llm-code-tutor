import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models import AuditLog
from app.services.audit_service import AuditService


@pytest.mark.asyncio
async def test_record_persists_audit_log(session):
    await AuditService(session).record(
        "login", user_id="u1", detail={"ok": True}, request_id="rid"
    )
    await session.commit()

    row = (await session.execute(select(AuditLog).where(AuditLog.request_id == "rid"))).scalar_one()
    assert row.action == "login"
    assert row.user_id == "u1"
    assert row.detail == {"ok": True}


@pytest.mark.asyncio
async def test_audit_log_survives_without_user(session):
    """审计日志不随用户删除：user_id 可空（spec §8.9）。"""
    await AuditService(session).record(
        "admin_user_delete", user_id=None, target_type="user", target_id="u9"
    )
    await session.commit()

    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.user_id is None
    assert row.target_id == "u9"
