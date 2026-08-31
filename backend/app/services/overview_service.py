"""仪表盘聚合（spec §6.2 admin 行，P2 遗留 7.3，P6 Task 6）。

裁定 3（2026-08-31）：**最小集** —— 演示规模下用单事务逐表 `count` 聚合；
字段面回写 spec 时标注「最小集，实际响应为超集」。embedder 快照与 /health 同源。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth.user import ACTIVE, ADMIN
from app.domain.exercise.judging import STATUS_DRAFT, STATUS_PUBLISHED
from app.infrastructure.persistence.models import (
    AuditLog,
    CodeAnalysis,
    CodeRun,
    CodeSession,
    Conversation,
    Document,
    Exercise,
    KnowledgeBase,
    Message,
    MistakeBookEntry,
    Submission,
    User,
)
from app.infrastructure.registry import get_or_create_singleton
from app.infrastructure.runtime import get_embedder_runtime


async def _count(session: AsyncSession, model) -> int:
    return (
        await session.execute(select(func.count()).select_from(model))
    ).scalar_one()


class OverviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview(self) -> dict:
        users = {
            "total": await _count(self._session, User),
            "active": (
                await self._session.execute(
                    select(func.count()).select_from(User).where(User.status == ACTIVE)
                )
            ).scalar_one(),
            "admin": (
                await self._session.execute(
                    select(func.count()).select_from(User).where(User.role == ADMIN)
                )
            ).scalar_one(),
        }
        cfg = await get_or_create_singleton(self._session)
        return {
            "users": users,
            "conversations": await _count(self._session, Conversation),
            "messages": await _count(self._session, Message),
            "knowledge_bases": await _count(self._session, KnowledgeBase),
            "documents": await _count(self._session, Document),
            "code_sessions": await _count(self._session, CodeSession),
            "code_analyses": await _count(self._session, CodeAnalysis),
            "code_runs": await _count(self._session, CodeRun),
            "exercises": {
                "published": (
                    await self._session.execute(
                        select(func.count())
                        .select_from(Exercise)
                        .where(Exercise.status == STATUS_PUBLISHED)
                    )
                ).scalar_one(),
                "draft": (
                    await self._session.execute(
                        select(func.count())
                        .select_from(Exercise)
                        .where(Exercise.status == STATUS_DRAFT)
                    )
                ).scalar_one(),
            },
            "submissions": await _count(self._session, Submission),
            "mistake_entries": {
                "total": await _count(self._session, MistakeBookEntry),
                "unmastered": (
                    await self._session.execute(
                        select(func.count())
                        .select_from(MistakeBookEntry)
                        .where(MistakeBookEntry.mastered.is_(False))
                    )
                ).scalar_one(),
            },
            "audit_logs": await _count(self._session, AuditLog),
            "model_config": {
                "provider": cfg.provider,
                "model": cfg.model,
                "anti_plagiarism_mode": cfg.anti_plagiarism_mode,
                "revision": cfg.revision,
            },
            "embedder": get_embedder_runtime().snapshot(),
        }
