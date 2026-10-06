import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen } from '../../../../tests/test-utils'
import { StreamingMessageLoadingIndicator } from '../assistant-message-loading'
import type { RunActivity } from '@/lib/chat/langgraph-runtime/activity-model'

const mocks = vi.hoisted(() => ({
  state: {
    thread: { isRunning: true },
    message: {
      metadata: { custom: { isStreamingMessage: true as boolean | undefined } } as
        | { custom: { isStreamingMessage: boolean | undefined } }
        | undefined,
      status: undefined as { readonly type?: string } | undefined,
      parts: [] as readonly unknown[],
    },
  },
  useSubagentProgressSummary: vi.fn(),
}))

vi.mock('@assistant-ui/react', () => ({
  AuiIf: ({
    children,
    condition,
  }: {
    children: ReactNode
    condition: (state: typeof mocks.state) => boolean
  }) => (condition(mocks.state) ? <>{children}</> : null),
  useAuiState: (selector: (state: typeof mocks.state) => unknown) => selector(mocks.state),
}))

vi.mock('@/components/chat/witty-loading', () => ({
  WittyLoadingMessage: () => <div data-testid="witty-loading">witty</div>,
}))

vi.mock('@/lib/chat/langgraph-runtime/subagent-runtime', () => ({
  useSubagentProgressSummary: mocks.useSubagentProgressSummary,
}))

function activity(overrides: Partial<RunActivity> = {}): RunActivity {
  return {
    id: overrides.id ?? 'activity-1',
    runId: overrides.runId ?? 'run-1',
    kind: overrides.kind ?? 'tool',
    status: overrides.status ?? 'running',
    title: overrides.title ?? 'web_search',
    namespace: overrides.namespace ?? [],
    ...overrides,
  }
}

