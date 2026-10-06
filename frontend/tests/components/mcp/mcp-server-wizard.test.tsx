import { render, screen, userEvent, waitFor } from '../../test-utils'
import { McpServerWizard } from '@/app/mcp-servers/_components/mcp-server-wizard'

const hookMocks = vi.hoisted(() => ({
  create: vi.fn(),
  createFromRegistry: vi.fn(),
  discover: vi.fn(),
  probe: vi.fn(),
}))

vi.mock('@/components/credential/credential-picker', () => ({
  CredentialPicker: () => <button type="button">选择凭证</button>,
}))

vi.mock('@/lib/hooks/use-mcp-servers', () => ({
  useMcpRegistry: () => ({ data: [] }),
  useCreateMcpServer: () => ({
    mutateAsync: hookMocks.create,
    isPending: false,
  }),
  useCreateFromRegistry: () => ({
    mutateAsync: hookMocks.createFromRegistry,
    isPending: false,
  }),
  useDiscoverMcpTools: () => ({
    mutateAsync: hookMocks.discover,
    isPending: false,
  }),
  useProbeMcpServer: () => ({
    mutateAsync: hookMocks.probe,
    isPending: false,
  }),
}))

describe('McpServerWizard', () => {
  beforeEach(() => {
    hookMocks.create.mockReset()
    hookMocks.createFromRegistry.mockReset()
    hookMocks.discover.mockReset()
    hookMocks.probe.mockReset()
    hookMocks.probe.mockResolvedValue({
      success: true,
      server_info: {},
      tools: [
        {
          name: 'repo_search',
          description: 'Search repositories',
          input_schema: { properties: { query: { type: 'string' } } },
        },
      ],
      error: null,
    })
  })

  it('re-runs probe when a probed manual URL changes', async () => {
    const user = userEvent.setup()

    render(<McpServerWizard open onOpenChange={vi.fn()} />)

    await user.type(screen.getByLabelText(/名称/), 'GitHub MCP')
    await user.type(screen.getByLabelText(/网址/), 'https://old.example.com/mcp')
    await user.click(screen.getByRole('tab', { name: /工具/ }))

    await waitFor(() => expect(hookMocks.probe).toHaveBeenCalledTimes(1))
    expect(hookMocks.probe).toHaveBeenLastCalledWith(
      expect.objectContaining({ url: 'https://old.example.com/mcp' }),
    )

    await user.click(screen.getByRole('tab', { name: /基本设置/ }))
    await user.clear(screen.getByLabelText(/网址/))
    await user.type(screen.getByLabelText(/网址/), 'https://new.example.com/mcp')
    await user.click(screen.getByRole('tab', { name: /工具/ }))

    await waitFor(() => expect(hookMocks.probe).toHaveBeenCalledTimes(2))
    expect(hookMocks.probe).toHaveBeenLastCalledWith(
      expect.objectContaining({ url: 'https://new.example.com/mcp' }),
    )
  })

  it('shows probed tools without unsaved per-tool enable checkboxes', async () => {
    const user = userEvent.setup()

    render(<McpServerWizard open onOpenChange={vi.fn()} />)

    await user.type(screen.getByLabelText(/名称/), 'GitHub MCP')
    await user.type(screen.getByLabelText(/网址/), 'https://example.com/mcp')
    await user.click(screen.getByRole('tab', { name: /工具/ }))

    await screen.findByText('repo_search')

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
