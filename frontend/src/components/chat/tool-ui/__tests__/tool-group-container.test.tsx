import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../../tests/test-utils'

type ToolPart = { readonly result?: unknown }
type AuiState = { readonly message?: { readonly parts?: readonly ToolPart[] } }

const mocks = vi.hoisted(() => ({
  state: { message: { parts: [] as readonly ToolPart[] } } as {
    message: { parts: readonly ToolPart[] }
  },
}))

// ToolGroupContainer 使用的唯一 aui API 是 useAuiState。搜索组的来源汇总会
// 读取 `s.message.parts[i].result`，因此 mock 成可直接注入 parts。
vi.mock('@assistant-ui/react', () => ({
  useAuiState: <T,>(selector: (state: AuiState) => T): T => selector(mocks.state),
}))

// 必须在注册 mock 后再 import，组件才能拿到 mock 后的 useAuiState。
const { ToolGroupContainer } = await import('../tool-group-container')

/** tavily 形状的结果 —— results:[{title,url}]。 */
function tavilyResult(urls: readonly string[]): unknown {
  return { results: urls.map((url, i) => ({ title: `r${i}`, url })) }
}

function setParts(parts: readonly ToolPart[]) {
  mocks.state.message.parts = parts
}

describe('ToolGroupContainer', () => {
  beforeEach(() => {
    setParts([])
  })

  it('已知工具名用 i18n 标签显示，并同时显示数量标签', () => {
    render(
      <ToolGroupContainer toolName="tavily_search" count={10} running={false} indices={[]}>
        <div data-testid="child">leaf</div>
      </ToolGroupContainer>,
    )
    expect(screen.getByText('网页搜索')).toBeInTheDocument()
    expect(screen.getByText('10次')).toBeInTheDocument()
  })

  it('没有标签映射的工具直接用 toolName 本身作为标签', () => {
    render(
      <ToolGroupContainer toolName="some_custom_tool" count={3} running={false} indices={[]}>
        <div>leaf</div>
      </ToolGroupContainer>,
    )
    expect(screen.getByText('some_custom_tool')).toBeInTheDocument()
    expect(screen.getByText('3次')).toBeInTheDocument()
  })

  it('running=true 时默认展开，可看到 children', () => {
    render(
      <ToolGroupContainer toolName="read_file" count={2} running={true} indices={[0, 1]}>
        <div data-testid="leaf">文件内容</div>
      </ToolGroupContainer>,
    )
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.getByTestId('leaf')).toBeInTheDocument()
  })

  it('running=false(done) 时默认折叠，children 被隐藏', () => {
    render(
      <ToolGroupContainer toolName="read_file" count={2} running={false} indices={[0, 1]}>
        <div data-testid="leaf">文件内容</div>
      </ToolGroupContainer>,
    )
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.queryByTestId('leaf')).not.toBeInTheDocument()
  })

  describe('搜索组来源汇总 (LITE)', () => {
    it('合并多个域名结果，显示唯一域名 badge + "来源 N 个"', () => {
      // 搜索 3 次 —— domain 4 种(s/r/v/n)，URL 9 个（无重复）
      setParts([
        { result: tavilyResult(['https://s.com/a', 'https://r.com/b', 'https://v.com/c']) },
        { result: tavilyResult(['https://n.com/d', 'https://s.com/e', 'https://r.com/f']) },
        { result: tavilyResult(['https://v.com/g', 'https://n.com/h', 'https://s.com/i']) },
      ])
      render(
        <ToolGroupContainer toolName="tavily_search" count={3} running={false} indices={[0, 1, 2]}>
          <div>leaf</div>
        </ToolGroupContainer>,
      )
      // 唯一 URL 9 个 → "来源 9 个"
      expect(screen.getByText('来源 9 个')).toBeInTheDocument()
      // 唯一 domain 4 种 → badge 最多只显示 3 个（S/R/V —— s 出现 3 次，频率最高）
      expect(screen.getByText('S')).toBeInTheDocument()
      expect(screen.getByText('R')).toBeInTheDocument()
      expect(screen.getByText('V')).toBeInTheDocument()
      // 同时显示数量标签
      expect(screen.getByText('3次')).toBeInTheDocument()
    })

    it('URL 重复项会 dedup，来源数量准确', () => {
      setParts([
        { result: tavilyResult(['https://a.com/1', 'https://b.com/2']) },
        { result: tavilyResult(['https://a.com/1', 'https://b.com/2']) }, // 同一 URL 2 次
      ])
      render(
        <ToolGroupContainer toolName="web_search" count={2} running={false} indices={[0, 1]}>
          <div>leaf</div>
        </ToolGroupContainer>,
      )
      expect(screen.getByText('来源 2 个')).toBeInTheDocument()
    })

    it('running=true（进行中）时不显示来源行', () => {
      setParts([{ result: tavilyResult(['https://a.com/1']) }])
      render(
        <ToolGroupContainer toolName="tavily_search" count={2} running={true} indices={[0, 1]}>
          <div>leaf</div>
        </ToolGroupContainer>,
      )
      expect(screen.queryByText(/来源/)).not.toBeInTheDocument()
    })

    it('非搜索组(read_file)不显示来源行', () => {
      // 即使是 read_file 且 parts 中有搜索形状 result，也不能参与汇总。
      setParts([
        { result: tavilyResult(['https://a.com/1', 'https://b.com/2']) },
        { result: tavilyResult(['https://c.com/3']) },
      ])
      render(
        <ToolGroupContainer toolName="read_file" count={2} running={false} indices={[0, 1]}>
          <div>leaf</div>
        </ToolGroupContainer>,
      )
      expect(screen.getByText('读取文件')).toBeInTheDocument()
      expect(screen.queryByText(/来源/)).not.toBeInTheDocument()
      // 也不应显示 domain badge
      expect(screen.queryByText('A')).not.toBeInTheDocument()
    })
  })
})
