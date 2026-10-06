import { fetchEventSource, type EventSourceMessage } from '@microsoft/fetch-event-source'
import { API_BASE, fireSessionExpired } from '@/lib/api/client'
import { ApiError, parseApiErrorBody } from '@/lib/api/errors'
import { csrfStore } from '@/lib/auth/csrf'

/** Error thrown when a stream POST/GET returns a non-2xx with a parseable
 *  ``{error: {code, message}}`` body. Carries the structured fields so the
 *  chat runtime (``useChatRuntime``) can render an inline assistant-side
 *  message for actionable codes (e.g. ``llm_credential_required``) instead
 *  of a generic toast.
 *
 *  Subclasses ``ApiError`` so ``instanceof ApiError`` catches both REST
 *  and SSE failures uniformly (auth-errors / session reload paths).
 *  ``StreamHttpError`` (legacy GET resume path) stays intact for callers
 *  that only need status. */
export class StreamApiError extends ApiError {
  constructor(status: number, code: string | null, message: string) {
    super(status, code ?? 'UNKNOWN_STREAM_ERROR', message)
    this.name = 'StreamApiError'
  }
}

async function readStreamErrorBody(
  response: Response,
): Promise<{ code: string | null; message: string }> {
  const { code, message } = await parseApiErrorBody(response, { clone: true })
  return {
    code,
    message: message ?? `HTTP ${response.status}`,
  }
}

/**
 * 单个 SSE event。
 *
 * - ``event``：``event:`` 行的值（没有则用 ``defaultEvent``）。
 * - ``data``：``data:`` 行的 JSON parsed value。
 * - ``id``：``id:`` 行的值（仅服务器发布时存在）。客户端可用它在
 *   同一 stream retry 时 dedup 重复 event，或丢弃 stale event。
 */
export interface SSEEvent<TEvent extends string> {
  event: TEvent
  data: unknown
  id?: string
}

/**
 * Shared SSE stream parsing utility.
 * Extracts event/id/data triples from a ReadableStream following the SSE protocol.
 */
export async function* parseSSEStream<TEvent extends string>(
  body: ReadableStream<Uint8Array>,
  defaultEvent: TEvent,
): AsyncGenerator<SSEEvent<TEvent>> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent: TEvent = defaultEvent
  let currentId: string | undefined

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        // SSE 标准：``field:value`` — 最多 trim colon 后 1 个空格。``id: x`` /
        // ``id:x`` 都有效。如果某些 proxy 去掉空格，startsWith 匹配会
        // 失效，曾导致 lastEventId 追踪损坏。统一改为 colon-split。
        const colon = line.indexOf(':')
        if (colon < 0) continue // comment 行（``: ...``）或空行
        const field = line.slice(0, colon)
        const rawValue = line.slice(colon + 1)
        const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
        if (field === 'event') {
          currentEvent = value.trim() as TEvent
        } else if (field === 'id') {
          currentId = value.trim()
        } else if (field === 'data') {
          try {
            const data: unknown = JSON.parse(value)
            yield { event: currentEvent, data, id: currentId }
          } catch {
            // Skip malformed JSON lines
          }
          // SSE 标准：id 只在同一个 message 内有效。它可以保留到下一个 message 边界
          // （空行），但我们自己的 stream 会为每个 chunk 发布新 id，
          // 因此每次 yield 后 reset 也安全。
          currentId = undefined
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {})
  }
}

/**
 * 基于 POST 的 SSE stream 选项。
 *
 * - ``onRunId`` — W3-out M5。响应头 ``X-Run-Id`` 到达时调用 1 次。调用
 *   方把此 id 存入 ref，之后通过 GET ``/stream?run_id=`` 重连。
 *   primary stream 如果没有 header 就结束，则不会调用。
 */
export interface StreamSSEPostOptions {
  onRunId?: (runId: string) => void
  onConversationId?: (conversationId: string) => void
}

export interface HeadIndexQueue<T> {
  push(item: T): void
  take(): T | undefined
  length(): number
}

export function createHeadIndexQueue<T>({
  compactAfter = 64,
}: { compactAfter?: number } = {}): HeadIndexQueue<T> {
  const buffer: T[] = []
  let head = 0

  const compact = () => {
    if (head === 0) return
    if (head < compactAfter && head < buffer.length) return
    buffer.splice(0, head)
    head = 0
  }

  return {
    push(item) {
      buffer.push(item)
    },
    take() {
      if (head >= buffer.length) return undefined
      const item = buffer[head]
      head += 1
      compact()
      return item
    },
    length() {
      return buffer.length - head
    },
  }
}

