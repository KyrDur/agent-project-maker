'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useAtom } from 'jotai'
import { useTranslations } from 'next-intl'
import { useConversationRowActions } from '@/components/chat/use-conversation-row-actions'
import { SidebarGroup, SidebarGroupContent, useSidebar } from '@/components/ui/sidebar'
import { SearchInput } from '@/components/shared/search-input'
import { useAgentSummaries } from '@/lib/hooks/use-agents'
import { useGlobalConversationPages } from '@/lib/hooks/use-conversations'
import {
  CHAT_ROUTE_CLEARED_EVENT,
  CHAT_ROUTE_REPLACED_EVENT,
  isChatRouteReplacedEvent,
} from '@/lib/chat/chat-route-replacement'
import {
  agentSortAtom,
  collapsedAgentIdsAtom,
  expandedAgentIdsAtom,
  expandedListScopesAtom,
  navigatorModeAtom,
  sessionSortAtom,
  singleExpandedAgentAtom,
} from '@/lib/stores/chat-navigator-store'
import { ChatNavigatorHeader } from './chat-navigator-header'
import {
  AgentGroupedSection,
  ChatNavigatorLoadingRows,
  RecentAgentsSection,
  RecentSessionsSection,
} from './chat-navigator-sections'
import {
  RECENT_SESSION_CAP,
  agentSortTime,
  matchesAgent,
  parseChatRoute,
} from './chat-navigator-utils'
import { ChatQuickSwitcher } from './chat-quick-switcher'
import { useChatNavigatorShortcuts } from './use-chat-navigator-shortcuts'

