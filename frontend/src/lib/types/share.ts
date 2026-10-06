import type { Message } from './index'

/**
 * One SSE event captured during an assistant turn. Mirrors backend
 * ``TraceEvent`` (``backend/app/schemas/conversation.py``).
 */
export interface LegacyTraceEvent {
  id: string | null
  event: string
  data: Record<string, unknown>
}

export interface ProtocolTraceEvent {
  id: string | null
  method: string
  data?: unknown
  namespace?: string[]
  params?: {
    namespace?: string[]
    timestamp?: string | number
    data?: unknown
  }
  seq?: number | null
  event_id?: string | null
  upstream_event_id?: string | null
  run_id?: string | null
  type?: string | null
}

export type TraceEvent = LegacyTraceEvent | ProtocolTraceEvent

/**
 * One assistant turn's full event sequence. Used by W6 (shared page chips)
 * and (later) W3-out resume.
 */
export interface TurnTrace {
  assistant_msg_id: string
  events: TraceEvent[]
  last_event_id: string | null
  /** 此 turn 中暴露的 assistant 消息 parsed UUID 列表。
   * 与 MessageResponse.id 格式相同，可直接匹配（W6 accuracy）。
   * null 表示 m33 之前的 row → chronological fallback。 */
  linked_message_ids: string[] | null
  created_at: string
  completed_at: string | null
}

/**
 * Owner-facing share link metadata. ``revoked_at`` is non-null only for
 * historical rows surfaced through audit endpoints — the active-link
 * fetch always returns either ``null`` (no active share) or a row with
 * ``revoked_at: null``.
 */
export interface ShareLink {
  id: string
  share_token: string
  conversation_id: string
  created_at: string
  revoked_at: string | null
}

export interface SharedAgentBrief {
  name: string
  description: string | null
  image_url: string | null
}

/**
 * Public read-only conversation snapshot returned by ``/api/shares/{token}``.
 * Visitors render this without authentication.
 */
export interface SharedConversationView {
  share_token: string
  conversation_title: string | null
  conversation_created_at: string
  agent: SharedAgentBrief
  messages: Message[]
  /** W6 — 每个 turn 的 SSE event sequence。用于渲染 tool/Skill chip。W5 merge
   * 之前的对话会返回空数组，因此自然不显示 chip。 */
  traces: TurnTrace[]
  shared_at: string
}
