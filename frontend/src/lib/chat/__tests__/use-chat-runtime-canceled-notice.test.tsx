import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConversationRun, Message, SSEEvent } from '@/lib/types'
import { appendDurableCanceledNotice, useChatRuntime } from '../use-chat-runtime'

const mocks = vi.hoisted(() => ({
  setAtom: vi.fn(),
  translate: (key: string) => key,
}))

vi.mock('next-intl', () => ({
  useTranslations: () => mocks.translate,
}))

vi.mock('jotai', async () => {
  const actual = await vi.importActual<typeof import('jotai')>('jotai')
  return {
    ...actual,
    useSetAtom: () => mocks.setAtom,
    useAtomValue: () => undefined,
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/lib/api/conversation-runs', () => ({
  conversationRunsApi: { cancel: vi.fn() },
}))

vi.mock('@/lib/sse/stream-resume-attach', () => ({
  streamResumeAttach: vi.fn(),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function conversationRun(
  status: ConversationRun['status'],
  overrides?: Partial<ConversationRun>,
): ConversationRun {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    agent_id: 'agent-1',
    status,
    source: 'chat',
    parent_run_id: null,
    worker_instance_id: null,
    interrupt_id: null,
    last_event_id: null,
    input_preview: null,
    error_code: null,
    error_message: null,
    cancel_requested_at: '2026-06-11T00:00:01.000Z',
    started_at: '2026-06-11T00:00:00.000Z',
    heartbeat_at: null,
    completed_at: '2026-06-11T00:00:02.000Z',
    created_at: '2026-06-11T00:00:00.000Z',
    updated_at: '2026-06-11T00:00:02.000Z',
    ...overrides,
    metrics: overrides?.metrics ?? null,
  }
}

function message(overrides: Pick<Message, 'id' | 'role' | 'content'> & Partial<Message>): Message {
  return {
    conversation_id: 'conversation-1',
    tool_calls: null,
    tool_call_id: null,
    created_at: '2026-06-11T00:00:00.000Z',
    ...overrides,
  }
}

async function* emptyStream(): AsyncGenerator<SSEEvent> {}

/** 提取 thread 渲染列表中每条消息的文本（连接文本 part）。 */
function threadTexts(runtime: ReturnType<typeof useChatRuntime>['runtime']): string[] {
  return runtime.thread
    .getState()
    .messages.map((m) => m.content.map((part) => (part.type === 'text' ? part.text : '')).join(''))
}

const CANCELED_TEXT = '响应已中断'

describe('appendDurableCanceledNotice', () => {
  it('在最后一条 assistant 消息末尾追加 notice 文本且不修改原文', () => {
    const original = [
      message({ id: 'm1', role: 'user', content: '问题' }),
      message({ id: 'm2', role: 'assistant', content: '部分响应' }),
    ]

    const result = appendDurableCanceledNotice(original, CANCELED_TEXT, conversationRun('canceled'))

    expect(result).toHaveLength(2)
    expect(result[1].content).toBe(`部分响应\n\n${CANCELED_TEXT}`)
    expect(original[1].content).toBe('部分响应')
  })

  it('notice 已存在时不重复追加', () => {
    const original = [
      message({ id: 'm1', role: 'assistant', content: `部分响应\n\n${CANCELED_TEXT}` }),
    ]

    const result = appendDurableCanceledNotice(original, CANCELED_TEXT, conversationRun('canceled'))

    expect(result).toHaveLength(1)
    expect(result[0].content).toBe(`部分响应\n\n${CANCELED_TEXT}`)
  })

  it('对内容为空的 assistant 消息只填入 notice 文本', () => {
    const original = [message({ id: 'm1', role: 'assistant', content: '' })]

    const result = appendDurableCanceledNotice(original, CANCELED_TEXT, conversationRun('canceled'))

    expect(result[0].content).toBe(CANCELED_TEXT)
  })

  it('最后一条是 user 消息时，追加以 run id 为键的合成 assistant notice', () => {
    const original = [message({ id: 'm1', role: 'user', content: '问题' })]
    const run = conversationRun('canceled')

    const result = appendDurableCanceledNotice(original, CANCELED_TEXT, run)

    expect(result).toHaveLength(2)
    expect(result[1]).toMatchObject({
      id: 'canceled-run-1',
      role: 'assistant',
      content: CANCELED_TEXT,
      created_at: run.completed_at,
    })
  })

  it('合成 notice 的 created_at 按 completed_at → cancel_requested_at → updated_at 顺序选择', () => {
    const original = [message({ id: 'm1', role: 'user', content: '问题' })]
    const withoutCompleted = conversationRun('canceling', { completed_at: null })
    const withoutBoth = conversationRun('canceling', {
      completed_at: null,
      cancel_requested_at: null,
    })

    const fromCancelRequested = appendDurableCanceledNotice(
      original,
      CANCELED_TEXT,
      withoutCompleted,
    )
    const fromUpdated = appendDurableCanceledNotice(original, CANCELED_TEXT, withoutBoth)

    expect(fromCancelRequested[1].created_at).toBe(withoutCompleted.cancel_requested_at)
    expect(fromUpdated[1].created_at).toBe(withoutBoth.updated_at)
  })
})

describe('useChatRuntime durable canceled notice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('latest_run 为 canceled 时，仅根据 fetch 消息渲染 notice（refetch 清空/刷新场景）', async () => {
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [
            message({ id: 'm1', role: 'user', content: '问题' }),
            message({ id: 'm2', role: 'assistant', content: '部分响应' }),
          ],
          streamFn: emptyStream,
          conversationId: 'conversation-1',
          latestRun: conversationRun('canceled'),
        }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      const texts = threadTexts(result.current.runtime)
      // useTranslations mock 原样返回 key，因此 notice 文本为 'canceled'
      expect(texts[texts.length - 1]).toBe('部分响应\n\ncanceled')
    })
  })

  it('在输出前被取消、没有 assistant 消息时渲染合成 notice 消息', async () => {
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [message({ id: 'm1', role: 'user', content: '问题' })],
          streamFn: emptyStream,
          conversationId: 'conversation-1',
          latestRun: conversationRun('canceled'),
        }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      const texts = threadTexts(result.current.runtime)
      expect(texts).toHaveLength(2)
      expect(texts[1]).toBe('canceled')
    })
  })

  it('canceling 状态也渲染 notice（刚 cancel、worker 转换前的 refetch 场景）', async () => {
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [
            message({ id: 'm1', role: 'user', content: '问题' }),
            message({ id: 'm2', role: 'assistant', content: '部分响应' }),
          ],
          streamFn: emptyStream,
          conversationId: 'conversation-1',
          latestRun: conversationRun('canceling', { completed_at: null }),
        }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      const texts = threadTexts(result.current.runtime)
      expect(texts[texts.length - 1]).toBe('部分响应\n\ncanceled')
    })
  })

  it('latest_run 为 completed 时不渲染 notice', async () => {
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [
            message({ id: 'm1', role: 'user', content: '问题' }),
            message({ id: 'm2', role: 'assistant', content: '完整响应' }),
          ],
          streamFn: emptyStream,
          conversationId: 'conversation-1',
          latestRun: conversationRun('completed', { cancel_requested_at: null }),
        }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      const texts = threadTexts(result.current.runtime)
      expect(texts).toHaveLength(2)
      expect(texts[1]).toBe('完整响应')
    })
  })
})
