import type {
  FileEventPayload,
  InterruptPayload,
  MemoryEventPayload,
  SSEEvent,
  StalePayload,
  TokenUsageBreakdown,
} from '@/lib/types'
import { streamSSEGetResume } from '@/lib/sse/parse-sse'

export type AgUiEventType =
  | 'RUN_STARTED'
  | 'RUN_FINISHED'
  | 'RUN_ERROR'
  | 'TEXT_MESSAGE_START'
  | 'TEXT_MESSAGE_CONTENT'
  | 'TEXT_MESSAGE_END'
  | 'TOOL_CALL_START'
  | 'TOOL_CALL_ARGS'
  | 'TOOL_CALL_END'
  | 'TOOL_CALL_RESULT'
  | 'CUSTOM'

export type AgUiEvent = {
  type: AgUiEventType
  rawEvent?: unknown
  [key: string]: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function customPayload(event: AgUiEvent): unknown {
  const value = recordValue(event.value)
  return 'payload' in value ? value.payload : event.value
}

function usageFromRaw(
  raw: Record<string, unknown>,
): Partial<TokenUsageBreakdown> & Record<string, number> {
  const usage = raw.usage
  return isRecord(usage) ? (usage as Partial<TokenUsageBreakdown> & Record<string, number>) : {}
}

function messageEndStatus(value: unknown): 'completed' | 'failed' | 'canceled' | undefined {
  return value === 'completed' || value === 'failed' || value === 'canceled' ? value : undefined
}

export function agUiEventToMoldyEvents(event: AgUiEvent, id?: string): SSEEvent[] {
  switch (event.type) {
    case 'RUN_STARTED':
    case 'RUN_FINISHED':
    case 'TOOL_CALL_ARGS':
    case 'TOOL_CALL_END':
      return []
    case 'TEXT_MESSAGE_START': {
      return [
        {
          id,
          event: 'message_start',
          data: {
            id: stringValue(event.messageId) ?? crypto.randomUUID(),
            role: 'assistant',
          },
        },
      ]
    }
    case 'TEXT_MESSAGE_CONTENT': {
      return [
        {
          id,
          event: 'content_delta',
          data: { delta: stringValue(event.delta) ?? '' },
        },
      ]
    }
    case 'TEXT_MESSAGE_END': {
      const raw = recordValue(event.rawEvent)
      return [
        {
          id,
          event: 'message_end',
          data: {
            content: stringValue(raw.content) ?? '',
            usage: usageFromRaw(raw),
            status: messageEndStatus(raw.status),
          },
        },
      ]
    }
    case 'TOOL_CALL_START': {
      const raw = recordValue(event.rawEvent)
      return [
        {
          id,
          event: 'tool_call_start',
          data: {
            tool_call_id: stringValue(event.toolCallId),
            tool_name:
              stringValue(event.toolCallName) ?? stringValue(raw.tool_name) ?? 'unknown_tool',
            parameters: recordValue(raw.parameters),
          },
        },
      ]
    }
    case 'TOOL_CALL_RESULT': {
      const raw = recordValue(event.rawEvent)
      return [
        {
          id,
          event: 'tool_call_result',
          data: {
            tool_call_id: stringValue(event.toolCallId),
            tool_name: stringValue(raw.tool_name) ?? 'unknown_tool',
            result: stringValue(event.content) ?? stringValue(raw.result) ?? '',
          },
        },
      ]
    }
    case 'RUN_ERROR':
      return [
        {
          id,
          event: 'error',
          // 保留 code — 让 Moldy 路径的 actionable error（例如 llm_credential_required）
          // 分支在 ag_ui 路径中也能相同工作。
          data: {
            message: stringValue(event.message) ?? 'Run failed.',
            code: stringValue(event.code),
          },
        },
      ]
    case 'CUSTOM': {
      const name = stringValue(event.name)
      const payload = customPayload(event)
      if (name === 'moldy.file_event') {
        return [{ id, event: 'file_event', data: payload as FileEventPayload }]
      }
      if (name === 'moldy.interrupt') {
        return [{ id, event: 'interrupt', data: payload as InterruptPayload }]
      }
      if (name === 'moldy.stale') {
        return [{ id, event: 'stale', data: payload as StalePayload }]
      }
      if (
        name === 'moldy.memory_proposed' ||
        name === 'moldy.memory_saved' ||
        name === 'moldy.memory_rejected' ||
        name === 'moldy.memory_deleted'
      ) {
        return [
          {
            id,
            event: name.replace('moldy.', '') as
              | 'memory_proposed'
              | 'memory_saved'
              | 'memory_rejected'
              | 'memory_deleted',
            data: payload as MemoryEventPayload,
          } as SSEEvent,
        ]
      }
      return []
    }
    default:
      // 即使后端先引入新的 AG-UI 事件类型，运行时值也可能超出 union，
      // 因此通过返回 undefined 做防御，避免 for...of throw。
      return []
  }
}

export async function* streamAgUiRunAttach(
  conversationId: string,
  runId: string,
  lastEventId: string | undefined,
  signal?: AbortSignal,
  onMode?: (info: { mode: 'live' | 'replay' | string; runId: string | null }) => void,
): AsyncGenerator<SSEEvent> {
  const stream = streamSSEGetResume<AgUiEventType>(
    `/api/conversations/${conversationId}/runs/${runId}/ag-ui-stream`,
    signal,
    {
      runId,
      lastEventId,
      onMode,
      defaultEvent: 'CUSTOM',
    },
  )

  for await (const event of stream) {
    if (!isRecord(event.data) || !stringValue(event.data.type)) continue
    for (const moldyEvent of agUiEventToMoldyEvents(event.data as AgUiEvent, event.id)) {
      yield moldyEvent
    }
  }
}
