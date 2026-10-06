import { render, screen } from '../test-utils'
import ModelsPage from '@/app/settings/models/page'
import { mockModelList } from '../mocks/fixtures'

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

const mockUseModels = vi.fn()
const mockDeleteModel = vi.fn()

vi.mock('@/lib/hooks/use-models', () => ({
  useModels: () => mockUseModels(),
  useUpdateModel: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDeleteModel: () => ({
    mutate: mockDeleteModel,
    isPending: false,
  }),
}))

vi.mock('@/lib/hooks/use-providers', () => ({
  useProviders: () => ({ data: [], isLoading: false }),
  useDeleteProvider: () => ({ mutate: vi.fn(), isPending: false }),
}))

// Mock complex sub-components
vi.mock('@/components/model/provider-card', () => ({
  ProviderCard: () => <div data-testid="provider-card" />,
}))

vi.mock('@/components/model/provider-form', () => ({
  ProviderForm: () => null,
}))

vi.mock('@/components/model/model-add-dialog', () => ({
  ModelAddDialog: () => null,
}))

vi.mock('@/components/model/model-detail-modal', () => ({
  ModelDetailModal: () => null,
}))

// Mock Dialog components from base-ui which are complex
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: React.ReactNode; open?: boolean }) => (
    <div data-testid="dialog" data-open={open}>
      {children}
    </div>
  ),
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dialog-content">{children}</div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/ui/alert-dialog', () => ({
  AlertDialog: ({ children, open }: { children: React.ReactNode; open?: boolean }) => (
    <div data-testid="alert-dialog" data-open={open}>
      {children}
    </div>
  ),
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogAction: ({
    children,
    onClick,
  }: {
    children: React.ReactNode
    onClick?: () => void
    variant?: string
  }) => <button onClick={onClick}>{children}</button>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
  ),
}))

// Extend mockModelList with new required fields
const modelsWithNewFields = mockModelList.map((m) => ({
  ...m,
  provider_id: `provider-${m.provider}`,
  provider_name: m.provider === 'openai' ? 'OpenAI' : 'Anthropic',
  context_window: null,
  max_output_tokens: null,
  input_modalities: null,
  output_modalities: null,
  supports_vision: null,
  supports_function_calling: null,
  supports_reasoning: null,
  agent_count: 0,
}))

/**
 * 页面结构（M10 之后）：PageHeader（英文 "Models" 标题 + New model 按钮）+
 * DataTable + EmptyState. 旧测试假定了韩语 i18n + Tabs 结构，但
 * 当前页面是未应用 i18n 的英文 + 无标签。provider/model detail 已
 * 拆分到 model-detail-modal 组件单元测试。
 */
describe('ModelsPage', () => {
  beforeEach(() => {
    mockUseModels.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('renders page header with title + 新模型 action', () => {
    render(<ModelsPage />)
    expect(screen.getByText('模型')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新模型/ })).toBeInTheDocument()
  })

  it('shows empty state when no models', () => {
    mockUseModels.mockReturnValue({ data: [], isLoading: false })
    render(<ModelsPage />)
    expect(screen.getByText('空')).toBeInTheDocument()
  })

  it('renders model display names when data is loaded', () => {
    mockUseModels.mockReturnValue({ data: modelsWithNewFields, isLoading: false })
    render(<ModelsPage />)
    expect(screen.getByText('GPT-4o')).toBeInTheDocument()
    expect(screen.getByText('Claude Sonnet 4')).toBeInTheDocument()
  })

  it('uses compact pricing and action columns to avoid horizontal overflow', () => {
    mockUseModels.mockReturnValue({ data: modelsWithNewFields, isLoading: false })
    render(<ModelsPage />)

    expect(screen.getByRole('columnheader', { name: /价格/ })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '输入单价' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '输出单价' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /检查 .* 状态/ })[0]).toHaveClass('px-2')
  })

  // 页面内的 DataTable / model detail / provider card / delete flow
  // 由 model-* component unit test 和 e2e 负责（从 page unit 中排除）。
})
