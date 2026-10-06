import { getActiveClientLocale } from '@/i18n/client-locale'
import type { SSEEvent, SSEEventType } from '@/lib/types'
import { streamSSEPost } from './parse-sse'

/**
 * Builder v3 — POST 消息 + SSE stream。
 * 第一条消息：从头执行 graph（Phase 1）。
 * 后续消息：仅追加 messages（graph 进行中时）。
 */
export async function* streamBuilderMessage(
  sessionId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/builder/${sessionId}/messages`,
    { content, locale: getActiveClientLocale() },
    signal,
    'content_delta',
  ) as AsyncGenerator<SSEEvent>
}
