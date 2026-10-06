import { render } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { MessagesEnvelope } from '@/lib/types'

const appendMock = vi.fn()
let mockThreadEmpty = true

vi.mock('@assistant-ui/react', () => ({
  useAui: () => ({ thread: { append: appendMock } }),
  useAuiState: (selector: (s: { thread?: { isEmpty: boolean } }) => unknown) =>
    selector({ thread: { isEmpty: mockThreadEmpty } }),
}))

import { SkillBuilderAutoRequest, resolveAutoFirstMessage } from '../skill-builder-auto-request'

const ENVELOPE_EMPTY = { messages: [], active_run: null, latest_run: null } as MessagesEnvelope

function session(overrides: Partial<{ status: string; user_request: string }> = {}) {
  return {
    status: 'active',
    user_request: '帮我创建会议记录 skill',
    ...overrides,
  } as Parameters<typeof resolveAutoFirstMessage>[0]
}

describe('resolveAutoFirstMessage', () => {
  it('active session + 空对话 + 无 run 历史时返回 user_request', () => {
    expect(resolveAutoFirstMessage(session(), ENVELOPE_EMPTY)).toBe('帮我创建会议记录 skill')
  })

  it('envelope query 尚未 resolved 时不发出消息', () => {
    expect(resolveAutoFirstMessage(session(), undefined)).toBeNull()
  })

  it('存在对话历史（reload）时不发出消息', () => {
    const envelope = { ...ENVELOPE_EMPTY, messages: [{ id: 'm1' }] } as MessagesEnvelope
    expect(resolveAutoFirstMessage(session(), envelope)).toBeNull()
  })

  it('存在 run 历史（进行中或已结束的 run）时不发出消息', () => {
    const active = { ...ENVELOPE_EMPTY, active_run: { id: 'r1' } } as MessagesEnvelope
    const latest = { ...ENVELOPE_EMPTY, latest_run: { id: 'r1' } } as MessagesEnvelope
    expect(resolveAutoFirstMessage(session(), active)).toBeNull()
    expect(resolveAutoFirstMessage(session(), latest)).toBeNull()
  })

  it('session 非 active（重新进入 completed/confirming）时不发出消息', () => {
    expect(resolveAutoFirstMessage(session({ status: 'completed' }), ENVELOPE_EMPTY)).toBeNull()
    expect(resolveAutoFirstMessage(session({ status: 'confirming' }), ENVELOPE_EMPTY)).toBeNull()
  })

  it('user_request 为空白时不发出消息', () => {
    expect(resolveAutoFirstMessage(session({ user_request: '  ' }), ENVELOPE_EMPTY)).toBeNull()
    expect(resolveAutoFirstMessage(undefined, ENVELOPE_EMPTY)).toBeNull()
  })
})

describe('SkillBuilderAutoRequest', () => {
  beforeEach(() => {
    appendMock.mockClear()
    mockThreadEmpty = true
  })

  it('text 存在时准确 append 1 次 user message', () => {
    const { rerender } = render(<SkillBuilderAutoRequest text="帮我创建 skill" />)
    expect(appendMock).toHaveBeenCalledTimes(1)
    expect(appendMock).toHaveBeenCalledWith({
      content: [{ type: 'text', text: '帮我创建 skill' }],
    })

    // 父级 rerender（envelope 仍为 stale-empty）时也不会再次发出消息（ref latch）。
    rerender(<SkillBuilderAutoRequest text="帮我创建 skill" />)
    expect(appendMock).toHaveBeenCalledTimes(1)
  })

  it('text 为 null 时不 append', () => {
    render(<SkillBuilderAutoRequest text={null} />)
    expect(appendMock).not.toHaveBeenCalled()
  })

  it('live thread 非空时不 append（防止 remount 重复发出）', () => {
    mockThreadEmpty = false
    render(<SkillBuilderAutoRequest text="帮我创建 skill" />)
    expect(appendMock).not.toHaveBeenCalled()
  })

  it('thread 之后转为空状态（guard 解除）时再发出 1 次', () => {
    // production 中的真实 trigger 路径 — isThreadEmpty 初始为 false（hydration 前），
    // 当变为 true（thread ready & empty）的瞬间，effect 会重新执行并发出消息。
    mockThreadEmpty = false
    const { rerender } = render(<SkillBuilderAutoRequest text="帮我创建 skill" />)
    expect(appendMock).not.toHaveBeenCalled()

    mockThreadEmpty = true
    rerender(<SkillBuilderAutoRequest text="帮我创建 skill" />)
    expect(appendMock).toHaveBeenCalledTimes(1)
  })
})
