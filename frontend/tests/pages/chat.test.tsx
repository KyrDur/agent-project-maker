import { render, screen, waitFor } from '../test-utils'
import ChatPage from '@/app/agents/[agentId]/conversations/[conversationId]/page'
import { mockAgent, mockMessageList } from '../mocks/fixtures'

// Mock scrollIntoView for jsdom
Element.prototype.scrollIntoView = vi.fn()

const mockPush = vi.fn()
const mockReplace = vi.fn()

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode
    href: string
    [key: string]: unknown
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

// Override: pins useParams/usePathname to the chat route fixture.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useParams: () => ({ conversationId: 'conv-1' }),
  usePathname: () => '/agents/agent-1/conversations/conv-1',
}))

// Mock React.use() for params Promise
vi.mock('react', async () => {
  const actual = await vi.importActual('react')
  return {
    ...actual,
    use: (value: unknown) => {
      if (value && typeof value === 'object' && 'agentId' in value && 'conversationId' in value)
        return value
      if (value && typeof value === 'object' && 'agentId' in value) return value
      return (actual as Record<string, unknown>).use(value)
    },
  }
})

const mockUseAgent = vi.fn()
const mockUseMessages = vi.fn()
const mockUseConversationTitle = vi.fn()
const mockInvalidateConversationNavigators = vi.fn()

vi.mock('@/lib/hooks/use-agents', () => ({
  useAgent: (...args: unknown[]) => mockUseAgent(...args),
  useAgentRuntimeReadiness: () => ({ data: { ready: true } }),
}))

vi.mock('@/lib/auth/session', () => ({
  useSession: () => ({ data: undefined }),
}))