export function ChatNavigator() {
  const pathname = usePathname()
  const [replacedPathname, setReplacedPathname] = useState<string | null>(null)
  const shouldUseReplacedPathname =
    replacedPathname !== null &&
    (typeof window === 'undefined' || pathname !== window.location.pathname)
  const visiblePathname = shouldUseReplacedPathname ? replacedPathname : pathname
  const t = useTranslations('sidebar.agents')
  const { setOpen, state } = useSidebar()
  const route = useMemo(() => parseChatRoute(visiblePathname), [visiblePathname])
  const { data: agents, isLoading } = useAgentSummaries()
  const [mode, setMode] = useAtom(navigatorModeAtom)
  const [agentSort, setAgentSort] = useAtom(agentSortAtom)
  const [sessionSort, setSessionSort] = useAtom(sessionSortAtom)
  const [singleExpandedAgent, setSingleExpandedAgent] = useAtom(singleExpandedAgentAtom)
  const [expandedAgentIds, setExpandedAgentIds] = useAtom(expandedAgentIdsAtom)
  const [collapsedAgentIds, setCollapsedAgentIds] = useAtom(collapsedAgentIdsAtom)
  const [expandedListScopes, setExpandedListScopes] = useAtom(expandedListScopesAtom)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [quickSwitcherOpen, setQuickSwitcherOpen] = useState(false)
  const search = searchQuery.trim()
  const searchVisible = searchOpen || search.length > 0
  const shouldFetchGlobalConversations = mode === 'recent_sessions' || search.length > 0
  const sortedAgents = useMemo(
    () =>
      (agents ?? [])
        .slice()
        .sort((left, right) => agentSortTime(right, agentSort) - agentSortTime(left, agentSort)),
    [agents, agentSort],
  )
  const filteredAgents = useMemo(
    () => sortedAgents.filter((agent) => (search ? matchesAgent(agent, search) : true)),
    [search, sortedAgents],
  )
  const actions = useConversationRowActions({
    activeConversationId: route.conversationId,
    translationNamespace: 'sidebar.agents.conversationActions',
  })
  const {
    data: globalPages,
    isLoading: globalLoading,
    hasNextPage: hasNextGlobalPage,
    fetchNextPage: fetchNextGlobalPage,
    isFetchingNextPage: isFetchingNextGlobalPage,
  } = useGlobalConversationPages(
    {
      limit: 30,
      q: search || undefined,
      sort: sessionSort,
    },
    {
      enabled: shouldFetchGlobalConversations,
    },
  )
  const globalConversations = globalPages?.pages.flatMap((page) => page.items) ?? []
  const recentSessionsExpanded = expandedListScopes.includes('recent_sessions')
  const recentAgentsExpanded = expandedListScopes.includes('recent_agents')
  const isSidebarCollapsed = state === 'collapsed'

  const closeTransientUi = useCallback(() => {
    setQuickSwitcherOpen(false)
    setSearchQuery('')
    setSearchOpen(false)
  }, [])

  const openQuickSwitcher = useCallback(() => setQuickSwitcherOpen(true), [])
  const expandSidebarFromIcon = useCallback(() => {
    if (isSidebarCollapsed) {
      setOpen(true)
    }
  }, [isSidebarCollapsed, setOpen])

  useChatNavigatorShortcuts({
    onOpenQuickSwitcher: openQuickSwitcher,
    onEscape: closeTransientUi,
  })

  useEffect(() => {
    const handleRouteReplacement = (event: Event) => {
      if (isChatRouteReplacedEvent(event)) setReplacedPathname(event.detail.pathname)
    }
    const clearRouteReplacement = () => setReplacedPathname(null)

    window.addEventListener(CHAT_ROUTE_REPLACED_EVENT, handleRouteReplacement)
    window.addEventListener(CHAT_ROUTE_CLEARED_EVENT, clearRouteReplacement)
    window.addEventListener('popstate', clearRouteReplacement)
    return () => {
      window.removeEventListener(CHAT_ROUTE_REPLACED_EVENT, handleRouteReplacement)
      window.removeEventListener(CHAT_ROUTE_CLEARED_EVENT, clearRouteReplacement)
      window.removeEventListener('popstate', clearRouteReplacement)
    }
  }, [])

  // M7 — 当 `usePathname()` 追上 replaced pathname 后，清理 stale override。
  // 如果在 effect 中同步 setState，会触发 `react-hooks/set-state-in-effect`，
  // 并（参见 AGENTS.md）导致 cascading render，因此改为在路由器追上时
  // 直接在渲染中清空 state。setState during render 会在同一渲染内
  // 会立即重新执行并在无 cascade 的情况下稳定，是 React 推荐的模式
  // (https://react.dev/reference/react/useState#storing-information-from-previous-renders).
  if (replacedPathname !== null && pathname === replacedPathname) {
    setReplacedPathname(null)
  }

  const activeAgentId = route.agentId

  const isAgentExpanded = useCallback(
    (agentId: string) =>
      agentId === activeAgentId
        ? !collapsedAgentIds.includes(agentId)
        : expandedAgentIds.includes(agentId),
    [activeAgentId, collapsedAgentIds, expandedAgentIds],
  )

  const toggleAgentExpanded = useCallback(
    (agentId: string) => {
      if (isAgentExpanded(agentId)) {
        // 活跃智能体的默认展开只能由 collapse override 覆盖
        if (agentId === activeAgentId) {
          setCollapsedAgentIds((current) =>
            current.includes(agentId) ? current : [...current, agentId],
          )
        }
        setExpandedAgentIds((current) => current.filter((id) => id !== agentId))
        return
      }
      setCollapsedAgentIds((current) => current.filter((id) => id !== agentId))
      setExpandedAgentIds((current) => {
        if (singleExpandedAgent) return [agentId]
        return current.includes(agentId) ? current : [...current, agentId]
      })
    },
    [
      activeAgentId,
      isAgentExpanded,
      setCollapsedAgentIds,
      setExpandedAgentIds,
      singleExpandedAgent,
    ],
  )

  function toggleListScope(scope: string) {
    setExpandedListScopes((current) =>
      current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope],
    )
  }

  function handleSearchChange(value: string) {
    setSearchQuery(value)
  }

  async function handleRecentSessionsMore() {
    if (!recentSessionsExpanded) {
      toggleListScope('recent_sessions')
      return
    }
    if (hasNextGlobalPage) {
      await fetchNextGlobalPage()
      return
    }
    toggleListScope('recent_sessions')
  }

  const searchResultSessions =
    mode === 'agent_grouped' && search ? globalConversations.slice(0, RECENT_SESSION_CAP) : []

  return (
    <SidebarGroup>
      <ChatNavigatorHeader
        activeAgentId={route.agentId}
        sortedAgents={sortedAgents}
        mode={mode}
        agentSort={agentSort}
        sessionSort={sessionSort}
        singleExpandedAgent={singleExpandedAgent}
        onOpenSearch={() => setSearchOpen(true)}
        onModeChange={setMode}
        onAgentSortChange={setAgentSort}
        onSessionSortChange={setSessionSort}
        onSingleExpandedAgentChange={setSingleExpandedAgent}
      />
      <SidebarGroupContent className="space-y-2">
        {searchVisible ? (
          <SearchInput
            value={searchQuery}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchPlaceholder')}
            className="h-8"
            autoFocus
          />
        ) : null}
        {isLoading ? (
          <ChatNavigatorLoadingRows />
        ) : mode === 'recent_agents' ? (
          <RecentAgentsSection
            agents={filteredAgents}
            expanded={recentAgentsExpanded}
            isSidebarCollapsed={isSidebarCollapsed}
            onExpandSidebar={expandSidebarFromIcon}
            onToggleExpanded={() => toggleListScope('recent_agents')}
          />
        ) : mode === 'recent_sessions' ? (
          <RecentSessionsSection
            conversations={globalConversations}
            activeConversationId={route.conversationId}
            actions={actions}
            expanded={recentSessionsExpanded}
            hasNextPage={hasNextGlobalPage}
            isLoading={globalLoading}
            isFetchingNextPage={isFetchingNextGlobalPage}
            search={search}
            isSidebarCollapsed={isSidebarCollapsed}
            onExpandSidebar={expandSidebarFromIcon}
            onMore={handleRecentSessionsMore}
          />
        ) : (
          <AgentGroupedSection
            agents={filteredAgents}
            activeAgentId={route.agentId}
            activeConversationId={route.conversationId}
            searchQuery={searchQuery}
            sessionSort={sessionSort}
            isAgentExpanded={isAgentExpanded}
            expandedListScopes={expandedListScopes}
            searchResultSessions={searchResultSessions}
            actions={actions}
            isSidebarCollapsed={isSidebarCollapsed}
            onExpandSidebar={expandSidebarFromIcon}
            onToggleAgentExpanded={toggleAgentExpanded}
            onToggleListExpanded={toggleListScope}
          />
        )}
      </SidebarGroupContent>
      {actions.dialogs}
      <ChatQuickSwitcher
        open={quickSwitcherOpen}
        onOpenChange={setQuickSwitcherOpen}
        agents={sortedAgents}
      />
    </SidebarGroup>
  )
}
