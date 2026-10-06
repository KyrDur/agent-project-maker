'use client'

import { useRef, useState, useCallback, useMemo, useEffect } from 'react'
import {
  useExternalStoreRuntime,
  useExternalMessageConverter,
  type DictationAdapter,
} from '@assistant-ui/react'
import { useSetAtom } from 'jotai'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'
import type {
  Decision,
  ConversationRun,
  Message,
  MessagesEnvelope,
  SSEEvent,
  StandardInterruptPayload,
  ToolCallInfo,
  TokenUsageBreakdown,
  ArtifactSummary,
  FileEventPayload,
} from '@/lib/types'
import { isActiveRunStatus } from '@/lib/chat-runs/status'
import {
  chatCancelInFlightAtom,
  sessionTokenUsageAtom,
  reconnectStateAtom,
  type TokenUsage,
} from '@/lib/stores/chat-store'
import { upsertArtifactList, upsertChatArtifactAtom } from '@/lib/stores/chat-artifacts'
import { chatRightRailAtom } from '@/lib/stores/chat-right-rail'
import { convertMessage } from './convert-message'
import { extractText } from './utils'
import { streamResumeDecisions } from '@/lib/sse/stream-resume'
import { streamEdit } from '@/lib/sse/stream-edit'
import { streamRegenerate } from '@/lib/sse/stream-regenerate'
import { streamResumeAttach } from '@/lib/sse/stream-resume-attach'
import { withAutoResume } from '@/lib/sse/with-auto-resume'
import { StreamApiError } from '@/lib/sse/parse-sse'
import { createStreamGuard } from '@/lib/sse/stream-guard'
import { memoryKeys } from '@/lib/hooks/use-memory'
import type { FeedbackAdapter, AttachmentAdapter } from '@assistant-ui/react'
import {
  createHiTLDecisionCoordinator,
  mergeInterruptToolCalls,
  standardInterruptToToolCalls,
  type HiTLDecisionCoordinator,
} from './standard-interrupt'
import { artifactKeys } from '@/lib/api/artifacts'
import { conversationRunsApi } from '@/lib/api/conversation-runs'
import { reportClientError, reportClientWarning } from '@/lib/logging/client-logger'
import { agentQueryKeys } from '@/lib/query-keys/agents'
import { conversationQueryKeys } from '@/lib/query-keys/conversations'

const PHASE_TIMELINE_TOOL_NAME = 'phase_timeline'

// Toast dedup ids — sonner 会替换相同 id 的 toast，阻止同一 stream 内多个
// 错误堆叠的回归。按分类使用独立槽位 → SSE error / stale / reconnect /
// interrupt-state-lost 即使同时发生，也各自只显示 1 条。
const TOAST_ID_STREAM_ERROR = 'chat-stream-error'
const TOAST_ID_STREAM_STALE = 'chat-stream-stale'
const TOAST_ID_RECONNECT_FAILED = 'chat-reconnect-failed'
const TOAST_ID_INTERRUPT_LOST = 'chat-interrupt-state-lost'

const MUTATION_PREFIXES = [
  'add_',
  'remove_',
  'update_',
  'edit_',
  'delete_',
  'enable_',
  'disable_',
  'create_',
] as const

function isMutationToolName(name: string | undefined): boolean {
  if (!name) return false
  return MUTATION_PREFIXES.some((p) => name.startsWith(p))
}

/**
 * 判断 messages refetch 结果中是否到达了新的 assistant 消息。
 *
 * Stream 结束后 messages query refetch 时，用于决定是否清除 streamingMessages
 * 的启发式逻辑。``run_id``(uuid4) 与 ``messages.id``(uuid5(raw_id)) 格式
 * 不同，无法直接匹配 — 通过 set-diff 判断。mid-stream 中断时 backend
 * 未能完成 checkpointer commit，因此没有新的 assistant id，要保留 partial token。
 */
export function hasNewAssistantMessage(
  prev: readonly Message[],
  next: readonly Message[],
): boolean {
  const prevIds = new Set(prev.map((m) => m.id))
  return next.some((m) => m.role === 'assistant' && !prevIds.has(m.id))
}

function snapshotPart(value: unknown): string {
  return JSON.stringify(value ?? null)
}

function messageSnapshot(message: Message): string {
  return [
    message.id,
    message.role,
    message.content,
    message.tool_call_id,
    snapshotPart(message.tool_calls),
    snapshotPart(message.feedback),
    snapshotPart(message.attachments),
    message.parent_id ?? null,
    message.branch_checkpoint_id ?? null,
    snapshotPart(message.siblings),
    snapshotPart(message.sibling_checkpoint_ids),
    message.branch_index ?? null,
    message.branch_total ?? null,
    snapshotPart(message.artifacts),
    snapshotPart(message.usage),
  ].join('\u001f')
}

export function sameMessageSnapshot(prev: readonly Message[], next: readonly Message[]): boolean {
  if (prev.length !== next.length) return false
  return prev.every((message, index) => {
    const other = next[index]
    return other !== undefined && messageSnapshot(message) === messageSnapshot(other)
  })
}

function messagesCheapKey(messages: readonly Message[]): string {
  const first = messages[0]
  const last = messages[messages.length - 1]
  let lastAssistantId = ''
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role === 'assistant') {
      lastAssistantId = message.id
      break
    }
  }

  return [messages.length, first?.id ?? '', last?.id ?? '', lastAssistantId].join('\u001f')
}

interface MergeMessagesForRenderOptions {
  messages: readonly Message[]
  streamingMessages: readonly Message[]
  previousMessages: readonly Message[]
  isRunning: boolean
}

function pushUniqueMessage(target: Message[], seen: Set<string>, message: Message): void {
  if (seen.has(message.id)) return
  seen.add(message.id)
  target.push(message)
}

function newlyPersistedUserContents(
  previousMessages: readonly Message[],
  messages: readonly Message[],
): Set<string> {
  const previousIds = new Set(previousMessages.map((m) => m.id))
  const contents = new Set<string>()
  for (const message of messages) {
    if (message.role === 'user' && !previousIds.has(message.id)) {
      contents.add(message.content)
    }
  }
  return contents
}

export function mergeMessagesForRender({
  messages,
  streamingMessages,
  previousMessages,
  isRunning,
}: MergeMessagesForRenderOptions): Message[] {
  const seen = new Set<string>()
  const merged: Message[] = []
  for (const message of messages) {
    pushUniqueMessage(merged, seen, message)
  }

  if (streamingMessages.length === 0) return merged

  if (!isRunning && hasNewAssistantMessage(previousMessages, messages)) {
    return merged
  }

  const persistedUserContents = !isRunning
    ? newlyPersistedUserContents(previousMessages, messages)
    : null
  for (const message of streamingMessages) {
    if (message.role === 'user' && persistedUserContents?.has(message.content)) continue
    pushUniqueMessage(merged, seen, message)
  }
  return merged
}

/**
 * 基于 fetch 数据，将最后一个 turn 已被取消这一事实（``envelope.latest_run``）
 * 反映到渲染列表中。
 *
 * streaming 路径中的 optimistic notice 可能在 refetch 清空 streamingMessages 的
 * 瞬间一起消失（cancel 显示竞态），刷新后则完全不存在。
 * 若从服务器 truth 推导，两种情况都能稳定显示。
 *
 * - 如果最后一条消息是 assistant，则在该消息末尾追加 notice 文本
 *   （与 optimistic ``appendCanceledNotice`` 形态相同 — 已存在时不变）。
 * - 如果在输出前就被取消、没有 assistant 消息，则追加一条以 run id 为 key 的合成 notice
 *   消息（id 固定 — 避免每次重渲染都被视为新消息）。
 */
