import { AIMessage } from '@langchain/core/messages'
import { getDefaultStore } from 'jotai'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'
import { SubagentCard } from '../subagent-card'
import { chatSubagentNamesAtom } from '@/lib/stores/chat-subagent-names'

const mocks = vi.hoisted(() => ({
  useMessages: vi.fn(),
  useToolCalls: vi.fn(),
  useSubagentInlinePolicy: vi.fn(),
  useSubagentSnapshot: vi.fn(),
  useSubagentStream: vi.fn(),
}))

vi.mock('@langchain/react', () => ({
  useMessages: mocks.useMessages,
  useToolCalls: mocks.useToolCalls,
}))

vi.mock('@/components/chat/conversation-context', () => ({
  useChatConversationId: () => 'conversation-1',
}))

vi.mock('@/lib/chat/langgraph-runtime/subagent-runtime', () => ({
  useSubagentInlinePolicy: mocks.useSubagentInlinePolicy,
  useSubagentSnapshot: mocks.useSubagentSnapshot,
  useSubagentStream: mocks.useSubagentStream,
}))

const streamToken = { stream: 'shared' }

const researcherSnapshot = {
  id: 'tc-task-1',
  name: 'researcher',
  namespace: ['tools:tc-task-1'],
  parentId: null,
  depth: 0,
  status: 'complete',
  taskInput: '帮我调研市场资料',
  output: '调研完成',
  error: undefined,
  startedAt: new Date('2026-06-13T00:00:00Z'),
  completedAt: new Date('2026-06-13T00:01:00Z'),
}

function renderCard() {
  return render(
    <SubagentCard
      fallback={{ agentName: 'fallback', input: 'fallback input', status: 'loading' }}
      toolCallId="tc-task-1"
    />,
  )
}

describe('SubagentCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Components read the display-name map from the default Jotai store (the test
    // wrapper has no Provider). Reset it so cases without an injected mapping keep
    // showing the raw runtime name.
    getDefaultStore().set(chatSubagentNamesAtom, {})
    mocks.useSubagentSnapshot.mockReturnValue(researcherSnapshot)
    mocks.useSubagentStream.mockReturnValue(streamToken)
    mocks.useMessages.mockReturnValue([new AIMessage('详细消息')])
    mocks.useToolCalls.mockReturnValue([])
    mocks.useSubagentInlinePolicy.mockReturnValue({
      defaultExpanded: false,
      canRenderInlineDetails: true,
      overflowedLiveDetails: false,
    })
  })

  it('keeps scoped root-transcript details unmounted while a completed card is collapsed', () => {
    renderCard()

    expect(screen.getByText('researcher')).toBeInTheDocument()
    expect(screen.queryByText('详细消息')).not.toBeInTheDocument()
    expect(mocks.useMessages).not.toHaveBeenCalled()
    expect(mocks.useToolCalls).not.toHaveBeenCalled()
  })

  it('mounts scoped detail selectors for default-expanded live cards', () => {
    mocks.useSubagentSnapshot.mockReturnValue({
      ...researcherSnapshot,
      status: 'running',
      completedAt: null,
      output: undefined,
    })
    mocks.useSubagentInlinePolicy.mockReturnValue({
      defaultExpanded: true,
      canRenderInlineDetails: true,
      overflowedLiveDetails: false,
    })

    renderCard()

    expect(mocks.useMessages).toHaveBeenCalledWith(streamToken, {
      ...researcherSnapshot,
      status: 'running',
      completedAt: null,
      output: undefined,
    })
    expect(screen.getByText('详细消息')).toBeInTheDocument()
  })

  it('redacts private reasoning parts from expanded scoped messages', () => {
    mocks.useSubagentSnapshot.mockReturnValue({
      ...researcherSnapshot,
      status: 'running',
      completedAt: null,
      output: undefined,
    })
    mocks.useSubagentInlinePolicy.mockReturnValue({
      defaultExpanded: true,
      canRenderInlineDetails: true,
      overflowedLiveDetails: false,
    })
    mocks.useMessages.mockReturnValue([
      new AIMessage({
        content: [
          { type: 'text', text: '可见的详细消息' },
          { type: 'reasoning', text: 'hidden chain' },
          { type: 'thinking', text: 'private thought' },
          { type: 'text', reasoning: 'raw private reason', text: '安全的后续消息' },
        ],
      }),
    ])

    renderCard()

    expect(screen.getByText('可见的详细消息安全的后续消息')).toBeInTheDocument()
    expect(screen.queryByText(/hidden chain/)).not.toBeInTheDocument()
    expect(screen.queryByText(/private thought/)).not.toBeInTheDocument()
    expect(screen.queryByText(/raw private reason/)).not.toBeInTheDocument()
  })

  it('does not mount scoped detail selectors for overflow live cards', () => {
    mocks.useSubagentSnapshot.mockReturnValue({
      ...researcherSnapshot,
      status: 'running',
      completedAt: null,
      output: undefined,
    })
    mocks.useSubagentInlinePolicy.mockReturnValue({
      defaultExpanded: false,
      canRenderInlineDetails: false,
      overflowedLiveDetails: true,
    })

    renderCard()

    expect(screen.getByText('researcher')).toBeInTheDocument()
    expect(screen.queryByText('详细消息')).not.toBeInTheDocument()
    expect(mocks.useMessages).not.toHaveBeenCalled()
    expect(mocks.useToolCalls).not.toHaveBeenCalled()
  })

  it('substitutes the runtime name with the conversation display name when mapped', () => {
    getDefaultStore().set(chatSubagentNamesAtom, {
      'conversation-1': { researcher: '调研机器人' },
    })

    renderCard()

    expect(screen.getByText('调研机器人')).toBeInTheDocument()
    expect(screen.queryByText('researcher')).not.toBeInTheDocument()
  })

  it('keeps rail action buttons outside clickable subagent pill buttons', () => {
    mocks.useSubagentSnapshot.mockReturnValue(null)
    mocks.useSubagentStream.mockReturnValue(null)
    mocks.useSubagentInlinePolicy.mockReturnValue({
      defaultExpanded: false,
      canRenderInlineDetails: false,
      overflowedLiveDetails: false,
    })

    renderCard()

    for (const button of screen.getAllByRole('button')) {
      expect(button.querySelector('button')).toBeNull()
    }
  })
})
