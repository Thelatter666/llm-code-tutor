import type { ApiResponse } from '@/types/api'
import type {
  ChatStreamHandlers,
  ConversationOut,
  MessageOut,
} from '@/types/chat'
import { ACCESS_KEY, api } from './client'
import { readSseStream } from '@/composables/useSse'

export const listConversations = () =>
  api.get<ApiResponse<ConversationOut[]>>('/chat/conversations')

export const createConversation = (title?: string) =>
  api.post<ApiResponse<ConversationOut>>('/chat/conversations', { title })

export const deleteConversation = (conversationId: string) =>
  api.delete<ApiResponse<{ deleted: boolean }>>(`/chat/conversations/${conversationId}`)

export const listMessages = (conversationId: string) =>
  api.get<ApiResponse<MessageOut[]>>(`/chat/conversations/${conversationId}/messages`)

export const stopGeneration = (conversationId: string, requestId: string) =>
  api.post<ApiResponse<{ cancelled: boolean }>>(`/chat/conversations/${conversationId}/stop`, {
    request_id: requestId,
  })

export interface StreamOptions extends ChatStreamHandlers {
  conversationId: string
  content: string
  useRag: boolean
  kbIds?: string[]
  requestId: string
}

/**
 * 发起一次 SSE 答疑。
 *
 * `requestId` 由调用方生成并放进 `x-request-id` 请求头 —— 后端中间件会原样采用，
 * 于是同一串 id 既能出现在响应头里，也能回传给 `/stop` 作为中断键。
 */
export async function streamMessage(options: StreamOptions): Promise<void> {
  const token = localStorage.getItem(ACCESS_KEY) ?? ''
  const response = await fetch(
    `/api/v1/chat/conversations/${options.conversationId}/messages`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        'x-request-id': options.requestId,
      },
      body: JSON.stringify({
        content: options.content,
        use_rag: options.useRag,
        kb_ids: options.kbIds?.length ? options.kbIds : undefined,
      }),
    },
  )

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