export function appendDurableCanceledNotice(
  messages: readonly Message[],
  canceledText: string,
  run: ConversationRun,
): Message[] {
  const last = messages[messages.length - 1]
  if (last && last.role === 'assistant') {
    if (last.content.includes(canceledText)) return [...messages]
    return [
      ...messages.slice(0, -1),
      {
        ...last,
        content: last.content ? `${last.content}\n\n${canceledText}` : canceledText,
      },
    ]
  }
  return [
    ...messages,
    {
      id: `canceled-${run.id}`,
      conversation_id: run.conversation_id,
      role: 'assistant',
      content: canceledText,
      tool_calls: null,
      tool_call_id: null,
      created_at: run.completed_at ?? run.cancel_requested_at ?? run.updated_at,
    },
  ]
}

function addUsageTotals(totals: TokenUsage, usage: TokenUsageBreakdown | null | undefined): void {
  if (!usage) return
  totals.inputTokens += usage.prompt_tokens
  totals.outputTokens += usage.completion_tokens
  totals.cost += usage.estimated_cost ?? 0
}

function sumMessageUsage(messages: readonly Message[]): TokenUsage {
  const totals: TokenUsage = { inputTokens: 0, outputTokens: 0, cost: 0 }
  for (const message of messages) {
    addUsageTotals(totals, message.usage)
  }
  return totals
}

function sameTokenUsage(left: TokenUsage | null, right: TokenUsage): boolean {
  return (
    left !== null &&
    left.inputTokens === right.inputTokens &&
    left.outputTokens === right.outputTokens &&
    left.cost === right.cost
  )
}

