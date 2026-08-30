"""全量表定义（spec §5 共 14 张）。

P0 落 User / ModelConfig / AuditLog；P1 追加 KnowledgeBase / Document / Chunk。
建表走 create_all，不做迁移（ADR-0006）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.knowledge.status import DOC_PENDING, KB_READY
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


class KnowledgeBase(Base):
    """知识库：一组同源课程文档的集合，是检索的作用域单位（CONTEXT.md）。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # 课程代码：可空表示不限课程（spec §3.3：选课关系属边界外）
    course_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    embed_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # spec §6.2 要求「KB 未就绪 → 5032」，§8.7 要求重建期间 KB 置 reindexing；
    # 两者都需要 KB 级状态，故在 §5 的关键字段清单之外补此列
    status: Mapped[str] = mapped_column(String, default=KB_READY)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Document(Base):
    """文档：知识库中的一份原始文件（PDF/MD/TXT/DOCX）。"""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)  # pdf | md | txt | docx
    source_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default=DOC_PENDING, index=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # spec §8.2 进度可见：管理端轮询这两个字段展示索引进度
    chunk_indexed: Mapped[int] = mapped_column(Integer, default=0)
    chunk_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class Chunk(Base):
    """切片：文档经切分后产生的最小检索单位，带 vector_id 指向 Chroma。"""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String, index=True)
    kb_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer)
    # 列名保持 spec §5 的 meta；属性名加下划线以避开 DeclarativeBase 的保留名
    meta_: Mapped[dict | None] = mapped_column("meta", JSON, nullable=True)
    # §8.7 步骤 4：记录实际索引所用模型，供启动一致性校验
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
