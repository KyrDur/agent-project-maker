import { render, screen, userEvent, waitFor } from '../test-utils'
import SettingsPage from '@/app/settings/page'
import SecuritySettingsPage from '@/app/settings/security/page'
import AppearanceSettingsPage from '@/app/settings/appearance/page'
import AgentApiSettingsPage from '@/app/settings/agent-api/page'
import MemorySettingsPage from '@/app/settings/memory/page'

const updateProfile = vi.fn()
const uploadAvatarImage = vi.fn()
const deleteAvatarImage = vi.fn()
const updateUserMemorySettings = vi.fn()
const createMemory = vi.fn()
const updateMemory = vi.fn()
const deleteMemory = vi.fn()
const mockUseSession = vi.fn()
const mockUseAgentDeploymentCandidates = vi.fn()
const mockUseAgentDeployments = vi.fn()
const mockUseAgentApiKeys = vi.fn()
const mockCreateAgentDeployment = vi.fn()
const mockCreateAgentApiKey = vi.fn()
const mockRevokeAgentApiKey = vi.fn()

vi.mock('@/lib/api/auth', () => ({
  authApi: {
    updateProfile: (...args: unknown[]) => updateProfile(...args),
    uploadAvatarImage: (...args: unknown[]) => uploadAvatarImage(...args),
    deleteAvatarImage: (...args: unknown[]) => deleteAvatarImage(...args),
  },
}))

vi.mock('next-themes', () => ({
  useTheme: () => ({
    theme: 'system',
    setTheme: vi.fn(),
  }),
}))

vi.mock('@/lib/auth/session', () => ({
  useSession: () => mockUseSession(),
}))

vi.mock('@/lib/hooks/use-agent-api', () => ({
  useAgentDeploymentCandidates: () => mockUseAgentDeploymentCandidates(),
  useAgentDeployments: () => mockUseAgentDeployments(),
  useAgentApiKeys: () => mockUseAgentApiKeys(),
  useCreateAgentDeployment: () => mockCreateAgentDeployment(),
  useCreateAgentApiKey: () => mockCreateAgentApiKey(),
  useRevokeAgentApiKey: () => mockRevokeAgentApiKey(),
}))

vi.mock('@/lib/hooks/use-agents', () => ({
  useAgents: () => ({
    data: [
      {
        id: 'agent-1',
        name: '리서치 에이전트',
        description: '뉴스를 요약합니다.',
        status: 'active',
        is_favorite: false,
        image_url: null,
        model_display_name: 'GPT-5',
        tool_count: 0,
        fallback_count: 0,
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        unread_count: 0,
      },
    ],
    isLoading: false,
  }),
}))

vi.mock('@/lib/hooks/use-memory', () => ({
  useUserMemorySettings: () => ({
    data: {
      memory_enabled: true,
      memory_read_enabled: true,
      memory_write_policy: 'ask',
      allowed_scopes: 'both',
      trigger_memory_write_policy: 'off',
    },
    isLoading: false,
  }),
  useUpdateUserMemorySettings: () => ({
    mutateAsync: updateUserMemorySettings,
    isPending: false,
  }),
  useMemories: () => ({
    data: [
      {
        id: 'memory-1',
        user_id: 'user-1',
        agent_id: null,
        scope: 'user',
        content: '회의는 오후 3시 이후를 선호합니다.',
        reason: '일정 선호',
        store_path: '/memories/users/user-1/memory-1.md',
        source_conversation_id: null,
        source_message_id: null,
        source_run_id: null,
        status: 'active',
        created_at: '2026-06-03T00:00:00Z',
        updated_at: '2026-06-03T00:00:00Z',
        deleted_at: null,
      },
    ],
    isLoading: false,
  }),
  useCreateMemory: () => ({ mutateAsync: createMemory, isPending: false }),
  useUpdateMemory: () => ({ mutateAsync: updateMemory, isPending: false }),
  useDeleteMemory: () => ({ mutateAsync: deleteMemory, isPending: false }),
}))

