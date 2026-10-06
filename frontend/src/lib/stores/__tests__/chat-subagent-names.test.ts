import { describe, expect, it } from 'vitest'
import { createStore } from 'jotai'
import {
  chatSubagentNamesAtom,
  mergeConversationSubagentNamesAtom,
  resolveSubagentDisplayName,
} from '../chat-subagent-names'

describe('chat-subagent-names store', () => {
  it('累积 merge 同一 conversation 的 mapping', () => {
    const store = createStore()
    store.set(mergeConversationSubagentNamesAtom, {
      conversationId: 'c1',
      names: { agent_11111111: '调研员' },
    })
    store.set(mergeConversationSubagentNamesAtom, {
      conversationId: 'c1',
      names: { agent_22222222: '作者' },
    })

    expect(store.get(chatSubagentNamesAtom)).toEqual({
      c1: { agent_11111111: '调研员', agent_22222222: '作者' },
    })
  })

  it('不同 conversation 相互隔离', () => {
    const store = createStore()
    store.set(mergeConversationSubagentNamesAtom, { conversationId: 'c1', names: { a: 'A' } })
    store.set(mergeConversationSubagentNamesAtom, { conversationId: 'c2', names: { b: 'B' } })

    expect(store.get(chatSubagentNamesAtom)).toEqual({ c1: { a: 'A' }, c2: { b: 'B' } })
  })

  it('重复 merge 相同 mapping 仍是 idempotent（replay 安全）', () => {
    const store = createStore()
    const payload = { conversationId: 'c1', names: { a: 'A' } }
    store.set(mergeConversationSubagentNamesAtom, payload)
    store.set(mergeConversationSubagentNamesAtom, payload)

    expect(store.get(chatSubagentNamesAtom)).toEqual({ c1: { a: 'A' } })
  })

  it('resolveSubagentDisplayName 有 mapping 时替换，没有时返回 raw name', () => {
    expect(resolveSubagentDisplayName(undefined, 'agent_123')).toBe('agent_123')
    expect(resolveSubagentDisplayName({ agent_123: '机器人' }, 'agent_123')).toBe('机器人')
    expect(resolveSubagentDisplayName({ other: 'x' }, 'agent_123')).toBe('agent_123')
  })
})
