import type { Citation } from './chat'

export interface KnowledgeBaseOut {
  id: string
  name: string
  description: string | null
  course_code: string | null
  embed_provider: string | null
  embed_model: string | null
  status: 'ready' | 'reindexing'
}

export interface DocumentOut {
  id: string
  kb_id: string
  title: string
  source_type: 'pdf' | 'md' | 'txt' | 'docx'
  status: 'pending' | 'indexing' | 'ready' | 'failed' | 'reindexing'
  error_msg: string | null
  /** spec §8.2 进度可见：管理端轮询这两个字段展示索引进度 */
  chunk_indexed: number
  chunk_total: number
}

export interface ChunkOut {
  id: string
  document_id: string
  ordinal: number
  char_count: number
  content: string
  embed_model: string | null
}

export interface SearchOut {
  rag_hit: boolean
  degraded: boolean
  fallback_reason: string | null
  threshold: number
  embedder: string | null
  citations: Citation[]
}

export interface GcOut {
  scanned: number
  orphans: number
  deleted: number
}
