import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HumanMessage, type BaseMessage } from '@langchain/core/messages'
import type { MessageMetadataMap, UseStreamReturn } from '@langchain/react'
import type { AppendMessage } from '@assistant-ui/react'
import { useCheckpointForkHandlers, type MoldySubmitState } from '../use-checkpoint-fork-handlers'
import type { ServerCheckpointContext } from '../thread-state-checkpoints'

const mocks = vi.hoisted(() => ({
  // useMessageMetadataSnapshot 的 useSyncExternalStore 通过 STREAM_CONTROLLER symbol
  // 从 stream 读取 metadata store，因此暴露同一个 symbol。
  STREAM_CONTROLLER: Symbol('STREAM_CONTROLLER'),
  loadServerCheckpointContext:
    vi.fn<(conversationId: string) => Promise<ServerCheckpointContext>>(),
  reportClientWarning: vi.fn(),
}))

const STREAM_CONTROLLER = mocks.STREAM_CONTROLLER

vi.mock('@langchain/react', () => ({
  STREAM_CONTROLLER: mocks.STREAM_CONTROLLER,
}))

vi.mock('../thread-state-checkpoints', () => ({
  loadServerCheckpointContext: mocks.loadServerCheckpointContext,
}))

vi.mock('@/lib/logging/client-logger', () => ({
  reportClientWarning: mocks.reportClientWarning,
}))

interface MutableStream {
  submit: ReturnType<typeof vi.fn>
  [STREAM_CONTROLLER]: {
    messageMetadataStore: {
      subscribe: (onChange: () => void) => () => void
      getSnapshot: () => MessageMetadataMap
    }
  }
}

function createStream(): MutableStream {
  const emptyMetadata: MessageMetadataMap = new Map()
  return {
    submit: vi.fn().mockResolvedValue(undefined),
    [STREAM_CONTROLLER]: {
      messageMetadataStore: {
        subscribe: () => () => {},
        getSnapshot: () => emptyMetadata,
      },
    },
  }
}

/** 找不到 checkpoint 且服务器消息也为空的上下文——让 retryServerCheckpoint
 *  持续 poll，并进入 abortable sleep。 */
function emptyServerContext(): ServerCheckpointContext {
  return {
    checkpointByMessageId: new Map(),
    metadataByMessageId: new Map(),
    messageIdsByIndex: [],
  }
}

function renderHandlers(stream: MutableStream) {
  return renderHook(() =>
    useCheckpointForkHandlers({
      conversationId: 'conversation-1',
      stream: stream as unknown as UseStreamReturn<MoldySubmitState>,
      // 提供空的可见消息/消息列表，使本地找不到 checkpoint →
      // 落到服务器 poll 路径。
      visibleMessages: [],
      langChainMessages: [] as readonly BaseMessage[],
    }),
  )
}

function editMessage(): AppendMessage {
  return {
    content: [{ type: 'text', text: 'edited prompt' }],
    parentId: 'missing-parent',
    sourceId: 'missing-source',
  } as unknown as AppendMessage
}

describe('useCheckpointForkHandlers resource context', () => {
  it('places strict run-config references beside messages in idle stream input', async () => {
    const stream = createStream()
    const { result } = renderHandlers(stream)
    const reference = {
      kind: 'conversation',
      id: '11111111-1111-4111-8111-111111111111',
      label: 'Prior chat',
    } as const

    await act(() =>
      result.current.onNew({
        content: [{ type: 'text', text: 'Use this context' }],
        attachments: [],
        runConfig: { custom: { resource_context: [reference] } },
      } as unknown as AppendMessage),
    )

    expect(stream.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        resource_context: [reference],
        messages: [expect.any(HumanMessage)],
      }),
    )
  })

  it('rejects malformed run-config references without submitting', async () => {
    const stream = createStream()
    const { result } = renderHandlers(stream)

    await expect(
      result.current.onNew({
        content: [{ type: 'text', text: 'Do not send' }],
        attachments: [],
        runConfig: {
          custom: {
            resource_context: [
              {
                kind: 'file',
                id: '11111111-1111-4111-8111-111111111111',
                path: '/tmp/private',
              },
            ],
          },
        },
      } as unknown as AppendMessage),
    ).rejects.toThrow('Resource context cannot be submitted: malformed')
    expect(stream.submit).not.toHaveBeenCalled()
  })
})

