/**
 * ``hasNewAssistantMessage`` 回归保护——use-chat-runtime 的 streamingMessages
 * 清理启发式。PR #132 fix（说明：run_id/uuid4 ↔ messages.id/uuid5 格式
 * 不一致导致回答显示两次）的关键分支点。
 *
 * 回归场景：
 * - 正常结束：新 assistant id 到达 → 触发清理（true）
 * - mid-stream 中断：assistant id 未到达 → 保留 partial token（false）
 * - 仅新增 user：assistant 未到达 → false（W3-out M5 保护意图）
 */

import { describe, expect, it } from 'vitest'
import type { Message } from '@/lib/types'
import { hasNewAssistantMessage } from '../use-chat-runtime'

function msg(id: string, role: Message['role'], content = ''): Message {
  return {
    id,
    conversation_id: 'c',
    role,
    content,
    tool_calls: null,
    tool_call_id: null,
    created_at: '2026-01-01T00:00:00Z',
    feedback: null,
    attachments: null,
    usage: null,
    parent_id: null,
    branch_checkpoint_id: null,
    siblings: null,
    sibling_checkpoint_ids: null,
    branch_index: null,
    branch_total: null,
  } as unknown as Message
}

describe('hasNewAssistantMessage', () => {
  it('正常结束——新 assistant id 到达时为 true（streamingMessages 清理触发）', () => {
    const prev = [msg('u-1', 'user', 'hi')]
    const next = [msg('u-1', 'user', 'hi'), msg('a-1', 'assistant', '你好！')]
    expect(hasNewAssistantMessage(prev, next)).toBe(true)
  })

  it('mid-stream 中断——assistant 未到达时为 false（保留 partial token）', () => {
    // backend 只保存了 user 消息，assistant 尚未完成 checkpointer commit 的状态。
    const prev: Message[] = []
    const next = [msg('u-1', 'user', 'hi')]
    expect(hasNewAssistantMessage(prev, next)).toBe(false)
  })

  it('仅新增 user——false（W3-out M5 保护）', () => {
    const prev = [msg('a-prev', 'assistant', '之前的回答')]
    const next = [msg('a-prev', 'assistant', '之前的回答'), msg('u-1', 'user', 'hi')]
    expect(hasNewAssistantMessage(prev, next)).toBe(false)
  })

  it('无变化——messages 相同时为 false', () => {
    const m = [msg('u-1', 'user', 'hi'), msg('a-1', 'assistant', 'ok')]
    expect(hasNewAssistantMessage(m, m)).toBe(false)
  })

  it('assistant id 已存在于 prev set 中时为 false（虽重新 fetch，但不是新 turn）', () => {
    const a = msg('a-1', 'assistant', 'ok')
    const prev = [msg('u-1', 'user', 'hi'), a]
    const next = [msg('u-1', 'user', 'hi'), a, msg('u-2', 'user', 'q2')]
    expect(hasNewAssistantMessage(prev, next)).toBe(false)
  })

  it('multi-turn——assistant 1 + tool n + assistant 2 一次到达也为 true', () => {
    const prev = [msg('u-1', 'user', 'q')]
    const next = [
      msg('u-1', 'user', 'q'),
      msg('a-1', 'assistant', 'thinking'),
      msg('t-1', 'tool', 'tool result'),
      msg('a-2', 'assistant', 'final'),
    ]
    expect(hasNewAssistantMessage(prev, next)).toBe(true)
  })
})
