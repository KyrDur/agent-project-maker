import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'
import type { AgentSort, ConversationSort, NavigatorMode } from '@/lib/types'

/** 仅在同一 tab 中 SSE stream 正在进行时使用的本地 overlay 状态。
 *  服务器 truth 是 ``Conversation.active_run``（1 秒 polling）— 此值用于 polling
 *  跟上之前的即时响应；其他 tab/background run 只通过 active_run 显示。 */
export type ConversationRuntimeStatus = 'idle' | 'running'

export const navigatorModeAtom = atomWithStorage<NavigatorMode>(
  'moldy.chatNavigator.mode',
  'agent_grouped',
)
export const agentSortAtom = atomWithStorage<AgentSort>('moldy.chatNavigator.agentSort', 'recent')
export const sessionSortAtom = atomWithStorage<ConversationSort>(
  'moldy.chatNavigator.sessionSort',
  'updated',
)
export const singleExpandedAgentAtom = atomWithStorage(
  'moldy.chatNavigator.singleExpandedAgent',
  false,
)
export const expandedAgentIdsAtom = atomWithStorage<string[]>(
  'moldy.chatNavigator.expandedAgentIds',
  [],
)
/** active agent 默认展开 — 只有用户明确折叠时才记录在这里。 */
export const collapsedAgentIdsAtom = atomWithStorage<string[]>(
  'moldy.chatNavigator.collapsedAgentIds',
  [],
)
export const expandedListScopesAtom = atomWithStorage<string[]>(
  'moldy.chatNavigator.expandedListScopes',
  [],
)
export const shortcutPreviewActiveAtom = atom(false)
export const conversationRuntimeStatusAtom = atom<Record<string, ConversationRuntimeStatus>>({})
