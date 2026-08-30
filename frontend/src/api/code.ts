import type { ApiResponse } from '@/types/api'
import type { CodeAnalysisOut } from '@/types/code'
import { api } from './client'

export type CodeLanguage = 'python' | 'javascript'

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
