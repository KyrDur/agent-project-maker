import { useState, type ReactNode } from 'react'
import { act } from '@testing-library/react'
import { render, screen, userEvent } from '../../test-utils'
import { AssistantPanel } from '@/components/agent/assistant-panel'
import { useHiTL } from '@/lib/chat/hitl-context'
import type { Decision, SSEEvent } from '@/lib/types'

// --- Mocks ---

const mockRegisterDecision = vi.fn()
const mockOnResumeDecisions = vi.fn()
const mockSendMessage = vi.fn()
const mockInvalidateQueries = vi.fn()
const mockUseChatRuntime = vi.fn(() => ({
  runtime: { kind: 'assistant-panel-runtime' },
  onResumeDecisions: mockOnResumeDecisions,
  registerDecision: mockRegisterDecision,
  sendMessage: mockSendMessage,
}))

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>()
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
  }
})

vi.mock('@assistant-ui/react', () => ({
  AuiConfig: (config: unknown) => config,
  Tools: ({ toolkit }: { toolkit: Record<string, unknown> }) => ({ toolkit }),
  AssistantRuntimeProvider: ({
    children,
    config,
  }: {
    children: ReactNode
    config: { tools: { toolkit: Record<string, unknown> } }
  }) => (
    <div
      data-testid="assistant-runtime-provider"
      data-tool-names={Object.keys(config.tools.toolkit).join(',')}
    >
      {children}
    </div>
  ),
  useAui: () => ({ optional: { composer: { setText: vi.fn() } } }),
}))

vi.mock('@/lib/chat/use-chat-runtime', () => ({
  useChatRuntime: (...args: unknown[]) => mockUseChatRuntime(...args),
}))

vi.mock('@/lib/chat/tool-ui-registry', () => ({
  ALL_TOOLKIT: { request_approval: {}, ask_user: {} },
}))

vi.mock('@/components/chat/assistant-thread', () => ({
  AssistantThread: ({ emptyContent }: { emptyContent: ReactNode }) => {
    const hitl = useHiTL()
    return (
      <div
        data-has-register-decision={String(typeof hitl?.registerDecision === 'function')}
        data-testid="assistant-thread"
      >
        {emptyContent}
      </div>
    )
  },
}))

vi.mock('@/components/chat/markdown-content', () => ({
  MarkdownContent: ({ content }: { content: string }) => <span>{content}</span>,
}))

vi.mock('@/components/chat/markdown-components', () => ({
  // 测试本身不验证 markdown 渲染 — 使用空对象 stub。
  buildMarkdownComponents: () => ({}),
}))

