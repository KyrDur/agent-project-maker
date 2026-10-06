import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../test-utils'
import userEvent from '@testing-library/user-event'

// useAuiState mock — 按测试用例用 mockReturnValue 替换。
const mockUseAssistantState = vi.fn()

vi.mock('@assistant-ui/react', () => ({
  useAuiState: (selector: (state: unknown) => unknown) =>
    selector({
      message: {
        metadata: {
          custom: { usage: mockUseAssistantState() },
        },
      },
    }),
}))

import { TokenUsagePopover } from '@/components/chat/token-usage-popover'

describe('TokenUsagePopover', () => {
  it('没有 usage 时不渲染', () => {
    mockUseAssistantState.mockReturnValue(undefined)
    const { container } = render(<TokenUsagePopover />)
    expect(container).toBeEmptyDOMElement()
  })

  it('总 token 为 0 时不渲染', () => {
    mockUseAssistantState.mockReturnValue({
      prompt_tokens: 0,
      completion_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
    })
    const { container } = render(<TokenUsagePopover />)
    expect(container).toBeEmptyDOMElement()
  })

  it('在按钮上显示总 token 数', () => {
    mockUseAssistantState.mockReturnValue({
      prompt_tokens: 1200,
      completion_tokens: 300,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
    })
    render(<TokenUsagePopover />)
    // 1200 + 300 = 1,500
    expect(screen.getByText('1,500')).toBeInTheDocument()
  })

  it('hover 时展示全部 4 类明细', async () => {
    mockUseAssistantState.mockReturnValue({
      prompt_tokens: 1200,
      completion_tokens: 300,
      cache_creation_tokens: 800,
      cache_read_tokens: 200,
      estimated_cost: 0.0123,
    })
    const user = userEvent.setup()
    render(<TokenUsagePopover />)

    // 通过 hover 打开 popover — click 会先由 onMouseEnter 设置 open(true)，然后
    // button onClick 再次 toggle 导致关闭。实际使用中 hover 也是主要入口。
    await user.hover(screen.getByRole('button', { name: '切换咏叹调' }))

    expect(screen.getByText('Token 用量')).toBeInTheDocument()
    expect(screen.getByText('1,200')).toBeInTheDocument() // input
    expect(screen.getByText('300')).toBeInTheDocument() // output
    expect(screen.getByText('800')).toBeInTheDocument() // cache_creation
    expect(screen.getByText('200')).toBeInTheDocument() // cache_read
    expect(screen.getByText('$0.0123')).toBeInTheDocument()
  })

  it('详细 popover 通过 portal 渲染，避免被父级 overflow 裁切', async () => {
    mockUseAssistantState.mockReturnValue({
      prompt_tokens: 1200,
      completion_tokens: 300,
      cache_creation_tokens: 800,
      cache_read_tokens: 200,
      estimated_cost: 0.0123,
    })
    const user = userEvent.setup()
    const { container } = render(
      <div className="overflow-hidden">
        <TokenUsagePopover />
      </div>,
    )

    await user.hover(screen.getByRole('button', { name: '切换咏叹调' }))

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveTextContent('Token 用量')
    expect(container).not.toContainElement(tooltip)
  })

  it('estimated_cost 为 0 时隐藏费用行', async () => {
    mockUseAssistantState.mockReturnValue({
      prompt_tokens: 100,
      completion_tokens: 50,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      estimated_cost: 0,
    })
    const user = userEvent.setup()
    render(<TokenUsagePopover />)
    await user.hover(screen.getByRole('button', { name: '切换咏叹调' }))
    expect(screen.queryByText('预计费用')).not.toBeInTheDocument()
  })
})
