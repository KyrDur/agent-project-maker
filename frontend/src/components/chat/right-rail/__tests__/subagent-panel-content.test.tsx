import { AIMessage } from '@langchain/core/messages'
import { getDefaultStore } from 'jotai'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../../tests/test-utils'
import { SubagentPanelContent } from '../subagent-panel-content'
import { chatSubagentNamesAtom } from '@/lib/stores/chat-subagent-names'

const mocks = vi.hoisted(() => ({
  useMessages: vi.fn(),
  useToolCalls: vi.fn(),
  useSharedSubagentRuntime: vi.fn(),
}))

vi.mock('@langchain/react', () => ({
  useMessages: mocks.useMessages,
  useToolCalls: mocks.useToolCalls,
}))

vi.mock('@/lib/chat/langgraph-runtime/subagent-runtime', () => ({
  useSharedSubagentRuntime: mocks.useSharedSubagentRuntime,
}))

const streamToken = { stream: 'shared' }

const subagentSnapshot = {
  id: 'tc-task-1',
  name: 'researcher',
  namespace: ['tools:exec-1'],
  parentId: null,
  depth: 0,
  status: 'complete',
  taskInput: '帮我调研市场资料',
  output: '调研完成',
  error: undefined,
  startedAt: new Date('2026-06-13T00:00:00Z'),
  completedAt: new Date('2026-06-13T00:01:00Z'),
}

describe('SubagentPanelContent', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The panel reads the display-name map from the default Jotai store; reset it
    // so cases without an injected mapping keep showing the raw runtime name.
    getDefaultStore().set(chatSubagentNamesAtom, {})
    mocks.useSharedSubagentRuntime.mockReturnValue(null)
    mocks.useMessages.mockReturnValue([])
    mocks.useToolCalls.mockReturnValue([])
  })

  it('keeps the existing pending panel when no shared LangGraph stream is available', () => {
    render(
      <SubagentPanelContent
        payload={{
          conversationId: 'conversation-1',
          toolCallId: 'tc-task-1',
          agentName: 'researcher',
          input: '帮我调研市场资料',
        }}
      />,
    )

    expect(screen.getByText('子智能体的执行详情将在运行时显示。')).toBeInTheDocument()
    expect(mocks.useMessages).not.toHaveBeenCalled()
  })

  it('renders scoped subagent messages and tools from the shared stream', () => {
    mocks.useSharedSubagentRuntime.mockReturnValue({
      conversationId: 'conversation-1',
      stream: streamToken,
      subagentsByToolCallId: new Map([['tc-task-1', subagentSnapshot]]),
    })
    mocks.useMessages.mockReturnValue([new AIMessage('详细消息')])
    mocks.useToolCalls.mockReturnValue([
      {
        name: 'web_search',
        callId: 'tool-1',
        id: 'tool-1',
        namespace: ['tools:exec-1'],
        input: { query: 'market' },
        args: { query: 'market' },
        output: '搜索完成',
        status: 'finished',
        error: undefined,
      },
    ])

    render(
      <SubagentPanelContent
        payload={{
          conversationId: 'conversation-1',
          toolCallId: 'tc-task-1',
          agentName: 'fallback',
          input: 'fallback input',
        }}
      />,
    )

    expect(mocks.useMessages).toHaveBeenCalledWith(streamToken, subagentSnapshot)
    expect(mocks.useToolCalls).toHaveBeenCalledWith(streamToken, subagentSnapshot)
    expect(screen.getByText('researcher')).toBeInTheDocument()
    expect(screen.getByText('tools:exec-1')).toBeInTheDocument()
    expect(screen.getByText('详细消息')).toBeInTheDocument()
    expect(screen.getByText('web_search')).toBeInTheDocument()
    expect(screen.getByText('调研完成')).toBeInTheDocument()
  })

  it('substitutes the runtime name with the conversation display name when mapped', () => {
    getDefaultStore().set(chatSubagentNamesAtom, {
      'conversation-1': { researcher: '调研机器人' },
    })
    mocks.useSharedSubagentRuntime.mockReturnValue({
      conversationId: 'conversation-1',
      stream: streamToken,
      subagentsByToolCallId: new Map([['tc-task-1', subagentSnapshot]]),
    })

    render(
      <SubagentPanelContent
        payload={{
          conversationId: 'conversation-1',
          toolCallId: 'tc-task-1',
          agentName: 'fallback',
          input: 'fallback input',
        }}
      />,
    )

    expect(screen.getByText('调研机器人')).toBeInTheDocument()
    expect(screen.queryByText('researcher')).not.toBeInTheDocument()
  })
})
