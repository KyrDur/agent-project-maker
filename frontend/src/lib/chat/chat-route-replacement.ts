export const CHAT_ROUTE_REPLACED_EVENT = 'moldy:chat-route-replaced'
export const CHAT_ROUTE_CLEARED_EVENT = 'moldy:chat-route-cleared'

export interface ChatRouteReplacedDetail {
  readonly pathname: string
}

export function isChatRouteReplacedEvent(
  event: Event,
): event is CustomEvent<ChatRouteReplacedDetail> {
  if (event.type !== CHAT_ROUTE_REPLACED_EVENT) return false
  const detail = (event as CustomEvent<unknown>).detail
  return (
    typeof detail === 'object' &&
    detail !== null &&
    'pathname' in detail &&
    typeof detail.pathname === 'string'
  )
}

/**
 * draft → real 对话升级时只替换 URL，避免组件 remount
 * （langgraph-v3 专用路径）。Next.js 16 官方指南（`docs/.../linking-and-navigating`
 * "Native History API"）明确说明，直接调用 `window.history.replaceState` 会与 Next
 * Router 集成，并与 `usePathname`/`useSearchParams` 同步。
 *
 * 约束/历史 bug：
 * - 必须调用 `window.history.replaceState`。如果直接调用 `History.prototype`，
 *   会绕过 Next monkey-patch 的 wrapper，导致 App Router 缓存/pathname
 *   不更新（这样"draft 发送 → 点击其他对话 → 后退"会回到错误的
 *   对话或 `/new`）。
 * - state 参数按新 URL 传 `null`。旧代码直接复用了 OLD URL 的
 *   `window.history.state`，导致后退时恢复 stale state。
 *   与 Next 指南示例一致，使用 `null`。
 */
export function replaceChatRouteWithoutRemount(path: string): void {
  if (typeof window === 'undefined') return
  window.history.replaceState(null, '', path)
  const pathname = new URL(path, window.location.href).pathname
  window.dispatchEvent(
    new CustomEvent<ChatRouteReplacedDetail>(CHAT_ROUTE_REPLACED_EVENT, {
      detail: { pathname },
    }),
  )
}

export function clearChatRouteReplacement(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(CHAT_ROUTE_CLEARED_EVENT))
}

/**
 * 从 `/agents/<agentId>/conversations/<conversationId>` 路径中
 * 提取 conversationId。agentId 不同或格式不匹配时返回 null。conversationId
 * 用 `decodeURIComponent` 解码（支持 percent-encoded id）。如果解码失败，
 * （malformed % sequence）则原样返回 raw 段。
 */
export function conversationIdFromChatPath(pathname: string, agentId: string): string | null {
  const match = /^\/agents\/([^/]+)\/conversations\/([^/]+)$/.exec(pathname)
  if (!match || match[1] !== agentId) return null
  try {
    return decodeURIComponent(match[2])
  } catch {
    return match[2]
  }
}
