"""admin 用户管理出入参（spec §6.2 admin 行 / §8.9，P6 Task 1）。

裁定 4（2026-08-31）：管理端出参含 email（管理员互见），`hashed_password` 永不出参。
裁定 1（2026-08-31，扩面）：PATCH 全字段可选、schema 外字段 422 显式拒绝；对自己
role/status 的变更由**服务层**拒绝 —— schema 层不知道「自己是谁」。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.auth.user import ROLES, STATUSES

ROLE_PATTERN = f"^({'|'.join(ROLES)})$"
STATUS_PATTERN = f"^({'|'.join(STATUSES)})$"
# 与 auth.register 的 email 校验同口径（schemas/auth.py::RegisterIn）
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserOut(BaseModel):
    """管理端用户出参（裁定 4）：含 email；不落 hashed_password。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None


class UserIn(BaseModel):
    """管理员新建用户入参；密码口径与注册一致（8–128 位）。"""

    username: str = Field(min_length=1, max_length=64)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="student", pattern=ROLE_PATTERN)
    status: str = Field(default="active", pattern=STATUS_PATTERN)


class UserPatch(BaseModel):
    """admin 更新入参：全部字段可选，**schema 外字段一律 422 显式拒绝**。

    `extra="forbid"` 照 P5 ExercisePatch 先例：静默忽略未知字段属「看起来成功、
    实际没生效」的静默型失败。传 password 即管理员重置密码。
    """

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(default=None, pattern=STATUS_PATTERN)
    role: str | None = Field(default=None, pattern=ROLE_PATTERN)
    email: str | None = Field(default=None, pattern=EMAIL_PATTERN)
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def _requires_something_to_change(self) -> "UserPatch":
        if (
            self.status is None
            and self.role is None
            and self.email is None
            and self.password is None
        ):
            raise ValueError("PATCH 至少需要一个待更新字段")
        return self
