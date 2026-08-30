from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    # 课程代码：可空表示不限课程（CONTEXT.md「课程代码」）
    course_code: str | None = None


class KnowledgeBasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    course_code: str | None = None


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    course_code: str | None = None
    embed_provider: str | None = None
    embed_model: str | None = None
    status: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kb_id: str
    title: str
    source_type: str
    status: str
    error_msg: str | None = None
    chunk_indexed: int
    chunk_total: int


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    ordinal: int
    char_count: int
    content: str
    embed_model: str | None = None


class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    doc_title: str
    kb_id: str
    snippet: str
    score: float
    number: int


class SearchOut(BaseModel):
    rag_hit: bool
    degraded: bool
    fallback_reason: str | None = None
    threshold: float
    embedder: str | None = None
    citations: list[CitationOut]


class RebuildOut(BaseModel):
    kb_id: str
    status: str


class GcOut(BaseModel):
    scanned: int
    orphans: int
    deleted: int


class EmbeddingConfigIn(BaseModel):
    provider: str
    model: str
    # spec §8.7 步骤 3：前端二次确认后回传 true
    confirm: bool = False