/**
 * Generic POST-based SSE stream. Sends a JSON body to the given path and
 * yields parsed SSE events.
 *
 * 基于 @microsoft/fetch-event-source：
 * - ``openWhenHidden: true`` → 即使 tab 进入后台也保持 connection。默认
 *   EventSource 可能被浏览器 throttle 或断开，但 fetch-event-source 直接使用 fetch
 *   API，因此 hidden 状态下也能继续存活。
 * - 自动重连 **禁用**。重新执行 POST = 新 LangGraph run = 成本 + 重复。
 *   重连在 W3-out M5 中通过 ``streamSSEGetResume``（GET）+ ``withAutoResume``
 *   （caller 侧 generator decorator）组合实现。
 * - id/event/data 直接从 ``EventSourceMessage`` 获取，绕过 ``parseSSEStream``。
 *
 * generator 接口保持不变（所有 caller 兼容）。
 */
export async function* streamSSEPost<TEvent extends string>(
  path: string,
  body: Record<string, unknown>,
  signal: AbortSignal | undefined,
  defaultEvent: TEvent,
  options?: StreamSSEPostOptions,
): AsyncGenerator<SSEEvent<TEvent>> {
  // Callback-driven fetchEventSource → bridge 为 generator。
  const buffer = createHeadIndexQueue<SSEEvent<TEvent>>()
  let resolver: (() => void) | null = null
  let terminalError: Error | null = null
  let closed = false

  const wakeUp = () => {
    if (resolver) {
      const r = resolver
      resolver = null
      r()
    }
  }

  // 用 .catch 处理 fetchEventSource Promise，防止 unhandled rejection。
  // 真正的结束信号在 onclose/onerror 中设为 closed=true。
  // CSRF token is grabbed once per stream — fetchEventSource doesn't retry
  // automatically, so a token rotation mid-stream isn't a concern.
  const csrf = csrfStore.get()

  void fetchEventSource(`${API_BASE}${path}`, {
    method: 'POST',
    // Cross-origin (3000 → 8001) needs explicit ``credentials`` so the
    // HttpOnly auth cookies attach. Without it the backend sees an
    // anonymous request and returns 401.
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      // 库的默认 onopen 会严格检查 Content-Type。backend 虽然
      // 总是发送 text/event-stream，但部分 proxy 可能转换，因此
      // 统一使用自定义验证。
      if (response.status === 401) {
        // Fire the global session-expired handler so the user sees the toast
        // + redirect, then bail with a clear error. Stream restart on refresh
        // is intentionally out of scope (LangGraph run cost — see plan).
        fireSessionExpired()
        throw new Error(`Stream failed: 401`)
      }
      if (!response.ok) {
        const { code, message } = await readStreamErrorBody(response)
        throw new StreamApiError(response.status, code, message)
      }
      // W3-out M5 — X-Run-Id header 是 stream 重连标识符。从 POST 响应头中
      // 提取 1 次并传给 caller。没有 header（legacy/异常路径）时静默
      // 跳过 — withAutoResume 在没有 runId 时不会尝试重连。
      // ``Headers.get`` 是 case-insensitive（由 HTML living standard 保证），因此
      // 与 ``streamSSEGetResume`` 的 ``X-Resume-Mode`` 相同，使用 single-case
      // lookup。用于整理 track 结束 retrospective 中发现的不对称。
      if (options?.onRunId) {
        const runId = response.headers.get('X-Run-Id')
        if (runId) options.onRunId(runId)
      }
      if (options?.onConversationId) {
        const conversationId = response.headers.get('X-Conversation-Id')
        if (conversationId) options.onConversationId(conversationId)
      }
    },
    onmessage(msg: EventSourceMessage) {
      try {
        const data: unknown = JSON.parse(msg.data)
        buffer.push({
          event: (msg.event || defaultEvent) as TEvent,
          data,
          id: msg.id || undefined,
        })
        wakeUp()
      } catch {
        // malformed JSON — 与之前 parseSSEStream 相同，silently skip。
      }
    },
    onclose() {
      closed = true
      wakeUp()
    },
    onerror(err) {
      // POST 非 idempotent，因此禁止自动 retry。throw 时
      // fetchEventSource 不会 retry，而是 reject promise。
      terminalError = err instanceof Error ? err : new Error(String(err))
      closed = true
      wakeUp()
      throw err
    },
  })
    .catch((err) => {
      if (!terminalError && !(err instanceof DOMException && err.name === 'AbortError')) {
        terminalError = err instanceof Error ? err : new Error(String(err))
      }
    })
    .finally(() => {
      // fetch-event-source 在 input signal abort 时，promise 不是 reject，
      // 而是 **resolve**，且不调用 onclose/onerror。仅靠 catch 会导致
      // closed 永远为 false，使下方消费循环等待 resolver，形成 deadlock。
      // （Stop 后 isRunning 不释放 — durable run cancel 回归的根因）。
      // 将 abort 转换为 AbortError，保持现有消费者契约（swallow AbortError）。
      if (!terminalError && signal?.aborted) {
        terminalError = new DOMException('Aborted', 'AbortError')
      }
      closed = true
      wakeUp()
    })

  while (true) {
    if (buffer.length() > 0) {
      const event = buffer.take()
      if (event) yield event
      continue
    }
    if (closed) {
      if (terminalError) throw terminalError
      return
    }
    await new Promise<void>((resolve) => {
      resolver = resolve
    })
  }
}

