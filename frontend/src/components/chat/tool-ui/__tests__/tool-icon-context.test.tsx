import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { ClockIcon, PlugIcon, SearchIcon, WrenchIcon } from 'lucide-react'
import { getDomainIcon } from '@/components/shared/icon'
import { ToolIconProvider, useMcpToolServer, useToolIcon } from '../tool-icon-context'

function wrapper(iconIds: Record<string, string>, mcpServers: Record<string, string> = {}) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <ToolIconProvider iconIds={iconIds} mcpServers={mcpServers}>
        {children}
      </ToolIconProvider>
    )
  }
}

describe('useToolIcon', () => {
  it('内置 map 是第 1 优先（即使有 icon_id 也优先内置）', () => {
    const { result } = renderHook(() => useToolIcon('current_datetime'), {
      wrapper: wrapper({ current_datetime: 'calendar' }),
    })
    expect(result.current).toBe(ClockIcon)
  })

  it('内置中没有时，将工具 icon_id 交给 getDomainIcon 解析', () => {
    const { result } = renderHook(() => useToolIcon('custom_registry_tool'), {
      wrapper: wrapper({ custom_registry_tool: 'calendar' }),
    })
    expect(result.current).toBe(getDomainIcon('calendar'))
  })

  it('内置和 icon_id 都没有时 fallback 到扳手图标', () => {
    const { result } = renderHook(() => useToolIcon('unknown_mcp_tool'), {
      wrapper: wrapper({}),
    })
    expect(result.current).toBe(WrenchIcon)
  })

  it('MCP 工具解析为插件图标', () => {
    const { result } = renderHook(() => useToolIcon('notion_search'), {
      wrapper: wrapper({}, { notion_search: 'Notion' }),
    })
    expect(result.current).toBe(PlugIcon)
  })

  it('内置固定 map 的优先级高于 MCP 映射', () => {
    const { result } = renderHook(() => useToolIcon('web_search'), {
      wrapper: wrapper({}, { web_search: 'ShouldNotWin' }),
    })
    expect(result.current).toBe(SearchIcon)
  })
})

describe('useMcpToolServer', () => {
  it('MCP 工具返回服务器显示名，否则为 null', () => {
    const { result } = renderHook(
      () => ({
        mcp: useMcpToolServer('notion_search'),
        plain: useMcpToolServer('unknown_tool'),
      }),
      { wrapper: wrapper({}, { notion_search: 'Notion' }) },
    )
    expect(result.current.mcp).toBe('Notion')
    expect(result.current.plain).toBeNull()
  })
})