describe('useCheckpointForkHandlers abortable server checkpoint polling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.loadServerCheckpointContext.mockReset()
    mocks.reportClientWarning.mockReset()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('unmount 时中断 poll loop，不向 dead stream submit', async () => {
    // 服务器上下文每次都返回无 checkpoint 的结果，使 polling 持续进行。
    mocks.loadServerCheckpointContext.mockResolvedValue(emptyServerContext())

    const stream = createStream()
    const { result, unmount } = renderHandlers(stream)

    let editResult: boolean | undefined
    // onEdit 不会通过 await 结束，而是挂在 polling loop（sleep）上。
    act(() => {
      void result.current.onEdit(editMessage()).then((value) => {
        editResult = value
      })
    })

    // 首次服务器加载（microtask）后推进到进入 sleep timer。
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(mocks.loadServerCheckpointContext).toHaveBeenCalled()
    expect(stream.submit).not.toHaveBeenCalled()

    // unmount → cleanup 调用 AbortController.abort() → sleep 立即 resolve →
    // 在 signal.aborted guard 中退出循环，并在不 submit 的情况下返回 false。
    await act(async () => {
      unmount()
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(stream.submit).not.toHaveBeenCalled()
    expect(editResult).toBe(false)
  })

  it('即使因 handler recreate 取消之前的 poll，也不会 submit', async () => {
    mocks.loadServerCheckpointContext.mockResolvedValue(emptyServerContext())

    const stream = createStream()
    const { result } = renderHandlers(stream)

    let firstEditResult: boolean | undefined
    act(() => {
      void result.current.onEdit(editMessage()).then((value) => {
        firstEditResult = value
      })
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // beginServerCheckpointPoll 在新调用时 abort 之前的 controller。
    // onReload 启动新 poll 时，第一个 onEdit poll 的 signal 会触发。
    act(() => {
      void result.current.onReload('missing-parent')
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // 第一个 onEdit 被取消，不 submit，最终返回 false。
    expect(firstEditResult).toBe(false)
    expect(stream.submit).not.toHaveBeenCalled()
  })

  it('abort 的 sleep 无需等待 timer 到期就立即 resolve 并退出循环', async () => {
    // 进入 sleep(250ms) 后收到 abort，必须在 setTimeout 到期前 resolve。
    // 即使不 advance fake timer，只靠 unmount 让 onEdit 结束，也能证明它会立即 resolve。
    // 这证明了这一点。
    mocks.loadServerCheckpointContext.mockResolvedValue(emptyServerContext())

    const stream = createStream()
    const { result, unmount } = renderHandlers(stream)

    let settled = false
    act(() => {
      void result.current.onEdit(editMessage()).then(() => {
        settled = true
      })
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(settled).toBe(false)

    // 不 advance timer（不足 250ms）。必须仅靠 abort 就 resolve。
    await act(async () => {
      unmount()
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(settled).toBe(true)
    expect(stream.submit).not.toHaveBeenCalled()
  })
})

describe('useCheckpointForkHandlers retry fork excludes synthetic notice bubbles (G2)', () => {
  it('跳过失败 notice 气泡，从最后一个 user checkpoint fork', async () => {
    const stream = createStream()
    const userId = 'user-1'
    const failedBubbleId = 'moldy-failed-run-1'
    const langChainMessages = [
      new HumanMessage({
        id: userId,
        content: 'hi',
        additional_kwargs: { metadata: { checkpoint_id: 'ck-user' } },
      }),
    ] as unknown as readonly BaseMessage[]

    const { result } = renderHook(() =>
      useCheckpointForkHandlers({
        conversationId: 'conversation-1',
        stream: stream as unknown as UseStreamReturn<MoldySubmitState>,
        // user 之后出现合成失败气泡（assistant role，无 checkpoint）。
        visibleMessages: [
          { id: userId, role: 'user' },
          { id: failedBubbleId, role: 'assistant' },
        ],
        langChainMessages,
      }),
    )

    await act(async () => {
      await result.current.onReload(userId)
    })

    // 如果不过滤合成 notice，checkpointForReload 会把它误认成需要重新生成的
    // assistant，从而得到 null → no-op（retry bug）。过滤后才能从
    // 带 checkpoint 的最后一个 user turn fork。
    expect(stream.submit).toHaveBeenCalledWith(null, { forkFrom: 'ck-user' })
  })
})
