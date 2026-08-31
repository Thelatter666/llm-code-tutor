import { ACCESS_KEY, api } from './client'
import { readSseStream } from '@/composables/useSse'
import type { ApiResponse } from '@/types/api'
import type {
  AnswerValue,
  ExerciseDetail,
  ExerciseListOut,
  ExerciseType,
  HintDoneEvent,
  HintErrorEvent,
  HintIntent,
  SubmitOut,
} from '@/types/exercise'
import type { Citation } from '@/types/chat'

export interface ExerciseFilters {
  type?: ExerciseType | ''
  difficulty?: number | ''
  knowledgeTag?: string
  page?: number
  pageSize?: number
}

/** 学生端列表：后端只暴露 published（spec §6.2）。 */
export const listExercises = (filters: ExerciseFilters = {}) =>
  api.get<ApiResponse<ExerciseListOut>>('/exercises', {
    params: {
      type: filters.type || undefined,
      difficulty: filters.difficulty || undefined,
      knowledge_tag: filters.knowledgeTag || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    },
  })

export const getExercise = (id: string) =>
  api.get<ApiResponse<ExerciseDetail>>(`/exercises/${id}`)

/** 判分四路入口；响应里才带回正确答案与解析。 */
export const submitExercise = (id: string, answer: AnswerValue) =>
  api.post<ApiResponse<SubmitOut>>(`/exercises/${id}/submit`, { answer })

export interface HintOptions {
  exerciseId: string
  intent: HintIntent
  /** 与 submit 同形；`review_my_code` 必填（后端 422），`seek_answer` 可缺省。 */
  answer?: AnswerValue
  requestId: string
  /**
   * 中断信号。hint **没有 /stop 端点**（裁定 10）：停止只靠断开连接，
   * 服务端感知断连后结束生成 —— 因此前端不必等流跑完就能收手。
   */
  signal?: AbortSignal
  onCitation: (citation: Citation) => void
  onToken: (delta: string) => void
  onDone: (done: HintDoneEvent) => void
  onError: (error: HintErrorEvent) => void
}

/** 发起一次习题辅导（SSE）。与 `streamMessage` 同构，载荷字段集见契约定稿 4。 */
export async function streamExerciseHint(options: HintOptions): Promise<void> {
  const token = localStorage.getItem(ACCESS_KEY) ?? ''
  const response = await fetch(`/api/v1/exercises/${options.exerciseId}/hint`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'x-request-id': options.requestId,
    },
    body: JSON.stringify({ intent: options.intent, answer: options.answer ?? undefined }),
    signal: options.signal,
  })

  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const body = (await response.json()) as ApiResponse<null>
      if (body?.message) message = body.message
    } catch {
      // 非 JSON 错误体：保留默认文案
    }
    throw new Error(message)
  }

  await readSseStream(response, (event, data) => {
    if (event === 'citation') options.onCitation(data as never)
    else if (event === 'token') options.onToken((data as { delta: string }).delta)
    else if (event === 'done') options.onDone(data as never)
    else if (event === 'error') options.onError(data as never)
  })
}