describe('settings pages', () => {
  beforeEach(() => {
    updateProfile.mockClear()
    updateProfile.mockResolvedValue({
      id: 'user-1',
      name: 'Test User',
      display_name: '새이름',
      avatar_mode: 'initials',
      avatar_initials: '새',
      avatar_color: 'sky',
      avatar_image_url: null,
      email: 'test@example.com',
      is_super_user: true,
      created_at: '2026-05-01T00:00:00Z',
      last_login_at: '2026-05-02T00:00:00Z',
    })
    uploadAvatarImage.mockClear()
    deleteAvatarImage.mockClear()
    updateUserMemorySettings.mockClear()
    createMemory.mockClear()
    updateMemory.mockClear()
    deleteMemory.mockClear()
    mockUseAgentDeploymentCandidates.mockReturnValue({ data: [], isLoading: false })
    mockUseAgentDeployments.mockReturnValue({ data: [], isLoading: false })
    mockUseAgentApiKeys.mockReturnValue({ data: [], isLoading: false })
    mockCreateAgentDeployment.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
    mockCreateAgentApiKey.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
    mockRevokeAgentApiKey.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
    mockUseSession.mockReturnValue({
      data: {
        id: 'user-1',
        name: 'Test User',
        display_name: '用户',
        avatar_mode: 'initials',
        avatar_initials: '체',
        avatar_color: 'sky',
        avatar_image_url: null,
        email: 'test@example.com',
        is_super_user: true,
        created_at: '2026-05-01T00:00:00Z',
        last_login_at: '2026-05-02T00:00:00Z',
      },
      isPending: false,
    })
  })

  it('renders editable profile settings from the active session', () => {
    render(<SettingsPage />)

    expect(screen.getByRole('heading', { name: '公司简介' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('用户')).toBeInTheDocument()
    expect(screen.getByLabelText('체스터 프로필 아이콘')).toHaveTextContent('체')
    expect(screen.getByDisplayValue('체')).toBeInTheDocument()
    expect(screen.getByText('test@example.com')).toBeInTheDocument()
    expect(screen.getAllByText('管理员').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText('用户')).not.toBeInTheDocument()
  })

  it('saves display name and letter avatar settings', async () => {
    render(<SettingsPage />)

    await userEvent.clear(screen.getByLabelText('显示名称'))
    await userEvent.type(screen.getByLabelText('显示名称'), '새이름')
    await userEvent.clear(screen.getByLabelText('图标字母'))
    await userEvent.type(screen.getByLabelText('图标字母'), '새')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(updateProfile).toHaveBeenCalledWith({
        display_name: '새이름',
        avatar_mode: 'initials',
        avatar_initials: '새',
        avatar_color: 'sky',
      })
    })
  })

  it('renders the security placeholder page', () => {
    render(<SecuritySettingsPage />)

    expect(screen.getByRole('heading', { name: '安全性' })).toBeInTheDocument()
    expect(screen.getByText('密码更改和会话管理即将推出。')).toBeInTheDocument()
  })

  it('renders appearance and language settings', () => {
    render(<AppearanceSettingsPage />)

    expect(screen.getByRole('heading', { name: '外貌与语言' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /라이트/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /다크/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /시스템/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /한국어/ })).toBeInTheDocument()
  })

  it('renders the Agent API management page', () => {
    render(<AgentApiSettingsPage />)

    expect(screen.getByRole('heading', { name: 'Agent API' })).toBeInTheDocument()
    expect(
      screen.getByText(
        '部署智能体，颁发服务器端API密钥，并从外部系统调用Agent Project Maker。',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('部署候选版本')).toBeInTheDocument()
    expect(screen.getAllByText('API 密钥').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('调用示例')).toBeInTheDocument()
  })

  it('translates Agent API deployment candidate reason codes', () => {
    mockUseAgentDeploymentCandidates.mockReturnValue({
      data: [
        {
          agent_id: 'agent-1',
          agent_name: '리서치 에이전트',
          runtime_name: 'agent_runtime_1',
          existing_deployment_id: null,
          existing_public_id: null,
          eligible: false,
          ineligible_reason: null,
          ineligible_reason_code: 'fixed_identity_required',
        },
      ],
      isLoading: false,
    })

    render(<AgentApiSettingsPage />)

    expect(
      screen.getByText('API 部署需要使用 智能体 固定凭据。'),
    ).toBeInTheDocument()
    expect(screen.queryByText('API deployment requires fixed identity.')).not.toBeInTheDocument()
  })

  it('shows the admin settings section for super users', () => {
    render(<SettingsPage />)

    expect(screen.getAllByText('管理员').length).toBeGreaterThanOrEqual(1)
  })

  it('hides the admin settings section for regular users', () => {
    mockUseSession.mockReturnValue({
      data: {
        id: 'user-2',
        name: 'Regular User',
        display_name: '일반 사용자',
        avatar_mode: 'initials',
        avatar_initials: '太阳',
        avatar_color: 'mint',
        avatar_image_url: null,
        email: 'regular@example.com',
        is_super_user: false,
        created_at: '2026-05-01T00:00:00Z',
        last_login_at: '2026-05-02T00:00:00Z',
      },
      isPending: false,
    })

    render(<SettingsPage />)

    expect(screen.queryByText('管理员')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '市场管理员' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '系统凭据' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '系统大模型设置' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '所有活动' })).not.toBeInTheDocument()
  })

  it('renders memory policy controls and recorded memories', () => {
    render(<MemorySettingsPage />)

    expect(screen.getByRole('heading', { name: '记忆' })).toBeInTheDocument()
    expect(screen.getByLabelText('启用内存')).toBeChecked()
    expect(screen.getByLabelText('在回答中使用记忆')).toBeChecked()
    expect(screen.getByText('保存前询问')).toBeInTheDocument()
    expect(screen.getByText('用户+智能体')).toBeInTheDocument()
    expect(screen.getByText('회의는 오후 3시 이후를 선호합니다.')).toBeInTheDocument()
  })

  it('creates a memory from the settings page', async () => {
    createMemory.mockResolvedValue({
      id: 'memory-2',
      user_id: 'user-1',
      agent_id: null,
      scope: 'user',
      content: '문서 초안은 한국어로 먼저 작성합니다.',
      reason: null,
      store_path: '/memories/users/user-1/memory-2.md',
      source_conversation_id: null,
      source_message_id: null,
      source_run_id: null,
      status: 'active',
      created_at: '2026-06-04T00:00:00Z',
      updated_at: '2026-06-04T00:00:00Z',
      deleted_at: null,
    })
    render(<MemorySettingsPage />)

    await userEvent.type(
      screen.getByLabelText('新的记忆内容'),
      '문서 초안은 한국어로 먼저 작성합니다.',
    )
    await userEvent.click(screen.getByRole('button', { name: '添加内存' }))

    await waitFor(() => {
      expect(createMemory).toHaveBeenCalledWith({
        scope: 'user',
        content: '문서 초안은 한국어로 먼저 작성합니다.',
        reason: null,
        agent_id: null,
      })
    })
  })
})
