"""知识库与文档的状态常量（零 IO，供领域层与持久化层共用）。"""

# --- 文档状态（spec §5 Document.status） ---
DOC_PENDING = "pending"  # 已上传，等待索引
DOC_INDEXING = "indexing"  # 索引进行中
DOC_READY = "ready"  # 索引完成，可检索
DOC_FAILED = "failed"  # 解析或索引失败，error_msg 可见
DOC_REINDEXING = "reindexing"  # 重建向量中
DOC_STATUSES = (DOC_PENDING, DOC_INDEXING, DOC_READY, DOC_FAILED, DOC_REINDEXING)

# 终态：轮询进度时可据此停止
DOC_TERMINAL_STATUSES = (DOC_READY, DOC_FAILED)

# --- 知识库状态 ---
# spec §5 的关键字段清单未列 status，但 §6.2（未就绪 → 5032）与 §8.7（重建期间
# 置 reindexing）都要求 KB 级状态，故补此列。文档索引不改变 KB 状态 ——
# spec §3.2 权衡 16 明确「检索允许读到中间态」，只有全量重建才需要阻断检索。
KB_READY = "ready"
KB_REINDEXING = "reindexing"
KB_STATUSES = (KB_READY, KB_REINDEXING)

# --- 来源类型（spec §5 Document.source_type） ---
SOURCE_PDF = "pdf"
SOURCE_MD = "md"
SOURCE_TXT = "txt"
SOURCE_DOCX = "docx"
SOURCE_TYPES = (SOURCE_PDF, SOURCE_MD, SOURCE_TXT, SOURCE_DOCX)

# --- 审计动作（spec §8.6 与 CONTEXT.md「审计日志」） ---
ACTION_KB_CREATE = "admin_kb_create"
ACTION_KB_UPDATE = "admin_kb_update"
ACTION_KB_DELETE = "admin_kb_delete"
ACTION_KB_DOCUMENT_UPLOAD = "admin_kb_document_upload"
ACTION_KB_DOCUMENT_DELETE = "admin_kb_document_delete"
ACTION_KB_REINDEX = "admin_kb_reindex"
ACTION_KB_REBUILD = "admin_kb_rebuild"
ACTION_KB_GC = "admin_kb_gc_orphan_vectors"
