import type { AgentSort, AgentSummary } from '@/lib/types'

export const RECENT_AGENT_CAP = 8
export const RECENT_SESSION_CAP = 10

export interface ChatRouteContext {
  agentId: string | null
  conversationId: string | null
}

export function parseChatRoute(pathname: string): ChatRouteContext {
  const match = /^\/agents\/([^/]+)(?:\/conversations\/([^/]+))?/.exec(pathname)
  return {
    agentId: match?.[1] ?? null,
    conversationId: match?.[2] ?? null,
  }
}

export function agentSortTime(agent: AgentSummary, sort: AgentSort): number {
  const value = sort === 'recent' ? (agent.last_used_at ?? agent.created_at) : agent.created_at
  const time = new Date(value).getTime()
  // 混入无效日期字符串时，NaN 比较会让整个排序变得不稳定
  return Number.isNaN(time) ? 0 : time
}

export function matchesAgent(agent: AgentSummary, query: string): boolean {
  const normalized = query.toLowerCase()
  return (
    agent.name.toLowerCase().includes(normalized) ||
    (agent.description ?? '').toLowerCase().includes(normalized)
  )
}