describe('StreamingMessageLoadingIndicator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.state.thread.isRunning = true
    mocks.state.message.metadata = { custom: { isStreamingMessage: true } }
    mocks.state.message.status = undefined
    mocks.state.message.parts = []
    mocks.useSubagentProgressSummary.mockReturnValue({
      total: 0,
      running: 0,
      completed: 0,
      failed: 0,
    })
  })

  it('shows witty loading when no semantic activity exists', () => {
    render(<StreamingMessageLoadingIndicator activities={[]} />)

    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('run-activity-strip')).not.toBeInTheDocument()
  })

  it('shows witty loading when assistant-ui marks the message running', () => {
    mocks.state.message.metadata = { custom: { isStreamingMessage: undefined } }
    mocks.state.message.status = { type: 'running' }

    render(<StreamingMessageLoadingIndicator activities={[]} />)

    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('run-activity-strip')).not.toBeInTheDocument()
  })

  it('hides witty loading when semantic activity exists', () => {
    render(<StreamingMessageLoadingIndicator activities={[activity()]} />)

    expect(screen.getByTestId('run-activity-strip')).toBeInTheDocument()
    expect(screen.queryByTestId('witty-loading')).not.toBeInTheDocument()
  })

  it('keeps witty loading when only interrupt activities exist', () => {
    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:interrupt:one',
            kind: 'interrupt',
            status: 'requires_action',
            title: 'Needs approval',
          }),
          activity({
            id: 'run-1:interrupt:two',
            kind: 'interrupt',
            status: 'requires_action',
            title: 'Needs approval',
          }),
        ]}
      />,
    )

    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('run-activity-strip')).not.toBeInTheDocument()
  })

  it('keeps witty loading when only generic responding and terminal rows exist while streaming', () => {
    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:responding:root',
            kind: 'responding',
            status: 'running',
            title: 'Responding',
          }),
          activity({
            id: 'run-1:responding:old',
            kind: 'responding',
            status: 'complete',
            title: 'Responding',
          }),
          activity({
            id: 'run-1:done:run',
            kind: 'done',
            status: 'complete',
            title: 'Done',
          }),
        ]}
      />,
    )

    expect(screen.queryByTestId('run-activity-strip')).not.toBeInTheDocument()
    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
    expect(screen.queryByText('写回复')).not.toBeInTheDocument()
    expect(screen.queryByText('完成')).not.toBeInTheDocument()
  })

  it('keeps witty loading once assistant text is visible while streaming', () => {
    mocks.state.message.parts = [{ type: 'text', text: 'Partial assistant response' }]

    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:responding:root',
            kind: 'responding',
            status: 'running',
            title: 'Responding',
          }),
        ]}
      />,
    )

    expect(screen.queryByTestId('run-activity-strip')).not.toBeInTheDocument()
    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
  })

  it('keeps non-text progress visible while assistant text is streaming', () => {
    mocks.state.message.parts = [{ type: 'text', text: 'Partial assistant response' }]

    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:tool:search',
            kind: 'tool',
            status: 'running',
            title: 'web_search',
          }),
        ]}
      />,
    )

    expect(screen.getByTestId('run-activity-strip')).toBeInTheDocument()
    expect(screen.getByText('运行web_search')).toBeInTheDocument()
    expect(screen.queryByTestId('witty-loading')).not.toBeInTheDocument()
  })

  it('keeps completed current-run activity in expanded history while another activity runs', async () => {
    const user = userEvent.setup()
    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:tool:completed-search',
            kind: 'tool',
            status: 'complete',
            title: 'completed_search',
          }),
          activity({
            id: 'run-1:tool:running-fetch',
            kind: 'tool',
            status: 'running',
            title: 'running_fetch',
          }),
        ]}
      />,
    )

    await user.click(screen.getByRole('button', { name: '显示活动' }))

    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('completed_search')).toBeInTheDocument()
    expect(screen.getByText('running_fetch')).toBeInTheDocument()
  })

  it('shows the live panel for files but defers todos to the message plan card', () => {
    render(
      <StreamingMessageLoadingIndicator
        activities={[]}
        deepAgentsState={{
          todos: [{ id: 'todo-1', content: 'Plan work', status: 'in_progress' }],
          files: [{ id: 'file-1', name: 'brief.md', path: 'reports/brief.md', sizeBytes: 1200 }],
        }}
      />,
    )

    // Files are live-only, so they render in the loading panel...
    expect(screen.getByText('文件')).toBeInTheDocument()
    // ...but the todos are not duplicated here — the assistant message's
    // persistent "Plan" card (write_todos tool-ui) is their single source.
    expect(screen.queryByText('任务列表')).not.toBeInTheDocument()
    expect(screen.queryByText('Plan work')).not.toBeInTheDocument()
    expect(screen.queryByTestId('witty-loading')).not.toBeInTheDocument()
  })

  it('defers a todos-only run to witty loading (todos shown by the message plan card)', () => {
    render(
      <StreamingMessageLoadingIndicator
        activities={[]}
        deepAgentsState={{
          todos: [{ id: 'todo-1', content: 'Plan work', status: 'in_progress' }],
          files: [],
        }}
      />,
    )

    expect(screen.queryByText('任务列表')).not.toBeInTheDocument()
    expect(screen.getByTestId('witty-loading')).toBeInTheDocument()
  })

  it('renders nothing outside the active streaming message', () => {
    // 已完成消息的真实形态：convert-message 只在 streaming 时
    // 设置 isStreamingMessage=true，完成后会直接省略该字段（不会写 false）。
    // status 也不是 running，因此两个信号都处于关闭状态。
    mocks.state.message.metadata = { custom: { isStreamingMessage: undefined } }
    mocks.state.message.status = { type: 'complete' }

    const { container } = render(<StreamingMessageLoadingIndicator activities={[activity()]} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('M6 — a completed message with neither metadata flag nor running status is not streaming', () => {
    // 回归测试用于覆盖担忧：sticky/converted 复用可能在已完成消息中残留 stale running。
    // production 路径不会在已完成消息中写 isStreamingMessage:false，
    // metadata.custom 本身也可能不存在，因此固定验证在真实可发生的形态（字段缺失 +
    // 非 running）下不会误判为 streaming。
    mocks.state.message.metadata = undefined
    mocks.state.message.status = { type: 'complete' }

    const { container } = render(<StreamingMessageLoadingIndicator activities={[activity()]} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('scopes subagent progress to inline subagents in the current assistant turn', () => {
    mocks.useSubagentProgressSummary.mockImplementation((toolCallIds: readonly string[]) => {
      if (toolCallIds.includes('tc-current')) {
        return { total: 1, running: 0, completed: 1, failed: 0 }
      }
      return { total: 2, running: 0, completed: 2, failed: 0 }
    })

    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:subagent:tc-current',
            kind: 'subagent',
            toolCallId: 'tc-current',
            status: 'complete',
            title: 'Researcher',
          }),
          activity({
            id: 'run-1:background_subagent:bg-1',
            kind: 'background_subagent',
            status: 'running',
            title: 'Background writer',
          }),
        ]}
      />,
    )

    expect(mocks.useSubagentProgressSummary).toHaveBeenCalledWith(['tc-current'])
    expect(screen.getByText('子智能体 1/1 完成')).toBeInTheDocument()
    expect(screen.queryByText('2/2 子 智能体 完成')).not.toBeInTheDocument()
  })

  it('renders background subagent tasks as activity rows distinct from inline progress cards', () => {
    render(
      <StreamingMessageLoadingIndicator
        activities={[
          activity({
            id: 'run-1:background_subagent:bg-1',
            kind: 'background_subagent',
            status: 'running',
            title: 'Background writer',
          }),
        ]}
      />,
    )

    expect(screen.getByTestId('run-activity-strip')).toBeInTheDocument()
    expect(screen.getByText('Background writer 正在工作')).toBeInTheDocument()
    expect(screen.getByText('Background writer 正在工作').closest('[data-kind]')).toHaveAttribute(
      'data-kind',
      'background_subagent',
    )
    expect(screen.queryByRole('progressbar', { name: '子智能体进度' })).not.toBeInTheDocument()
  })
})
