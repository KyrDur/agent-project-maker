import { getActiveClientLocale } from '@/i18n/client-locale'
import type { Decision, SSEEvent, SSEEventType } from '@/lib/types'
import { streamSSEPost } from './parse-sse'

/**
 * Builder v3 — interrupt 响应后恢复 graph。
 *
 * ADR-012 §Phase 5 — 标准 ``decisions: Decision[]`` wire 单一格式（clean break）。
 * Builder router 用 ``decisions_to_builder_response`` helper 按 phase 转换为 native
 * shape（string / approval dict / image dict）后再传给 graph。
 */
export async function* streamBuilderResume(
  sessionId: string,
  decisions: Decision[],
  signal?: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/builder/${sessionId}/messages/resume`,
    {
      locale: getActiveClientLocale(),
      decisions,
      display_text: displayText,
      interrupt_id: interruptId ?? null,
    },
    signal,
    'content_delta',
  ) as AsyncGenerator<SSEEvent>
}
