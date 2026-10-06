import type { Decision, SSEEvent, SSEEventType } from '@/lib/types'
import { streamSSEPost, type StreamSSEPostOptions } from './parse-sse'

/**
 * HiTL resume — 以 `{decisions}` body 发送 LangChain `HITLResponse`。
 * `decisions.length` 必须与 interrupt 的 `action_requests.length` 一致。
 */
export async function* streamResumeDecisions(
  conversationId: string,
  decisions: Decision[],
  signal?: AbortSignal,
  options?: StreamSSEPostOptions,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/conversations/${conversationId}/messages/resume`,
    { decisions },
    signal,
    'content_delta',
    options,
  ) as AsyncGenerator<SSEEvent>
}