function createOptimisticMessage(
  role: 'user' | 'assistant' | 'tool',
  content: string,
  overrides?: Partial<Message>,
): Message {
  return {
    id: `opt-${crypto.randomUUID()}`,
    conversation_id: '',
    role,
    content,
    tool_calls: null,
    tool_call_id: null,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

const BACKEND_MESSAGE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function isBackendMessageId(id: string | null | undefined): id is string {
  return typeof id === 'string' && BACKEND_MESSAGE_ID_PATTERN.test(id)
}

interface StreamFnOptions {
  /** Pre-uploaded attachment ids that should ride along with this message. */
  attachmentIds?: string[]
  /** W3-out M5 — primary POST 响应头 ``X-Run-Id`` 到达时调用 1 次。
   *  仅支持 conversation 路由器的 streamChat/Edit/Regenerate/ResumeDecisions。
   *  其他 streamFn 忽略 → resume 尝试本身禁用。 */
  onRunId?: (runId: string) => void
  /** Draft conversation start endpoint returns the created conversation id. */
  onConversationId?: (conversationId: string) => void
}

type StreamFn = (
  content: string,
  signal: AbortSignal,
  options?: StreamFnOptions,
) => AsyncGenerator<SSEEvent>
type ResumeFn = (
  decisions: Decision[],
  signal: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
) => AsyncGenerator<SSEEvent>

interface RunStreamOptions {
  /** A durable conversation resume is accepted once the POST returns its run id. */
  acceptAfterRunId?: boolean
  /** Keep the current decision batch alive until its resume stream is accepted. */
  preserveHiTLCoordinator?: boolean
  /** Let the decision UI roll back and retry when transport or SSE resume fails. */
  propagateFailure?: boolean
  /** Reject a custom resume that reports an error without a dispatch completion status. */
  requireResumeAcceptance?: boolean
}

interface UseChatRuntimeOptions {
  /** 从 TanStack Query 获取的消息列表 */
  messages: Message[]
  /** W7-4 — 服务器基于 ``token_usages`` 总和发布的 conversation 累计费用（USD）。
   *  fetch 路径的 ``MessageResponse.usage`` 中 ``estimated_cost`` 为空，
   *  必须从这里传递，才能让 Composer token bar 的价格在刷新后仍然保留。 */
  totalCost?: number
  /** SSE 流式函数（streamChat 或 streamAssistant） */
  streamFn: StreamFn
  /** 流式完成后调用。didMutate=true 表示调用了 mutation 工具（建议 invalidate） */
  onStreamEnd?: (didMutate: boolean) => void
  /** 流式消息确认时调用 — 用于保留本地历史记录（AssistantPanel） */
  onMessagesCommit?: (messages: Message[]) => void
  /**
   * 标准 interrupt（`action_requests` / `review_configs` chunk）到达时调用。
   * 自有 `ask_user` native interrupt 也会经过后端适配器走同一路径。
   */
  onStandardInterrupt?: (payload: StandardInterruptPayload) => void
  /** resume 时需要 conversationId（用于 conversations 页面） */
  conversationId?: string
  /** 自定义 resume 函数（用于 Builder v3 等没有 conversationId 的上下文） */
  resumeFn?: ResumeFn
  /** Optional thumbs up/down adapter (P0-1c). */
  feedbackAdapter?: FeedbackAdapter
  /** Optional attachment adapter (P1-7). */
  attachmentAdapter?: AttachmentAdapter
  /** Browser-only speech-to-text adapter for editable composer dictation. */
  dictationAdapter?: DictationAdapter
  /** Durable active run discovered from conversation/message hydration. */
  activeRun?: ConversationRun | null
  /** envelope.latest_run — 最新 run（含 terminal）。基于 fetch 数据推导最后一个 turn 的
   *  canceled/canceling 状态，并据此持久渲染 "被遗弃" notice。
   *  activeRun 不会报告 terminal run。 */
  latestRun?: ConversationRun | null
}

/**
 * 连接现有 SSE 后端与 assistant-ui ExternalStoreRuntime 的适配器 hook。
 *
 * - messages: 从 TanStack Query 加载的既有消息
 * - streamFn: SSE AsyncGenerator（streamChat、streamAssistant 等）
 * - 内部管理 isRunning 和流式消息状态
 */
export function useChatRuntime({
  messages,
  totalCost,
  streamFn,
  onStreamEnd,
  onStandardInterrupt,
  onMessagesCommit,
  conversationId,
  resumeFn,
  feedbackAdapter,
  attachmentAdapter,
  dictationAdapter,
  activeRun,
  latestRun,
}: UseChatRuntimeOptions) {
  const [isRunning, setIsRunning] = useState(false)
  const [streamingMessages, setStreamingMessages] = useState<Message[]>([])
  // streamError 目前仍是尚未暴露给 caller 的 setter-only 状态。将来在 UI 中
  // 显示错误 banner 时使用（目前由 toast 代替）。现在不删除，
  // 只保留 setter 的原因 = 为了不丢失 SSE 事件路径中的 state transition，
  // 正因如此。
  const [, setStreamError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const cancelInFlightRef = useRef(false)
  const cancelNoticePendingRef = useRef(false)
  // 最近一次 emit 的 interrupt_id（用于 resume 时的 stale 校验）
  const lastInterruptIdRef = useRef<string | null>(null)
  const pendingHiTLCoordinatorRef = useRef<HiTLDecisionCoordinator | null>(null)
  const resumeHiTLDecisionRef = useRef<
    (decisions: Decision[], displayText?: string, interruptId?: string | null) => Promise<void>
  >(async () => {})
  // W3-out M5 — primary POST 响应头 ``X-Run-Id`` 与最后一个 SSE event id。
  // 用于 GET ``/stream?run_id=&last_event_id=`` 重连。stream 结束或
  // 新 stream 开始时，在 ``prepareStream`` 中 reset。
  const runIdRef = useRef<string | null>(null)
  const conversationIdRef = useRef<string | undefined>(conversationId)
  const lastEventIdRef = useRef<string | null>(null)
  const attachedActiveRunIdRef = useRef<string | null>(null)
  const failedActiveRunAttachIdRef = useRef<string | null>(null)
  // 本地 stream（POST 发送 or attach）当前是否正在消费。用于 active run attach
  // effect 的守卫，防止其 abort 并抢占正在进行的本地 stream 的竞态。
  // 与 isRunning state 不同，这是无需放进 effect deps 的同步 ref。
  const streamInFlightRef = useRef(false)
  // 当前挂载周期内已消费到底（正常结束 or 用户 cancel）的 run id。即使 stale
  // envelope 仍将该 run 报告为 active，也不再 reattach。
  // 因网络失败而中断的 run 不会记录在这里，因此允许 attach 恢复。
  const consumedRunIdRef = useRef<string | null>(null)
  // 阻止 SSE stream race — 在 Edit/Regenerate fork 过程中，防止旧 generator 的 stale
  // chunk 混入新 stream，并对相同 id 的重复 chunk 做 dedup。
  // ``createStreamGuard`` 是纯函数，因此可安全用作 useState 初始值。
  const streamGuardRef = useRef(createStreamGuard())
  const prevMessagesRef = useRef(messages)
  const lastTokenUsageRef = useRef<TokenUsage | null>(null)
  const setTokenUsage = useSetAtom(sessionTokenUsageAtom)
  const setReconnectState = useSetAtom(reconnectStateAtom)
  const setChatCancelInFlight = useSetAtom(chatCancelInFlightAtom)
  const upsertArtifact = useSetAtom(upsertChatArtifactAtom)
  const setRightRail = useSetAtom(chatRightRailAtom)
  const queryClient = useQueryClient()
  const tReconnect = useTranslations('chat.reconnect')
  const tPage = useTranslations('chat.page')
  const tMemory = useTranslations('chat.memory')

  /** B1 fix — when the user edits/regenerates we already know the new turn
   * will replace messages from ``truncateAtIndex`` onward. Optimistically
   * shorten the messages query cache so the UI doesn't show
   * ``[old chain ... + streaming new turn]`` simultaneously (the visual
   * "flicker" before refetch). The post-stream ``invalidateQueries`` from
   * ``onStreamEnd`` then re-syncs against the new active branch. */
  const truncateMessagesCache = useCallback(
    (truncateAtIndex: number) => {
      if (!conversationId) return
      // 缓存形态为 ``MessagesEnvelope``（{messages, active_tip_message_id, ...}）。
      // ``useMessages`` 通过 ``select`` 只暴露 ``messages``，因此 setQueryData
      // 必须整体更新 envelope（此前假设为 ``Message[]``，调用 prev.slice
      // 时发生 TypeError）。
      queryClient.setQueryData<MessagesEnvelope | undefined>(
        conversationQueryKeys.messages(conversationId),
        (prev) => (prev ? { ...prev, messages: prev.messages.slice(0, truncateAtIndex) } : prev),
      )
    },
    [queryClient, conversationId],
  )

  const prepareStream = useCallback(
    (preserveHiTLCoordinator = false): { signal: AbortSignal; token: number } => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      streamInFlightRef.current = true
      setIsRunning(true)
      if (!preserveHiTLCoordinator) {
        pendingHiTLCoordinatorRef.current?.cancel(
          new DOMException('Pending HiTL decisions were replaced', 'AbortError'),
        )
        pendingHiTLCoordinatorRef.current = null
      }
      runIdRef.current = null
      lastEventIdRef.current = null
      setReconnectState('idle')
      // 发放 stream version — 旧 stream 的 stale event 通过比较此 token 丢弃。
      const token = streamGuardRef.current.begin()
      return { signal: controller.signal, token }
    },
    [setReconnectState],
  )

  // 合并已加载的消息 + 正在流式中的消息。
  // assistant-ui MessageRepository 要求 id 唯一性作为不变量。builder
  // 流程在通过 onMessagesCommit 把 stream 消息放入 ``messages`` 后，
  // ``streamingMessages`` 仍未被清空（因为没有服务器 refetch，hasNewAssistantMessage
  // 为 false），导致相同 id 同时留在两侧 → "same id already exists" 崩溃。优先保留
  // 先出现的项（=messages 中的确认版本），并移除重复 id。普通对话中
  // optimistic(opt-*) 与 backend uuid 不同，不会重复，因此不受影响。
  // 最后一个 turn 是否取消 — 从服务器 truth（envelope.latest_run）推导。isRunning
  // 期间正在进行新的 turn/attach replay，因此不显示。canceling
  // 是指 cancel 请求后、worker 完成 canceled 转换之前 refetch 到达的
  // 情况 — 用户已经请求停止，因此同样显示 notice。
  const durableCanceledRun =
    !isRunning && (latestRun?.status === 'canceled' || latestRun?.status === 'canceling')
      ? latestRun
      : null

  const allMessages = useMemo(() => {
    // 搜索类 N 个分组不再依赖消息预转换（deep-research compaction），
    // 而是在渲染时由 `MessagePrimitive.GroupedParts` 在所有表面统一
    // 泛化处理（Phase-2b）。这里仅负责 fetch/stream 合并。
    const merged = mergeMessagesForRender({
      messages,
      streamingMessages,
      // eslint-disable-next-line react-hooks/refs -- merge needs the last committed snapshot without triggering renders.
      previousMessages: prevMessagesRef.current,
      isRunning,
    })
    if (!durableCanceledRun) return merged
    return appendDurableCanceledNotice(merged, tPage('canceled'), durableCanceledRun)
  }, [isRunning, messages, streamingMessages, durableCanceledRun, tPage])

  const streamingUsageTotals = useMemo(
    () => sumMessageUsage(streamingMessages),
    [streamingMessages],
  )

  useEffect(() => {
    conversationIdRef.current = conversationId
  }, [conversationId])

  useEffect(
    () => () => {
      abortRef.current?.abort()
    },
    [],
  )

  // W7-2 — Composer token bar 由 persisted messages usage + streaming assistant 的
  // message_end usage 推导。为了避免每次 content_delta flush 都重新遍历整个很长的 messages，
  // 仅响应 persisted messages 的变化和 usage 值变化。
  useEffect(() => {
    const persistedUsage = sumMessageUsage(messages)
    const inputTokens = persistedUsage.inputTokens + streamingUsageTotals.inputTokens
    const outputTokens = persistedUsage.outputTokens + streamingUsageTotals.outputTokens
    const perMessageCost = persistedUsage.cost + streamingUsageTotals.cost
    // 若存在 server-side 汇总值（``token_usages`` 表），则优先使用。否则按消息
    // 汇总 cost。fetch 路径的消息中通常 ``estimated_cost`` 为空，因此为
    // 0，但 streaming.py 在 ``message_end`` 中写入 cost 的 streaming 消息仍然
    // 存在，因此对实时显示也有一定帮助。
    const cost = totalCost ?? perMessageCost
    const nextUsage: TokenUsage = { inputTokens, outputTokens, cost }
    if (sameTokenUsage(lastTokenUsageRef.current, nextUsage)) return
    lastTokenUsageRef.current = nextUsage
    setTokenUsage(nextUsage)
  }, [
    messages,
    totalCost,
    setTokenUsage,
    streamingUsageTotals.inputTokens,
    streamingUsageTotals.outputTokens,
    streamingUsageTotals.cost,
  ])

  // Message[] → ThreadMessage[] 转换（自动合并 tool 消息）
  const threadMessages = useExternalMessageConverter({
    callback: convertMessage,
    messages: allMessages,
    isRunning,
  })

  const appendCanceledNotice = useCallback(
    (items: Message[]): Message[] => {
      const canceledText = tPage('canceled')
      let updated = false
      const next = items.map((message) => {
        if (message.role !== 'assistant') return message
        if (message.content.includes(canceledText)) return message
        updated = true
        return {
          ...message,
          content: message.content ? `${message.content}\n\n${canceledText}` : canceledText,
        }
      })
      return updated ? next : [...items, createOptimisticMessage('assistant', canceledText)]
    },
    [tPage],
  )

  /** SSE 流消费的公共逻辑（onNew、onResumeDecisions 共用）
   *
   * ``token`` — ``prepareStream()`` 发放的 stream version。在该 stream 进行
   * 期间如果用户启动新 stream（Edit/Regenerate/cancel），version 会
   * 改变，``isStale(token) === true``，后续 chunk 全部丢弃。
   * AbortController 虽然会中断 fetch，但无法阻止已经 yield 到 buffer 的 chunk，
   * 因此在 caller side 再过滤一次。 */
  const consumeStream = useCallback(
    async (
      stream: AsyncGenerator<SSEEvent>,
      optimisticUserMsg: Message | null,
      token: number,
      requireResumeAcceptance = false,
    ) => {
      let accumulated = ''
      const toolCalls: ToolCallInfo[] = []
      const toolResults: Message[] = []
      const assistantId = `stream-${crypto.randomUUID()}`
      const assistantCreatedAt = new Date().toISOString()
      let streamArtifacts: ArtifactSummary[] = []
      // W7 — 在 message_end 时填充的 4 类 token usage。写入 assistant 消息，
      // 供 footer hover popover 直接引用。
      let messageUsage: TokenUsageBreakdown | null = null
      let hadLifecycleNotice = false
      let resumeError: Error | null = null
      let resumeCompletionStatus: string | null = null

      // tool_calls 数组不会按 token 重新生成，只在 dirty 时做 snapshot。
      // 即使 content_delta 很频繁，也保持 cachedToolCalls 引用不变，使 React.memo 子组件
      // 能用同一引用比较 tool_calls prop。
      let cachedToolCalls: ToolCallInfo[] | null = null
      let toolCallsDirty = true

      const buildStreamState = (): Message[] => {
        if (toolCallsDirty) {
          cachedToolCalls = toolCalls.length > 0 ? [...toolCalls] : null
          toolCallsDirty = false
        }
        const assistantMsg: Message = {
          id: assistantId,
          conversation_id: '',
          role: 'assistant',
          content: accumulated,
          tool_calls: cachedToolCalls,
          tool_call_id: null,
          created_at: assistantCreatedAt,
          usage: messageUsage,
          artifacts: streamArtifacts.length > 0 ? streamArtifacts : null,
        }
        const msgs: Message[] = []
        if (optimisticUserMsg) msgs.push(optimisticUserMsg)
        msgs.push(assistantMsg, ...toolResults)
        return msgs
      }

      setStreamingMessages(buildStreamState())

      // content_delta 从后端每秒到达 60+ 次，但 React 在 SSE 事件
      // 之间不会自动 batching（每个都是独立 microtask）。如果每次都 setState，
      // Streamdown 会重新解析全部累积文本，文本越长累计成本越高。
      // 每个 rAF tick（约 16ms = 60fps）只 flush 一次，在保持相同视觉流畅度的
      // 同时减少渲染次数。
      let rafId: number | null = null
      // stream 是否在无 throw/abort 的情况下消费到底 — 在 finally 中
      // 决定是否记录 ``consumedRunIdRef``。
      let endedNormally = false
      const cancelPendingFlush = () => {
        if (rafId === null) return
        cancelAnimationFrame(rafId)
        rafId = null
      }
      const flushStreamState = () => {
        rafId = null
        if (streamGuardRef.current.isStale(token)) return
        setStreamingMessages(buildStreamState())
      }
      const scheduleFlush = () => {
        if (rafId !== null) return
        rafId = requestAnimationFrame(flushStreamState)
      }

      try {
        for await (const event of stream) {
          // 如果该 stream 已 stale（新 stream 已开始）则立即结束。AbortController
          // 会中断 fetch，但无法阻止已 yield 的 chunk，因此需要 caller side gate。
          if (streamGuardRef.current.isStale(token)) return
          // 忽略同一 stream 内相同 id 的重复 chunk（后端为每个 chunk
          // 发布 ``{msg_id}-{seq}`` 格式的 unique id）。resume 时 boundary
          // 的 1 个重复也通过同一 dedup 过滤。
          if (streamGuardRef.current.isDuplicate(event.id)) continue
          // W3-out M5 — 记住最近看到的 event id。中断时通过 GET
          // ``/stream?last_event_id=`` 从下一个事件继续接收。
          if (event.id) lastEventIdRef.current = event.id
          switch (event.event) {
            case 'content_delta': {
              accumulated += event.data.content ?? event.data.delta ?? ''
              scheduleFlush()
              break
            }
            case 'tool_call_start': {
              const toolName = event.data.tool_name
              const params = event.data.parameters as Record<string, unknown>
              const eventToolCallId =
                typeof event.data.tool_call_id === 'string' && event.data.tool_call_id.trim()
                  ? event.data.tool_call_id.trim()
                  : null
              // phase_timeline 采用单卡片更新（不变模式 — 在相同索引位置替换为新对象）
              if (toolName === PHASE_TIMELINE_TOOL_NAME) {
                const idx = toolCalls.findIndex((tc) => tc.name === PHASE_TIMELINE_TOOL_NAME)
                if (idx >= 0) {
                  toolCalls[idx] = {
                    ...toolCalls[idx],
                    id: eventToolCallId ?? toolCalls[idx].id,
                    args: params,
                  }
                  toolCallsDirty = true
                  setStreamingMessages(buildStreamState())
                  break
                }
              }
              const tcId = eventToolCallId ?? `tc-${crypto.randomUUID()}`
              toolCalls.push({ id: tcId, name: toolName, args: params })
              toolCallsDirty = true
              setStreamingMessages(buildStreamState())
              break
            }
            case 'tool_call_result': {
              const eventToolName = (event.data as { tool_name?: string }).tool_name
              const eventToolCallId =
                typeof event.data.tool_call_id === 'string' && event.data.tool_call_id.trim()
                  ? event.data.tool_call_id.trim()
                  : null
              const resultStr = String(event.data.result ?? '')

              const upsertToolResult = (tc: ToolCallInfo) => {
                const trIdx = toolResults.findIndex((tr) => tr.tool_call_id === tc.id)
                if (trIdx >= 0) {
                  toolResults[trIdx] = { ...toolResults[trIdx], content: resultStr }
                } else {
                  toolResults.push({
                    id: `tr-${crypto.randomUUID()}`,
                    conversation_id: '',
                    role: 'tool',
                    content: resultStr,
                    tool_calls: null,
                    tool_call_id: tc.id ?? null,
                    created_at: new Date().toISOString(),
                  })
                }
                setStreamingMessages(buildStreamState())
              }

              if (eventToolCallId) {
                const tc = toolCalls.find((candidate) => candidate.id === eventToolCallId)
                if (tc) {
                  upsertToolResult(tc)
                  break
                }
              }

              // phase_timeline result 基于 tool_name 匹配（不依赖 lastTc）
              // — 即使中间 emit 了其他 tool，也只精确更新 timeline 卡片
              if (eventToolName === PHASE_TIMELINE_TOOL_NAME) {
                const tcIdx = toolCalls
                  .map((tc, i) => (tc.name === PHASE_TIMELINE_TOOL_NAME ? i : -1))
                  .filter((i) => i >= 0)
                  .pop()
                if (tcIdx !== undefined) {
                  upsertToolResult(toolCalls[tcIdx])
                  break
                }
              }

              // Legacy SSE 没有 tool_call_id。此时对相同 tool_name 且尚未
              // 绑定 result 的调用按 FIFO 匹配。
              const usedToolCallIds = new Set(
                toolResults.map((result) => result.tool_call_id).filter(Boolean),
              )
              const matchingTc = toolCalls.find(
                (tc) =>
                  tc.name === eventToolName &&
                  Boolean(tc.id) &&
                  !usedToolCallIds.has(tc.id ?? null),
              )
              if (matchingTc) {
                upsertToolResult(matchingTc)
              }
              break
            }
            case 'file_event': {
              const fileEvent = event.data as FileEventPayload
              upsertArtifact(fileEvent)
              streamArtifacts = upsertArtifactList(streamArtifacts, fileEvent)
              setStreamingMessages(buildStreamState())
              queryClient.invalidateQueries({ queryKey: artifactKeys.all })
              if (fileEvent.op !== 'deleted') {
                setRightRail({
                  mode: 'artifacts',
                  artifacts: {
                    conversationId: fileEvent.conversation_id,
                    selectedArtifactId: fileEvent.id,
                    view: 'preview',
                  },
                })
              }
              break
            }
            case 'memory_proposed': {
              queryClient.invalidateQueries({ queryKey: memoryKeys.all })
              toast.info(tMemory('proposedToast'))
              break
            }
            case 'memory_saved': {
              queryClient.invalidateQueries({ queryKey: memoryKeys.all })
              toast.success(tMemory('savedToast'))
              break
            }
            case 'memory_rejected': {
              queryClient.invalidateQueries({ queryKey: memoryKeys.all })
              toast.warning(tMemory('rejectedToast'))
              break
            }
            case 'memory_deleted': {
              queryClient.invalidateQueries({ queryKey: memoryKeys.all })
              toast.success(tMemory('deletedToast'))
              break
            }
            case 'interrupt': {
              setIsRunning(false)
              const data = event.data as StandardInterruptPayload
              if (data.interrupt_id) lastInterruptIdRef.current = data.interrupt_id
              // 空 fallback chunk — backend 因 ``aget_state`` 失败无法给出精确 action，
              // 仅填充标准 middleware contract 后 emit（streaming.py）。
              // 为避免 turn 静默卡住，通过 toast 提示用户。
              if (data.action_requests.length === 0 && data.review_configs.length === 0) {
                toast.error(tPage('interruptStateLost'), { id: TOAST_ID_INTERRUPT_LOST })
                break
              }
              const coordinator = createHiTLDecisionCoordinator({
                totalActions: data.action_requests.length,
                interruptId: data.interrupt_id ?? null,
                resume: async (decisions, displayText, interruptId) => {
                  await resumeHiTLDecisionRef.current(decisions, displayText, interruptId)
                  if (pendingHiTLCoordinatorRef.current === coordinator) {
                    pendingHiTLCoordinatorRef.current = null
                  }
                },
              })
              pendingHiTLCoordinatorRef.current = coordinator
              const syntheticToolCalls = standardInterruptToToolCalls(data)
              if (syntheticToolCalls.length > 0) {
                toolCalls.splice(0, toolCalls.length, ...mergeInterruptToolCalls(toolCalls, data))
                toolCallsDirty = true
                setStreamingMessages(buildStreamState())
              }
              onStandardInterrupt?.(data)
              break
            }
            case 'error': {
              const errMsg = (event.data as { message?: string }).message ?? tPage('error')
              setStreamError(errMsg)
              // 为避免 SSE error event 静默消失，通过 toast 提示用户。
              // ``setStreamError`` 是 setter-only state，因此不会暴露到 UI。
              // 同一 stream 内出现多个 error event 时，为了让 sonner 替换相同 id 的 toast，
              // 赋予 dedup id — 只显示最后一条消息，避免堆叠。
              toast.error(errMsg, { id: TOAST_ID_STREAM_ERROR })
              resumeError ??= new Error(errMsg)
              break
            }
            case 'message_end': {
              const status = (event.data as { status?: unknown }).status
              if (typeof status === 'string') resumeCompletionStatus = status
              // 更新 token usage — 包括 session 累计值 + 消息级 4 类 usage。
              const usage = (
                event.data as {
                  usage?: Partial<TokenUsageBreakdown>
                }
              ).usage
              if (usage) {
                const breakdown: TokenUsageBreakdown = {
                  prompt_tokens: usage.prompt_tokens ?? 0,
                  completion_tokens: usage.completion_tokens ?? 0,
                  cache_creation_tokens: usage.cache_creation_tokens ?? 0,
                  cache_read_tokens: usage.cache_read_tokens ?? 0,
                  estimated_cost: usage.estimated_cost,
                  // streaming timing — 因为会显式重建 key，不补上就会被 drop。
                  ttft_ms: usage.ttft_ms,
                  generation_ms: usage.generation_ms,
                  tokens_per_second: usage.tokens_per_second,
                }
                messageUsage = breakdown
                // 写入 streamingMessages 后，上方 useEffect 会自动更新 token bar
                // （对 allMessages.usage 求和）自动更新。不需要额外的累计调用
                // — 累计逻辑会在刷新时把 atom reset 为 0，
                // 曾导致 token bar 消失的回归。
                setStreamingMessages(buildStreamState())
              }
              break
            }
            case 'stale': {
              // W3-out M3 — backend broker 在 in-flight turn 期间死亡，GET
              // resume 仅收到 DB replay 的信号。意味着 message_end 没有到达，
              // 因此 (a) token 可能部分缺失，且 (b)
              // withAutoResume 的自动 retry 也不再有意义。通过清理 indicator
              // 整理 + toast 提示，让用户知道 "为什么响应停止了"。
              setReconnectState('idle')
              setStreamError('broker_lost')
              const staleNotice = tReconnect('stale')
              accumulated = accumulated ? `${accumulated}\n\n${staleNotice}` : staleNotice
              hadLifecycleNotice = true
              setStreamingMessages(buildStreamState())
              if (!streamGuardRef.current.isStale(token)) {
                toast.warning(staleNotice, { id: TOAST_ID_STREAM_STALE })
              }
              break
            }
          }
        }
        if (requireResumeAcceptance && resumeCompletionStatus === null) {
          throw resumeError ?? new Error('Resume stream ended before dispatch acceptance')
        }
        endedNormally = true
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          throw err
        }
      } finally {
        const isStaleStream = streamGuardRef.current.isStale(token)
        const hadPendingFlush = rafId !== null
        cancelPendingFlush()
        // 如果 stale，则新 stream 已经持有 in-flight 标志 — 不要触碰。
        if (isStaleStream) return

        streamInFlightRef.current = false
        if (endedNormally) {
          // 仅把无 throw/abort、完整结束的 run 记录为 "消费完成" — 因网络失败
          // 中断的 run 不记录，以便 active run attach 可以恢复。
          consumedRunIdRef.current = runIdRef.current
        }
        setIsRunning(false)
        const hadCancelNotice = cancelNoticePendingRef.current
        let finalMsgs = buildStreamState()
        if (hadCancelNotice) {
          finalMsgs = appendCanceledNotice(finalMsgs)
          cancelNoticePendingRef.current = false
        }
        if (onMessagesCommit) {
          // commit 回调负责 messages。必须在同一 batch 中清空 streaming，
          // 才能确保下一次 render 的 ``allMessages`` 中相同 id（stream-{uuid}
          // / opt-{uuid} / tr-{uuid}）不会同时存在于 messages 与 streamingMessages
          // 两侧。如果同时存在，assistant-ui 的
          // MessageRepository.link 会以 "duplicate id in parent tree" 抛错。
          setStreamingMessages([])
          onMessagesCommit(finalMsgs)
        } else if (hadPendingFlush || hadCancelNotice || hadLifecycleNotice) {
          // refetch-driven 路径（普通聊天）：不清空 streamingMessages，
          // 一直保留到 backend messages refetch — 避免答案在屏幕上短暂消失
          // 后又出现的闪烁。仅将 rAF-batched 的最后一次 flush
          // 同步应用，让最终文本立即反映到屏幕上。cleanup
          // 由下方 prevMessagesRef 比较块（line 519~）负责。
          setStreamingMessages(finalMsgs)
        }
        // interrupt(HiTL) 也是图被暂停后的 stream 结束 — backend 已把 ask_user tool_call
        // 保存进 DB，因此必须通过 onStreamEnd invalidate messages query，
        // 才能避免清空 streaming 后 UI 中的 ask_user input 消失，并由 fetch 到的消息补上。
        // didMutate：是否调用了 write 工具？调用方据此决定是否 invalidate 表单缓存。
        const didMutate = toolCalls.some((tc) => isMutationToolName(tc.name))
        onStreamEnd?.(didMutate)
      }
    },
    [
      onStreamEnd,
      onStandardInterrupt,
      onMessagesCommit,
      setReconnectState,
      upsertArtifact,
      setRightRail,
      tReconnect,
      tPage,
      tMemory,
      queryClient,
      appendCanceledNotice,
    ],
  )
  const consumeStreamRef = useRef(consumeStream)
  useEffect(() => {
    consumeStreamRef.current = consumeStream
  }, [consumeStream])
  const activeAttachStaleFallbackRef = useRef<() => void>(() => {})
  useEffect(() => {
    activeAttachStaleFallbackRef.current = () => {
      const staleNotice = tReconnect('stale')
      setReconnectState('idle')
      setStreamError('broker_lost')
      setStreamingMessages([createOptimisticMessage('assistant', staleNotice)])
      toast.warning(staleNotice, { id: TOAST_ID_STREAM_STALE })
      onStreamEnd?.(false)
    }
  }, [onStreamEnd, setReconnectState, tReconnect])

  const activeRunId = activeRun?.id ?? null
  const activeRunStatus = activeRun?.status ?? null

  useEffect(() => {
    if (!conversationId || !activeRunId || !isActiveRunStatus(activeRunStatus)) return
    if (failedActiveRunAttachIdRef.current === activeRunId) return
    if (attachedActiveRunIdRef.current === activeRunId) return
    // 不抢占正在进行的本地 stream（POST 发送/既有 attach）— 服务器
    // 保证每个 conversation 只有 1 个 active run，因此正在进行的 stream 就是这个
    // run（envelope snapshot 延迟到达的情况）。
    if (streamInFlightRef.current) return
    // 防止对已经消费到底（正常结束/cancel）的 run 的 stale envelope 重新 attach。
    // 因网络失败而中断的 run 不会命中这里，因此可通过 attach 恢复。
    if (consumedRunIdRef.current === activeRunId) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    attachedActiveRunIdRef.current = activeRunId
    failedActiveRunAttachIdRef.current = null
    runIdRef.current = activeRunId
    lastEventIdRef.current = null
    streamInFlightRef.current = true
    setIsRunning(true)
    setReconnectState('reconnecting')
    const streamGuard = streamGuardRef.current
    const token = streamGuard.begin()

    const primary = () =>
      streamResumeAttach(conversationId, activeRunId, undefined, controller.signal, ({ mode }) => {
        if (mode === 'live' || mode === 'replay') setReconnectState('idle')
      }) as AsyncGenerator<SSEEvent>
    const wrapped = withAutoResume(
      primary,
      (lastEventId) =>
        streamResumeAttach(
          conversationId,
          activeRunId,
          lastEventId,
          controller.signal,
        ) as AsyncGenerator<SSEEvent>,
      {
        signal: controller.signal,
        onReconnecting: () => setReconnectState('reconnecting'),
        onReconnected: () => setReconnectState('idle'),
        onFailed: () => {
          if (controller.signal.aborted) return
          setReconnectState('idle')
        },
      },
    )

    void consumeStreamRef
      .current(wrapped, null, token)
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof StreamApiError && err.code === 'RESUME_NOT_FOUND') {
          failedActiveRunAttachIdRef.current = activeRunId
          streamInFlightRef.current = false
          setIsRunning(false)
          activeAttachStaleFallbackRef.current()
          return
        }
        failedActiveRunAttachIdRef.current = activeRunId
        setReconnectState('idle')
        setIsRunning(false)
        reportClientError('useChatRuntime', 'Active run attach failed:', err)
      })
      .finally(() => {
        if (attachedActiveRunIdRef.current === activeRunId) {
          attachedActiveRunIdRef.current = null
        }
      })

    return () => {
      // unmount/deps 变化时先使该 attach 的 token 失效 — 避免 abort 之后
      // consumeStream finally 对已 unmount 的组件执行 setState/onStreamEnd。
      // 防止这些调用执行。如果新 stream 已经替换令牌，则跳过。
      if (attachedActiveRunIdRef.current === activeRunId) {
        attachedActiveRunIdRef.current = null
      }
      if (!streamGuard.isStale(token)) {
        streamGuard.begin()
        streamInFlightRef.current = false
        setIsRunning(false)
        setReconnectState('idle')
      }
      controller.abort()
    }
  }, [activeRunId, activeRunStatus, conversationId, setReconnectState])

  // messages 重新 fetch 后（refetch 完成）清除 streaming messages。
  // 防止 streaming 刚结束时 messages → effective 切换产生闪烁。
  //
  // W3-out M5 回归守卫：turn 在 mid-stream 中断时，backend 无法完成 finalize_turn /
  // checkpointer commit，因此 ``messages`` 中没有 assistant row。在这种状态下
  // 若清空 streamingMessages，用户已经收到的 partial token 会从屏幕消失。
  // 通过 refetch 结果中是否到达新的 assistant 消息来判断 "是否真的已 persist"。
  // run_id ↔ messages.id 格式不同（uuid4 vs uuid5(raw_id)），无法直接
  // 匹配 — 不做 id 匹配，改用 ``hasNewAssistantMessage`` set-diff 启发式。
  const messagesKey = useMemo(() => messagesCheapKey(messages), [messages])
  useEffect(() => {
    const prevMessages = prevMessagesRef.current
    const prevMessagesKey = messagesCheapKey(prevMessages)

    if (prevMessages === messages) return
    if (prevMessagesKey === messagesKey && sameMessageSnapshot(prevMessages, messages)) return
    if (isRunning && streamingMessages.length > 0) return

    prevMessagesRef.current = messages
    if (streamingMessages.length === 0) return
    if (hasNewAssistantMessage(prevMessages, messages)) {
      setStreamingMessages([])
    } else {
      // assistant 未提交（中断的 turn）— 保留 partial assistant + tool 结果，
      // 但 user 消息通常在 backend 进入 POST 后立即保存，因此已经存在于 ``messages`` 中。
      // 若继续保留 optimistic user copy，user bubble 会重复
      // 显示（id 为 ``opt-{uuid}`` vs backend UUID，无法匹配）。
      setStreamingMessages((sm) => sm.filter((m) => m.role !== 'user'))
    }
  }, [isRunning, messages, messagesKey, streamingMessages.length])

  /** P0-C — shared stream runner for new/edit/reload/resume.
   *
   * - ``streamFactory`` builds the SSE generator lazily so each handler can
   *   close over its own args (signal, conversationId, attachments, ...).
   * - ``optimisticMsg`` is the user bubble injected immediately for visual
   *   responsiveness; ``null`` for reload (assistant-only).
   * - ``truncateAtIdx`` drops cached messages from that index onward (B1 fix)
   *   to prevent the "old chain underneath new" flicker on edit/reload.
   */
  const _runStream = useCallback(
    async (
      streamFactory: (
        signal: AbortSignal,
        onRunId: (id: string) => void,
        onConversationId: (id: string) => void,
      ) => AsyncGenerator<SSEEvent>,
      optimisticMsg: Message | null,
      truncateAtIdx?: number,
      options: RunStreamOptions = {},
    ) => {
      if (truncateAtIdx !== undefined && truncateAtIdx >= 0) {
        truncateMessagesCache(truncateAtIdx)
      }
      const { signal, token } = prepareStream(options.preserveHiTLCoordinator)
      let acceptedRunId = false
      const onRunId = (id: string) => {
        acceptedRunId = true
        runIdRef.current = id
        queryClient.invalidateQueries({ queryKey: agentQueryKeys.all })
      }
      const onConversationId = (id: string) => {
        conversationIdRef.current = id
      }
      const primary = () => streamFactory(signal, onRunId, onConversationId)
      // GET ``/stream`` resume 仅 conversations 路由器支持。builder/assistant
      // 等其他 streamFn 要么没有 conversationId，要么 runId 为空，因此
      // resumeFactory 为 ``null`` → withAutoResume 不重试并直接 throw。
      const resumeFactory = (lastEventId: string | undefined) => {
        const activeConversationId = conversationIdRef.current
        if (!activeConversationId) return null
        const runId = runIdRef.current
        if (!runId) return null
        return streamResumeAttach(
          activeConversationId,
          runId,
          lastEventId,
          signal,
        ) as AsyncGenerator<SSEEvent>
      }
      const wrapped = withAutoResume(primary, resumeFactory, {
        signal,
        onReconnecting: () => {
          // 忽略 stale stream（新 turn 已经开始）的 retry 提示 — 避免把新 turn
          // 的 prepareStream 已 reset 为 idle 的状态再次覆盖成 reconnecting
          // 覆盖。
          if (streamGuardRef.current.isStale(token)) return
          setReconnectState('reconnecting')
        },
        onReconnected: () => {
          if (streamGuardRef.current.isStale(token)) return
          setReconnectState('idle')
        },
        onFailed: (err) => {
          // 用户 cancel（AbortError）或 stale stream（Edit/Regenerate/新 turn）
          // 都静默处理，不显示 toast。只有同时通过两道守卫的真实失败才通知用户。
          if (streamGuardRef.current.isStale(token)) return
          setReconnectState('idle')
          if (signal.aborted) return
          // Actionable backend errors (e.g. ``llm_credential_required``)
          // surface as an inline assistant-side message instead of a toast
          // so the user sees the guidance in chat flow without a duplicate
          // "reconnect failed" notification on top.
          if (err instanceof StreamApiError && err.code === 'llm_credential_required') {
            setStreamingMessages((prev) => [
              ...prev,
              createOptimisticMessage(
                'assistant',
                tReconnect('credentialRequiredAction', { message: err.message }),
              ),
            ])
            return
          }
          toast.error(tReconnect('failed'), { id: TOAST_ID_RECONNECT_FAILED })
          reportClientError('useChatRuntime', 'Stream resume failed:', err)
        },
      })
      try {
        await consumeStream(wrapped, optimisticMsg, token, options.requireResumeAcceptance)
        const resumeWasAccepted = options.acceptAfterRunId === true && acceptedRunId
        if (options.propagateFailure && signal.aborted && !resumeWasAccepted) {
          throw new DOMException('Resume was aborted before acceptance', 'AbortError')
        }
      } catch (err) {
        const resumeWasAccepted = options.acceptAfterRunId === true && acceptedRunId
        if (err instanceof DOMException && err.name === 'AbortError') {
          if (options.propagateFailure && !resumeWasAccepted) throw err
          return
        }
        if (err instanceof StreamApiError && err.code === 'llm_credential_required') {
          if (options.propagateFailure && !resumeWasAccepted) throw err
          return
        }
        reportClientError('useChatRuntime', 'Stream error:', err)
        if (options.propagateFailure && !resumeWasAccepted) throw err
      }
    },
    [
      consumeStream,
      truncateMessagesCache,
      setReconnectState,
      tReconnect,
      prepareStream,
      queryClient,
    ],
  )

  const onNew = useCallback(
    async (appendMessage: {
      content: readonly { type: string; text?: string }[]
      attachments?: readonly { id: string }[]
    }) => {
      const content = extractText(appendMessage.content)
      if (!content && (!appendMessage.attachments || appendMessage.attachments.length === 0)) {
        return
      }
      const userMsg = createOptimisticMessage('user', content)
      const attachmentIds = appendMessage.attachments?.map((a) => a.id)
      await _runStream(
        (signal, onRunId, onConversationId) =>
          streamFn(content, signal, { attachmentIds, onRunId, onConversationId }),
        userMsg,
      )
    },
    [streamFn, _runStream],
  )

  /**
   * HiTL：标准 interrupt 响应后恢复图。`decisions.length` 必须
   * 与 `action_requests.length` 一致，middleware 才会将其识别为 valid response。
   *
   * 注入 `resumeFn` 时（builder v3）：ADR-012 §Phase 5 — 将标准 ``Decision[]``
   * 原样传给 builder router。Backend ``decisions_to_builder_response``
   * helper 会按 phase 转换为 native shape。
   */
  const onResumeDecisions = useCallback(
    async (decisions: Decision[], displayText?: string, interruptId?: string | null) => {
      const intrId = interruptId ?? lastInterruptIdRef.current
      const userMsg = displayText ? createOptimisticMessage('user', displayText) : null

      if (resumeFn) {
        await _runStream(
          (signal) => resumeFn(decisions, signal, displayText, intrId),
          userMsg,
          undefined,
          {
            preserveHiTLCoordinator: true,
            propagateFailure: true,
            requireResumeAcceptance: true,
          },
        )
        return
      }

      if (!conversationId) throw new Error('Resume target is unavailable')
      await _runStream(
        (signal, onRunId) => streamResumeDecisions(conversationId, decisions, signal, { onRunId }),
        userMsg,
        undefined,
        {
          acceptAfterRunId: true,
          preserveHiTLCoordinator: true,
          propagateFailure: true,
        },
      )
    },
    [conversationId, resumeFn, _runStream],
  )

  useEffect(() => {
    resumeHiTLDecisionRef.current = onResumeDecisions
  }, [onResumeDecisions])

  const registerDecision = useCallback(
    async (
      actionIndex: number,
      decision: Decision,
      displayText?: string,
      interruptId?: string | null,
    ) => {
      const coordinator = pendingHiTLCoordinatorRef.current
      if (!coordinator) {
        if (interruptId !== undefined) {
          throw new DOMException('HiTL interrupt is no longer active', 'InvalidStateError')
        }
        await onResumeDecisions([decision], displayText)
        return
      }
      if (interruptId !== undefined && coordinator.interruptId !== interruptId) {
        throw new DOMException('HiTL interrupt is no longer active', 'InvalidStateError')
      }
      await coordinator.registerDecision(actionIndex, decision, displayText)
    },
    [onResumeDecisions],
  )

  const onCancel = useCallback(async () => {
    const controller = abortRef.current
    const activeConversationId = conversationIdRef.current
    const runId = runIdRef.current

    if (!activeConversationId || !runId) {
      reportClientWarning('useChatRuntime', 'Stop requested before server run id was available.')
      controller?.abort()
      return
    }
    if (cancelInFlightRef.current) return

    cancelInFlightRef.current = true
    setChatCancelInFlight(true)
    try {
      const run = await conversationRunsApi.cancel(activeConversationId, runId)
      queryClient.invalidateQueries({ queryKey: agentQueryKeys.all })
      queryClient.invalidateQueries({
        queryKey: conversationQueryKeys.prefix(activeConversationId),
      })
      if (run.status === 'canceling' || run.status === 'canceled') {
        cancelNoticePendingRef.current = true
        // 用户取消的 run — 为避免 canceling 状态仍以 active 保留在 envelope 中
        // 时被 attach effect 重新唤起，将其记录为已消费完成。
        consumedRunIdRef.current = runId
        controller?.abort()
      }
    } catch (err) {
      reportClientWarning(
        'useChatRuntime',
        'Server cancel request failed; keeping stream attached.',
        err,
      )
    } finally {
      cancelInFlightRef.current = false
      setChatCancelInFlight(false)
    }
  }, [queryClient, setChatCancelInFlight])

  /** M-CHAT1b — edit a user message in place via LangGraph thread fork. */
  const onEdit = useCallback(
    async (message: {
      content: readonly { type: string; text?: string }[]
      sourceId?: string | null
      parentId?: string | null
    }) => {
      const content = extractText(message.content)
      if (!content) return
      const userMsg = createOptimisticMessage('user', content)
      // B1 fix — drop everything from the edited message onward.
      const editIdx =
        conversationId && message.sourceId
          ? messages.findIndex((m) => m.id === message.sourceId)
          : -1
      // Refetch race guard — optimistic id（`opt-…`）无法通过 backend UUID 校验
      // （422）。该路径发生在 refetch 未能替换 streamingMessages 的
      // 状态下，用户立即点击编辑时。回退为新 turn。
      const hasBackendId = isBackendMessageId(message.sourceId)
      const useFork = conversationId && hasBackendId
      await _runStream(
        (signal, onRunId, onConversationId) =>
          useFork
            ? streamEdit(conversationId as string, message.sourceId as string, content, signal, {
                onRunId,
              })
            : streamFn(content, signal, { onRunId, onConversationId }),
        userMsg,
        useFork ? editIdx : undefined,
      )
    },
    [streamFn, _runStream, conversationId, messages],
  )

  /** M-CHAT1b — regenerate an assistant turn in place via LangGraph fork. */
  const onReload = useCallback(
    async (parentId: string | null) => {
      if (conversationId) {
        // Find the assistant message that is a direct child of ``parentId``
        // in the active branch — that's the one BranchPicker should treat as
        // a sibling of the new turn.
        let targetMessageId: string | undefined
        let assistantIdxInMessages = -1
        if (parentId) {
          const merged = [...messages, ...streamingMessages]
          const idx = merged.findIndex((m) => m.id === parentId)
          const next = idx >= 0 ? merged[idx + 1] : undefined
          // Client-only ids（`opt-…`、`stream-…`）无法通过 backend UUID 校验，
          // 因此回退为空 targetMessageId，让 backend 自动选择最新 assistant tip。
          // 自动选择。
          if (next?.role === 'assistant' && isBackendMessageId(next.id)) {
            targetMessageId = next.id
            // Index inside ``messages`` (not merged) for the cache truncate.
            assistantIdxInMessages = messages.findIndex((m) => m.id === next.id)
          }
        }
        await _runStream(
          (signal, onRunId) =>
            streamRegenerate(conversationId, targetMessageId, signal, { onRunId }),
          null,
          assistantIdxInMessages >= 0 ? assistantIdxInMessages : undefined,
        )
        return
      }
      // No conversation context — replay the last user message.
      const merged = [...messages, ...streamingMessages]
      const lastUser = [...merged].reverse().find((m) => m.role === 'user')
      if (!lastUser?.content) return
      await _runStream(
        (signal, onRunId, onConversationId) =>
          streamFn(lastUser.content, signal, { onRunId, onConversationId }),
        null,
      )
    },
    [messages, streamingMessages, streamFn, _runStream, conversationId],
  )

  const adapters = useMemo(() => {
    if (!feedbackAdapter && !attachmentAdapter && !dictationAdapter) return undefined
    return {
      ...(feedbackAdapter ? { feedback: feedbackAdapter } : {}),
      ...(attachmentAdapter ? { attachments: attachmentAdapter } : {}),
      ...(dictationAdapter ? { dictation: dictationAdapter } : {}),
    }
  }, [feedbackAdapter, attachmentAdapter, dictationAdapter])

  const runtime = useExternalStoreRuntime({
    messages: threadMessages,
    isRunning,
    onNew,
    onEdit,
    onReload,
    onCancel,
    adapters,
  })

  /** 用于从外部自动发送第一条消息（e.g., URL ?initialMessage=...） */
  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed) return
      await _runStream(
        (signal, onRunId, onConversationId) =>
          streamFn(trimmed, signal, { onRunId, onConversationId }),
        createOptimisticMessage('user', trimmed),
      )
    },
    [streamFn, _runStream],
  )

  return { runtime, onResumeDecisions, registerDecision, sendMessage }
}
