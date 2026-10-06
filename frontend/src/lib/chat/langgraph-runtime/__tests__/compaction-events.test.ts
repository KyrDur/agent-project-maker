import { describe, expect, it } from 'vitest'
import { AIMessage, HumanMessage } from '@langchain/core/messages'
import {
  attachCompactionToMessages,
  compactionFromMessage,
  compactionMarkerFromPayload,
  computeCompactionByMessageId,
  type CompactionMarker,
} from '../compaction-events'
import { reduceActivity } from '../activity-model'
import type { ProtocolEvent } from '../activity-types'

function compactionEvent(seq: number, payload: Record<string, unknown>): ProtocolEvent {
  return {
    method: 'custom',
    seq,
    run_id: 'run-1',
    params: { data: { name: 'moldy.compaction', payload } },
  }
}

function messageStartEvent(seq: number, id: string): ProtocolEvent {
  return { method: 'messages', seq, params: { data: { event: 'message-start', id } } }
}

describe('computeCompactionByMessageId', () => {
  it('将 done 标记映射到其前一个最后的 message-start', () => {
    // 实测顺序：running(2) → 回答 message-start(7) → done(12)
    const events = [
      compactionEvent(2, { state: 'running' }),
      messageStartEvent(7, 'answer-msg'),
      compactionEvent(12, {
        state: 'done',
        history_id: 'hist_opaque',
        cutoff_index: 2,
        offload_path: '/private/runtime/conversation_history/legacy.md',
      }),
    ]

    const map = computeCompactionByMessageId(events)

    expect(map.get('answer-msg')).toEqual({
      historyId: 'hist_opaque',
      cutoffIndex: 2,
    })
  })

  it('只有 running 标记而没有 done 时为空', () => {
    const events = [compactionEvent(2, { state: 'running' }), messageStartEvent(3, 'm')]

    expect(computeCompactionByMessageId(events).size).toBe(0)
  })

  it('不映射晚于 done 的 message-start', () => {
    const events = [
      messageStartEvent(7, 'earlier'),
      compactionEvent(12, { state: 'done', history_id: 'hist_earlier' }),
      messageStartEvent(20, 'later'),
    ]

    const map = computeCompactionByMessageId(events)

    expect(map.get('earlier')).toEqual({ historyId: 'hist_earlier' })
    expect(map.has('later')).toBe(false)
  })

  it('将重复的完成事件分别独立映射到各回答', () => {
    const events = [
      messageStartEvent(7, 'first-answer'),
      compactionEvent(12, { state: 'done', history_id: 'history-first', cutoff_index: 2 }),
      messageStartEvent(20, 'second-answer'),
      compactionEvent(26, { state: 'done', history_id: 'history-second', cutoff_index: 4 }),
    ]

    expect(computeCompactionByMessageId(events)).toEqual(
      new Map<string, CompactionMarker>([
        ['first-answer', { historyId: 'history-first', cutoffIndex: 2 }],
        ['second-answer', { historyId: 'history-second', cutoffIndex: 4 }],
      ]),
    )
  })

  it('在嵌套 message payload 中也将重复完成事件分别映射到各回答', () => {
    const events = [
      {
        method: 'messages',
        seq: 7,
        params: {
          data: [{ event: 'message-start', id: 'nested-first' }, { langgraph_node: 'model' }],
        },
      },
      compactionEvent(12, { state: 'done', history_id: 'history-first' }),
      {
        method: 'messages',
        seq: 20,
        params: {
          data: [{ event: 'message-start', id: 'nested-second' }, { langgraph_node: 'model' }],
        },
      },
      compactionEvent(26, { state: 'done', history_id: 'history-second' }),
    ] satisfies readonly ProtocolEvent[]

    expect(computeCompactionByMessageId(events)).toEqual(
      new Map<string, CompactionMarker>([
        ['nested-first', { historyId: 'history-first' }],
        ['nested-second', { historyId: 'history-second' }],
      ]),
    )
  })

  it('从 marker 中移除不投影给用户的 upstream 字段', () => {
    const marker = compactionMarkerFromPayload({
      state: 'done',
      history_id: 'history-opaque',
      cutoff_index: 3,
      offload_path: '/private/runtime/conversation_history/summary.md',
      summary: 'raw upstream summary must not reach the chat',
      token_count: 987,
    })

    expect(marker).toEqual({ historyId: 'history-opaque', cutoffIndex: 3 })
    expect(JSON.stringify(marker)).not.toContain('private')
    expect(JSON.stringify(marker)).not.toContain('raw upstream summary')
  })
})

describe('attachCompactionToMessages + compactionFromMessage', () => {
  it('给已映射消息附加 marker 后重新读取', () => {
    const messages = [
      new HumanMessage({ id: 'u', content: 'q' }),
      new AIMessage({ id: 'answer-msg', content: 'a' }),
    ]
    const map = new Map<string, CompactionMarker>([
      ['answer-msg', { historyId: 'hist_opaque', cutoffIndex: 1 }],
    ])

    const attached = attachCompactionToMessages(messages, map)

    expect(compactionFromMessage(attached[1])).toEqual({ historyId: 'hist_opaque', cutoffIndex: 1 })
    expect(compactionFromMessage(attached[0])).toBeNull()
  })

  it('未渲染的 id 回退到最后一条 assistant 消息', () => {
    const messages = [new AIMessage({ id: 'visible-answer', content: 'a' })]
    const map = new Map<string, CompactionMarker>([['stale-id', { historyId: 'hist_stale' }]])

    const attached = attachCompactionToMessages(messages, map)

    expect(compactionFromMessage(attached[0])).toEqual({ historyId: 'hist_stale' })
  })

  it('没有 marker 时返回同一个数组引用', () => {
    const messages = [new AIMessage({ id: 'a', content: 'a' })]

    expect(attachCompactionToMessages(messages, new Map())).toBe(messages)
  })
})

describe('reduceActivity — compaction', () => {
  it('running 时显示压缩 activity，并在 done 时将同一个 pill 转为 complete', () => {
    const running = reduceActivity([], compactionEvent(2, { state: 'running' }))
    expect(running).toHaveLength(1)
    expect(running[0].kind).toBe('compaction')
    expect(running[0].status).toBe('running')

    const done = reduceActivity(
      running,
      compactionEvent(12, { state: 'done', history_id: 'hist_complete' }),
    )
    // same activity id (run:compaction:compaction) → upsert, not a second pill.
    expect(done).toHaveLength(1)
    expect(done[0].status).toBe('complete')
  })
})
