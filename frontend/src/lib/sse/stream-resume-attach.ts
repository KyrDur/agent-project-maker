import type { SSEEvent, SSEEventType } from '@/lib/types'
import { streamAgUiRunAttach } from '@/lib/ag-ui/chat-run-consumer'
import { streamSSEGetResume } from './parse-sse'

type ChatStreamProtocol = 'moldy_sse' | 'ag_ui'

export function getChatStreamProtocol(): ChatStreamProtocol {
  return process.env.NEXT_PUBLIC_CHAT_STREAM_PROTOCOL === 'ag_ui' ? 'ag_ui' : 'moldy_sse'
}

/**
 * 通过 GET ``/api/conversations/{id}/runs/{runId}/stream`` 恢复中断的 SSE stream。
 * ``runId`` 是从 primary stream 的 ``X-Run-Id`` 响应头或
 * ``Conversation.active_run`` 获取的 durable run id。
 */
export async function* streamResumeAttach(
  conversationId: string,
  runId: string,
  lastEventId: string | undefined,
  signal?: AbortSignal,
  onMode?: (info: { mode: 'live' | 'replay' | string; runId: string | null }) => void,
): AsyncGenerator<SSEEvent> {
  if (getChatStreamProtocol() === 'ag_ui') {
    yield* streamAgUiRunAttach(conversationId, runId, lastEventId, signal, onMode)
    return
  }
  yield* streamSSEGetResume<SSEEventType>(
    `/api/conversations/${conversationId}/runs/${runId}/stream`,
    signal,
    {
      runId,
      lastEventId,
      onMode,
      defaultEvent: 'content_delta',
    },
  ) as AsyncGenerator<SSEEvent>
}
