import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../../tests/test-utils'
import { PhaseTimelineRender } from '../phase-timeline-ui'

type ThreadMessageLite = {
  readonly role?: string
  readonly content?: readonly {
    readonly type?: string
    readonly toolName?: string
    readonly toolCallId?: string
  }[]
}

type AuiState = {
  readonly thread?: {
    readonly messages?: readonly ThreadMessageLite[]
  }
}

type MutableAuiState = {
  thread: {
    messages: readonly ThreadMessageLite[]
  }
}

const mocks = vi.hoisted(() => {
  const state: MutableAuiState = {
    thread: {
      messages: [],
    },
  }
  return { state }
})

vi.mock('@assistant-ui/react', () => ({
  useAuiState: <T,>(selector: (state: AuiState) => T): T => selector(mocks.state),
}))

describe('PhaseTimelineRender', () => {
  beforeEach(() => {
    mocks.state.thread = {
      messages: [
        {
          role: 'assistant',
          content: [{ type: 'tool-call', toolName: 'phase_timeline', toolCallId: 'phase-old' }],
        },
        {
          role: 'assistant',
          content: [{ type: 'tool-call', toolName: 'phase_timeline', toolCallId: 'phase-latest' }],
        },
      ],
    }
  })

  it('renders the latest phase_timeline tool call from assistant-ui thread state', () => {
    render(
      <PhaseTimelineRender
        toolCallId="phase-latest"
        args={{
          todos: [
            { id: 1, name: '整理需求', status: 'completed' },
            { id: 2, name: '连接 runtime', status: 'pending' },
          ],
        }}
      />,
    )

    expect(screen.getByText('整理需求')).toBeInTheDocument()
    expect(screen.getByText('连接 runtime')).toBeInTheDocument()
    expect(screen.getByText('进行中')).toBeInTheDocument()
  })

  it('hides replayed older phase_timeline tool calls', () => {
    render(
      <PhaseTimelineRender
        toolCallId="phase-old"
        args={{
          todos: [{ id: 1, name: '上一步', status: 'completed' }],
        }}
      />,
    )

    expect(screen.queryByText('上一步')).not.toBeInTheDocument()
  })
})
