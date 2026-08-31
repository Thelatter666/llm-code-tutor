"""用户管理用例（spec §6.2 admin 行 / §8.9，P6 Task 1/2）。

裁定 1（2026-08-31，扩面）：管理员禁自删、禁对自己的 role/status 变更 ——
自降权 student、自停用 disabled 与自删同样会把系统锁死（演示系统无 CLI 建号
通道，最后一个可用管理员失效即不可恢复）。删/停/降权**其他** admin 时按
「操作后剩余 ≥1 名 role=admin 且 status=active」校验，否则 4220 —— 该守卫在
当前规则下属于保险带（执行者本人必是 active admin，且自操作已被禁），
但它是「最后一道防线」而非死代码：库层被手动改坏或规则演变时它兜底。
email/password 自改允许。

软删除（status=disabled）是日常路径，**保留全部数据**；停用后的 4030 由
`deps.get_current_user` 既有分支承担，本服务不重复拦截。
"""

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import hash_password
from app.domain.auth.user import ACTIVE, ADMIN
from app.infrastructure.persistence.models import (
    CodeAnalysis,
    CodeRun,
    CodeSession,
    Conversation,
    Message,
    MistakeBookEntry,
    Submission,
    User,
)
from app.services.audit_service import AuditService


class UserService:
    def __init__(self, session: AsyncSession):
        self._session = session

    # ------------------------------------------------------------ 查询

    async def get_any(self, user_id: str) -> User:
        row = await self._session.get(User, user_id)
        if row is None:
            raise ApiError(4040, "用户不存在")
        return row

    async def list_all(
        self,
        *,
        q: str | None = None,
        role: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[User], int]:
        """管理端列表（spec §6.2 分页约定 `{items, total}`），按创建时间倒序。

        `q` 对 username / email 模糊匹配；role / status 精确匹配。
        """
        stmt = select(User).order_by(User.created_at.desc(), User.id)
        if q:
            stmt = stmt.where(User.username.contains(q) | User.email.contains(q))
        if role:
            stmt = stmt.where(User.role == role)
        if status:
            stmt = stmt.where(User.status == status)
        rows = list((await self._session.execute(stmt)).scalars().all())
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    # ------------------------------------------------------------ 创建 / 更新

    async def create(
        self,
        *,
        username: str,
        email: str,
        password: str,
        role: str = "student",
        status: str = "active",
        admin_id: str,
        request_id: str,
    ) -> User:
        await self._ensure_unique(username=username, email=email)
        # bcrypt 约 100ms/次，属同步阻塞调用，须卸载到线程池（照 auth_service 先例）
        hashed = await run_in_threadpool(hash_password, password)
        row = User(
            username=username, email=email, hashed_password=hashed, role=role, status=status
        )
        self._session.add(row)
        await self._session.flush()
        await AuditService(self._session).record(
            "admin_user_create",
            user_id=admin_id,
            target_type="user",
            target_id=row.id,
            # 密码明文与哈希都不进审计
            detail={"username": row.username, "role": row.role, "status": row.status},
            request_id=request_id,
        )
        return row

    async def update(
        self, user_id: str, *, fields: dict, admin_id: str, request_id: str
    ) -> User:
        """按字段更新（含 status 停用/启用 —— 软删除路径）。

        裁定 1 扩面：对自己的 role/status 变更一律 4220；对其他 admin 的
        停用/降权走「末位 active admin」守卫。密码重置走重哈希。
        """
        row = await self.get_any(user_id)
        if not fields:
            raise ApiError(4220, "PATCH 至少需要一个待更新字段")

        if user_id == admin_id and ("role" in fields or "status" in fields):
            raise ApiError(4220, "不能变更自己的角色或状态")

        new_role = fields.get("role", row.role)
        new_status = fields.get("status", row.status)
        if (
            row.role == ADMIN
            and user_id != admin_id
            and (new_role != ADMIN or new_status != ACTIVE)
        ):
            await self._ensure_last_admin(exclude_user_id=user_id)

        if "email" in fields and fields["email"] != row.email:
            await self._ensure_unique(
                username=row.username, email=fields["email"], exclude_user_id=user_id
            )

        if "password" in fields:
            # 先 pop 再写 hashed_password：dict 字面量的 **fields 展开发生在
            # 求值 password 之前，顺序写反会让 password 残留进落库字段
            plain = fields.pop("password")
            fields["hashed_password"] = await run_in_threadpool(hash_password, plain)

        for key, value in fields.items():
            setattr(row, key, value)
        await self._session.flush()
        await AuditService(self._session).record(
            "admin_user_update",
            user_id=admin_id,
            target_type="user",
            target_id=row.id,
            # 只记改了哪些字段与结果状态；密码与 email 的值不进审计
            detail={
                "fields": sorted(fields),
                "username": row.username,
                "role": row.role,
                "status": row.status,
            },
            request_id=request_id,
        )
        return row

    # ------------------------------------------------------------ 硬删除（Task 2）

    async def delete(self, user_id: str, *, admin_id: str, request_id: str) -> dict:
        """硬删除 + 手工级联（spec §8.9；无 ForeignKey，级联靠服务层序列）。

        **级联清单（按删除顺序）**：
        1. 会话（Conversation）→ 先删其消息（Message，按会话 id 定位）
        2. 提交（Submission）
        3. 错题条目（MistakeBookEntry）
        4. 代码会话（CodeSession）
        5. 代码分析（CodeAnalysis）
        6. 代码运行（CodeRun）

        **不级联的两项例外（裁定 9 / spec §8.9）**：
        - `AuditLog` 一律保留 —— 审计的可追溯性优先于数据清理，硬删除本身也写一条
          `admin_user_delete` 审计（含级联计数，照 admin_exercise_delete 先例）。
        - `KnowledgeBase.owner_id` 悬空 —— 知识库是共享资产，不随建库管理员删除；
          知识库展示必须容忍 owner 缺失（不得 5000 或消失）。

        **级联清单新增表时**：必须同步更新本 docstring 与 `admin_user_delete`
        审计的 detail 计数键 —— 无 FK 架构下漏删即孤儿数据。
        """
        row = await self.get_any(user_id)
        if user_id == admin_id:
            raise ApiError(4220, "不能删除自己")
        if row.role == ADMIN:
            # 裁定 1：末位 active admin 守卫（防御性保险带，见类 docstring）
            await self._ensure_last_admin(exclude_user_id=user_id)

        conversation_ids = list(
            (
                await self._session.execute(
                    select(Conversation.id).where(Conversation.user_id == user_id)
                )
            ).scalars().all()
        )
        messages_deleted = 0
        if conversation_ids:
            messages_deleted = (
                await self._session.execute(
                    delete(Message).where(Message.conversation_id.in_(conversation_ids))
                )
            ).rowcount
            await self._session.execute(
                delete(Conversation).where(Conversation.id.in_(conversation_ids))
            )

        counts = {
            "conversations_deleted": len(conversation_ids),
            "messages_deleted": messages_deleted,
            "submissions_deleted": (
                await self._session.execute(
                    delete(Submission).where(Submission.user_id == user_id)
                )
            ).rowcount,
            "mistake_entries_deleted": (
                await self._session.execute(
                    delete(MistakeBookEntry).where(MistakeBookEntry.user_id == user_id)
                )
            ).rowcount,
            "code_sessions_deleted": (
                await self._session.execute(
                    delete(CodeSession).where(CodeSession.user_id == user_id)
                )
            ).rowcount,
            "code_analyses_deleted": (
                await self._session.execute(
                    delete(CodeAnalysis).where(CodeAnalysis.user_id == user_id)
                )
            ).rowcount,
            "code_runs_deleted": (
                await self._session.execute(
                    delete(CodeRun).where(CodeRun.user_id == user_id)
                )
            ).rowcount,
        }
        await self._session.delete(row)
        await self._session.flush()
        await AuditService(self._session).record(
            "admin_user_delete",
            user_id=admin_id,
            target_type="user",
            target_id=user_id,
            detail={"username": row.username, **counts},
            request_id=request_id,
        )
        return counts

    # ------------------------------------------------------------ 内部

    async def _ensure_unique(
        self, *, username: str, email: str, exclude_user_id: str | None = None
    ) -> None:
        stmt = select(User).where((User.username == username) | (User.email == email))
        if exclude_user_id:
            stmt = stmt.where(User.id != exclude_user_id)
        exists = (await self._session.execute(stmt)).scalar_one_or_none()
        if exists is not None:
            raise ApiError(4090, "用户名或邮箱已存在")

    async def _ensure_last_admin(self, *, exclude_user_id: str) -> None:
        """裁定 1：操作后必须剩余 ≥1 名 role=admin 且 status=active 的用户。"""
        remaining = (
            await self._session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == ADMIN,
                    User.status == ACTIVE,
                    User.id != exclude_user_id,
                )
            )
        ).scalar_one()
        if remaining == 0:
            raise ApiError(4220, "必须保留至少一名启用的管理员")
