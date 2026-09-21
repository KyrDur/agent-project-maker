import { Suspense, type ReactNode } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import Page from '@/app/agents/new/conversational/page'
import messages from '../../messages/zh-CN.json'
import type { Message, SSEEvent } from '@/lib/types'

type Options = {
  messages: Message[]
  onStreamEnd: () => void
  resumeFn: (decisions: unknown[], signal: AbortSignal) => AsyncGenerator<SSEEvent>
}
const mocks = vi.hoisted(() => ({
  snapshot: vi.fn(),
  start: vi.fn(),
  getSession: vi.fn(),
  send: vi.fn(),
  resume: vi.fn(),
  options: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}))
const router = { push: mocks.push, replace: mocks.replace }
vi.mock('next/navigation', () => ({ useRouter: () => router }))
vi.mock('@/lib/api/builder', () => ({ builderApi: mocks }))
vi.mock('@/lib/sse/stream-builder-resume', () => ({
  streamBuilderResume: (...args: unknown[]) => {
    mocks.resume(...args)
    return (async function* () {})()
  },
}))
vi.mock('@/lib/chat/use-chat-runtime', () => ({
  useChatRuntime: (options: Options) => {
    mocks.options(options)
    return { runtime: {}, sendMessage: mocks.send }
  },
}))
vi.mock('@assistant-ui/react', () => ({
  AuiConfig: (value: unknown) => value,
  Tools: (value: unknown) => value,
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
vi.mock('@/lib/chat/tool-ui-registry', () => ({ BUILDER_TOOLKIT: {} }))
vi.mock('@/components/chat/assistant-thread', () => ({
  AssistantThread: () => <div data-testid="builder-thread" />,
}))

async function mount(params: { sessionId?: string; initialMessage?: string }) {
  const searchParams = Promise.resolve(params)
  await act(async () => {
    render(
      <NextIntlClientProvider locale="zh-CN" messages={messages}>
        <Suspense>
          <Page searchParams={searchParams} />
        </Suspense>
      </NextIntlClientProvider>,
    )
  })
}

beforeEach(() => vi.clearAllMocks())

it('restores the existing session and interrupt without starting or resending a build', async () => {
  const history = [{ id: 'message', role: 'assistant', content: '智能体设置确认' }]
  mocks.snapshot.mockResolvedValue({
    messages: history,
    interrupt_id: 'interrupt-1',
    status: 'preview',
  })
  await mount({ sessionId: 'session-1', initialMessage: '整理周报' })
  await screen.findByTestId('builder-thread')
  const options = mocks.options.mock.lastCall?.[0] as Options
  expect(options.messages).toEqual(history)
  await options.resumeFn([{ type: 'approve' }], new AbortController().signal).next()
  expect(mocks.resume).toHaveBeenCalledWith(
    'session-1',
    expect.any(Array),
    expect.any(AbortSignal),
    undefined,
    'interrupt-1',
  )
  expect(mocks.start).not.toHaveBeenCalled()
  expect(mocks.send).not.toHaveBeenCalled()
})

it('opens Project after a completed session is restored', async () => {
  mocks.snapshot.mockResolvedValue({
    messages: [],
    interrupt_id: null,
    status: 'completed',
    agent_id: 'agent-1',
  })
  await mount({ sessionId: 'session-1' })
  await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith('/agents/agent-1/project'))
  expect(mocks.start).not.toHaveBeenCalled()
})

it('opens Project when the live Builder completes', async () => {
  mocks.snapshot.mockResolvedValue({ messages: [], interrupt_id: null, status: 'preview' })
  mocks.getSession.mockResolvedValue({ status: 'completed', agent_id: 'agent-1' })
  await mount({ sessionId: 'session-1' })
  await screen.findByTestId('builder-thread')
  const options = mocks.options.mock.lastCall?.[0] as Options
  options.onStreamEnd()
  await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/agents/agent-1/project'))
})

it('shows an actionable Chinese restore error instead of an empty new session', async () => {
  mocks.snapshot.mockRejectedValue(new Error('offline'))
  await mount({ sessionId: 'session-1' })
  expect(await screen.findByText(messages.agent.conversational.restoreError)).toBeVisible()
  expect(screen.queryByTestId('builder-thread')).not.toBeInTheDocument()
  expect(mocks.start).not.toHaveBeenCalled()
})
