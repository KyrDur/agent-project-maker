import { render, screen } from '../test-utils'
import UsagePage from '@/app/settings/usage/page'
import { mockUsageSummary } from '../mocks/fixtures'

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode
    href: string
    [key: string]: unknown
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

const mockUseUsageSummary = vi.fn()
const mockUseDailyAggregate = vi.fn()

vi.mock('@/lib/hooks/use-usage', () => ({
  useUsageSummary: () => mockUseUsageSummary(),
  useDailyAggregate: () => mockUseDailyAggregate(),
}))

// SpendLineChart/SpendBarChart 依赖 recharts，在 jsdom 中渲染成本较高。
// 仅 stub Container 就足以验证页面布局。
vi.mock('@/components/usage/spend-line-chart', () => ({
  SpendLineChart: () => <div data-testid="spend-line-chart" />,
}))
vi.mock('@/components/usage/spend-bar-chart', () => ({
  SpendBarChart: () => <div data-testid="spend-bar-chart" />,
}))

describe('UsagePage', () => {
  beforeEach(() => {
    mockUseUsageSummary.mockReturnValue({ data: undefined, isLoading: false })
    mockUseDailyAggregate.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('renders page header', () => {
    render(<UsagePage />)
    expect(screen.getByText('用量')).toBeInTheDocument()
  })

  it('renders 4 summary cards (cost / tokens / requests / avg)', () => {
    mockUseUsageSummary.mockReturnValue({ data: mockUsageSummary, isLoading: false })
    render(<UsagePage />)
    expect(screen.getByText('本月费用')).toBeInTheDocument()
    expect(screen.getByText('本月Token')).toBeInTheDocument()
    expect(screen.getByText('本月请求')).toBeInTheDocument()
    expect(screen.getByText('平均成本/请求')).toBeInTheDocument()
  })

  it('renders filter bar with target-kind / group-by / metric tabs', () => {
    render(<UsagePage />)
    expect(screen.getByTestId('usage-filter-bar')).toBeInTheDocument()
    expect(screen.getByTestId('target-kind-tabs')).toBeInTheDocument()
    expect(screen.getByTestId('group-by-tabs')).toBeInTheDocument()
    expect(screen.getByTestId('metric-tabs')).toBeInTheDocument()
  })

  it('renders chart skeleton while daily aggregate is loading', () => {
    mockUseDailyAggregate.mockReturnValue({ data: undefined, isLoading: true })
    const { container } = render(<UsagePage />)
    const skeletons = container.querySelectorAll("[data-slot='skeleton']")
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('shows empty state when daily entries are empty', () => {
    mockUseDailyAggregate.mockReturnValue({ data: [], isLoading: false })
    render(<UsagePage />)
    // Chart + Table 两处都会显示相同 EmptyState — 两者都存在则 OK.
    expect(screen.getAllByText('还没有使用。').length).toBeGreaterThanOrEqual(1)
  })

  it('renders chart when daily entries are present', () => {
    mockUseDailyAggregate.mockReturnValue({
      data: [
        {
          bucket: '2026-04-30',
          target_kind: 'user',
          target_id: 'u-1',
          target_label: 'me',
          input_tokens: 100,
          output_tokens: 50,
          total_tokens: 150,
          request_count: 1,
          estimated_cost_usd: 0.001,
        },
      ],
      isLoading: false,
    })
    render(<UsagePage />)
    // 确认 chart component stub 被渲染 — 不显示空状态 EmptyState。
    expect(screen.queryByText('还没有使用。')).not.toBeInTheDocument()
  })
})
