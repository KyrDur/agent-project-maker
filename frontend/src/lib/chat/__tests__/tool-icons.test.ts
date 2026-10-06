import { describe, expect, it } from 'vitest'
import { ClockIcon, SearchIcon, WrenchIcon } from 'lucide-react'
import { builtinToolIcon, toolIcon } from '../tool-icons'
import { toolCallChildLabel } from '../tool-group-meta'

describe('toolIcon', () => {
  it('已知内置工具使用语义图标', () => {
    expect(toolIcon('current_datetime')).toBe(ClockIcon)
    expect(toolIcon('web_search')).toBe(SearchIcon)
  })

  it('前缀映射（google_）', () => {
    expect(toolIcon('google_search_web')).toBe(SearchIcon)
    expect(toolIcon('google_news_search')).toBe(SearchIcon)
  })

  it('未知工具回退为扳手图标', () => {
    expect(toolIcon('some_random_mcp_tool')).toBe(WrenchIcon)
  })
})

describe('builtinToolIcon', () => {
  it('内置工具返回图标，未知工具返回 null（icon_id/扳手回退交由调用方）', () => {
    expect(builtinToolIcon('current_datetime')).toBe(ClockIcon)
    expect(builtinToolIcon('some_custom_tool')).toBeNull()
  })
})

describe('toolCallChildLabel', () => {
  it('优先使用代表性参数（query/file_path）', () => {
    expect(toolCallChildLabel({ query: 'react 19' }, undefined)).toBe('react 19')
    expect(toolCallChildLabel({ file_path: 'src/app/page.tsx' }, undefined)).toBe(
      'src/app/page.tsx',
    )
  })

  it('没有代表性参数时使用第一个字符串参数', () => {
    expect(toolCallChildLabel({ foo: 'bar baz' }, undefined)).toBe('bar baz')
  })

  it('没有参数时使用结果预览（第一行）', () => {
    expect(toolCallChildLabel({}, '2026-06-27 14:03\n附加内容')).toBe('2026-06-27 14:03')
  })

  it('JSON 结果不显示 raw，而只显示代表性标量值', () => {
    expect(
      toolCallChildLabel({}, '{"now_iso": "2026-06-27T06:41:51+08:00", "tz": "Asia/Shanghai"}'),
    ).toBe('2026-06-27T06:41:51+08:00')
    expect(toolCallChildLabel({}, '{"results":[{"title":"hello","url":"x"}]}')).toBe('hello')
  })

  it('什么都没有时返回 null（调用方回退为工具名）', () => {
    expect(toolCallChildLabel({}, undefined)).toBeNull()
    expect(toolCallChildLabel({ n: 5 }, { obj: true })).toBeNull()
  })

  it('长值省略显示', () => {
    const long = 'a'.repeat(80)
    const out = toolCallChildLabel({ query: long }, undefined) ?? ''
    expect(out.length).toBeLessThanOrEqual(48)
    expect(out.endsWith('…')).toBe(true)
  })
})
