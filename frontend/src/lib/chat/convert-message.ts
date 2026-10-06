import type { ThreadMessageLike, useExternalMessageConverter } from '@assistant-ui/react'
import type { Message } from '@/lib/types'
import { parseTimestamp } from '@/lib/utils/format-relative-time'

type ConvertedMessage = useExternalMessageConverter.Message

/** P1-A — branch metadata is identical for user/assistant. Returns ``null``
 * when the message has no branching info so callers can skip the metadata
 * write entirely. */
function buildBranchMeta(message: Message): Record<string, unknown> | null {
  if (!message.siblings || message.siblings.length <= 1) return null
  return {
    branches: message.siblings,
    siblingCheckpointIds: message.sibling_checkpoint_ids ?? [],
    activeBranchId: message.id,
    branchCheckpointId: message.branch_checkpoint_id ?? null,
    branchIndex: message.branch_index ?? null,
    branchTotal: message.branch_total ?? null,
  }
}

/**
 * Message（backend）→ ThreadMessageLike（assistant-ui）转换回调。
 * 传给 useExternalMessageConverter 使用。
 *
 * - user/assistant → ThreadMessageLike（文本 + 工具调用）
 * - tool → { role: 'tool', toolCallId, result }（自动合并到 tool-call）
 */
export const convertMessage: useExternalMessageConverter.Callback<Message> = (
  message,
): ConvertedMessage => {
  // tool 消息 → 工具结果（assistant-ui 自动合并到 tool-call）
  if (message.role === 'tool') {
    return {
      role: 'tool' as const,
      toolCallId: message.tool_call_id ?? '',
      result: message.content,
    }
  }

  // user 消息 → 文本（+ 附件）
  if (message.role === 'user') {
    const userMsg: ConvertedMessage = {
      role: 'user' as const,
      id: message.id,
      content: message.content,
      createdAt: parseTimestamp(message.created_at),
    }
    // NOTE: attachments are intentionally NOT mapped onto the converted message.
    // Inline display is data-driven — UserMessageAttachments looks them up by
    // message id from /files — so attaching a CompleteAttachment shape here would
    // be dead for rendering and would only risk flattening `[attachment](url)`
    // text into the message body.
    // M-CHAT1b — surface branch info via metadata.custom so the inline
    // BranchPicker UI can read it from useAuiState.
    const userBranchMeta = buildBranchMeta(message)
    if (userBranchMeta) {
      ;(userMsg as unknown as { metadata: unknown }).metadata = {
        custom: userBranchMeta,
      }
    }
    return userMsg
  }

  // assistant 消息 → 文本 + tool-call part 数组
  type ContentPart =
    | { type: 'text'; text: string }
    | { type: 'tool-call'; toolCallId: string; toolName: string; args: Record<string, unknown> }
  const parts: ContentPart[] = []

  if (message.content) {
    parts.push({ type: 'text', text: message.content })
  }

  if (message.tool_calls) {
    for (const tc of message.tool_calls) {
      parts.push({
        type: 'tool-call',
        toolCallId: tc.id ?? `tc-${tc.name}`,
        toolName: tc.name,
        args: tc.args as Record<string, unknown>,
      })
    }
  }

  const result: ConvertedMessage = {
    role: 'assistant' as const,
    id: message.id,
    content: parts.length > 0 ? (parts as ThreadMessageLike['content']) : '',
    createdAt: new Date(message.created_at),
  }
  // M-CHAT1b — branch info on assistant messages (sibling regenerations).
  // ``message.usage``（W7）也一起 hoist 到同一个 metadata.custom 槽位，使 ActionBar
  // 旁边的 TokenUsagePopover 可通过 ``useAuiState`` 直接读取。
  const assistantBranchMeta = buildBranchMeta(message)

  const isStreamingMessage = message.id.startsWith('stream-')

  const artifacts = message.artifacts?.length ? message.artifacts : null

  if (message.feedback || assistantBranchMeta || message.usage || isStreamingMessage || artifacts) {
    // assistant-ui treats `metadata.submittedFeedback.type` as the active
    // rating — the FeedbackPositive/Negative buttons render highlighted when
    // it matches their type. We co-locate branch info + usage in `metadata.custom`.
    const customMeta: Record<string, unknown> = { ...(assistantBranchMeta ?? {}) }
    if (isStreamingMessage) {
      customMeta.isStreamingMessage = true
    }
    if (message.usage) {
      customMeta.usage = message.usage
    }
    if (artifacts) {
      customMeta.artifacts = artifacts
    }
    const meta: Record<string, unknown> = { custom: customMeta }
    if (message.feedback) {
      meta.submittedFeedback = {
        type: message.feedback.rating === 'up' ? 'positive' : 'negative',
      }
    }
    ;(result as unknown as { metadata: unknown }).metadata = meta
  }
  return result
}
