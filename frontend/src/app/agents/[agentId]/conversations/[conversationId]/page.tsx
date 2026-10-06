'use client'

import { use, useEffect, useCallback, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useSetAtom } from 'jotai'
import { useTranslations } from 'next-intl'
import type { Conversation, Message } from '@/lib/types'
import { useAgent, useAgentRuntimeReadiness } from '@/lib/hooks/use-agents'
import { useSession } from '@/lib/auth/session'
import {
  useMessagesEnvelope,
  useMarkConversationRead,
  conversationDetailQueryOptions,
  conversationKeys,
  invalidateConversationNavigators,
  upsertConversationNavigatorCache,
} from '@/lib/hooks/use-conversations'
import { useConversationTitle } from '@/lib/hooks/use-conversation-title'
import { useQueryClient } from '@tanstack/react-query'
import { streamChat, streamStartConversation, type StreamChatOptions } from '@/lib/sse/stream-chat'
import { sessionTokenUsageAtom } from '@/lib/stores/chat-store'
import { chatRightRailAtom, toggleArtifactListRailState } from '@/lib/stores/chat-right-rail'
import {
  conversationRuntimeStatusAtom,
  type ConversationRuntimeStatus,
} from '@/lib/stores/chat-navigator-store'
import { useChatFeedbackAdapter } from '@/lib/chat/feedback-adapter'
import { moldyAttachmentAdapter } from '@/lib/chat/attachment-adapter'
import { getChatRuntimeMode } from '@/lib/chat/runtime-mode'
import {
  CHAT_ROUTE_CLEARED_EVENT,
  CHAT_ROUTE_REPLACED_EVENT,
  clearChatRouteReplacement,
  conversationIdFromChatPath,
  isChatRouteReplacedEvent,
  replaceChatRouteWithoutRemount,
} from '@/lib/chat/chat-route-replacement'
import { useLangGraphDraftConversation } from '@/lib/chat/langgraph-runtime/use-langgraph-draft-conversation'
import { ChatRuntimeSection } from '@/components/chat/chat-runtime-section'
import { ToolIconProvider } from '@/components/chat/tool-ui/tool-icon-context'
import { ChatEmptyState } from '@/components/chat/chat-empty-state'
import { ChatPageHeader } from '@/components/chat/chat-page-header'
import { PinnedConversationSummary } from '@/components/chat/pinned-conversation-summary'
import { ExportDialog } from '@/components/chat/export-dialog'
import { SideChatWorkspace } from '@/components/chat/side-chat/side-chat-workspace'
import { SideChatPanel, ConversationDetailRail } from '@/components/chat/side-chat/side-chat-panel'
import { Skeleton } from '@/components/ui/skeleton'

const EMPTY_MESSAGES: Message[] = []

interface RouteConversationOverride {
  readonly routeKey: string
  readonly conversationId: string
}

interface DraftTitleDetailSuppression {
  readonly routeKey: string
  readonly conversationId: string
}

