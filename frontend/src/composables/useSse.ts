/**
 * SSE 帧解析。
 *
 * 为什么不用原生 `EventSource`：它无法携带 `Authorization` 与 `x-request-id`
 * 请求头，而中断注册表的键是 `(conversation_id, request_id)` —— 前端必须能把
 * 自己生成的 request_id 传上去，才能调用 `POST /chat/conversations/{id}/stop`。
 */

export type SseListener = (event: string, data: unknown) => void

function parseFrame(frame: string, emit: SseListener) {
  let name = ''
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice(7).trim()
    else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
    else if (line.startsWith(':')) continue // 注释帧（心跳）
  }
  if (!name || dataLines.length === 0) return
  try {
    emit(name, JSON.parse(dataLines.join('\n')))
  } catch {
    // 单帧解析失败不应当中断整条流
  }
}

export async function readSseStream(response: Response, emit: SseListener): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('当前环境不支持流式读取（ReadableStream 不可用）')

  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      parseFrame(frame, emit)
      boundary = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) parseFrame(buffer, emit)
}

/** 生成一次请求的 request_id；中断时原样回传给 /stop。 */
export function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `rid-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** 基线 §5：尊重 prefers-reduced-motion，打字机动画在减少动效下改为直接显示。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
