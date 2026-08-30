import type { ApiResponse } from '@/types/api'
import type {
  CodeAnalysisOut,
  CodeLanguage,
  CodeRunHistoryItem,
  CodeRunOut,
  CodeSessionOut,
  Paged,
} from '@/types/code'
import { api } from './client'

// 语言类型定义在 types/code.ts，这里转出以保持既有 import 路径可用
export type { CodeLanguage }

export interface AnalyzePayload {
  language: CodeLanguage
  source: string
}

/** 评改已写代码（spec §6.2 code 行）。意图固定 review_my_code，豁免防抄袭档位。 */
export const analyzeCode = (payload: AnalyzePayload) =>
  api.post<ApiResponse<CodeAnalysisOut>>('/code/analyze', {
    language: payload.language,
    source: payload.source,
  })

// ---------------------------------------------------------------- 代码运行（P4）

export interface RunPayload {
  language: CodeLanguage
  source: string
  stdin?: string
}

/**
 * 受限执行（spec §8.3）。
 *
 * 注意：并发满时后端返回 429（code=4290），axios 拦截器会弹错误提示；
 * 「命中黑名单」「超时」「内存超限」都是 200 —— 它们是对输入的正常业务结果。
 */
export const runCode = (payload: RunPayload) =>
  api.post<ApiResponse<CodeRunOut>>('/code/run', {
    language: payload.language,
    source: payload.source,
    stdin: payload.stdin ?? '',
  })

export const listRuns = (page = 1, pageSize = 10) =>
  api.get<ApiResponse<Paged<CodeRunHistoryItem>>>('/code/runs', {
    params: { page, page_size: pageSize },
  })

// ---------------------------------------------------------------- 草稿（CodeSession）

export const listSessions = () => api.get<ApiResponse<{ items: CodeSessionOut[] }>>('/code/sessions')

export const createSession = (payload: {
  language: CodeLanguage
  title?: string
  source_code?: string
}) => api.post<ApiResponse<CodeSessionOut>>('/code/sessions', payload)

export const updateSession = (
  id: string,
  payload: { language?: CodeLanguage; title?: string; source_code?: string },
) => api.patch<ApiResponse<CodeSessionOut>>(`/code/sessions/${id}`, payload)

export const deleteSession = (id: string) =>
  api.delete<ApiResponse<{ id: string }>>(`/code/sessions/${id}`)