vi.mock('@/components/chat/chat-image', () => ({
  ChatImage: () => null,
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const mockStreamAssistant = vi.fn()
const mockStreamAssistantResume = vi.fn()

vi.mock('@/lib/sse/stream-assistant', () => ({
  streamAssistant: (...args: unknown[]) => mockStreamAssistant(...args),
  streamAssistantResume: (...args: unknown[]) => mockStreamAssistantResume(...args),
}))

type ResumeFn = (
  decisions: Decision[],
  signal: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
) => AsyncGenerator<SSEEvent>

type ChatRuntimeOptions = {
  messages?: Message[]
  onMessagesCommit?: (messages: Message[]) => void
  resumeFn?: ResumeFn
  onStreamEnd?: (didMutate: boolean) => void
}

describe('AssistantPanel', () => {
  beforeEach(() => {
    mockStreamAssistant.mockReset()
    mockRegisterDecision.mockReset()
    mockOnResumeDecisions.mockReset()
    mockSendMessage.mockReset()
    mockUseChatRuntime.mockClear()
    mockStreamAssistantResume.mockReset()
    mockInvalidateQueries.mockReset()
    // jsdom 中没有 scrollTo，因此用 stub 处理
    Element.prototype.scrollTo = vi.fn()
  })

  // assistant-ui 的 ThreadEmptyMessage 在 jsdom 中无法同步完成 thread state 初始化，
  // 导致 emptyContent 非确定性渲染。只验证到 hero title。
  it('初始渲染时显示 hero title', () => {
    render(<AssistantPanel agentId="agent-1" agentName="Test Agent" />)

    // EmptyContent 的 FixHero 用 ``fixHeroTitle({ agentName })`` key（"修复{agentName}"）渲染。
    expect(screen.getByText('修复Test Agent')).toBeInTheDocument()
  })

  it('向 AssistantThread 提供 write 工具 approval UI 与 HiTL resume context', () => {
    render(<AssistantPanel agentId="agent-1" agentName="Test Agent" />)

    const provider = screen.getByTestId('assistant-runtime-provider')
    const thread = screen.getByTestId('assistant-thread')
    expect(provider).toHaveAttribute('data-tool-names', 'request_approval,ask_user')
    expect(thread).toHaveAttribute('data-has-register-decision', 'true')
  })

  it('通过 Assistant resume SSE 恢复 approval 决策', async () => {
    const decision: Decision = { type: 'approve' }
    mockStreamAssistantResume.mockImplementation(async function* (): AsyncGenerator<SSEEvent> {
      yield { event: 'message_end', data: { content: 'done' } } as SSEEvent
    })

    render(<AssistantPanel agentId="agent-1" agentName="Test Agent" />)

    const options = mockUseChatRuntime.mock.calls[0]?.[0] as ChatRuntimeOptions
    const resumeFn = options.resumeFn
    expect(resumeFn).toBeTypeOf('function')
    if (!resumeFn) throw new Error('Assistant resume function should be registered')

    const signal = new AbortController().signal
    for await (const _event of resumeFn([decision], signal, '已批准', 'intr-1')) {
      void _event
    }

    expect(mockStreamAssistantResume).toHaveBeenCalledWith(
      'agent-1',
      [decision],
      signal,
      '已批准',
      'intr-1',
      expect.any(String),
    )
  })

  it('批准恢复完成后刷新智能体设置缓存', async () => {
    mockStreamAssistantResume.mockImplementation(async function* (): AsyncGenerator<SSEEvent> {
      yield { event: 'message_end', data: { content: 'done' } } as SSEEvent
    })

    render(<AssistantPanel agentId="agent-1" agentName="Test Agent" />)

    const options = mockUseChatRuntime.mock.calls[0]?.[0] as ChatRuntimeOptions
    const resumeFn = options.resumeFn
    if (!resumeFn) throw new Error('Assistant resume function should be registered')
    const signal = new AbortController().signal
    for await (const _event of resumeFn([{ type: 'approve' }], signal)) {
      void _event
    }
    options.onStreamEnd?.(false)

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['agents'] })
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['agents', 'agent-1'] })
  })

  it('即使关闭再重新打开侧边聊天，也保留同一会话的消息', async () => {
    function Harness() {
      const [open, setOpen] = useState(true)
      const [messages, setMessages] = useState<Message[]>([])
      return (
        <>
          <button type="button" onClick={() => setOpen((value) => !value)}>
            toggle
          </button>
          {open ? (
            <AssistantPanel
              agentId="agent-1"
              agentName="Test Agent"
              session={{
                sessionId: 'side-session-1',
                messages,
                onMessagesCommit: (committed) =>
                  setMessages((current) => [...current, ...committed]),
              }}
            />
          ) : null}
        </>
      )
    }

    const user = userEvent.setup()
    render(<Harness />)
    const firstOptions = mockUseChatRuntime.mock.calls[0]?.[0] as ChatRuntimeOptions
    act(() => {
      firstOptions.onMessagesCommit?.([
        { id: 'side-message-1', role: 'assistant', content: 'retained' } as Message,
      ])
    })

    await user.click(screen.getByRole('button', { name: 'toggle' }))
    await user.click(screen.getByRole('button', { name: 'toggle' }))

    const reopenedOptions = mockUseChatRuntime.mock.calls.at(-1)?.[0] as ChatRuntimeOptions
    expect(reopenedOptions.messages).toEqual([
      expect.objectContaining({ id: 'side-message-1', content: 'retained' }),
    ])
  })
})
