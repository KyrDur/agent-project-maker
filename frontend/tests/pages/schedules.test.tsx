import { render, screen, userEvent, waitFor } from '../test-utils'
import SchedulesPage from '@/app/settings/schedules/page'
import { mockTriggerList } from '../mocks/fixtures'

const mockRunNow = vi.fn()

vi.mock('@/lib/hooks/use-triggers', () => ({
  useAllTriggers: () => ({ data: mockTriggerList, isLoading: false }),
  useUpdateTriggerGlobal: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteTriggerGlobal: () => ({ mutate: vi.fn(), isPending: false }),
  useRunTriggerNow: () => ({ mutate: mockRunNow, isPending: false }),
  useTriggerRuns: () => ({ data: [], isLoading: false }),
}))

vi.mock('@/components/shared/delete-confirm-dialog', () => ({
  DeleteConfirmDialog: () => null,
}))

describe('SchedulesPage', () => {
  beforeEach(() => {
    mockRunNow.mockClear()
  })

  it('renders global schedule table', () => {
    render(<SchedulesPage />)

    expect(screen.getByRole('heading', { name: '定时任务' })).toBeInTheDocument()
    expect(screen.getByText('Hourly update')).toBeInTheDocument()
    expect(screen.getAllByText('Good morning report').length).toBeGreaterThan(0)
    expect(screen.getByText('列表标题')).toBeInTheDocument()
  })

  it('runs a schedule from the global page', async () => {
    const user = userEvent.setup()
    render(<SchedulesPage />)

    await user.click(screen.getAllByRole('button', { name: '立即运行' })[0])

    await waitFor(() => {
      expect(mockRunNow).toHaveBeenCalledWith('trigger-1')
    })
  })

  it('filters schedules by search query', async () => {
    const user = userEvent.setup()
    render(<SchedulesPage />)

    await user.type(screen.getByPlaceholderText('搜索占位符'), 'morning')

    expect(screen.queryByText('Hourly update')).not.toBeInTheDocument()
    expect(screen.getAllByText('Good morning report').length).toBeGreaterThan(0)
  })

  it('shows an empty state when filters match nothing', async () => {
    const user = userEvent.setup()
    render(<SchedulesPage />)

    await user.type(screen.getByPlaceholderText('搜索占位符'), '없는 스케줄')

    expect(screen.getByText('已过滤')).toBeInTheDocument()
  })
})
