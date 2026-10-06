'use client'

import { createContext, useContext, type ReactNode } from 'react'
import { PlugIcon, WrenchIcon, type LucideIcon } from 'lucide-react'
import { builtinToolIcon } from '@/lib/chat/tool-icons'
import { getDomainIcon } from '@/components/shared/icon'

// ──────────────────────────────────────────────
// ToolIconContext — toolName → 工具 registry icon_id / MCP 服务器名。
//
// 聊天根（conversations 页面）注入由 agent.tools/agent.mcp_tools 构建的 map。
// 工具 pill 通过 useToolIcon 决定图标：内置固定映射（运行时
// 注入工具）→ agent.tools 的 icon_id（用户 registry 工具）→ MCP 工具使用插件
// 图标 → 扳手回退。useMcpToolServer 用于 pill 元信息的服务器徽标。
// 即使在没有 map 的界面（空上下文）上，也能通过内置映射 + 扳手 graceful 工作。
// ──────────────────────────────────────────────

const ToolIconIdContext = createContext<Readonly<Record<string, string>>>({})
const McpToolServerContext = createContext<Readonly<Record<string, string>>>({})

export function ToolIconProvider({
  iconIds,
  mcpServers = {},
  children,
}: {
  iconIds: Readonly<Record<string, string>>
  mcpServers?: Readonly<Record<string, string>>
  children: ReactNode
}) {
  return (
    <ToolIconIdContext.Provider value={iconIds}>
      <McpToolServerContext.Provider value={mcpServers}>{children}</McpToolServerContext.Provider>
    </ToolIconIdContext.Provider>
  )
}

/** toolName → leading 图标。内置映射 → 工具 icon_id → MCP 插件 → 扳手回退。 */
export function useToolIcon(toolName: string): LucideIcon {
  const iconIds = useContext(ToolIconIdContext)
  const mcpServers = useContext(McpToolServerContext)
  const builtin = builtinToolIcon(toolName)
  if (builtin) return builtin
  const iconId = iconIds[toolName]
  if (iconId) return getDomainIcon(iconId)
  if (toolName in mcpServers) return PlugIcon
  return WrenchIcon
}

/** 若 toolName 是当前智能体的 MCP 工具，则返回其服务器显示名，否则为 null。 */
export function useMcpToolServer(toolName: string): string | null {
  const mcpServers = useContext(McpToolServerContext)
  return mcpServers[toolName] ?? null
}
