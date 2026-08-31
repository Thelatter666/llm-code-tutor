"""admin 用户管理出入参（spec §6.2 admin 行 / §8.9，P6 Task 1）。

裁定 4（2026-08-31）：管理端出参含 email（管理员互见），`hashed_password` 永不出参。
裁定 1（2026-08-31，扩面）：PATCH 全字段可选、schema 外字段 422 显式拒绝；对自己
role/status 的变更由**服务层**拒绝 —— schema 层不知道「自己是谁」。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.auth.user import ROLES, STATUSES
from app.domain.chat.policy import ANTI_PLAGIARISM_MODES

ROLE_PATTERN = f"^({'|'.join(ROLES)})$"
STATUS_PATTERN = f"^({'|'.join(STATUSES)})$"
# 与 auth.register 的 email 校验同口径（schemas/auth.py::RegisterIn）
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# LLM provider 取值（spec §5 ModelConfig.provider：mock / openai_compat；
# 与 infrastructure/registry.py 的 LLM_PROVIDER_* 常量对齐，schema 层不依赖基础设施）
PROVIDER_PATTERN = r"^(mock|openai_compat)$"
ANTI_PLAGIARISM_PATTERN = f"^({'|'.join(ANTI_PLAGIARISM_MODES)})$"


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


class ModelConfigPut(BaseModel):
    """LLM 配置写入入参（spec §6.2 / §4.2 硬约束 4，P6 Task 3）。

    裁定 2（2026-08-31）：
    - `api_key` 缺省/null = **不变更**（前端掩码回显后常态回传 null，绝不能把已有
      密钥清掉）；空串 = 422 显式拒绝；
    - 保存时机校验「openai_compat 且库中无 key」在服务层 4220（需读库，schema 层
      做不了）；
    - embedding_provider / embedding_model **不在字段面**（仍走 /model-config/embedding
      409 重建流程）；mock_token_delay_ms 不入 PUT（env Settings，裁定 2 方案 A）。

    保存即 `revision += 1`（ProviderRegistry 缓存失效键），无需重启生效。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, pattern=PROVIDER_PATTERN)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    anti_plagiarism_mode: str | None = Field(
        default=None, pattern=ANTI_PLAGIARISM_PATTERN
    )
    # None = 恢复「按 embedding 模型用默认值」语义（models.py:60 M1 约定）
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def _reject_empty_api_key(self) -> "ModelConfigPut":
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("api_key 不能为空字符串；清除密钥请将 provider 切回 mock")
        return self
