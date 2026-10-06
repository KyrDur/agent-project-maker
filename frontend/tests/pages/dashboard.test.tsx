import { render, screen } from '../test-utils'
import DashboardPage from '@/app/dashboard-page-client'
import { mockAgentSummaryList } from '../mocks/fixtures'

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

vi.mock('@/lib/hooks/use-system-llm-settings', () => ({
  useSystemLlmReadiness: () => ({ data: [] }),
}))

const mockUseAgentSummaries = vi.fn()
const mockUseSession = vi.fn()
const mockToggleFavorite = vi.fn()

const greetingCases = [
  { hour: 4, minute: 59, expectedGreeting: '今晚工作到很晚' },
  { hour: 5, minute: 0, expectedGreeting: '早上好' },
  { hour: 12, minute: 0, expectedGreeting: '下午好' },
  { hour: 18, minute: 0, expectedGreeting: '晚上好' },
  { hour: 22, minute: 0, expectedGreeting: '今天干得好' },
] as const

vi.mock('@/lib/hooks/use-agents', () => ({
  useAgentSummaries: () => mockUseAgentSummaries(),
  useToggleFavorite: () => ({ mutate: mockToggleFavorite }),
}))

vi.mock('@/lib/auth/session', () => ({
  useSession: () => mockUseSession(),
}))

describe('DashboardPage', () => {
  beforeEach(() => {
    mockUseAgentSummaries.mockReturnValue({ data: undefined, isLoading: false })
    mockUseSession.mockReturnValue({ data: null })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders loading skeletons when agents are loading', () => {
    mockUseAgentSummaries.mockReturnValue({ data: undefined, isLoading: true })
    render(<DashboardPage />)
    expect(screen.getByText('我的智能体')).toBeInTheDocument()
  })

  it('renders agent cards when data is loaded', () => {
    mockUseAgentSummaries.mockReturnValue({
      data: mockAgentSummaryList,
      isLoading: false,
    })
    render(<DashboardPage />)
    expect(screen.getByText('Test Agent')).toBeInTheDocument()
    expect(screen.getByText('Second Agent')).toBeInTheDocument()
  })

  it('renders empty state when no agents', () => {
    mockUseAgentSummaries.mockReturnValue({ data: [], isLoading: false })
    render(<DashboardPage />)
    expect(screen.getByText('创建你的第一个智能体')).toBeInTheDocument()
  })

  it('shows quick action cards linking to creation pages', () => {
    render(<DashboardPage />)
    expect(screen.getByText('通过聊天构建')).toBeInTheDocument()
    expect(screen.queryByText('使用模板')).not.toBeInTheDocument()
    expect(screen.queryByText('手动构建')).not.toBeInTheDocument()

    const conversationalLink = screen.getByText('通过聊天构建').closest('a')
    expect(conversationalLink).toHaveAttribute('href', '/agents/new')
  })

  it.each(greetingCases)(
    'shows $expectedGreeting at $hour:$minute',
    ({ hour, minute, expectedGreeting }) => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date(2026, 8, 6, hour, minute))
      mockUseAgentSummaries.mockReturnValue({ data: mockAgentSummaryList, isLoading: false })
      mockUseSession.mockReturnValue({ data: { id: 'u1', name: '用户', email: 'a@b.c' } })
      render(<DashboardPage />)
      expect(screen.getByText(`${expectedGreeting},`, { exact: true })).toBeInTheDocument()
      expect(screen.getByText('你好，用户 👋')).toBeInTheDocument()
      expect(
        screen.getByText(new RegExp(`你目前有 ${mockAgentSummaryList.length} 个智能体`)),
      ).toBeInTheDocument()
    },
  )

  it('prefers display name in the hero greeting', () => {
    mockUseAgentSummaries.mockReturnValue({ data: [], isLoading: false })
    mockUseSession.mockReturnValue({
      data: {
        id: 'u1',
        name: '注册名称',
        display_name: '显示名称',
        email: 'a@b.c',
      },
    })
    render(<DashboardPage />)
    expect(screen.getByText('你好，显示名称 👋')).toBeInTheDocument()
    expect(screen.queryByText('你好，注册名称 👋')).not.toBeInTheDocument()
  })

  it('falls back to "用户" when session is null', () => {
    mockUseSession.mockReturnValue({ data: null })
    mockUseAgentSummaries.mockReturnValue({ data: [], isLoading: false })
    render(<DashboardPage />)
    expect(screen.getByText('你好，用户 👋')).toBeInTheDocument()
  })

  it('does not render usage summary or tip line (removed in redesign)', () => {
    mockUseAgentSummaries.mockReturnValue({ data: [], isLoading: false })
    render(<DashboardPage />)
    expect(screen.queryByText('本月使用情况')).not.toBeInTheDocument()
    expect(screen.queryByText(/💡 提示/)).not.toBeInTheDocument()
  })

  it('shows agent count in header section', () => {
    mockUseAgentSummaries.mockReturnValue({
      data: mockAgentSummaryList,
      isLoading: false,
    })
    render(<DashboardPage />)
    expect(screen.getByText('我的智能体')).toBeInTheDocument()
  })
})
