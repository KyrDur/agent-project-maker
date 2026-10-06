/**
 * 验证 `case 'interrupt'` 标准单独路径 + multi-action / fallback empty 标准 chunk
 * 是否原样传递给 `onStandardInterrupt`。
 *
 * Brittleness：assistant-ui 的 `useExternalStoreRuntime` /
 * `useExternalMessageConverter` 带有 internal state，因此直接渲染 hook。
 * jotai/sonner/next-intl 用轻量 mock 隔离。
 */
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Decision, Message, SSEEvent, StandardInterruptPayload } from '@/lib/types'
import { useChatRuntime } from '../use-chat-runtime'

// ── 轻量 mocks ──────────────────────────────────────────────────────────
const streamResumeDecisionsMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/sse/stream-resume', () => ({
  streamResumeDecisions: streamResumeDecisionsMock,
}))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

vi.mock('jotai', async () => {
  const actual = await vi.importActual<typeof import('jotai')>('jotai')
  return {
    ...actual,
    useSetAtom: () => vi.fn(),
    useAtomValue: () => undefined,
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

// ── helpers ──────────────────────────────────────────────────────────────

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

/** Build an SSE stream with `message_start` → custom events → `message_end`.
 *  IDs are unique so streamGuard dedup never blocks our events. */
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
  const promise = new Promise<void>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const STANDARD_PAYLOAD: StandardInterruptPayload = {
  interrupt_id: 'ns-1',
  action_requests: [{ name: 'send_email', args: { to: 'x@y' }, description: 'Send' }],
  review_configs: [
    {
      action_name: 'send_email',
      allowed_decisions: ['approve', 'edit', 'reject', 'respond'],
    },
  ],
}

type ResumeSpy = (
  decisions: Decision[],
  signal: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
) => AsyncGenerator<SSEEvent>

// ── 通用 hook 选项 builder ───────────────────────────────────────────────────

interface HookSpyOptions {
  events: SSEEvent[]
  initialMessages?: Message[]
}

function buildHookOptions(opts: HookSpyOptions) {
  const onStandardInterrupt = vi.fn<(p: StandardInterruptPayload) => void>()
  const streamFn = makeStreamFn(opts.events)
  return {
    onStandardInterrupt,
    streamFn,
    options: {
      messages: opts.initialMessages ?? [],
      streamFn: streamFn as unknown as (
        content: string,
        signal: AbortSignal,
        options?: { onRunId?: (id: string) => void },
      ) => AsyncGenerator<SSEEvent>,
      onStandardInterrupt,
      conversationId: 'conv-1',
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  streamResumeDecisionsMock.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('useChatRuntime — case "interrupt" 标准路径', () => {
  it('标准 chunk 到达时 onStandardInterrupt 被调用 1 次', async () => {
    const { onStandardInterrupt, options } = buildHookOptions({
      events: [{ event: 'interrupt', data: STANDARD_PAYLOAD }],
    })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(onStandardInterrupt).toHaveBeenCalledTimes(1))
    expect(onStandardInterrupt).toHaveBeenCalledWith(STANDARD_PAYLOAD)
  })

  it('标准 chunk 到达时也合成内部 tool UI 调用', async () => {
    const { options } = buildHookOptions({
      events: [{ event: 'interrupt', data: STANDARD_PAYLOAD }],
    })
    const onMessagesCommit = vi.fn<(messages: Message[]) => void>()
    const { result } = renderHook(
      () =>
        useChatRuntime({
          ...options,
          onStandardInterrupt: undefined,
          onMessagesCommit,
        }),
      {
        wrapper: createWrapper(),
      },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(onMessagesCommit).toHaveBeenCalled())
    const committed = onMessagesCommit.mock.calls.at(-1)?.[0] ?? []
    const assistant = committed.find((message) => message.role === 'assistant')
    expect(assistant?.tool_calls).toEqual([
      {
        id: 'ns-1:0',
        name: 'request_approval',
        args: {
          tool_name: 'send_email',
          tool_args: { to: 'x@y' },
          description: 'Send',
          approval_id: 'ns-1:0',
          allowed_decisions: ['approve', 'edit', 'reject', 'respond'],
          hitl_interrupt_id: 'ns-1',
          hitl_action_index: 0,
          hitl_total_actions: 1,
        },
      },
    ])
  })

  it('对 stream 中已出现的 ask_user tool call 只合并 interrupt metadata', async () => {
    const questionFlowPayload: StandardInterruptPayload = {
      interrupt_id: 'ns-ask-user',
      action_requests: [
        {
          name: 'ask_user',
          args: {
            mode: 'question_flow',
            title: '确认智能体设置',
            questions: [
              {
                id: 'agent_name',
                label: '智能体名称',
                type: 'single_select',
                options: [{ id: 'research', label: '研究智能体' }],
                required: true,
              },
            ],
          },
        },
      ],
      review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
    }
    const { options } = buildHookOptions({
      events: [
        {
          event: 'tool_call_start',
          data: {
            tool_name: 'ask_user',
            parameters: questionFlowPayload.action_requests[0].args,
          },
        },
        { event: 'interrupt', data: questionFlowPayload },
      ],
    })
    const onMessagesCommit = vi.fn<(messages: Message[]) => void>()
    const { result } = renderHook(
      () =>
        useChatRuntime({
          ...options,
          onMessagesCommit,
        }),
      {
        wrapper: createWrapper(),
      },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(onMessagesCommit).toHaveBeenCalled())
    const committed = onMessagesCommit.mock.calls.at(-1)?.[0] ?? []
    const assistant = committed.find((message) => message.role === 'assistant')
    expect(assistant?.tool_calls).toHaveLength(1)
    expect(assistant?.tool_calls?.[0]).toMatchObject({
      name: 'ask_user',
      args: {
        mode: 'question_flow',
        title: '确认智能体设置',
        approval_id: 'ns-ask-user:0',
        allowed_decisions: ['respond'],
        hitl_interrupt_id: 'ns-ask-user',
        hitl_action_index: 0,
        hitl_total_actions: 1,
      },
    })
  })

  it('multi-action(action_requests.length >= 2) 标准 chunk 一次性完整传递', async () => {
    // backend 按一个 interrupt = 一组（多个 action_requests）发布（§4.3）。
    // frontend 不拆分 multi-action 数组，直接交给回调。
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-multi',
      action_requests: [
        { name: 'send_email', args: { to: 'a@b' } },
        { name: 'delete_record', args: { id: 42 } },
        { name: 'create_event', args: { title: 'meet' } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'create_event', allowed_decisions: ['approve', 'edit', 'reject'] },
      ],
    }
    const { onStandardInterrupt, options } = buildHookOptions({
      events: [{ event: 'interrupt', data: multi }],
    })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(onStandardInterrupt).toHaveBeenCalledTimes(1))
    const arg = onStandardInterrupt.mock.calls[0][0]
    expect(arg.action_requests).toHaveLength(3)
    expect(arg.review_configs).toHaveLength(3)
  })

  it('fallback 标准 chunk(action_requests=[]) 显示 toast 提示 + 不调用 onStandardInterrupt', async () => {
    /**
     * Backend fallback（``aget_state`` 失败）：空标准 chunk
     * ``{interrupt_id: "", action_requests: [], review_configs: []}`` emit 1 次。
     * 为避免 turn silent 地卡住，hook 通过 toast 提示用户，
     * 且不调用 ``onStandardInterrupt``（渲染操作卡没有意义）。
     */
    vi.mocked(toast.error).mockClear()
    const fallbackStd: StandardInterruptPayload = {
      interrupt_id: '',
      action_requests: [],
      review_configs: [],
    }
    const { onStandardInterrupt, options } = buildHookOptions({
      events: [{ event: 'interrupt', data: fallbackStd }],
    })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(onStandardInterrupt).not.toHaveBeenCalled()
  })

  it('SSE error event 到达时调用 toast.error 1 次（silent fail 保护）', async () => {
    /** ``setStreamError`` 是 setter-only state，因此 UI 不展示。
     * Backend 的 SSE ``error`` event（如 OpenAI 404, model not found）不会
     * 在用户界面 silent 地消失，强制调用 toast。 */
    vi.mocked(toast.error).mockClear()
    const { options } = buildHookOptions({
      events: [
        {
          event: 'error',
          data: { message: 'Error code: 404' },
        },
      ],
    })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(toast.error).toHaveBeenCalledWith(
      'Error code: 404',
      expect.objectContaining({ id: 'chat-stream-error' }),
    )
  })

  it('一个 stream 内有多个 error event 时，用 dedup id 让 sonner 替换 toast', async () => {
    /**
     * Backend 在一个 turn 内 emit 多个 ``error`` SSE event（e.g. tool
     * 各阶段累计 fail）时，旧实现会堆叠 toast → 遮挡画面。确保所有
     * 调用都使用相同 id（``chat-stream-error``），让 sonner 进行替换
     * （视觉 dedup）。回归保护的是 id 一致性，而不是调用次数。
     */
    vi.mocked(toast.error).mockClear()
    const { options } = buildHookOptions({
      events: [
        { event: 'error', data: { message: 'first' } },
        { event: 'error', data: { message: 'second' } },
        { event: 'error', data: { message: 'third' } },
      ],
    })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(3))
    // 所有调用都带相同 dedup id——sonner 自动替换
    const calls = vi.mocked(toast.error).mock.calls
    for (const call of calls) {
      expect(call[1]).toEqual(expect.objectContaining({ id: 'chat-stream-error' }))
    }
  })
})

// ---------------------------------------------------------------------------
// 调用 onResumeDecisions——body builder 集成（stream 本身见 stream-resume.test.ts）。
// ---------------------------------------------------------------------------

describe('useChatRuntime — onResumeDecisions', () => {
  it('hook 暴露 onResumeDecisions 函数（兼容 HiTLContext §6.3）', () => {
    const { options } = buildHookOptions({ events: [] })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    expect(typeof result.current.onResumeDecisions).toBe('function')
    expect(typeof result.current.registerDecision).toBe('function')
    // legacy `onResume` 不再暴露（回归保护）。
    expect('onResume' in result.current).toBe(false)
  })

  it('conversationId 和 resumeFn 都不存在时，不把决定标记为完成', async () => {
    // 防止错误连接的 HiTL 上下文未发送决定却显示为已完成。
    const { options } = buildHookOptions({ events: [] })
    const noConvOptions = { ...options, conversationId: undefined }
    const { result } = renderHook(() => useChatRuntime(noConvOptions), {
      wrapper: createWrapper(),
    })

    const decisions: Decision[] = [{ type: 'approve' }]
    await expect(result.current.onResumeDecisions(decisions)).rejects.toThrow(
      'Resume target is unavailable',
    )
  })

  it('multi-action coordinator resumes through the latest resumeFn after rerender', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-multi-latest',
      action_requests: [
        { name: 'ask_user', args: { question: '要继续吗？' } },
        { name: 'send_email', args: { to: 'team@example.com' } },
      ],
      review_configs: [
        { action_name: 'ask_user', allowed_decisions: ['respond'] },
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    const resume1 = vi.fn<ResumeSpy>(async function* () {})
    const resume2 = vi.fn<ResumeSpy>(async function* () {
      yield {
        event: 'message_end' as const,
        id: 'resume-latest-end',
        data: { content: '', status: 'completed', usage: {} },
      }
    })
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result, rerender } = renderHook(
      ({ resumeFn }: { readonly resumeFn: ResumeSpy }) => useChatRuntime({ ...options, resumeFn }),
      {
        initialProps: { resumeFn: resume1 },
        wrapper: createWrapper(),
      },
    )

    await act(async () => {
      await result.current.sendMessage('hi')
    })
    let earlyDecision!: Promise<void>
    act(() => {
      earlyDecision = result.current.registerDecision(1, { type: 'reject', message: '不' }, '拒绝')
    })
    expect(resume1).not.toHaveBeenCalled()

    rerender({ resumeFn: resume2 })
    await act(async () => {
      const finalDecision = result.current.registerDecision(
        0,
        { type: 'respond', message: '是' },
        '是',
      )
      await Promise.all([earlyDecision, finalDecision])
    })

    expect(resume1).not.toHaveBeenCalled()
    expect(resume2).toHaveBeenCalledTimes(1)
    expect(resume2.mock.calls[0]?.[0]).toEqual([
      { type: 'respond', message: '是' },
      { type: 'reject', message: '不' },
    ])
    expect(resume2.mock.calls[0]?.[2]).toBe('是 | 拒绝')
    expect(resume2.mock.calls[0]?.[3]).toBe('ns-multi-latest')
  })

  it('keeps a rejected multi-action resume retryable as one complete ordered batch', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-multi-retry',
      action_requests: [
        { name: 'send_email', args: { to: 'team@example.com' } },
        { name: 'delete_record', args: { id: 42 } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    let resumeAttempt = 0
    const resume = vi.fn<ResumeSpy>(() => {
      resumeAttempt += 1
      const currentAttempt = resumeAttempt
      return (async function* () {
        if (currentAttempt === 1) throw new Error('resume rejected')
        yield {
          event: 'message_start' as const,
          id: `resume-${currentAttempt}-start`,
          data: { id: `resume-${currentAttempt}`, role: 'assistant' },
        }
        yield {
          event: 'message_end' as const,
          id: `resume-${currentAttempt}-end`,
          data: { content: '', status: 'completed', usage: {} },
        }
      })()
    })
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result } = renderHook(() => useChatRuntime({ ...options, resumeFn: resume }), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await act(async () => {
      const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
      const second = result.current.registerDecision(1, { type: 'reject', message: '拒绝' }, '拒绝')
      await expect(Promise.all([first, second])).rejects.toThrow('resume rejected')
    })

    expect(resume).toHaveBeenCalledTimes(1)
    expect(resume.mock.calls[0]?.[0]).toEqual([
      { type: 'approve' },
      { type: 'reject', message: '拒绝' },
    ])

    await act(async () => {
      const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
      const second = result.current.registerDecision(1, { type: 'reject', message: '拒绝' }, '拒绝')
      await Promise.all([first, second])
    })

    expect(resume).toHaveBeenCalledTimes(2)
    expect(resume.mock.calls[1]?.[0]).toEqual([
      { type: 'approve' },
      { type: 'reject', message: '拒绝' },
    ])
    expect(resume.mock.calls.every(([decisions]) => decisions.length === 2)).toBe(true)
  })

  it('treats a custom resume error with a dispatch completion status as accepted', async () => {
    const resume = vi.fn<ResumeSpy>(async function* () {
      yield {
        event: 'message_start' as const,
        id: 'resume-dispatched-start',
        data: { id: 'resume-dispatched', role: 'assistant' },
      }
      yield {
        event: 'error' as const,
        id: 'resume-dispatched-error',
        data: { message: 'agent failed after dispatch' },
      }
      yield {
        event: 'message_end' as const,
        id: 'resume-dispatched-end',
        data: { content: '', status: 'failed', usage: {} },
      }
    })
    const { options } = buildHookOptions({ events: [] })
    const { result } = renderHook(() => useChatRuntime({ ...options, resumeFn: resume }), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await expect(
        result.current.onResumeDecisions([{ type: 'approve' }], '批准', 'intr-dispatched'),
      ).resolves.toBeUndefined()
    })

    expect(resume).toHaveBeenCalledOnce()
  })

  it('rejects a custom resume error emitted before dispatch acceptance', async () => {
    const resume = vi.fn<ResumeSpy>(async function* () {
      yield {
        event: 'error' as const,
        id: 'resume-not-accepted-error',
        data: { message: 'stale interrupt' },
      }
    })
    const { options } = buildHookOptions({ events: [] })
    const { result } = renderHook(() => useChatRuntime({ ...options, resumeFn: resume }), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await expect(
        result.current.onResumeDecisions([{ type: 'approve' }], '批准', 'intr-stale'),
      ).rejects.toThrow('stale interrupt')
    })

    expect(resume).toHaveBeenCalledOnce()
  })

  it('retries a conversation batch only before the resume endpoint returns a run id', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-conversation-retry',
      action_requests: [
        { name: 'send_email', args: { to: 'team@example.com' } },
        { name: 'delete_record', args: { id: 42 } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    streamResumeDecisionsMock
      .mockImplementationOnce(() =>
        (async function* () {
          throw new Error('resume request rejected')
        })(),
      )
      .mockImplementationOnce(
        (
          _conversationId: string,
          _decisions: Decision[],
          _signal?: AbortSignal,
          options?: { onRunId?: (runId: string) => void },
        ) => {
          options?.onRunId?.('accepted-run')
          return (async function* () {
            yield {
              event: 'error' as const,
              id: 'accepted-run-error',
              data: { message: 'accepted run later failed' },
            }
            yield {
              event: 'message_end' as const,
              id: 'accepted-run-end',
              data: { content: '', status: 'failed', usage: {} },
            }
          })()
        },
      )
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await act(async () => {
      const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
      const second = result.current.registerDecision(1, { type: 'reject', message: '拒绝' }, '拒绝')
      await expect(Promise.all([first, second])).rejects.toThrow('resume request rejected')
    })

    await act(async () => {
      const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
      const second = result.current.registerDecision(1, { type: 'reject', message: '拒绝' }, '拒绝')
      await Promise.all([first, second])
    })

    expect(streamResumeDecisionsMock).toHaveBeenCalledTimes(2)
    for (const call of streamResumeDecisionsMock.mock.calls) {
      expect(call[1]).toEqual([{ type: 'approve' }, { type: 'reject', message: '拒绝' }])
    }
  })

  it('rejects an incomplete decision batch when a new stream replaces its interrupt', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-replaced-incomplete',
      action_requests: [
        { name: 'send_email', args: { to: 'team@example.com' } },
        { name: 'delete_record', args: { id: 42 } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    const resume = vi.fn<ResumeSpy>(async function* () {})
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result } = renderHook(() => useChatRuntime({ ...options, resumeFn: resume }), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })
    const pending = result.current.registerDecision(0, { type: 'approve' }, '批准')
    const pendingRejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' })

    await act(async () => {
      await result.current.sendMessage('replacement')
    })

    await pendingRejection
    expect(resume).not.toHaveBeenCalled()
  })

  it('rejects a stale card id instead of contaminating or bypassing the active batch', async () => {
    const payloadFor = (interruptId: string): StandardInterruptPayload => ({
      interrupt_id: interruptId,
      action_requests: [
        { name: 'send_email', args: { to: `${interruptId}@example.com` } },
        { name: 'delete_record', args: { id: interruptId } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    })
    const streamFn = async function* (content: string): AsyncGenerator<SSEEvent> {
      const interruptId = content === 'old' ? 'intr-old' : 'intr-new'
      yield {
        event: 'interrupt',
        id: `${interruptId}-event`,
        data: payloadFor(interruptId),
      }
      yield {
        event: 'message_end',
        id: `${interruptId}-end`,
        data: { content: '', usage: {} },
      }
    }
    const resume = vi.fn<ResumeSpy>(async function* () {
      yield {
        event: 'message_end',
        id: 'resume-current-end',
        data: { content: '', status: 'completed', usage: {} },
      }
    })
    const { result } = renderHook(
      () =>
        useChatRuntime({
          messages: [],
          streamFn,
          resumeFn: resume,
          conversationId: 'conv-identity',
        }),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.sendMessage('old')
    })
    const oldPending = result.current.registerDecision(
      0,
      { type: 'approve' },
      '之前的批准',
      'intr-old',
    )
    const oldRejection = expect(oldPending).rejects.toMatchObject({ name: 'AbortError' })

    await act(async () => {
      await result.current.sendMessage('new')
    })
    await oldRejection

    await expect(
      result.current.registerDecision(1, { type: 'approve' }, '错误的批准', 'intr-old'),
    ).rejects.toMatchObject({ name: 'InvalidStateError' })
    await expect(
      result.current.registerDecision(1, { type: 'approve' }, '空标识符批准', null),
    ).rejects.toMatchObject({ name: 'InvalidStateError' })

    const first = result.current.registerDecision(
      0,
      { type: 'reject', message: '当前拒绝' },
      '当前拒绝',
      'intr-new',
    )
    const second = result.current.registerDecision(1, { type: 'approve' }, '当前批准', 'intr-new')
    await Promise.all([first, second])

    expect(resume).toHaveBeenCalledOnce()
    expect(resume.mock.calls[0]?.[0]).toEqual([
      { type: 'reject', message: '当前拒绝' },
      { type: 'approve' },
    ])
    await expect(
      result.current.registerDecision(0, { type: 'approve' }, '重复批准', 'intr-new'),
    ).rejects.toMatchObject({ name: 'InvalidStateError' })
    expect(resume).toHaveBeenCalledOnce()
  })

  it('rejects an in-flight custom resume that is aborted before dispatch acceptance', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-aborted-before-acceptance',
      action_requests: [
        { name: 'send_email', args: { to: 'team@example.com' } },
        { name: 'delete_record', args: { id: 42 } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    const resumeStarted = deferred()
    const resume = vi.fn<ResumeSpy>(async function* (_decisions, signal) {
      resumeStarted.resolve()
      await new Promise<void>((_resolve, reject) => {
        const rejectAbort = () =>
          reject(new DOMException('Resume transport was aborted', 'AbortError'))
        if (signal.aborted) rejectAbort()
        else signal.addEventListener('abort', rejectAbort, { once: true })
      })
    })
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result } = renderHook(() => useChatRuntime({ ...options, resumeFn: resume }), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })
    const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
    const second = result.current.registerDecision(1, { type: 'approve' }, '批准')
    const batch = Promise.all([first, second])
    const batchRejection = expect(batch).rejects.toMatchObject({ name: 'AbortError' })
    await resumeStarted.promise

    await act(async () => {
      await result.current.sendMessage('replacement')
    })

    await batchRejection
    expect(resume).toHaveBeenCalledOnce()
  })

  it('accepts an in-flight conversation resume aborted after the endpoint returns a run id', async () => {
    const multi: StandardInterruptPayload = {
      interrupt_id: 'ns-aborted-after-run-id',
      action_requests: [
        { name: 'send_email', args: { to: 'team@example.com' } },
        { name: 'delete_record', args: { id: 42 } },
      ],
      review_configs: [
        { action_name: 'send_email', allowed_decisions: ['approve', 'reject'] },
        { action_name: 'delete_record', allowed_decisions: ['approve', 'reject'] },
      ],
    }
    const resumeStarted = deferred()
    streamResumeDecisionsMock.mockImplementation(
      (
        _conversationId: string,
        _decisions: Decision[],
        signal: AbortSignal,
        options?: { onRunId?: (runId: string) => void },
      ) => {
        options?.onRunId?.('accepted-before-abort')
        return (async function* () {
          resumeStarted.resolve()
          await new Promise<void>((_resolve, reject) => {
            const rejectAbort = () =>
              reject(new DOMException('Accepted stream was detached', 'AbortError'))
            if (signal.aborted) rejectAbort()
            else signal.addEventListener('abort', rejectAbort, { once: true })
          })
        })()
      },
    )
    const { options } = buildHookOptions({ events: [{ event: 'interrupt', data: multi }] })
    const { result } = renderHook(() => useChatRuntime(options), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      await result.current.sendMessage('hi')
    })
    const first = result.current.registerDecision(0, { type: 'approve' }, '批准')
    const second = result.current.registerDecision(1, { type: 'approve' }, '批准')
    const batch = Promise.all([first, second])
    const batchResolution = expect(batch).resolves.toEqual([undefined, undefined])
    await resumeStarted.promise

    await act(async () => {
      await result.current.sendMessage('replacement')
    })

    await batchResolution
    expect(streamResumeDecisionsMock).toHaveBeenCalledOnce()
  })
})