/**
 * 基于 GET 的 SSE stream — 专用于 W3-out M5 的 stream resume endpoint。
 *
 * - 通过 ``Last-Event-ID`` header 发送最后收到的 event id（服务器同时支持 query
 *   ``last_event_id`` 优先、header fallback）。
 * - ``X-Run-Id``、``X-Resume-Mode`` 响应头通过 ``onMode`` callback 传给 caller。
 *   用于 observability + dedup 策略判断（live → boundary 需要 1 个 dedup，replay →
 *   服务器已经只发送 after_id 之后的事件）。
 * - 后端进入 reject 分支时（4xx，尤其是 ``404 RESUME_NOT_FOUND`` /
 *   ``409 RESUME_INTERRUPT_PENDING``），在 ``onopen`` 中 throw ``StreamHttpError`` —
 *   ``withAutoResume`` 根据 status 判断是否 retryable。
 *
 * 使用 native ``fetch`` + ``parseSSEStream`` 实现（POST helper 的 fetch-event-
 * source 除了禁用自动重连外，对 GET 没有额外优势，而且使用 Last-Event-ID
 * header 会与库自身 retry 冲突）。
 */
export interface StreamSSEGetResumeOptions<TEvent extends string> {
  /** 通过 SSE 标准 ``Last-Event-ID`` header 发送的最后 event id。 */
  lastEventId?: string
  /** ``run_id`` query param。服务器用于识别 broker / DB row。 */
  runId?: string
  /** 传递 1 次响应头 ``X-Resume-Mode`` 与 ``X-Run-Id``。 */
  onMode?: (info: { mode: 'live' | 'replay' | string; runId: string | null }) => void
  defaultEvent: TEvent
}

/** 基于 GET 的 stream 被 4xx/5xx reject 时 throw 的错误。
 *  ``withAutoResume`` 用它只 retry ``status >= 500`` / 网络错误。 */
export class StreamHttpError extends Error {
  constructor(
    public status: number,
    public statusText: string,
  ) {
    super(`Stream HTTP ${status} ${statusText}`)
    this.name = 'StreamHttpError'
  }
}

export async function* streamSSEGetResume<TEvent extends string>(
  path: string,
  signal: AbortSignal | undefined,
  options: StreamSSEGetResumeOptions<TEvent>,
): AsyncGenerator<SSEEvent<TEvent>> {
  const url = new URL(`${API_BASE}${path}`)
  if (options.runId) url.searchParams.set('run_id', options.runId)
  if (options.lastEventId) url.searchParams.set('last_event_id', options.lastEventId)

  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (options.lastEventId) headers['Last-Event-ID'] = options.lastEventId

  const response = await fetch(url.toString(), {
    method: 'GET',
    credentials: 'include',
    headers,
    signal,
  })
  if (response.status === 401) {
    fireSessionExpired()
    throw new StreamHttpError(401, response.statusText)
  }
  if (!response.ok) {
    const { code, message } = await readStreamErrorBody(response)
    throw new StreamApiError(response.status, code, message)
  }
  if (options.onMode) {
    options.onMode({
      mode: response.headers.get('X-Resume-Mode') ?? 'unknown',
      runId: response.headers.get('X-Run-Id'),
    })
  }
  if (!response.body) {
    throw new Error('Stream response has no body')
  }
  yield* parseSSEStream(response.body, options.defaultEvent)
}

/**
 * 过滤同一 stream 内重复 event 的简单 dedup helper。
 *
 * 后端为每个 chunk 发布 ``id: {msg_id}-{seq}`` 格式的 unique id，
 * 因此同一 id 到达两次时（重连后重复收到同一 chunk 等），可以忽略第二次。
 * 没有 id 的 event 始终通过（兼容旧版后端）。
 *
 * 用法：
 *   const dedup = createEventDeduper()
 *   for await (const ev of parseSSEStream(...)) {
 *     if (dedup.isDuplicate(ev.id)) continue
 *     ...
 *   }
 */
export function createEventDeduper(): {
  isDuplicate(id: string | undefined): boolean
  reset(): void
  size(): number
} {
  const seen = new Set<string>()
  return {
    isDuplicate(id) {
      if (!id) return false
      if (seen.has(id)) return true
      seen.add(id)
      return false
    },
    reset() {
      seen.clear()
    },
    size() {
      return seen.size
    },
  }
}
