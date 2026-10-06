'use client'

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query'
import { conversationsApi } from '@/lib/api/conversations'
import { conversationPagesContainActiveRun } from '@/lib/chat-runs/status'
import { agentQueryKeys } from '@/lib/query-keys/agents'
import type {
  Conversation,
  ConversationAgentBrief,
  ConversationListEnvelope,
  ConversationPageParams,
  ConversationUpdateRequest,
  ConversationWithAgent,
  ConversationWithAgentListEnvelope,
} from '@/lib/types'
import { triggerKeys } from './use-triggers'

interface ConversationPagesOptions {
  readonly enabled?: boolean
}

function normalizeConversationPageParams(
  params: Omit<ConversationPageParams, 'cursor'> = {},
): Omit<ConversationPageParams, 'cursor'> {
  return {
    limit: params.limit ?? 30,
    q: params.q?.trim() || undefined,
    sort: params.sort ?? 'updated',
  }
}

export const conversationKeys = {
  list: (agentId: string) => ['agents', agentId, 'conversations'] as const,
  agentPagesRoot: (agentId: string) => ['agents', agentId, 'conversations', 'page'] as const,
  pages: (agentId: string, params: Omit<ConversationPageParams, 'cursor'>) =>
    ['agents', agentId, 'conversations', 'page', params] as const,
  globalPagesRoot: ['conversations', 'page'] as const,
  globalPages: (params: Omit<ConversationPageParams, 'cursor'>) =>
    ['conversations', 'page', params] as const,
  detail: (conversationId: string) => ['conversations', conversationId, 'detail'] as const,
  messages: (conversationId: string) => ['conversations', conversationId, 'messages'] as const,
  files: (conversationId: string | null | undefined) =>
    ['conversations', conversationId ?? 'none', 'files'] as const,
  debugTraces: (conversationId: string) =>
    ['conversations', conversationId, 'debug-traces'] as const,
  debugTraceDetail: (conversationId: string, traceId: string) =>
    ['conversations', conversationId, 'debug-traces', traceId] as const,
}

/** 使对话 navigator（sidebar/quick switcher/对话列表）缓存失效。
 *  由于 prefix 匹配特性，``list(agentId)`` 会覆盖 page query，
 *  而像 ``['agents']`` 这样的广域 invalidate 会触发无关 query refetch，因此禁止。 */
export function invalidateConversationNavigators(
  queryClient: QueryClient,
  agentId?: string | null,
  conversationId?: string | null,
): void {
  if (agentId) {
    queryClient.invalidateQueries({ queryKey: conversationKeys.list(agentId) })
  }
  if (conversationId) {
    queryClient.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })
  }
  queryClient.invalidateQueries({ queryKey: conversationKeys.globalPagesRoot })
  queryClient.invalidateQueries({ queryKey: agentQueryKeys.summary })
}

function mergeConversationRow(current: Conversation | undefined, next: Conversation): Conversation {
  return current ? { ...current, ...next } : next
}

// M1 — 纯 cache upsert helper 是单元测试对象，因此 export。
export function upsertConversationList(
  rows: readonly Conversation[] | undefined,
  conversation: Conversation,
): Conversation[] | undefined {
  if (!rows) return rows
  const existing = rows.find((row) => row.id === conversation.id)
  const merged = mergeConversationRow(existing, conversation)
  return [merged, ...rows.filter((row) => row.id !== conversation.id)]
}

export function upsertConversationPages(
  data: InfiniteData<ConversationListEnvelope> | undefined,
  conversation: Conversation,
): InfiniteData<ConversationListEnvelope> | undefined {
  if (!data) return data
  return {
    ...data,
    pages: data.pages.map((page, index) => {
      const existing = page.items.find((row) => row.id === conversation.id)
      const rowsWithoutConversation = page.items.filter((row) => row.id !== conversation.id)
      if (index !== 0) return { ...page, items: rowsWithoutConversation }
      return {
        ...page,
        items: [mergeConversationRow(existing, conversation), ...rowsWithoutConversation],
      }
    }),
  }
}

export function upsertGlobalConversationPages(
  data: InfiniteData<ConversationWithAgentListEnvelope> | undefined,
  conversation: ConversationWithAgent,
): InfiniteData<ConversationWithAgentListEnvelope> | undefined {
  if (!data) return data
  return {
    ...data,
    pages: data.pages.map((page, index) => {
      const existing = page.items.find((row) => row.id === conversation.id)
      const rowsWithoutConversation = page.items.filter((row) => row.id !== conversation.id)
      if (index !== 0) return { ...page, items: rowsWithoutConversation }
      return {
        ...page,
        // `...conversation` 会覆盖所有字段（包括 agent），所以 existing 使用空
        // 对象 fallback 就足够。
        items: [{ ...(existing ?? {}), ...conversation }, ...rowsWithoutConversation],
      }
    }),
  }
}

export function upsertConversationNavigatorCache(
  queryClient: QueryClient,
  conversation: Conversation,
  agent?: ConversationAgentBrief | null,
): void {
  queryClient.setQueryData<Conversation[]>(
    conversationKeys.list(conversation.agent_id),
    (current) => upsertConversationList(current, conversation),
  )
  queryClient.setQueriesData<InfiniteData<ConversationListEnvelope>>(
    { queryKey: conversationKeys.agentPagesRoot(conversation.agent_id) },
    (current) => upsertConversationPages(current, conversation),
  )
  if (!agent) return
  queryClient.setQueriesData<InfiniteData<ConversationWithAgentListEnvelope>>(
    { queryKey: conversationKeys.globalPagesRoot },
    (current) => upsertGlobalConversationPages(current, { ...conversation, agent }),
  )
}

