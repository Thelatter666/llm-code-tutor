"""全量表定义（spec §5 共 14 张）。

P0 落 User / ModelConfig / AuditLog；P1 追加 KnowledgeBase / Document / Chunk；
P2 追加 Conversation / Message；P3 追加 CodeAnalysis；
P4 追加 CodeSession / CodeRun；P5 追加 Exercise / Submission / MistakeBookEntry。
建表走 create_all，不做迁移（ADR-0006）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.chat.policy import DEFAULT_CONVERSATION_TITLE
from app.domain.exercise.judging import STATUS_DRAFT
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


class Conversation(Base):
    """会话：一次完整的答疑对话容器，包含多条消息（CONTEXT.md）。

    与「对话（Chat）」区分：Chat 指功能，Conversation 指数据实体。
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default=DEFAULT_CONVERSATION_TITLE)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    # 会话列表按最近活动排序，onupdate 保证每次新消息都推进它
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, onupdate=_now, index=True
    )


class Message(Base):
    """消息：会话中的单条发言（spec §5）。

    `citations` / `token_usage` / `truncated` / `anti_plagiarism_mode` /
    `blocked_by_policy` 是 P2 的四组关键落库字段，分别对应 spec §7.2 步骤 6、
    §6.1 `done` 事件的用量、§8.1 的中断标记与 §7.4 的拦截率度量。
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    # spec §7.2 步骤 6：命中的 chunk_id 写入 citations，前端点击可溯源
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 流末 Usage 元素；estimated=true 表示 Mock 估算（估算用量 EstimatedUsage）
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    # spec §8.1：流被中断时已生成内容仍落库并置 true
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    # 当次生效的防抄袭档位；豁免意图为 null（ADR-0005）
    anti_plagiarism_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    # 底线拦截：本次请求是否触发防抄袭底线（spec §7.4）
    blocked_by_policy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class CodeAnalysis(Base):
    """代码分析：一次代码解析的完整结果，含静态报告与 AI 报告（CONTEXT.md）。

    spec §5：user_id / language / source_hash / static_report(JSON) /
    ai_report(JSON?) / created_at。**CodeSession 与 CodeRun 归 P4，本批不建。**

    `source_hash = sha256(language + "\\x00" + source)`，命中即复用不重算
    （spec §8.4）；唯一约束 `(user_id, language, source_hash)` 把「不重复算」
    落到库层 —— 复用按 user 隔离，不跨账号共享。
    """

    __tablename__ = "code_analyses"
    __table_args__ = (UniqueConstraint("user_id", "language", "source_hash"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    language: Mapped[str] = mapped_column(String)
    source_hash: Mapped[str] = mapped_column(String, index=True)
    static_report: Mapped[dict] = mapped_column(JSON)
    # AI 报告可为 null（CONTEXT.md）；Mock 模式下由静态报告模板化生成（spec §8.4）
    ai_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class CodeSession(Base):
    """代码会话：在线编辑器中的一份代码草稿（CONTEXT.md）。

    不使用「代码片段」「草稿」称之。与 CodeRun 的关系是「草稿 → 多次运行」，
    但 spec §5 未要求外键，运行记录独立留存 —— 删草稿不该连带删掉运行历史。
    """

    __tablename__ = "code_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    language: Mapped[str] = mapped_column(String)
    source_code: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String, default="未命名草稿")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    # 编辑器每次保存都推进它，供列表按最近编辑排序
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, onupdate=_now, index=True
    )


class CodeRun(Base):
    """代码运行：一次代码执行的完整记录（spec §5 / §8.3）。

    与「调试」区分：本系统只提供运行与输出观测，不提供断点调试。

    `limit_detail` 是四层资源限制的**实测留痕**，不是配置回显：每层记录
    `applied`（该层是否真的设上了）、`triggered`（本次是否被它杀掉）与实测值
    （峰值 RSS、实际墙钟、截断与否）。平台不支持某层时 `applied=false` 并附
    `error` —— 降级必须可见（spec §9）。
    """

    __tablename__ = "code_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    language: Mapped[str] = mapped_column(String)
    source_code: Mapped[str] = mapped_column(Text)
    stdin: Mapped[str] = mapped_column(Text, default="")
    # spec §5 的封闭取值：accepted | runtime_error | timeout | memory_exceeded | blocked
    status: Mapped[str] = mapped_column(String)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    # blocked 时代码根本没跑，exit_code 为 None
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    limit_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class Exercise(Base):
    """习题：题库中的一道题目，含题干、答案与知识点标签（CONTEXT.md）。

    不使用「题目」「试题」称之。answer / test_cases 的各题型 JSON 形态契约
    见 P5 计划「契约定稿 7」（spec §5 只写了 JSON，P5 回写时补形态）。

    `answer` 对 choice/multi 存选项键（"B" / ["A","C"]），学生提交与判分共用
    同一形态；`options` 用键值对象（{"A": 文本}）而非数组，判分比对键名即可，
    无需下标换算。
    """

    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String)  # choice | multi | blank | short | coding
    stem: Mapped[str] = mapped_column(Text)
    # choice / multi 需要，其余题型为 null
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[dict | list | str] = mapped_column(JSON)
    # coding 专用：{"language": "python", "cases": [{"stdin", "expected_stdout"}]}
    test_cases: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    knowledge_tags: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[int] = mapped_column(Integer)  # 1-5，入参校验拒绝越界
    source: Mapped[str] = mapped_column(String)  # seed | admin | ai
    # 学生端列表/详情只暴露 published（spec §6.2）
    status: Mapped[str] = mapped_column(String, default=STATUS_DRAFT, index=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class Submission(Base):
    """提交：学生对某道习题的一次作答记录（CONTEXT.md）。

    与「答案」区分：答案（Exercise.answer）是一个字段，提交是实体。
    `is_correct` 按 spec §5 为 bool?（可空列）；判分四路总会落定它，
    可空性保留给 spec 原文。`attempt_no` 从 1 递增（同一学生同一习题）。
    """

    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    exercise_id: Mapped[str] = mapped_column(String, index=True)
    answer: Mapped[dict | list | str] = mapped_column(JSON)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[int] = mapped_column(Integer)  # 0-100
    judge_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class MistakeBookEntry(Base):
    """错题条目：学生在某道习题上的错误累积状态，按 (user, exercise) 唯一。

    不使用「错题」作为实体名；「错题本」是功能名（CONTEXT.md）。掌握度
    Mastery 的演进规则在 `domain/exercise/mastery.py`（spec §8.5），本表只
    存状态：错误时硬回滚（mastered=false、mastered_at=null）是硬要求。
    """

    __tablename__ = "mistake_book_entries"
    __table_args__ = (UniqueConstraint("user_id", "exercise_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    exercise_id: Mapped[str] = mapped_column(String, index=True)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0)
    last_wrong_answer: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    last_wrong_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    mastered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
