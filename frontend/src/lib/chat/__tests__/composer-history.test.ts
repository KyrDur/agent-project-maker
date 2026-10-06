import { describe, expect, it } from 'vitest'
import {
  caretOnFirstLine,
  caretOnLastLine,
  collectUserHistory,
  extractMessageText,
  historyItemAt,
  stepHistoryIndex,
} from '../composer-history'

describe('extractMessageText', () => {
  it('从字符串/文本 part 数组中提取纯文本', () => {
    expect(extractMessageText('你好')).toBe('你好')
    expect(
      extractMessageText([
        { type: 'text', text: '第一行' },
        { type: 'tool-call', toolName: 'x' },
        { type: 'text', text: '第二行' },
      ]),
    ).toBe('第一行\n第二行')
    expect(extractMessageText(undefined)).toBe('')
  })
})

describe('collectUserHistory', () => {
  it('只收集 user 消息，并移除连续重复项和空项', () => {
    const messages = [
      { role: 'user', content: '第一个问题' },
      { role: 'assistant', content: '回答' },
      { role: 'user', content: '第一个问题' }, // 직전과 중복 아님? assistant 사이 → 히스토리상 연속
      { role: 'user', content: '   ' },
      { role: 'user', content: '第二个问题' },
    ]
    expect(collectUserHistory(messages)).toEqual(['第一个问题', '第二个问题'])
  })
})

describe('caret line 判定', () => {
  it('区分插入符位于第一行/最后一行', () => {
    const value = '第一行\n第二行'
    expect(caretOnFirstLine(value, 2)).toBe(true)
    expect(caretOnFirstLine(value, value.length)).toBe(false)
    expect(caretOnLastLine(value, value.length)).toBe(true)
    expect(caretOnLastLine(value, 1)).toBe(false)
    // 空输入同时满足第一行/最后一行。
    expect(caretOnFirstLine('', 0)).toBe(true)
    expect(caretOnLastLine('', 0)).toBe(true)
  })
})

describe('stepHistoryIndex + historyItemAt', () => {
  const history = ['较旧', '中间', '最新']

  it('↑ 从最新向过去遍历，并在边界处停止', () => {
    expect(stepHistoryIndex(3, -1, 'up')).toBe(0)
    expect(stepHistoryIndex(3, 0, 'up')).toBe(1)
    expect(stepHistoryIndex(3, 2, 'up')).toBeNull()
    expect(historyItemAt(history, 0)).toBe('最新')
    expect(historyItemAt(history, 2)).toBe('较旧')
  })

  it('↓ 向最新方向移动，直到 -1（恢复 draft）', () => {
    expect(stepHistoryIndex(3, 2, 'down')).toBe(1)
    expect(stepHistoryIndex(3, 0, 'down')).toBe(-1)
    expect(stepHistoryIndex(3, -1, 'down')).toBeNull()
    expect(historyItemAt(history, -1)).toBeNull()
  })

  it('空历史始终返回 null', () => {
    expect(stepHistoryIndex(0, -1, 'up')).toBeNull()
  })
})