export function useConversations(agentId: string) {
  return useQuery({
    queryKey: conversationKeys.list(agentId),
    queryFn: () => conversationsApi.list(agentId),
    enabled: !!agentId,
  })
}

export function useConversationPages(
  agentId: string,
  params: Omit<ConversationPageParams, 'cursor'> = {},
  options: ConversationPagesOptions = {},
) {
  const pageParams = normalizeConversationPageParams(params)
  return useInfiniteQuery({
    queryKey: conversationKeys.pages(agentId, pageParams),
    queryFn: ({ pageParam }) =>
      conversationsApi.page(agentId, {
        ...pageParams,
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: (options.enabled ?? true) && !!agentId,
    refetchInterval: (query) =>
      conversationPagesContainActiveRun(query.state.data?.pages) ? 1000 : false,
  })
}

export function useGlobalConversationPages(
  params: Omit<ConversationPageParams, 'cursor'> = {},
  options: ConversationPagesOptions = {},
) {
  const pageParams = normalizeConversationPageParams(params)
  return useInfiniteQuery({
    queryKey: conversationKeys.globalPages(pageParams),
    queryFn: ({ pageParam }) =>
      conversationsApi.globalPage({
        ...pageParams,
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: options.enabled ?? true,
    // 只要 background run 可见，navigator 也通过每 1 秒 polling 跟踪状态
    refetchInterval: (query) =>
      conversationPagesContainActiveRun(query.state.data?.pages) ? 1000 : false,
  })
}

/** Detail query contract shared by consumers that need to prefill navigator cache. */
export function conversationDetailQueryOptions(conversationId: string) {
  return {
    queryKey: conversationKeys.detail(conversationId),
    queryFn: () => conversationsApi.get(conversationId),
  }
}

export function useConversationDetail(conversationId: string, enabled = true) {
  const query = conversationDetailQueryOptions(conversationId)
  return useQuery({
    ...query,
    enabled: enabled && !!conversationId && conversationId !== 'new',
  })
}

export function useMessages(conversationId: string, enabled = true) {
  return useQuery({
    queryKey: conversationKeys.messages(conversationId),
    // fetch 整个 envelope + 用 select 仅暴露 ``Message[]`` — 在保持 caller 兼容的
    // 同时与 ``useMessagesEnvelope`` 共享 cache。
    queryFn: () => conversationsApi.messagesEnvelope(conversationId),
    select: (env) => env.messages,
    enabled: enabled && !!conversationId,
    refetchOnWindowFocus: false,
  })
}

/** W7-4 — 为了显示 Composer token bar 的 cost 而访问整个 envelope 的 hook。
 *  与 ``useMessages`` 共享相同的 queryKey/queryFn，不产生额外 fetch 成本。 */
export function useMessagesEnvelope(conversationId: string, enabled = true) {
  return useQuery({
    queryKey: conversationKeys.messages(conversationId),
    queryFn: () => conversationsApi.messagesEnvelope(conversationId),
    enabled: enabled && !!conversationId,
    refetchOnWindowFocus: false,
  })
}

export function useConversationDebugTraces(conversationId: string, enabled = true) {
  return useQuery({
    queryKey: conversationKeys.debugTraces(conversationId),
    queryFn: () => conversationsApi.debugTraces(conversationId),
    enabled: enabled && !!conversationId,
    refetchOnWindowFocus: false,
  })
}

export function useConversationDebugTraceDetail(
  conversationId: string,
  traceId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: conversationKeys.debugTraceDetail(conversationId, traceId ?? 'none'),
    queryFn: () => conversationsApi.debugTraceDetail(conversationId, traceId ?? ''),
    enabled: enabled && !!conversationId && !!traceId,
    refetchOnWindowFocus: false,
  })
}

export function useCreateConversation(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => conversationsApi.create(agentId, title),
    onSuccess: () => invalidateConversationNavigators(qc, agentId),
  })
}

export function useUpdateConversation(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ConversationUpdateRequest }) =>
      conversationsApi.update(id, data),
    onSuccess: (_updated, variables) => invalidateConversationNavigators(qc, agentId, variables.id),
  })
}

export function useDeleteConversation(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => conversationsApi.delete(id),
    onSuccess: () => invalidateConversationNavigators(qc, agentId),
  })
}

export function useMarkConversationRead(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (conversationId: string) => conversationsApi.markRead(conversationId),
    onSuccess: (conversation) => {
      qc.setQueryData<Conversation[]>(conversationKeys.list(agentId), (current) =>
        current?.map((item) => (item.id === conversation.id ? { ...item, ...conversation } : item)),
      )
      qc.invalidateQueries({ queryKey: conversationKeys.list(agentId), refetchType: 'inactive' })
      invalidateConversationNavigators(qc, agentId, conversation.id)
      qc.invalidateQueries({ queryKey: triggerKeys.all })
      qc.invalidateQueries({ queryKey: triggerKeys.summary })
    },
  })
}

/**
 * 生成 1 条 Follow-up ghost 建议（run 结束时调用 1 次）。无法生成时
 * suggestion=null — 隐藏 ghost 即可。
 */
export function useFollowupSuggestionMutation() {
  return useMutation({
    mutationFn: (conversationId: string) => conversationsApi.followupSuggestion(conversationId),
  })
}
