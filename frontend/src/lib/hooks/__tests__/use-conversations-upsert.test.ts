import type { InfiniteData } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import {
  upsertConversationList,
  upsertConversationPages,
  upsertGlobalConversationPages,
} from '../use-conversations'
import type {
  Conversation,
  ConversationAgentBrief,
  ConversationListEnvelope,
  ConversationWithAgent,
  ConversationWithAgentListEnvelope,
} from '@/lib/types'

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: overrides.id ?? 'conv-1',
    agent_id: overrides.agent_id ?? 'agent-1',
    title: overrides.title ?? 'hello',
    is_pinned: overrides.is_pinned ?? false,
    unread_count: overrides.unread_count ?? 0,
    last_read_at: overrides.last_read_at ?? null,
    last_unread_at: overrides.last_unread_at ?? null,
    last_activity_source: overrides.last_activity_source ?? 'user',
    created_at: overrides.created_at ?? '2026-01-01T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const agentBrief: ConversationAgentBrief = {
  id: 'agent-1',
  name: 'Agent One',
  image_url: null,
}

function withAgent(overrides: Partial<Conversation> = {}): ConversationWithAgent {
  return { ...conversation(overrides), agent: agentBrief }
}

function listPages(items: Conversation[][]): InfiniteData<ConversationListEnvelope> {
  return {
    pageParams: items.map(() => undefined),
    pages: items.map((pageItems, index) => ({
      items: pageItems,
      next_cursor: index < items.length - 1 ? `cursor-${index}` : null,
      has_more: index < items.length - 1,
    })),
  }
}

function globalPages(
  items: ConversationWithAgent[][],
): InfiniteData<ConversationWithAgentListEnvelope> {
  return {
    pageParams: items.map(() => undefined),
    pages: items.map((pageItems, index) => ({
      items: pageItems,
      next_cursor: index < items.length - 1 ? `cursor-${index}` : null,
      has_more: index < items.length - 1,
    })),
  }
}

describe('upsertConversationList', () => {
  it('缓存为空时（undefined）原样返回 undefined', () => {
    expect(upsertConversationList(undefined, conversation())).toBeUndefined()
  })

  it('向空数组 prepend 新行', () => {
    const result = upsertConversationList([], conversation({ id: 'conv-new' }))
    expect(result).toHaveLength(1)
    expect(result?.[0].id).toBe('conv-new')
  })

  it('将新对话添加到最前面', () => {
    const existing = [conversation({ id: 'conv-old' })]
    const result = upsertConversationList(existing, conversation({ id: 'conv-new' }))
    expect(result?.map((row) => row.id)).toEqual(['conv-new', 'conv-old'])
  })

  it('merge 现有行并提到最前面（无重复）', () => {
    const existing = [
      conversation({ id: 'a', title: 'old-a', unread_count: 5 }),
      conversation({ id: 'b', title: 'b' }),
    ]
    const result = upsertConversationList(existing, conversation({ id: 'a', title: 'new-a' }))
    expect(result?.map((row) => row.id)).toEqual(['a', 'b'])
    // next 的字段优先，existing 字段仅在 next 中不存在时保留
    expect(result?.[0]).toMatchObject({ id: 'a', title: 'new-a', unread_count: 0 })
  })

  it('不修改原数组（immutability）', () => {
    const existing = [conversation({ id: 'a' })]
    const snapshot = [...existing]
    upsertConversationList(existing, conversation({ id: 'a', title: 'changed' }))
    expect(existing).toEqual(snapshot)
  })
})

describe('upsertConversationPages', () => {
  it('没有数据时返回 undefined', () => {
    expect(upsertConversationPages(undefined, conversation())).toBeUndefined()
  })

  it('向第一页 prepend 新对话', () => {
    const data = listPages([[conversation({ id: 'a' })], [conversation({ id: 'b' })]])
    const result = upsertConversationPages(data, conversation({ id: 'c' }))
    expect(result?.pages[0].items.map((row) => row.id)).toEqual(['c', 'a'])
    expect(result?.pages[1].items.map((row) => row.id)).toEqual(['b'])
  })

  it('移除其他页面中的对话并提到第一页（cross-page dedup）', () => {
    const data = listPages([
      [conversation({ id: 'a' })],
      [conversation({ id: 'target', title: 'old' }), conversation({ id: 'b' })],
    ])
    const result = upsertConversationPages(data, conversation({ id: 'target', title: 'new' }))
    expect(result?.pages[0].items.map((row) => row.id)).toEqual(['target', 'a'])
    expect(result?.pages[1].items.map((row) => row.id)).toEqual(['b'])
  })

  it('merge 第一页的现有行', () => {
    const data = listPages([[conversation({ id: 'target', unread_count: 3, title: 'old' })]])
    const result = upsertConversationPages(data, conversation({ id: 'target', title: 'new' }))
    expect(result?.pages[0].items).toHaveLength(1)
    expect(result?.pages[0].items[0]).toMatchObject({ title: 'new', unread_count: 0 })
  })
})

describe('upsertGlobalConversationPages', () => {
  it('没有数据时返回 undefined', () => {
    expect(upsertGlobalConversationPages(undefined, withAgent())).toBeUndefined()
  })

  it('向第一页 prepend 包含 agent 的对话', () => {
    const data = globalPages([[withAgent({ id: 'a' })]])
    const result = upsertGlobalConversationPages(data, withAgent({ id: 'c' }))
    expect(result?.pages[0].items.map((row) => row.id)).toEqual(['c', 'a'])
    expect(result?.pages[0].items[0].agent).toEqual(agentBrief)
  })

  it('在 cross-page dedup + merge 的同时，始终用新值覆盖 agent', () => {
    const staleAgent: ConversationAgentBrief = { id: 'agent-1', name: 'Stale', image_url: null }
    const data = globalPages([
      [{ ...conversation({ id: 'x' }), agent: agentBrief }],
      [{ ...conversation({ id: 'target', title: 'old' }), agent: staleAgent }],
    ])
    const result = upsertGlobalConversationPages(data, withAgent({ id: 'target', title: 'new' }))
    expect(result?.pages[0].items.map((row) => row.id)).toEqual(['target', 'x'])
    expect(result?.pages[1].items.map((row) => row.id)).toEqual([])
    expect(result?.pages[0].items[0]).toMatchObject({ title: 'new', agent: agentBrief })
  })
})
