import { render, screen, userEvent } from '../test-utils'
import ManualCreationPage from '@/app/agents/new/manual/page'

const mockUseModels = vi.fn()
const mockRefetchModels = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/lib/hooks/use-models', () => ({
  useModels: () => mockUseModels(),
}))

vi.mock('@/lib/hooks/use-agents', () => ({
  useCreateAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('@/lib/hooks/use-tools', () => ({
  useTools: () => ({ data: [] }),
}))

vi.mock('@/lib/hooks/use-skills', () => ({
  useSkills: () => ({ data: [] }),
}))

vi.mock('@/lib/hooks/use-middlewares', () => ({
  useMiddlewares: () => ({ data: [] }),
}))

describe('ManualCreationPage model availability', () => {
  beforeEach(() => {
    mockRefetchModels.mockReset()
  })

  it.each([
    ['a terminal model-query error', { data: undefined, isLoading: false, isError: true }],
    ['an empty loaded model list', { data: [], isLoading: false, isError: false }],
  ])('renders a retryable error surface for %s', async (_scenario, queryState) => {
    const user = userEvent.setup()
    mockUseModels.mockReturnValue({ ...queryState, refetch: mockRefetchModels })

    render(<ManualCreationPage />)

    expect(screen.getByRole('heading', { name: '出了点问题' })).toBeInTheDocument()
    expect(
      screen.getByText('我们无法加载模型信息。请稍后重试。'),
    ).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('智能体名称')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '重试' }))

    expect(mockRefetchModels).toHaveBeenCalledOnce()
  })
})
