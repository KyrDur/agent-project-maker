import { render, screen, userEvent, waitFor } from '../test-utils'
import MarketplaceAdminPage from '@/app/settings/marketplace-admin/page'
import SystemCredentialsPage from '@/app/settings/system-credentials/page'
import SystemLlmSettingsPage from '@/app/settings/system-llm/page'
import type { Credential, CredentialDefinition } from '@/lib/types/credential'
import type { SystemLlmSettingOut } from '@/lib/types/system-llm-setting'

vi.mock('@/components/credential/credential-create-modal', () => ({
  CredentialCreateModal: () => null,
}))

const hookMocks = vi.hoisted(() => ({
  isSuperUser: true,
  updateSystemLlmSetting: vi.fn(),
  testSystemLlmSetting: vi.fn(),
}))

vi.mock('@/lib/auth/session', () => ({
  useSession: () => ({ data: { id: 'user-1', is_super_user: hookMocks.isSuperUser }, isPending: false }),
}))

const credential: Credential = {
  id: 'cred-openrouter-uuid',
  user_id: '',
  definition_key: 'openrouter',
  name: 'OpenRouter 图像密钥',
  field_keys: ['base_url', 'api_key'],
  is_shared: false,
  is_system: true,
  status: 'active',
  key_id: 'key-1',
  last_used_at: null,
  last_tested_at: null,
  last_test_result: null,
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-02T00:00:00Z',
}

const definitions: CredentialDefinition[] = [
  {
    key: 'openrouter',
    display_name: 'OpenRouter',
    category: 'llm',
    extends: [],
    properties: [],
    has_test: true,
    has_oauth: false,
  },
]

const systemLlmSettings: SystemLlmSettingOut[] = [
  {
    role: 'builder',
    credential_id: credential.id,
    credential_name: credential.name,
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
    model_name: 'openai/gpt-5.4',
    configured: true,
    updated_at: '2026-05-02T00:00:00Z',
  },
  {
    role: 'evaluation_generator',
    credential_id: null,
    credential_name: null,
    provider: null,
    base_url: null,
    model_name: null,
    configured: false,
    updated_at: '2026-05-02T00:00:00Z',
  },
  {
    role: 'judge_optimizer',
    credential_id: null,
    credential_name: null,
    provider: null,
    base_url: null,
    model_name: null,
    configured: false,
    updated_at: '2026-05-02T00:00:00Z',
  },
]

vi.mock('@/lib/hooks/use-credentials', () => ({
  useCredentials: () => ({ data: [{ ...credential, is_system: false, user_id: 'user-1' }], isLoading: false }),
  useSystemCredentials: () => ({ data: [credential], isLoading: false }),
  useCredentialTypes: () => ({ data: definitions }),
  useDeleteSystemCredential: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('@/lib/hooks/use-system-llm-settings', () => ({
  useSystemLlmSettings: () => ({ data: systemLlmSettings, isLoading: false }),
  useUpdateSystemLlmSetting: () => ({
    mutateAsync: hookMocks.updateSystemLlmSetting,
    isPending: false,
  }),
  useTestSystemLlmSetting: () => ({
    mutateAsync: hookMocks.testSystemLlmSetting,
    isPending: false,
  }),
}))

vi.mock('@/lib/hooks/use-marketplace', () => ({
  useAdminSetListed: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisableItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useModerationQueue: () => ({ data: [], isLoading: false }),
}))

vi.mock('@/lib/hooks/use-models', () => ({
  useDiscoverModels: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
  }),
}))

describe('admin settings pages', () => {
  beforeEach(() => {
    hookMocks.isSuperUser = true
    hookMocks.updateSystemLlmSetting.mockReset()
    hookMocks.updateSystemLlmSetting.mockResolvedValue({})
    hookMocks.testSystemLlmSetting.mockReset()
    hookMocks.testSystemLlmSetting.mockResolvedValue({
      success: true,
      response: 'pong',
      latency_ms: 10,
      tokens_in: null,
      tokens_out: null,
      estimated_cost_usd: null,
      error: null,
      raw_request: null,
      raw_response: null,
      curl_command: null,
    })
  })

  it('renders system credentials with Chinese operator copy', () => {
    render(<SystemCredentialsPage />)

    expect(screen.getByRole('heading', { name: '系统凭据' })).toBeInTheDocument()
    expect(screen.getByText('仅限运营商')).toBeInTheDocument()
    expect(screen.getByText('只有超级用户才能管理系统凭据。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /添加/ })).toBeInTheDocument()
    expect(
      screen.getAllByText((_, node) => node?.textContent?.includes('2 字段') ?? false).length,
    ).toBeGreaterThanOrEqual(1)
  })

  it('lets a regular user configure personal keys and models', () => {
    hookMocks.isSuperUser = false
    render(<SystemLlmSettingsPage />)

    expect(screen.getByRole('heading', { name: '我的 AI 配置' })).toBeInTheDocument()
    expect(screen.getByText('使用你的个人 API Key')).toBeInTheDocument()
    expect(screen.getAllByText('OpenRouter 图像密钥').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('openai/gpt-5.4').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('提供商').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('OpenRouter').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText('cred-openrouter-uuid')).not.toBeInTheDocument()
  })

  it('tests the selected platform AI provider, credential, and model', async () => {
    const user = userEvent.setup()
    render(<SystemLlmSettingsPage />)

    await user.click(screen.getAllByRole('button', { name: '测试' })[0])

    await waitFor(() => {
      expect(hookMocks.testSystemLlmSetting).toHaveBeenCalledWith({
        provider: 'openrouter',
        credential_id: 'cred-openrouter-uuid',
        model_name: 'openai/gpt-5.4',
      })
    })
  })

  it('applies quick setup to the three platform roles', async () => {
    const user = userEvent.setup()
    render(<SystemLlmSettingsPage />)

    await user.click(screen.getByRole('button', { name: '应用到创建、评测和优化' }))

    await waitFor(() => {
      expect(hookMocks.updateSystemLlmSetting).toHaveBeenCalledTimes(3)
    })
    expect(hookMocks.updateSystemLlmSetting).toHaveBeenCalledWith({
      role: 'builder',
      data: { credential_id: 'cred-openrouter-uuid', model_name: 'openai/gpt-5.4' },
    })
    expect(hookMocks.updateSystemLlmSetting).toHaveBeenCalledWith({
      role: 'evaluation_generator',
      data: { credential_id: 'cred-openrouter-uuid', model_name: 'openai/gpt-5.4' },
    })
    expect(hookMocks.updateSystemLlmSetting).toHaveBeenCalledWith({
      role: 'judge_optimizer',
      data: { credential_id: 'cred-openrouter-uuid', model_name: 'openai/gpt-5.4' },
    })
  })

  it('renders marketplace moderation inside the settings admin area', () => {
    render(<MarketplaceAdminPage />)

    expect(screen.getByRole('heading', { name: '市场审核' })).toBeInTheDocument()
    expect(screen.getByText('没有等待审核的项目')).toBeInTheDocument()
  })
})
