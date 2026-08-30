/** 引用：模型回答所依据的切片来源，可点击溯源（spec §7.2 步骤 6）。 */
export interface Citation {
  chunk_id: string
  document_id: string
  doc_title: string
  kb_id: string
  snippet: string
  score: number
  /** 片段编号，与正文里的内联引用 [1][2] 对齐 */
  number: number
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ConversationOut {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface MessageOut {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: Citation[] | null
  token_usage: (TokenUsage & { estimated: boolean }) | null
  model: string | null
  provider: string | null
  truncated: boolean
  anti_plagiarism_mode: string | null
  blocked_by_policy: boolean
  created_at: string
}

/** spec §6.1 `done` 事件载荷。 */
export interface ChatDoneEvent {
  message_id: string
  token_usage: TokenUsage
  /** 估算用量 EstimatedUsage：Mock 提供方无真实计数 */
  usage_estimated: boolean
  model: string | null
  provider: string | null
  rag_hit: boolean
  degraded: boolean
  fallback_reason: string | null
}

export interface ChatErrorEvent {
  code: number
  message: string
}

export interface ChatStreamHandlers {
  onCitation: (citation: Citation) => void
  onToken: (delta: string) => void
  onDone: (done: ChatDoneEvent) => void
  onError: (error: ChatErrorEvent) => void
}
