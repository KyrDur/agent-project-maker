import { AIMessage, HumanMessage } from '@langchain/core/messages'
import { describe, expect, it } from 'vitest'
import {
  TERMINAL_NOTICE_METADATA_KEY,
  isTerminalNoticeMessageId,
  isTerminalNoticeStatus,
  terminalNoticeFromMessage,
} from '../terminal-notice'

function noticeBubble(status: string): AIMessage {
  return new AIMessage({
    id: `moldy-${status}-run1`,
    content: '通知文本',
    additional_kwargs: { metadata: { [TERMINAL_NOTICE_METADATA_KEY]: status } },
  })
}

describe('terminalNoticeFromMessage', () => {
  it('提取取消/中断/stale/失败状态', () => {
    expect(terminalNoticeFromMessage(noticeBubble('failed'))).toBe('failed')
    expect(terminalNoticeFromMessage(noticeBubble('canceled'))).toBe('canceled')
    expect(terminalNoticeFromMessage(noticeBubble('canceling'))).toBe('canceling')
    expect(terminalNoticeFromMessage(noticeBubble('stale'))).toBe('stale')
  })

  it('未知状态或普通消息返回 null', () => {
    expect(terminalNoticeFromMessage(noticeBubble('running'))).toBeNull()
    expect(terminalNoticeFromMessage(new AIMessage({ content: '你好' }))).toBeNull()
    expect(terminalNoticeFromMessage(new HumanMessage({ content: '你好' }))).toBeNull()
  })

  it('即使没有 additional_kwargs.metadata 也安全返回 null', () => {
    const bare = new AIMessage({ content: '正文' })
    // additional_kwargs 为空也不会 crash，返回 null。
    expect(terminalNoticeFromMessage(bare)).toBeNull()
  })
})

describe('isTerminalNoticeStatus', () => {
  it('只收窄已知状态', () => {
    expect(isTerminalNoticeStatus('failed')).toBe(true)
    expect(isTerminalNoticeStatus('stale')).toBe(true)
    expect(isTerminalNoticeStatus('completed')).toBe(false)
    expect(isTerminalNoticeStatus(undefined)).toBe(false)
    expect(isTerminalNoticeStatus(123)).toBe(false)
  })
})

describe('isTerminalNoticeMessageId', () => {
  it('识别合成 notice 气泡 id（moldy-<status>-<runId>）', () => {
    expect(isTerminalNoticeMessageId('moldy-failed-run1')).toBe(true)
    expect(isTerminalNoticeMessageId('moldy-canceled-run1')).toBe(true)
    expect(isTerminalNoticeMessageId('moldy-canceling-x')).toBe(true)
    expect(isTerminalNoticeMessageId('moldy-stale-abc')).toBe(true)
  })

  it('真实消息 id、其他合成 id、空值均为 false（避免误判为 fork 对象）', () => {
    // 不能排除真实 assistant turn——因为它是 checkpoint fork 对象。
    expect(isTerminalNoticeMessageId('run-abc-123')).toBe(false)
    expect(isTerminalNoticeMessageId('moldy-compaction-1')).toBe(false)
    expect(isTerminalNoticeMessageId(undefined)).toBe(false)
    expect(isTerminalNoticeMessageId(null)).toBe(false)
  })
})
