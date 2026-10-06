/**
 * `onMessagesCommit` 路径（builder / AssistantPanel / TestChatPanel）回归保护。
 *
 * 回归：stream 结束时 finally 通过 `onMessagesCommit(finalMsgs)` 将 streaming
 * 消息移到父 state，但如果同一 batch 中没有清空 `streamingMessages`，
 * 下一次 render 的 `allMessages = [...messages, ...streamingMessages]`
 * 中相同的 `stream-{uuid}` / `opt-{uuid}` / `tr-{uuid}` id 会同时存在于两边
 * → `useExternalMessageConverter` 调用 assistant-ui `MessageRepository.link`
 * 时 throw "A message with the same id already exists in the parent tree"。
 *
 * 本测试在 hook 内像父组件一样保存 `messages`，并在 `onMessagesCommit`
 * 中直接 append，以复现真实模式；若发生回归，hook 自身会在
 * render 过程中 throw。
 */
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import type { ConversationRun, Message, SSEEvent } from '@/lib/types'
import { conversationRunsApi } from '@/lib/api/conversation-runs'
import { chatCancelInFlightAtom, sessionTokenUsageAtom } from '@/lib/stores/chat-store'
import { mergeMessagesForRender, sameMessageSnapshot, useChatRuntime } from '../use-chat-runtime'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

const jotaiMock = vi.hoisted(() => {
  const setters = new WeakMap<object, Mock>()
  const useSetAtom = vi.fn((atom: object) => {
    let setter = setters.get(atom)
    if (!setter) {
      setter = vi.fn()
      setters.set(atom, setter)
    }
    return setter
  })

  return {
    getSetter: (atom: object) => setters.get(atom),
    useSetAtom,
  }
})

