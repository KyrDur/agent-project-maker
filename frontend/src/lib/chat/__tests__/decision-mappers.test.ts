/**
 * Decision 映射器回归保护——与 ADR-012 §Decision schema 一一对应的 contract。
 * Decision shape 变更时，本文件是统一影响范围。
 */
import { describe, expect, it } from 'vitest'
import {
  serializeOptionListResponse,
  serializeQuestionFlowResponse,
  toApprove,
  toEdit,
  toReject,
  toRespond,
} from '../decision-mappers'

describe('toApprove', () => {
  it('返回纯 approve decision（无其他字段）', () => {
    expect(toApprove()).toEqual({ type: 'approve' })
  })
})

describe('toReject', () => {
  it('message 参数——type=reject + message', () => {
    expect(toReject('not allowed')).toEqual({ type: 'reject', message: 'not allowed' })
  })

  it('未指定 message——type=reject（无 message 字段）', () => {
    expect(toReject()).toEqual({ type: 'reject' })
  })

  it('空字符串 message 也原样保留（用户明确意图）', () => {
    expect(toReject('')).toEqual({ type: 'reject', message: '' })
  })
})

describe('toEdit', () => {
  it('原样包含 edited_action', () => {
    const edited = { name: 'send_email', args: { to: 'a@b.c' } }
    expect(toEdit(edited)).toEqual({ type: 'edit', edited_action: edited })
  })

  it('空 args 也保留', () => {
    expect(toEdit({ name: 'noop', args: {} })).toEqual({
      type: 'edit',
      edited_action: { name: 'noop', args: {} },
    })
  })
})

describe('toRespond', () => {
  it('message 参数——type=respond + message', () => {
    expect(toRespond('红色')).toEqual({ type: 'respond', message: '红色' })
  })

  it('空字符串——message 字段保持空值（响应决定是明确的）', () => {
    expect(toRespond('')).toEqual({ type: 'respond', message: '' })
  })
})

describe('serializeQuestionFlowResponse', () => {
  it('serializes ids in message and labels in receipt text', () => {
    const result = serializeQuestionFlowResponse(
      [
        {
          id: 'tone',
          label: '回答语气',
          type: 'single_select',
          options: [
            { id: 'concise', label: '简洁明了' },
            { id: 'detailed', label: '详细地' },
          ],
        },
        {
          id: 'tools',
          label: '工具',
          type: 'multi_select',
          options: [
            { id: 'web', label: 'Web Search' },
            { id: 'calendar', label: 'Calendar' },
          ],
        },
      ],
      { tone: ['concise'], tools: ['web', 'calendar'] },
    )

    expect(JSON.parse(result.message)).toEqual({
      mode: 'question_flow',
      answers: {
        tone: ['concise'],
        tools: ['web', 'calendar'],
      },
      labels: {
        tone: '简洁明了',
        tools: ['Web Search', 'Calendar'],
      },
    })
    expect(result.displayText).toBe('回答语气: 简洁明了 | 工具: Web Search, Calendar')
  })
})

describe('serializeOptionListResponse', () => {
  it('serializes selected option ids with human-readable receipt text', () => {
    const result = serializeOptionListResponse(
      [
        { id: 'web', label: 'Web Search', description: '搜索最新信息' },
        { id: 'calendar', label: 'Calendar' },
      ],
      ['web', 'calendar'],
    )

    expect(JSON.parse(result.message)).toEqual({
      mode: 'option_list',
      selection: ['web', 'calendar'],
      labels: ['Web Search', 'Calendar'],
    })
    expect(result.displayText).toBe('Web Search, Calendar')
  })
})
