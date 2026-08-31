/**
 * 管理后台出入参类型（对齐后端 `app/schemas/admin.py` 与各 admin 路由，P6）。
 *
 * 术语：实体是「习题」「用户」「审计日志」；文案不用「题目/试题」。
 * 裁定 4：管理端用户出参含 email（管理员互见）。
 */

import type { ExerciseType } from './exercise'

export interface PageResult<T> {
  items: T[]
  total: number
}

// ---------------------------------------------------------------- 用户

export interface AdminUserOut {
  id: string
  username: string
  email: string
  role: 'student' | 'admin'
  status: 'active' | 'disabled'
  created_at: string
  last_login_at: string | null
}

export interface AdminUserIn {
  username: string
  email: string
  password: string
  role?: 'student' | 'admin'
  status?: 'active' | 'disabled'
}

export interface AdminUserPatch {
  status?: 'active' | 'disabled'
  role?: 'student' | 'admin'
  email?: string
  password?: string
}

// ---------------------------------------------------------------- 模型配置

export type LlmProvider = 'mock' | 'openai_compat'
export type AntiPlagiarismMode = 'strict' | 'guided' | 'loose'

export interface ModelConfigOut {
  provider: LlmProvider
  model: string
  base_url: string | null
  /** 掩码形态（sk-****abcd）；明文只存在于后端加密列与运行时内存。 */
  api_key: string
  temperature: number
  top_p: number
  max_tokens: number
  anti_plagiarism_mode: AntiPlagiarismMode
  score_threshold: number | null
  top_k: number
  embedding_provider: string | null
  embedding_model: string | null
  revision: number
  updated_by: string | null
  updated_at: string
}

/** PUT /admin/model-config：全可选；api_key 缺省/null = 不变更（裁定 2）。 */
export interface ModelConfigPutPayload {
  provider?: LlmProvider
  model?: string
  base_url?: string | null
  api_key?: string | null
  temperature?: number
  top_p?: number
  max_tokens?: number
  anti_plagiarism_mode?: AntiPlagiarismMode
  score_threshold?: number | null
  top_k?: number
}

export interface ModelConfigTestOut {
  ok: boolean
  latency_ms: number | null
  sample: string
}

// ---------------------------------------------------------------- 日志 / 仪表盘 / 统计

export interface LogOut {
  id: string
  user_id: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  ip: string | null
  request_id: string | null
  created_at: string
}

export interface OverviewOut {
  users: { total: number; active: number; admin: number }
  conversations: number
  messages: number
  knowledge_bases: number
  documents: number
  code_sessions: number
  code_analyses: number
  code_runs: number
  exercises: { published: number; draft: number }
  submissions: number
  mistake_entries: { total: number; unmastered: number }
  audit_logs: number
  model_config: {
    provider: string
    model: string
    anti_plagiarism_mode: string
    revision: number
  }
  /** 与 /health 同源（embedder_runtime.snapshot）。 */
  embedder: { name: string | null; model: string | null; ready: boolean; error: string | null }
}

export interface AntiPlagiarismStatsOut {
  intent: string
  items: Array<{ mode: string; total: number; blocked: number; block_rate: number }>
  overall: { mode: string; total: number; blocked: number; block_rate: number }
}

// ---------------------------------------------------------------- 习题（管理端）

/** admin 习题全量出参：含 draft 与答案/解析/用例 —— 出题人必须看得到。 */
export interface AdminExerciseOut {
  id: string
  type: ExerciseType
  stem: string
  options: Record<string, string> | null
  answer: unknown
  test_cases: Record<string, unknown> | null
  explanation: string
  knowledge_tags: string[]
  difficulty: number
  source: 'seed' | 'admin' | 'ai'
  status: 'draft' | 'published'
  created_by: string | null
  created_at: string
}

/** 管理端新建入参：source/created_by 由服务端决定（契约定稿 1）。 */
export interface AdminExerciseIn {
  type: ExerciseType
  stem: string
  options?: Record<string, string> | null
  answer: unknown
  test_cases?: Record<string, unknown> | null
  explanation?: string
  knowledge_tags?: string[]
  difficulty: number
  status?: 'draft' | 'published'
}

export interface AdminExercisePatch {
  type?: ExerciseType
  stem?: string
  options?: Record<string, string> | null
  answer?: unknown
  test_cases?: Record<string, unknown> | null
  explanation?: string
  knowledge_tags?: string[]
  difficulty?: number
  status?: 'draft' | 'published'
}