vi.mock('jotai', async () => {
  const actual = await vi.importActual<typeof import('jotai')>('jotai')
  return {
    ...actual,
    useSetAtom: jotaiMock.useSetAtom,
    useAtomValue: () => undefined,
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/lib/api/conversation-runs', () => ({
  conversationRunsApi: { cancel: vi.fn() },
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

function makeStreamFn(customEvents: SSEEvent[]): (content: string) => AsyncGenerator<SSEEvent> {
  return async function* () {
    yield {
      event: 'message_start' as const,
      id: 'evt-start',
      data: { id: 'msg-1', role: 'assistant' },
    }
    let i = 0
    for (const ev of customEvents) {
      i += 1
      yield { ...ev, id: ev.id ?? `evt-${i}` }
    }
    yield {
      event: 'message_end' as const,
      id: 'evt-end',
      data: { content: '', usage: {} },
    }
  }
}

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function conversationRun(status: ConversationRun['status']): ConversationRun {
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
    cancel_requested_at: null,
    started_at: null,
    heartbeat_at: null,
    completed_at: null,
    created_at: '2026-06-11T00:00:00.000Z',
    updated_at: '2026-06-11T00:00:00.000Z',
    metrics: null,
  }
}

/** 复现 builder / AssistantPanel / TestChatPanel 的真实模式的 harness。 */
function useCommitHarness(events: SSEEvent[], onCommit?: (messages: Message[]) => void) {
  const [messages, setMessages] = useState<Message[]>([])
  const streamFn = useMemo(
    () =>
      makeStreamFn(events) as unknown as (
        content: string,
        signal: AbortSignal,
      ) => AsyncGenerator<SSEEvent>,
    [events],
  )
  const onMessagesCommit = useCallback(
    (msgs: Message[]) => {
      onCommit?.(msgs)
      setMessages((prev) => [...prev, ...msgs])
    },
    [onCommit],
  )
  const chat = useChatRuntime({ messages, streamFn, onMessagesCommit })
  return { ...chat, messages }
}

function useCommitHarnessWithStream(
  streamFn: (content: string, signal: AbortSignal) => AsyncGenerator<SSEEvent>,
  onCommit?: (messages: Message[]) => void,
) {
  const [messages, setMessages] = useState<Message[]>([])
  const onMessagesCommit = useCallback(
    (msgs: Message[]) => {
      onCommit?.(msgs)
      setMessages((prev) => [...prev, ...msgs])
    },
    [onCommit],
  )
  const chat = useChatRuntime({ messages, streamFn, onMessagesCommit })
  return { ...chat, messages }
}

function useUnstableEmptyMessagesHarness() {
  const [, setTick] = useState(0)
  const streamFn = useMemo(
    () =>
      async function* () {} as unknown as (
        content: string,
        signal: AbortSignal,
      ) => AsyncGenerator<SSEEvent>,
    [],
  )
  const chat = useChatRuntime({ messages: [], streamFn })
  return { ...chat, bump: () => setTick((value) => value + 1) }
}

beforeEach(() => {
  vi.clearAllMocks()
})

function message(id: string, role: Message['role'], content: string): Message {
  return {
    id,
    conversation_id: 'conversation-1',
    role,
    content,
    tool_calls: null,
    tool_call_id: null,
    created_at: '2026-06-04T00:00:00.000Z',
    feedback: null,
    attachments: null,
    usage: null,
    parent_id: null,
    branch_checkpoint_id: null,
    branch_index: null,
    branch_total: null,
  }
}

describe('useChatRuntime — onMessagesCommit dedup', () => {
  it('refetch 获取 persisted assistant 的 render 中立即隐藏 streaming turn', () => {
    const previousMessages: Message[] = []
    const persistedUser = message('user-db', 'user', 'probe')
    const persistedAssistant = message('assistant-db', 'assistant', 'done')
    const optimisticUser = message('opt-user', 'user', 'probe')
    const streamingAssistant = message('stream-assistant', 'assistant', 'done')

    const merged = mergeMessagesForRender({
      messages: [persistedUser, persistedAssistant],
      previousMessages,
      streamingMessages: [optimisticUser, streamingAssistant],
      isRunning: false,
    })

    expect(merged.map((m) => m.id)).toEqual(['user-db', 'assistant-db'])
  })

  it('assistant row 尚未 persist 的 refetch 中保留 partial assistant', () => {
    const persistedUser = message('user-db', 'user', 'probe')
    const optimisticUser = message('opt-user', 'user', 'probe')
    const partialAssistant = message('stream-assistant', 'assistant', 'partial')

    const merged = mergeMessagesForRender({
      messages: [persistedUser],
      previousMessages: [],
      streamingMessages: [optimisticUser, partialAssistant],
      isRunning: false,
    })

    expect(merged.map((m) => m.id)).toEqual(['user-db', 'stream-assistant'])
  })

  it('父组件即使以新引用传入空 messages 数组也不会产生 render loop', () => {
    const { result } = renderHook(() => useUnstableEmptyMessagesHarness(), {
      wrapper: createWrapper(),
    })

    expect(() => {
      act(() => {
        result.current.bump()
      })
    }).not.toThrow()
  })

  it('stream 结束后父组件把 commit append 到 messages 也不会发生重复 id throw', async () => {
    /**
     * 回归保护：修复前 finally 的 setState 在同一 batch 中处理，
     * 下一次 render 时 `messages` 与 `streamingMessages` 会同时包含 `stream-{uuid}`，
     * 导致 `useExternalMessageConverter` throw。
     * 修复后，`setStreamingMessages([])` 会在调用 `onMessagesCommit` 前
     * 进入同一 batch，使下一次 render 的 `allMessages` 保持为无重复的单一
     * source。
     */
    const { result } = renderHook(
      () => useCommitHarness([{ event: 'content_delta', data: { content: 'Hello' } }]),
      { wrapper: createWrapper() },
    )

    // 回归时，此调用结束后的下一次 render 会 throw。
    await act(async () => {
      await result.current.sendMessage('hi')
    })

    // 1) 父 messages 中已加入 commit 结果（user opt + assistant）。
    const ids = result.current.messages.map((m) => m.id)
    expect(ids.length).toBeGreaterThanOrEqual(2)

    // 2) 没有重复 id——assistant-ui MessageRepository 的核心 contract。
    expect(new Set(ids).size).toBe(ids.length)

    // 3) assistant 消息只存在一次。
    const assistantIds = result.current.messages
      .filter((m) => m.role === 'assistant')
      .map((m) => m.id)
    expect(assistantIds).toHaveLength(1)
  })

  it('Stop 在服务器 cancel 成功后 detach 本地 stream', async () => {
    const started = deferred()
    const release = deferred()
    let resolveCancel!: () => void
    const cancelPromise = new Promise<ReturnType<typeof conversationRun>>((resolve) => {
      resolveCancel = () => resolve(conversationRun('canceling'))
    })
    const cancelMock = vi.mocked(conversationRunsApi.cancel)
    cancelMock.mockReturnValue(cancelPromise)
    const abortSeen = vi.fn()
    const cancelInFlightSetter = jotaiMock.getSetter(chatCancelInFlightAtom)

    async function* streamFn(
      _content: string,
      signal: AbortSignal,
      options?: { onRunId?: (runId: string) => void },
    ): AsyncGenerator<SSEEvent> {
      options?.onRunId?.('run-1')
      signal.addEventListener('abort', abortSeen)
      yield {
        event: 'message_start',
        id: 'run-1-1',
        data: { id: 'run-1', role: 'assistant' },
      }
      started.resolve()
      await release.promise
      yield {
        event: 'message_end',
        id: 'run-1-2',
        data: { content: '', usage: {} },
      }
    }

    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [],
          streamFn,
          conversationId: 'conversation-1',
        }),
      { wrapper: createWrapper() },
    )

    let sendPromise!: Promise<void>
    act(() => {
      sendPromise = result.current.sendMessage('cancel me')
    })
    await started.promise

    act(() => {
      result.current.runtime.thread.cancelRun()
    })

    await waitFor(() => expect(cancelMock).toHaveBeenCalledWith('conversation-1', 'run-1'))
    expect(cancelInFlightSetter).toHaveBeenCalledWith(true)
    expect(abortSeen).not.toHaveBeenCalled()

    resolveCancel()
    await waitFor(() => expect(abortSeen).toHaveBeenCalledTimes(1))
    expect(cancelInFlightSetter).toHaveBeenCalledWith(false)

    release.resolve()
    await sendPromise
  })

  it('Stop 收到已完成 run 的响应时不 abort 本地 stream', async () => {
    const started = deferred()
    const release = deferred()
    const cancelMock = vi.mocked(conversationRunsApi.cancel)
    cancelMock.mockResolvedValue(conversationRun('completed'))
    const abortSeen = vi.fn()

    async function* streamFn(
      _content: string,
      signal: AbortSignal,
      options?: { onRunId?: (runId: string) => void },
    ): AsyncGenerator<SSEEvent> {
      options?.onRunId?.('run-1')
      signal.addEventListener('abort', abortSeen)
      yield {
        event: 'message_start',
        id: 'run-1-1',
        data: { id: 'run-1', role: 'assistant' },
      }
      started.resolve()
      await release.promise
      yield {
        event: 'content_delta',
        id: 'run-1-2',
        data: { content: 'finished normally' },
      }
      yield {
        event: 'message_end',
        id: 'run-1-3',
        data: { content: '', usage: {}, status: 'completed' },
      }
    }

    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [],
          streamFn,
          conversationId: 'conversation-1',
        }),
      { wrapper: createWrapper() },
    )

    let sendPromise!: Promise<void>
    act(() => {
      sendPromise = result.current.sendMessage('race cancel')
    })
    await started.promise

    act(() => {
      result.current.runtime.thread.cancelRun()
    })

    await waitFor(() => expect(cancelMock).toHaveBeenCalledWith('conversation-1', 'run-1'))
    await waitFor(() => expect(abortSeen).not.toHaveBeenCalled())

    release.resolve()
    await sendPromise
  })

  it('包含 tool_call 的 turn 也会无重复地 commit', async () => {
    const { result } = renderHook(
      () =>
        useCommitHarness([
          {
            event: 'tool_call_start',
            data: { tool_name: 'web_search', parameters: { q: 'foo' } },
          },
          {
            event: 'tool_call_result',
            data: { tool_name: 'web_search', result: 'bar' },
          },
          { event: 'content_delta', data: { content: 'done' } },
        ]),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    const ids = result.current.messages.map((m) => m.id)
    expect(new Set(ids).size).toBe(ids.length)

    // assistant + tool result 各 1 条。
    const roleCount = result.current.messages.reduce<Record<string, number>>((acc, m) => {
      acc[m.role] = (acc[m.role] ?? 0) + 1
      return acc
    }, {})
    expect(roleCount.assistant).toBe(1)
    expect(roleCount.tool).toBe(1)
  })

  it('同一工具重复调用的 result 按 tool_call_id 匹配', async () => {
    const { result } = renderHook(
      () =>
        useCommitHarness([
          {
            event: 'tool_call_start',
            data: {
              tool_call_id: 'call-a',
              tool_name: 'web_search',
              parameters: { q: 'A' },
            },
          },
          {
            event: 'tool_call_start',
            data: {
              tool_call_id: 'call-b',
              tool_name: 'web_search',
              parameters: { q: 'B' },
            },
          },
          {
            event: 'tool_call_result',
            data: { tool_call_id: 'call-a', tool_name: 'web_search', result: 'result A' },
          },
          {
            event: 'tool_call_result',
            data: { tool_call_id: 'call-b', tool_name: 'web_search', result: 'result B' },
          },
        ]),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    const assistant = result.current.messages.find((m) => m.role === 'assistant')
    expect(assistant?.tool_calls).toEqual([
      { id: 'call-a', name: 'web_search', args: { q: 'A' } },
      { id: 'call-b', name: 'web_search', args: { q: 'B' } },
    ])

    const resultByCallId = Object.fromEntries(
      result.current.messages
        .filter((m) => m.role === 'tool')
        .map((m) => [m.tool_call_id, m.content]),
    )
    expect(resultByCallId).toEqual({
      'call-a': 'result A',
      'call-b': 'result B',
    })
  })

  it('新 stream 开始后，stale stream cleanup 不会 commit', async () => {
    const firstYielded = deferred()
    const releaseFirst = deferred()
    const commitSpy = vi.fn()
    const streamFn = vi.fn((content: string) => {
      if (content === 'first') {
        return (async function* () {
          yield {
            event: 'content_delta' as const,
            id: 'first-delta',
            data: { content: 'old answer' },
          }
          firstYielded.resolve()
          await releaseFirst.promise
          yield {
            event: 'message_end' as const,
            id: 'first-end',
            data: { usage: {} },
          }
        })()
      }

      return (async function* () {
        yield {
          event: 'content_delta' as const,
          id: 'second-delta',
          data: { content: 'new answer' },
        }
        yield {
          event: 'message_end' as const,
          id: 'second-end',
          data: { usage: {} },
        }
      })()
    })

    const { result } = renderHook(
      () =>
        useCommitHarnessWithStream(
          streamFn as unknown as (content: string, signal: AbortSignal) => AsyncGenerator<SSEEvent>,
          commitSpy,
        ),
      { wrapper: createWrapper() },
    )

    let firstPromise!: Promise<void>
    await act(async () => {
      firstPromise = result.current.sendMessage('first')
      await firstYielded.promise
    })

    await act(async () => {
      await result.current.sendMessage('second')
    })

    await act(async () => {
      releaseFirst.resolve()
      await firstPromise
    })

    expect(commitSpy).toHaveBeenCalledTimes(1)
    expect(
      result.current.messages.filter((m) => m.role === 'assistant').map((m) => m.content),
    ).toEqual(['new answer'])
  })

  it('无 usage 的 content flush 不会反复更新 token usage atom', async () => {
    const { result } = renderHook(
      () =>
        useCommitHarness([
          { event: 'content_delta', data: { content: 'Hello' } },
          { event: 'content_delta', data: { content: ' world' } },
        ]),
      { wrapper: createWrapper() },
    )
    const tokenUsageSetter = jotaiMock.getSetter(sessionTokenUsageAtom)
    expect(tokenUsageSetter).toBeDefined()
    const callsBeforeStream = tokenUsageSetter?.mock.calls.length ?? 0

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    expect(tokenUsageSetter).toHaveBeenCalledTimes(callsBeforeStream)
  })

  it('messages refetch 中 branch/attachment/feedback/usage 变化也视为 snapshot 变化', () => {
    const base: Message = {
      id: 'm1',
      conversation_id: 'c1',
      role: 'assistant',
      content: 'same text',
      tool_calls: null,
      tool_call_id: null,
      created_at: '2026-05-29T00:00:00Z',
      branch_index: 0,
      branch_total: 2,
      sibling_checkpoint_ids: ['ck1', 'ck2'],
      feedback: { rating: 'up' },
      usage: {
        prompt_tokens: 1,
        completion_tokens: 2,
        cache_creation_tokens: 0,
        cache_read_tokens: 0,
      },
    }

    expect(sameMessageSnapshot([base], [{ ...base }])).toBe(true)
    expect(sameMessageSnapshot([base], [{ ...base, branch_index: 1 }])).toBe(false)
    expect(
      sameMessageSnapshot(
        [base],
        [
          {
            ...base,
            attachments: [
              {
                id: 'att-1',
                filename: 'guide.png',
                mime_type: 'image/png',
                size_bytes: 12,
                url: '/api/conversations/c1/files/guide.png',
              },
            ],
          },
        ],
      ),
    ).toBe(false)
    expect(
      sameMessageSnapshot(
        [base],
        [
          {
            ...base,
            artifacts: [
              {
                id: 'artifact-1',
                agent_id: 'agent-1',
                conversation_id: 'c1',
                assistant_msg_id: 'run-1',
                run_id: 'run-1',
                tool_call_id: null,
                source_tool_name: 'execute_in_skill',
                path: 'report.md',
                display_name: 'report.md',
                mime_type: 'text/markdown',
                extension: 'md',
                artifact_kind: 'markdown',
                size_bytes: 10,
                sha256: 'a'.repeat(64),
                status: 'ready',
                is_favorite: false,
                last_opened_at: null,
                preview_count: 0,
                download_count: 0,
                version_id: 'version-1',
                version_number: 1,
                created_at: '2026-06-05T00:00:00',
                updated_at: '2026-06-05T00:00:00',
                agent_name: null,
                conversation_title: null,
                url: '/api/conversations/c1/artifacts/artifact-1',
                preview_url: '/api/conversations/c1/artifacts/artifact-1/content',
                download_url: '/api/conversations/c1/artifacts/artifact-1/download',
              },
            ],
          },
        ],
      ),
    ).toBe(false)
    expect(sameMessageSnapshot([base], [{ ...base, feedback: { rating: 'down' } }])).toBe(false)
    expect(
      sameMessageSnapshot(
        [base],
        [
          {
            ...base,
            usage: {
              prompt_tokens: 1,
              completion_tokens: 3,
              cache_creation_tokens: 0,
              cache_read_tokens: 0,
            },
          },
        ],
      ),
    ).toBe(false)
  })

  it('收到 memory_saved 事件时 invalidate memory query 并显示 toast', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const Wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const streamFn = makeStreamFn([
      {
        event: 'memory_saved',
        data: {
          scope: 'user',
          content: '偏好把会议安排在下午 3 点以后。',
          id: 'memory-1',
        },
      },
    ])
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [],
          streamFn: streamFn as unknown as (
            content: string,
            signal: AbortSignal,
          ) => AsyncGenerator<SSEEvent>,
          onMessagesCommit: vi.fn(),
        }),
      { wrapper: Wrapper },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['memory'] })
    expect(toast.success).toHaveBeenCalledWith('savedToast')
  })
})