export default function ChatPage({
  params,
}: {
  params: Promise<{ agentId: string; conversationId: string }>
}) {
  const { agentId, conversationId } = use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const routeKey = `${agentId}:${conversationId}`
  const [routeConversationOverride, setRouteConversationOverride] =
    useState<RouteConversationOverride | null>(null)
  const routeConversationId =
    routeConversationOverride?.routeKey === routeKey
      ? routeConversationOverride.conversationId
      : conversationId
  const isDraftConversation = routeConversationId === 'new'
  const startedConversationIdRef = useRef<string | null>(null)
  const [draftTitleDetailSuppression, setDraftTitleDetailSuppression] =
    useState<DraftTitleDetailSuppression | null>(null)
  const draftTitleDetailSuppressionConversationId =
    draftTitleDetailSuppression?.routeKey === routeKey
      ? draftTitleDetailSuppression.conversationId
      : null
  const [suppressEmptyStateForConversationId, setSuppressEmptyStateForConversationId] = useState<
    string | null
  >(null)
  const [exportOpen, setExportOpen] = useState(false)
  const { data: agent } = useAgent(agentId)
  const { data: runtimeReadiness } = useAgentRuntimeReadiness(agentId)
  const { data: user } = useSession()
  const messageEnvelopeConversationId = routeConversationId
  const shouldLoadMessageEnvelope = !isDraftConversation
  const isPromotedDraftRoute = conversationId === 'new' && !isDraftConversation
  // W7-4 — 从 envelope 获取 conversation 累计成本并传到 token bar。同一个
  // query observer 中同时派生 messages 和 cost，以减少 chat tree rerender。
  const { data: envelope, isLoading: messagesLoading } = useMessagesEnvelope(
    messageEnvelopeConversationId,
    shouldLoadMessageEnvelope,
  )
  const messages = envelope?.messages ?? EMPTY_MESSAGES
  const markConversationRead = useMarkConversationRead(agentId)
  const { mutate: markRead, isPending: isMarkingRead } = markConversationRead
  const t = useTranslations('chat.page')
  const setSessionTokenUsage = useSetAtom(sessionTokenUsageAtom)
  const setRightRail = useSetAtom(chatRightRailAtom)
  const setConversationRuntimeStatus = useSetAtom(conversationRuntimeStatusAtom)

  // 仅从 cache 提取当前 conversation title（避免订阅整个列表）
  const currentConversation = queryClient
    .getQueryData<Conversation[]>(conversationKeys.list(agentId))
    ?.find((c) => c.id === routeConversationId)
  const markedReadKeyRef = useRef<string | null>(null)
  const runtimeMode = getChatRuntimeMode()

  useEffect(() => {
    const handleRouteReplacement = (event: Event) => {
      if (!isChatRouteReplacedEvent(event)) return
      const replacedConversationId = conversationIdFromChatPath(event.detail.pathname, agentId)
      if (!replacedConversationId) return
      setRouteConversationOverride({
        routeKey,
        conversationId: replacedConversationId,
      })
    }
    const clearRouteOverride = () => setRouteConversationOverride(null)

    window.addEventListener(CHAT_ROUTE_REPLACED_EVENT, handleRouteReplacement)
    window.addEventListener(CHAT_ROUTE_CLEARED_EVENT, clearRouteOverride)
    window.addEventListener('popstate', clearRouteOverride)
    return () => {
      window.removeEventListener(CHAT_ROUTE_REPLACED_EVENT, handleRouteReplacement)
      window.removeEventListener(CHAT_ROUTE_CLEARED_EVENT, clearRouteOverride)
      window.removeEventListener('popstate', clearRouteOverride)
    }
  }, [agentId, routeKey])

  useEffect(() => {
    setSessionTokenUsage({ inputTokens: 0, outputTokens: 0, cost: 0 })
    markedReadKeyRef.current = null
    startedConversationIdRef.current = null
  }, [agentId, conversationId, setSessionTokenUsage])

  // M4 — read 处理 effect。
  // ``currentConversation`` 为避免订阅整个列表，会从 cache 同步
  // 读取，因此该 component 不订阅 list query。于是这个 effect
  // 再次看到新的 unread 并运行的 trigger 只有以下两个：
  //   1) ``routeConversationId`` 变化（切换 conversation），
  //   2) navigator invalidation 导致 list query refetch，``unread_count`` 变化并
  //      发生 rerender → 这个 effect 的 ``currentConversation?.unread_count`` 依赖项
  //      更新时。
  // 由于 markedReadKey 是 ``${id}:${unreadCount}``，对相同 unread 值的重复
  // mark 会被抑制为一次，unread 增加时只会再次 mark 一次。
  useEffect(() => {
    if (isDraftConversation) return
    if (messagesLoading || isMarkingRead) return
    const unreadCount = currentConversation?.unread_count ?? 0
    if (unreadCount <= 0) return
    const markReadKey = `${routeConversationId}:${unreadCount}`
    if (markedReadKeyRef.current === markReadKey) return
    markedReadKeyRef.current = markReadKey
    markRead(routeConversationId)
  }, [
    currentConversation?.unread_count,
    isDraftConversation,
    isMarkingRead,
    markRead,
    messagesLoading,
    routeConversationId,
  ])

  const setRuntimeStatus = useCallback(
    (id: string, status: ConversationRuntimeStatus) => {
      setConversationRuntimeStatus((current) => ({ ...current, [id]: status }))
    },
    [setConversationRuntimeStatus],
  )
  const handleLangGraphDraftConversationId = useCallback(
    (id: string) => {
      startedConversationIdRef.current = id
      setDraftTitleDetailSuppression({ routeKey, conversationId: id })
    },
    [routeKey],
  )
  const {
    conversationId: langGraphDraftConversationId,
    isBootstrapping: isLangGraphDraftBootstrapping,
    retainDraftConversation,
    commitDraftConversation,
  } = useLangGraphDraftConversation({
    agentId,
    isDraftConversation,
    runtimeMode,
    onConversationId: handleLangGraphDraftConversationId,
  })
  const activeConversationId = isDraftConversation
    ? langGraphDraftConversationId
    : routeConversationId
  const resolvedSideEffectConversationId = activeConversationId ?? routeConversationId
  const titleConversationId = routeConversationId
  const resolvedConversationTitle = useConversationTitle(
    agentId,
    titleConversationId,
    agent?.name,
    {
      detailEnabled:
        draftTitleDetailSuppressionConversationId !== titleConversationId &&
        suppressEmptyStateForConversationId !== titleConversationId,
    },
  )
  const currentTitle = isDraftConversation ? t('newConversation') : resolvedConversationTitle

  const streamFn = useCallback(
    async function* (content: string, signal: AbortSignal, options?: StreamChatOptions) {
      let runtimeConversationId = isDraftConversation ? null : routeConversationId
      if (runtimeConversationId) setRuntimeStatus(runtimeConversationId, 'running')
      try {
        const stream = !isDraftConversation
          ? streamChat(routeConversationId, content, signal, options)
          : streamStartConversation(agentId, content, signal, {
              ...options,
              onConversationId: (id) => {
                runtimeConversationId = id
                startedConversationIdRef.current = id
                setRuntimeStatus(id, 'running')
                options?.onConversationId?.(id)
              },
            })
        for await (const event of stream) {
          yield event
        }
      } finally {
        if (runtimeConversationId) setRuntimeStatus(runtimeConversationId, 'idle')
      }
    },
    [agentId, isDraftConversation, routeConversationId, setRuntimeStatus],
  )
  const promoteDraftRoute = useCallback(
    (createdConversationId: string) => {
      setRouteConversationOverride({
        routeKey,
        conversationId: createdConversationId,
      })
      replaceChatRouteWithoutRemount(`/agents/${agentId}/conversations/${createdConversationId}`)
    },
    [agentId, routeKey],
  )

  const syncPromotedDraftNavigator = useCallback(
    (createdConversationId: string) => {
      void queryClient
        .fetchQuery({
          ...conversationDetailQueryOptions(createdConversationId),
        })
        .then((conversation) => {
          // M5 — 通过 optimistic upsert 立即填充 navigator(list/agent pages/global pages)，
          // 如果这里再次调用 broad invalidate，刚刚 upsert 的
          // page/summary 会立刻被标记为 stale，引发 refetch storm，并使 optimistic
          // upsert 失效。navigator 的最终一致性由 ``onStreamEnd`` 负责，因此
          // 这里不再执行额外 invalidation。
          upsertConversationNavigatorCache(
            queryClient,
            conversation,
            agent
              ? {
                  id: agent.id,
                  name: agent.name,
                  image_url: agent.image_url ?? null,
                }
              : null,
          )
        })
        .catch(() => {
          // 由于 detail fetch 失败，无法 upsert，因此仅此时 invalidate navigator，
          // 让下一次 fetch 将新 conversation 加入列表。
          invalidateConversationNavigators(queryClient, agentId, createdConversationId)
        })
    },
    [agent, agentId, queryClient],
  )

  const onStreamEnd = useCallback(() => {
    // 从 draft 开始的 stream 会使用记录在 ref 中的真实 conversation id，连 detail 一并 invalidate
    const settledConversationId = isDraftConversation
      ? startedConversationIdRef.current
      : routeConversationId
    invalidateConversationNavigators(queryClient, agentId, settledConversationId)
    if (settledConversationId) {
      void queryClient.refetchQueries({
        queryKey: conversationKeys.messages(settledConversationId),
        type: 'active',
      })
      queryClient.invalidateQueries({
        queryKey: conversationKeys.debugTraces(settledConversationId),
      })
    }
    if (!isDraftConversation) {
      return
    }
    const createdConversationId = startedConversationIdRef.current
    if (createdConversationId) {
      setSuppressEmptyStateForConversationId(createdConversationId)
      if (runtimeMode !== 'langgraph_v3') {
        router.replace(`/agents/${agentId}/conversations/${createdConversationId}`)
      }
    }
  }, [agentId, isDraftConversation, queryClient, routeConversationId, router, runtimeMode])

  // P0-1c — current feedback per message id, derived from the messages query.
  // Looked up by ``feedback-adapter`` to decide between POST(upsert) vs DELETE.
  const ratingByMessage = useMemo(() => {
    const map = new Map<string, 'up' | 'down'>()
    for (const m of messages) {
      if (m.feedback?.rating) map.set(m.id, m.feedback.rating)
    }
    return map
  }, [messages])
  const getActiveRating = useCallback((mid: string) => ratingByMessage.get(mid), [ratingByMessage])

  const feedbackAdapter = useChatFeedbackAdapter(
    resolvedSideEffectConversationId,
    getActiveRating,
    () => {
      queryClient.invalidateQueries({
        queryKey: conversationKeys.messages(resolvedSideEffectConversationId),
      })
    },
  )
  const useLangGraphRuntime = runtimeMode === 'langgraph_v3' && activeConversationId !== null

  function handleNewConversation() {
    clearChatRouteReplacement()
    router.push(`/agents/${agentId}/conversations/new`)
  }
  const handleOpenTrace = useCallback(() => {
    router.push(`/agents/${agentId}/conversations/${resolvedSideEffectConversationId}/traces`)
  }, [agentId, resolvedSideEffectConversationId, router])
  const handleOpenSettings = useCallback(() => {
    router.push(`/agents/${agentId}/settings`)
  }, [agentId, router])
  const handleToggleArtifacts = useCallback(() => {
    setRightRail((current) =>
      toggleArtifactListRailState(current, resolvedSideEffectConversationId),
    )
  }, [resolvedSideEffectConversationId, setRightRail])
  const handleRuntimeStatusChange = useCallback(
    (status: ConversationRuntimeStatus) => {
      if (activeConversationId) setRuntimeStatus(activeConversationId, status)
    },
    [activeConversationId, setRuntimeStatus],
  )
  const handleBeforeNewMessage = useCallback(() => {
    if (!isDraftConversation) return
    const draftConversationId =
      retainDraftConversation() ?? langGraphDraftConversationId ?? startedConversationIdRef.current
    if (!draftConversationId) return
    startedConversationIdRef.current = draftConversationId
    setSuppressEmptyStateForConversationId(draftConversationId)
  }, [isDraftConversation, langGraphDraftConversationId, retainDraftConversation])
  const handleNewMessageAccepted = useCallback(() => {
    const acceptedConversationId =
      commitDraftConversation() ?? startedConversationIdRef.current ?? langGraphDraftConversationId
    if (!acceptedConversationId) return
    startedConversationIdRef.current = acceptedConversationId
    setSuppressEmptyStateForConversationId(acceptedConversationId)
    promoteDraftRoute(acceptedConversationId)
    syncPromotedDraftNavigator(acceptedConversationId)
  }, [
    commitDraftConversation,
    langGraphDraftConversationId,
    promoteDraftRoute,
    syncPromotedDraftNavigator,
  ])

  // 用于 chat tool pill icon — 该 Agent tool 的 toolName → registry icon_id。
  const toolIconIds = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const tool of agent?.tools ?? []) {
      if (tool.icon_id) map[tool.name] = tool.icon_id
    }
    return map
  }, [agent?.tools])

  // MCP tool name → server display name。作为 tool pill 的 plugin icon + server badge 依据。
  const mcpServerNames = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const mcpTool of agent?.mcp_tools ?? []) {
      map[mcpTool.name] = mcpTool.server_name ?? 'MCP'
    }
    return map
  }, [agent?.mcp_tools])

  const emptyContent = <ChatEmptyState agent={agent} fallback={t('emptyState')} />
  const shouldSuppressEmptyContent =
    useLangGraphRuntime &&
    ((activeConversationId !== null &&
      suppressEmptyStateForConversationId === activeConversationId) ||
      messages.length > 0)
  const renderedEmptyContent = shouldSuppressEmptyContent ? (
    <div aria-hidden="true" />
  ) : (
    emptyContent
  )

  return (
    <SideChatWorkspace
      key={activeConversationId ?? 'draft'}
      conversationId={useLangGraphRuntime ? activeConversationId : null}
      title={currentTitle ?? agent?.name ?? ''}
    >
      <div className="moldy-app-surface flex min-h-0 flex-1 gap-3 overflow-hidden p-3">
        {/* 主 chat card */}
        <section className="moldy-panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <ChatPageHeader
            agent={agent}
            agentId={agentId}
            title={currentTitle}
            onNewConversation={handleNewConversation}
            onOpenSettings={handleOpenSettings}
            onOpenTrace={handleOpenTrace}
            onToggleArtifacts={handleToggleArtifacts}
          />
          <PinnedConversationSummary conversationId={activeConversationId} />

          {/* Thread */}
          {(!isPromotedDraftRoute && !isDraftConversation && messagesLoading) ||
          isLangGraphDraftBootstrapping ? (
            <div className="flex-1 px-4 py-4">
              <div className="mx-auto max-w-3xl space-y-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex gap-3">
                    <Skeleton className="size-8 rounded-full" />
                    <Skeleton className="moldy-skeleton-message h-16 flex-1" />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <ToolIconProvider iconIds={toolIconIds} mcpServers={mcpServerNames}>
              <ChatRuntimeSection
                activeConversationId={activeConversationId}
                activeRun={envelope?.active_run ?? null}
                agentId={agentId}
                agentImageUrl={agent?.image_url}
                agentName={agent?.name}
                attachmentAdapter={moldyAttachmentAdapter}
                emptyContent={renderedEmptyContent}
                feedbackAdapter={feedbackAdapter}
                latestRun={envelope?.latest_run ?? null}
                messages={messages}
                modelName={
                  runtimeReadiness?.model
                    ? `${runtimeReadiness.model.provider} · ${
                        runtimeReadiness.model.display_name || runtimeReadiness.model.model_name
                      }`
                    : agent?.model
                      ? `${agent.model.provider} · ${
                          agent.model.display_name || agent.model.model_name
                        }`
                      : undefined
                }
                runtimeCredentialName={
                  runtimeReadiness?.credential?.name ?? agent?.llm_credential_name
                }
                runtimeReady={
                  typeof runtimeReadiness?.ready === 'boolean' ? runtimeReadiness.ready : undefined
                }
                showContextGauge
                contextWindow={agent?.model?.context_window ?? null}
                onBeforeNewMessage={handleBeforeNewMessage}
                onNewMessageAccepted={handleNewMessageAccepted}
                onRuntimeStatusChange={handleRuntimeStatusChange}
                onStreamEnd={onStreamEnd}
                streamFn={streamFn}
                totalCost={envelope?.total_estimated_cost}
                useLangGraphRuntime={useLangGraphRuntime}
                user={user}
                linkedSkills={agent?.skills}
                commandActions={{
                  createNewConversation: handleNewConversation,
                  openFilesRail: handleToggleArtifacts,
                  ...(activeConversationId ? { openExportChooser: () => setExportOpen(true) } : {}),
                }}
              />
            </ToolIconProvider>
          )}
        </section>

        {/* 右侧 RightRail — sub-agent / tool-result / outline panel slot */}
        <ConversationDetailRail conversationId={activeConversationId} />
        <SideChatPanel agent={agent} user={user} />
        {activeConversationId ? (
          <ExportDialog
            open={exportOpen}
            onOpenChange={setExportOpen}
            conversationId={activeConversationId}
            title={currentTitle}
          />
        ) : null}
      </div>
    </SideChatWorkspace>
  )
}
