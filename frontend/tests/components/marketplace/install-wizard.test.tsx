import { render, screen, userEvent, waitFor } from '../../test-utils'
import { InstallWizard } from '@/components/marketplace/install-wizard'
import type { MarketplaceInstallation, MarketplaceItem } from '@/lib/types/marketplace'

const mockInstall = vi.hoisted(() => vi.fn())
const mockUseMarketplaceVersion = vi.hoisted(() => vi.fn())

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

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/lib/hooks/use-marketplace', () => ({
  useMarketplaceVersion: mockUseMarketplaceVersion,
  useInstallItem: () => ({ mutateAsync: mockInstall, isPending: false }),
}))

vi.mock('@/lib/hooks/use-credentials', () => ({
  useCredentials: () => ({ data: [], isLoading: false }),
}))

function agentItem(): MarketplaceItem {
  return {
    id: 'item-agent',
    resource_type: 'agent',
    name: 'Research Blueprint',
    slug: 'research-blueprint',
    description: 'Creates a research agent.',
    visibility: 'public',
    status: 'published',
    is_system: false,
    is_listed: true,
    tags: [],
    categories: [],
    locale: 'zh-CN',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-02T00:00:00Z',
    latest_version: {
      id: 'version-agent',
      version_label: 'agent-1',
      version_number: 1,
      content_hash: 'abc123',
      created_at: '2026-05-02T00:00:00Z',
    },
    credential_summary: {
      status: 'none',
      required_count: 0,
      optional_count: 0,
      missing_required_count: 0,
    },
    execution_profile: { support_level: 'ready_python' },
    origin_summary: null,
    publication_summary: {
      state: 'not_published',
      is_listed: true,
      shared_user_count: 0,
    },
    installation: {
      installed: false,
      update_available: false,
      dirty: false,
    },
  }
}

describe('InstallWizard', () => {
  beforeEach(() => {
    mockInstall.mockReset()
    mockUseMarketplaceVersion.mockReset()
    mockUseMarketplaceVersion.mockReturnValue({
      data: { credential_requirements: [] },
      isLoading: false,
    })
  })

  it('does not show the create-from-template link for needs_setup agent installs', async () => {
    const user = userEvent.setup()
    const installation: MarketplaceInstallation = {
      id: 'installation-agent',
      item_id: 'item-agent',
      version_id: 'version-agent',
      resource_type: 'agent',
      installed_agent_blueprint_id: 'blueprint-needs-setup',
      install_status: 'needs_setup',
      is_dirty: false,
      installed_at: '2026-05-02T00:00:00Z',
      updated_at: '2026-05-02T00:00:00Z',
    }
    mockInstall.mockResolvedValue(installation)

    render(<InstallWizard item={agentItem()} open onOpenChange={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '安装' }))

    await waitFor(() => {
      expect(mockInstall).toHaveBeenCalled()
    })
    expect(await screen.findByText('Research Blueprint 설치 완료')).toBeInTheDocument()
    expect(screen.queryByText('打开蓝图')).not.toBeInTheDocument()
  })

  it('starts a needs_setup item with requirements on the credentials step', () => {
    mockUseMarketplaceVersion.mockReturnValue({
      data: {
        credential_requirements: [
          {
            key: 'openai_api_key',
            definition_key: 'openai',
            required: true,
            label: 'OpenAI API Key',
          },
        ],
      },
      isLoading: false,
    })
    const item: MarketplaceItem = {
      ...agentItem(),
      installation: {
        installed: true,
        installation_id: 'installation-agent',
        installed_resource_id: 'blueprint-needs-setup',
        status: 'needs_setup',
        update_available: false,
        dirty: false,
      },
    }

    render(<InstallWizard item={item} open onOpenChange={vi.fn()} />)

    // The credentials step must be active on the very first render —
    // previously the initial step was frozen before the version loaded.
    expect(screen.getByText('凭据').closest('li')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('OpenAI API Key')).toBeInTheDocument()
  })

  it('shows a loading state while the version detail is loading', () => {
    mockUseMarketplaceVersion.mockReturnValue({ data: undefined, isLoading: true })

    render(<InstallWizard item={agentItem()} open onOpenChange={vi.fn()} />)

    expect(screen.getByText('正在加载版本详细信息...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '下一步' })).not.toBeInTheDocument()
  })

  it('버전 로드 실패 시 자격증명 단계로 진행하지 않고 에러와 재시도를 보여준다', async () => {
    const user = userEvent.setup()
    const refetch = vi.fn()
    mockUseMarketplaceVersion.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
      refetch,
    })

    render(<InstallWizard item={agentItem()} open onOpenChange={vi.fn()} />)

    // Error UI is shown — no install/next progression, no infinite loading.
    expect(
      screen.getByText('无法加载版本详细信息。重试设置其凭据。'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '下一步' })).not.toBeInTheDocument()
    expect(screen.queryByText('正在加载版本详细信息...')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })
})
