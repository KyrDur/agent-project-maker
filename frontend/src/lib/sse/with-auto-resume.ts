import { StreamApiError, StreamHttpError } from './parse-sse'

/** withAutoResume 用于追踪 lastEventId 的最小接口。parse-sse 的
 *  ``SSEEvent<TEvent>`` 与 lib/types 的 discriminated-union ``SSEEvent`` 都
 *  暴露 ``id?: string``，因此两者都可以原样接收。 */
export interface IdentifiedEvent {
  id?: string
}

/**
 * W3-out M5 — primary SSE stream 异常结束（网络断开等）时，
 * 通过 ``resumeFactory`` 重新 attach GET ``/stream``，从缺失的 event 开始
 * 继续接收的 generator decorator。
 *
 * - lastEventId 追踪：记住 primary yield 的每个 event 的 ``id``，
 *   retry 时调用 ``resumeFactory(lastEventId, attempt)``。
 * - retryable 判断：
 *   - ``AbortError`` / ``signal.aborted`` → 不 retry（用户 cancel）
 *   - ``StreamHttpError`` 4xx（404 RESUME_NOT_FOUND、409 INTERRUPT_PENDING 等）
 *     → 不 retry。原样 throw 给 caller。
 *   - 其他（network error、``StreamHttpError`` 5xx）→ backoff 后 retry。
 * - boundary dedup：服务器只发送 ``after_id`` *之后* 的事件，但 timing race 可能导致
 *   1 个相同 event 重叠（primary publish 后立即断开，且仍留在 broker buffer
 *   中的情况）。此时由 caller 的 ``streamGuard.isDuplicate`` 处理，
 *   因此这里不额外 dedup — 只需准确追踪 id。
 * - 回调调用顺序：
 *   - 检测到断开 → backoff 开始前 ``onReconnecting(attempt)``
 *   - 收到 retry stream 的第一个 event → ``onReconnected()``
 *   - 超过 maxAttempts → ``onFailed(error)`` 后 throw
 */
export interface WithAutoResumeOptions {
  signal?: AbortSignal
  /** retry 次数上限（primary 1 次 + retry maxAttempts 次）。默认 3。 */
  maxAttempts?: number
  /** 每次 retry 前的等待时间（ms）。attempt 超出长度时使用最后一个值。 */
  backoffMs?: number[]
  /** retry 前调用 1 次（attempt: 1, 2, ...）。UI indicator ON。 */
  onReconnecting?: (attempt: number) => void
  /** retry stream 的第一个 event 到达时调用 1 次。UI indicator OFF。 */
  onReconnected?: () => void
  /** 所有 retry 失败或遇到非 retryable 错误时调用 1 次。 */
  onFailed?: (error: Error) => void
}

const DEFAULT_BACKOFF_MS = [500, 1500, 4000]
const DEFAULT_MAX_ATTEMPTS = 3

function isRetryableError(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return false
  if (err instanceof DOMException && err.name === 'AbortError') return false
  if (err instanceof StreamApiError && err.status >= 400 && err.status < 500) {
    return err.status === 409 && err.code === 'RUN_ATTACH_RETRY'
  }
  if (err instanceof StreamHttpError && err.status >= 400 && err.status < 500) {
    return false
  }
  return true
}

function backoffFor(attempt: number, schedule: number[]): number {
  const idx = Math.min(attempt - 1, schedule.length - 1)
  return schedule[idx] ?? schedule[schedule.length - 1] ?? 0
}

async function sleepWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return
  await new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export async function* withAutoResume<E extends IdentifiedEvent>(
  primary: () => AsyncGenerator<E>,
  resumeFactory: (lastEventId: string | undefined, attempt: number) => AsyncGenerator<E> | null,
  options: WithAutoResumeOptions = {},
): AsyncGenerator<E> {
  const max = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS
  const backoff = options.backoffMs ?? DEFAULT_BACKOFF_MS
  const signal = options.signal

  const toError = (e: unknown): Error => (e instanceof Error ? e : new Error(String(e)))

  let lastEventId: string | undefined
  let attempt = 0
  let stream: AsyncGenerator<E> | null = primary()
  let isResumed = false

  while (stream !== null) {
    const current = stream
    stream = null
    try {
      for await (const ev of current) {
        if (isResumed) {
          options.onReconnected?.()
          isResumed = false
          attempt = 0
        }
        if (ev.id) lastEventId = ev.id
        yield ev
      }
      return
    } catch (err) {
      // 非 retryable（4xx、AbortError、已经 abort 的 signal）→ 立即结束。
      if (!isRetryableError(err, signal)) {
        options.onFailed?.(toError(err))
        throw err
      }
      attempt += 1
      if (attempt > max) {
        options.onFailed?.(toError(err))
        throw toError(err)
      }
      options.onReconnecting?.(attempt)
      try {
        await sleepWithAbort(backoffFor(attempt, backoff), signal)
      } catch (abortErr) {
        // backoff 过程中 abort — 将原始 err 传给 onFailed，让 caller
        // 能知道 "为什么中断"，实际 throw 的是 abortErr（caller 可通过
        // AbortController 识别）。
        options.onFailed?.(toError(err))
        throw abortErr
      }
      const next = resumeFactory(lastEventId, attempt)
      if (next === null) {
        options.onFailed?.(toError(err))
        throw toError(err)
      }
      stream = next
      isResumed = true
    }
  }
}