vi.mock('@/lib/hooks/use-conversations', () => ({
  conversationKeys: {
    list: (agentId: string) => ['conversations', agentId] as const,
    pages: (agentId: string, params: unknown) =>
      ['agents', agentId, 'conversations', 'page', params] as const,
    messages: (conversationId: string) => ['messages', conversationId] as const,
    files: (conversationId: string | null | undefined) =>
      ['conversations', conversationId ?? 'none', 'files'] as const,
    debugTraces: (conversationId: string) => ['debug-traces', conversationId] as const,
    debugTraceDetail: (conversationId: string, traceId: string) =>
      ['debug-traces', conversationId, traceId] as const,
  },
  invalidateConversationNavigators: (...args: unknown[]) =>
    mockInvalidateConversationNavigators(...args),
  // W2-7 follow-up 幽灵建议 — 页面测试中将建议 fetch 设为 no-op。
  useFollowupSuggestionMutation: () => ({
    mutateAsync: async () => ({ suggestion: null }),
  }),
  useMessages: (...args: unknown[]) => mockUseMessages(...args),
  useMessagesEnvelope: (...args: unknown[]) => {
    const result = mockUseMessages(...args)
    if (args[1] === false) {
      return {
        data: {
          messages: [],
          active_checkpoint_id: null,
          total_cost: 0,
        },
        isLoading: false,
      }
    }
    return {
      ...result,
      data:
        result.data === undefined
          ? undefined
          : {
              messages: result.data,
              active_checkpoint_id: null,
              total_cost: 0,
            },
    }
  },
  useCreateConversation: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useMarkConversationRead: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useConversations: () => ({
    data: [],
    isLoading: false,
  }),
  useConversationPages: () => ({
    data: { pages: [{ items: [], next_cursor: null, has_more: false }] },
    isLoading: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
    isFetchingNextPage: false,
  }),
  useGlobalConversationPages: () => ({
    data: { pages: [{ items: [], next_cursor: null, has_more: false }] },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
    isFetchingNextPage: false,
  }),
  useConversationDebugTraces: () => ({
    data: { conversation_id: 'conv-1', langfuse_enabled: false, traces: [], fallback_reason: null },
    isLoading: false,
    refetch: vi.fn(),
  }),
  useConversationDebugTraceDetail: () => ({
    data: undefined,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useUpdateConversation: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useDeleteConversation: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('@/lib/hooks/use-conversation-title', () => ({
  useConversationTitle: (...args: unknown[]) => mockUseConversationTitle(...args),
}))

vi.mock('@/lib/chat/runtime-mode', () => ({
  getChatRuntimeMode: () => 'legacy',
}))

vi.mock('@/components/shared/delete-confirm-dialog', () => ({
  DeleteConfirmDialog: () => null,
}))

const mockStreamChat = vi.fn()
const mockStreamStartConversation = vi.fn()

vi.mock('@/lib/sse/stream-chat', () => ({
  streamChat: (...args: unknown[]) => mockStreamChat(...args),
  streamStartConversation: (...args: unknown[]) => mockStreamStartConversation(...args),
}))

const mockToastError = vi.fn()
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => mockToastError(...args), success: vi.fn() },
}))

vi.mock('jotai', async () => {
  const actual = await vi.importActual('jotai')
  return {
    ...actual,
    useSetAtom: () => vi.fn(),
    useAtomValue: () => ({ inputTokens: 0, outputTokens: 0, cost: 0 }),
  }
})

describe('ChatPage', () => {
  beforeEach(() => {
    mockUseAgent.mockClear()
    mockUseMessages.mockClear()
    mockUseConversationTitle.mockClear()
    mockInvalidateConversationNavigators.mockClear()
    mockUseAgent.mockReturnValue({ data: undefined })
    mockUseConversationTitle.mockReturnValue('Test Conversation')
    mockUseMessages.mockReturnValue({
      data: undefined,
      isLoading: false,
    })
    mockStreamChat.mockClear()
    mockStreamStartConversation.mockClear()
    mockPush.mockClear()
    mockReplace.mockClear()
    mockToastError.mockClear()
  })

  it('renders chat input area', () => {
    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    expect(screen.getByPlaceholderText('示例：请说明你能帮我完成什么，并给出一个输入示例')).toBeInTheDocument()
  })

  it('renders loading skeletons when messages loading', () => {
    mockUseMessages.mockReturnValue({
      data: undefined,
      isLoading: true,
    })
    const { container } = render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    const skeletons = container.querySelectorAll("[data-slot='skeleton']")
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders message list when data loaded', () => {
    mockUseMessages.mockReturnValue({
      data: mockMessageList,
      isLoading: false,
    })
    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    expect(screen.getByText('Hello, how are you?')).toBeInTheDocument()
  })

  it('shows resolved conversation title in header when loaded', () => {
    mockUseAgent.mockReturnValue({ data: mockAgent })
    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    expect(screen.getByText('Test Conversation')).toBeInTheDocument()
  })

  it('shows empty conversation prompt when no messages', () => {
    mockUseMessages.mockReturnValue({
      data: [],
      isLoading: false,
    })
    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    expect(screen.getAllByText('试用示例（虚构输入，可编辑后发送）').length).toBeGreaterThanOrEqual(1)
  })

  it('calls streamChat when message is sent', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()

    // Mock streamChat to return an async iterable that ends immediately
    mockStreamChat.mockReturnValue(
      (async function* () {
        yield {
          event: 'content_delta',
          data: { content: 'Hello!' },
        }
        yield {
          event: 'message_end',
          data: {},
        }
      })(),
    )

    mockUseMessages.mockReturnValue({ data: [], isLoading: false })

    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )

    const textarea = screen.getByPlaceholderText('示例：请说明你能帮我完成什么，并给出一个输入示例')
    await user.type(textarea, 'Test message')
    const sendButton = screen.getByRole('button', { name: /发送/ })
    await user.click(sendButton)

    // streamChat: (conversationId, content, signal, options).
    // 引入 P1-7 附件后，chat-input 始终传递空 attachmentIds 数组。
    expect(mockStreamChat).toHaveBeenCalledWith(
      'conv-1',
      'Test message',
      expect.any(AbortSignal),
      expect.objectContaining({ attachmentIds: expect.any(Array) }),
    )
  })

  it('renders draft conversation without loading server messages', () => {
    mockUseAgent.mockReturnValue({ data: mockAgent })
    mockUseMessages.mockReturnValue({
      data: undefined,
      isLoading: true,
    })

    const { container } = render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'new',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )

    expect(mockUseMessages).toHaveBeenCalledWith('new', false)
    expect(screen.getByPlaceholderText('示例：请说明你能帮我完成什么，并给出一个输入示例')).toBeInTheDocument()
    expect(container.querySelectorAll("[data-slot='skeleton']")).toHaveLength(0)
  })

  it('starts a conversation from draft and replaces the URL after streaming', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()

    mockUseMessages.mockReturnValue({ data: [], isLoading: false })
    mockStreamStartConversation.mockImplementation(
      async function* (_agentId, _content, _signal, options) {
        options.onConversationId('conv-started')
        yield {
          event: 'message_end',
          data: {},
        }
      },
    )

    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'new',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )

    await user.type(screen.getByPlaceholderText('示例：请说明你能帮我完成什么，并给出一个输入示例'), 'Draft message')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    expect(mockStreamStartConversation).toHaveBeenCalledWith(
      'agent-1',
      'Draft message',
      expect.any(AbortSignal),
      expect.objectContaining({ attachmentIds: expect.any(Array) }),
    )
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/agents/agent-1/conversations/conv-started')
    })
  })

  it('handles stream with tool calls', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()

    mockStreamChat.mockReturnValue(
      (async function* () {
        yield {
          event: 'tool_call_start',
          data: { name: 'web_search', args: { query: 'test' } },
        }
        yield {
          event: 'tool_call_result',
          data: { result: 'search results' },
        }
        yield {
          event: 'content_delta',
          data: { delta: 'Based on search...' },
        }
        yield {
          event: 'message_end',
          data: {},
        }
      })(),
    )

    mockUseMessages.mockReturnValue({ data: [], isLoading: false })

    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )

    const textarea = screen.getByPlaceholderText('示例：请说明你能帮我完成什么，并给出一个输入示例')
    await user.type(textarea, 'Search for something')
    const sendButton = screen.getByRole('button', { name: /发送/ })
    await user.click(sendButton)

    expect(mockStreamChat).toHaveBeenCalled()
  })

  // streamChat 错误处理已移入 useChatRuntime 内部（M? assistant-ui 集成）。
  // 因为在页面外 mock 的 streamChat 结果不会直接转换成 toast.error，
  // 无法通过单元测试验证。改用 e2e/smoke 或 manual QA。
  it('removes the chat-local conversation list and keeps compact agent context', () => {
    mockUseAgent.mockReturnValue({ data: mockAgent })
    render(
      <ChatPage
        params={
          {
            agentId: 'agent-1',
            conversationId: 'conv-1',
          } as unknown as Promise<{
            agentId: string
            conversationId: string
          }>
        }
      />,
    )
    expect(screen.queryByText('对话')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '智能体信息' })).toBeInTheDocument()
  })
})
