"""P0 所需表定义（spec §5 共 14 张，其余在 P1–P5 追加）。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.db import UTCDateTime, Base

MODEL_CONFIG_SINGLETON_ID = "singleton"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="student")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=MODEL_CONFIG_SINGLETON_ID)
    provider: Mapped[str] = mapped_column(String, default="mock")
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String, default="mock-1")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    top_p: Mapped[float] = mapped_column(Float, default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    # H1：spec §8.7 embedding 配置变更依赖下列两列
    embedding_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    anti_plagiarism_mode: Mapped[str] = mapped_column(String, default="guided")
    # M1：None 表示「用按 embedding 模型的默认值」（spec §3.2 权衡 8）
    score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    # H2：onupdate 缺失会导致改配置后 updated_at 不变，registry 取到旧行
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
