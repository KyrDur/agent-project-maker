import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NextIntlClientProvider } from 'next-intl'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { server } from '../../setup'
import messages from '../../../messages/zh-CN.json'
import { TestChatPanel } from '@/app/agents/[agentId]/settings/_components/right-panel/test-chat-panel'
import type { StreamChatOptions } from '@/lib/sse/stream-chat'
import type { SSEEvent } from '@/lib/types'
import { useHiTL } from '@/lib/chat/hitl-context'

type RuntimeOptions = {
  conversationId?: string
  resumeFn?: unknown
  streamFn: (
    content: string,
    signal: AbortSignal,
    options?: StreamChatOptions,
  ) => AsyncGenerator<SSEEvent>
}
const mocks = vi.hoisted(() => ({
  runtime: vi.fn(),
  start: vi.fn(),
  chat: vi.fn(),
  assistant: vi.fn(),
  resume: vi.fn(),
  register: vi.fn(),
}))
vi.mock('@/lib/chat/use-chat-runtime', () => ({
  useChatRuntime: (options: RuntimeOptions) => {
    mocks.runtime(options)
    return { runtime: {}, onResumeDecisions: mocks.resume, registerDecision: mocks.register }
  },
}))
vi.mock('@/lib/sse/stream-chat', () => ({
  streamStartConversation: (...args: unknown[]) => {
    mocks.start(...args)
    return (async function* () {})()
  },
  streamChat: (...args: unknown[]) => {
    mocks.chat(...args)
    return (async function* () {})()
  },
}))
vi.mock('@/lib/sse/stream-assistant', () => ({ streamAssistant: mocks.assistant }))
vi.mock('@assistant-ui/react', () => ({
  AuiConfig: (value: unknown) => value,
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
vi.mock('@/lib/chat/tool-ui-registry', () => ({
  ALL_TOOLKIT: { ask_user: {}, request_approval: {} },
  createMoldyChatTools: (toolkit: unknown) => ({ toolkit }),
}))
vi.mock('@/components/chat/assistant-thread', () => ({
  AssistantThread: () => {
    const hitl = useHiTL()
    return <div data-testid="runtime-thread" data-approvals={!!hitl?.registerDecision} />
  },
}))

function mount() {
  return render(
    <NextIntlClientProvider locale="zh-CN" messages={messages}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <TestChatPanel agentId="agent-id" agentName="周报助手" />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

it('starts and continues production Agent chat and retains approval/resume semantics', async () => {
  server.use(
    http.get('http://localhost:8001/api/agents/agent-id/runtime-readiness', () =>
      HttpResponse.json({ ready: true }),
    ),
  )
  mount()
  expect(await screen.findByTestId('runtime-thread')).toHaveAttribute('data-approvals', 'true')
  const signal = new AbortController().signal
  const options = mocks.runtime.mock.lastCall?.[0] as RuntimeOptions
  await options.streamFn('First', signal).next()
  expect(mocks.start).toHaveBeenCalledWith(
    'agent-id',
    'First',
    signal,
    expect.objectContaining({ onConversationId: expect.any(Function) }),
  )
  await act(async () => {
    const call = mocks.start.mock.lastCall
    if (!call) throw new Error('Expected production chat start')
    call[3].onConversationId('conversation-id')
  })
  const next = mocks.runtime.mock.lastCall?.[0] as RuntimeOptions
  expect(next.conversationId).toBe('conversation-id')
  expect(next.resumeFn).toBeUndefined()
  await next.streamFn('Next', signal).next()
  expect(mocks.chat).toHaveBeenCalledWith('conversation-id', 'Next', signal, expect.any(Object))
  expect(mocks.assistant).not.toHaveBeenCalled()
})

it.each([
  ['llm_credential_required', '缺少兼容且可用的个人模型凭据'],
  ['no_model', '未绑定运行模型'],
  ['builder_tool_credential', '必需工具缺少兼容的个人凭据'],
])('shows the exact setup reason and action for %s in Chinese', async (code, reason) => {
  server.use(
    http.get('http://localhost:8001/api/agents/agent-id/runtime-readiness', () =>
      HttpResponse.json({ ready: false, code }),
    ),
  )
  const { container } = mount()
  await waitFor(() => expect(container).toHaveTextContent(reason))
  expect(screen.getByRole('link', { name: '配置个人凭据' })).toHaveAttribute('href', '/credentials')
  expect(screen.getByRole('link', { name: '配置工具' })).toHaveAttribute('href', '/tools')
  expect(screen.queryByTestId('runtime-thread')).not.toBeInTheDocument()
  expect(container.textContent).not.toMatch(/[\uac00-\ud7af]|agentProject\.|agent\.settings\./)
})
