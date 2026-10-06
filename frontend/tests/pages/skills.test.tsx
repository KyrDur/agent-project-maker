import { render, screen, userEvent, within } from '../test-utils'
// Phase 2: page.tsx 是 async server redirect wrapper — UI 直接渲染 client component。
import { SkillsPageClient } from '@/app/skills/_components/skills-page-client'
import type { Skill } from '@/lib/types/skill'

const mockUseSkills = vi.fn()
const mockCreateDialog = vi.fn()
const mockDeleteSkill = vi.fn()

vi.mock('@/lib/hooks/use-skills', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/hooks/use-skills')>()
  return {
    ...actual,
    useSkills: (...args: unknown[]) => mockUseSkills(...args),
    useDeleteSkill: () => ({ mutateAsync: mockDeleteSkill, isPending: false }),
  }
})

vi.mock('@/components/skill/skill-create-dialog', () => ({
  SkillCreateDialog: (props: { readonly open: boolean; readonly initialTab?: string }) => {
    mockCreateDialog(props)
    return props.open ? <div data-testid="skill-create-dialog">{props.initialTab}</div> : null
  },
}))

vi.mock('@/lib/hooks/use-agents', () => ({
  useAgents: () => ({
    data: [
      {
        id: 'agent-1',
        name: '会议助手',
        skills: [{ id: 'skill-1', name: 'Korea Weather' }],
      },
    ],
  }),
}))

vi.mock('@/components/marketplace/publish-wizard', () => ({
  PublishWizard: () => null,
}))

const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}))

const skill: Skill = {
  id: 'skill-1',
  name: 'Korea Weather',
  slug: 'korea-weather',
  description: '查询韩国天气。',
  kind: 'package',
  version: '0.1.0',
  storage_path: null,
  content_hash: null,
  size_bytes: 1200,
  used_by_count: 2,
  package_metadata: null,
  health: {
    state: 'ready',
    label: '已验证',
    reason: 'Latest evaluation passed for the current skill.',
    severity: 'success',
  },
  latest_evaluation_summary: {
    status: 'completed',
    latest_run_id: 'run-1',
    evaluation_set_id: 'set-1',
    pass_rate: 0.92,
    skill_content_hash: 'hash-1',
    created_at: '2026-06-01T00:00:00Z',
    completed_at: '2026-06-01T00:01:00Z',
  },
  last_modified_at: '2026-05-01T00:00:00Z',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-02T00:00:00Z',
  origin_summary: null,
  publication_summary: null,
  installation: null,
}

function buildSkill(overrides: Partial<Skill>): Skill {
  return {
    ...skill,
    ...overrides,
  }
}

function publishedSummary(id: string): NonNullable<Skill['publication_summary']> {
  return {
    state: 'published_private',
    item_id: id,
    visibility: 'private',
    status: 'published',
    is_listed: false,
    latest_version_id: `${id}-version`,
    version_number: 1,
    shared_user_count: 0,
  }
}

describe('SkillsPage', () => {
  beforeEach(() => {
    mockCreateDialog.mockClear()
    mockUseSkills.mockReturnValue({ data: [skill], isLoading: false })
  })

  it('将 studio 列表渲染为表格(DataTable) — Phase 2', () => {
    render(<SkillsPageClient />)

    expect(screen.getByRole('tab', { name: '全部 1' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索技巧')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /技能/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /智能体/ })).toBeInTheDocument()
    expect(screen.getByText('Korea Weather')).toBeInTheDocument()
    expect(screen.getByText(/korea-weather · v0\.1\.0/)).toBeInTheDocument()
    // 连接计数真实数据 (M1)
    expect(screen.getByText('2 个智能体')).toBeInTheDocument()
  })

  it('在表格行中显示状态·评估摘要 badge', () => {
    render(<SkillsPageClient />)

    expect(screen.getByText('已验证')).toBeInTheDocument()
    expect(screen.getByText('评估92%')).toBeInTheDocument()
  })

  it("'清除选择' 会同时重置 controlled 选择(rowSelection+selected)", async () => {
    const user = userEvent.setup()
    render(<SkillsPageClient />)

    // 行级 checkbox 路径（项目规则 — 如果只用 header 全选，就无法捕获行点击
    // 传播类别）。
    await user.click(screen.getByRole('checkbox', { name: '选择行' }))
    expect(screen.getByTestId('skill-bulk-bar')).toHaveTextContent('1 已选择')

    await user.click(screen.getByRole('button', { name: '清除选择' }))

    expect(screen.queryByTestId('skill-bulk-bar')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '选择行' })).not.toBeChecked()
  })

  it('选择行时显示 bulk bar，并在批量删除确认中列出名称', async () => {
    const user = userEvent.setup()
    mockDeleteSkill.mockResolvedValue(undefined)
    render(<SkillsPageClient />)

    expect(screen.queryByTestId('skill-bulk-bar')).not.toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: '选择所有行' }))

    expect(screen.getByTestId('skill-bulk-bar')).toHaveTextContent('1 已选择')

    await user.click(
      within(screen.getByTestId('skill-bulk-bar')).getByRole('button', { name: '删除' }),
    )

    // 确认 dialog — 为防止搜索隐藏的已选行，明确显示目标名称。
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('Korea Weather')
    expect(dialog).toHaveTextContent('2 个关联智能体')
    // AD-4.1 — 영향받는 智能体 이름 역도출 표시.
    expect(dialog).toHaveTextContent('受影响的智能体：会议助手')

    await user.click(within(dialog).getByRole('button', { name: '删除' }))

    expect(mockDeleteSkill).toHaveBeenCalledWith('skill-1')
  })

  it('批量删除中的 404 视为幂等成功 — 不误发失败 toast（R5 规则 ④）', async () => {
    const { ApiError } = await import('@/lib/api/errors')
    const user = userEvent.setup()
    mockToastSuccess.mockClear()
    mockToastError.mockClear()
    // 已在其他标签页删除的目标 — backend 返回 404。
    mockDeleteSkill.mockRejectedValue(new ApiError(404, 'SKILL_NOT_FOUND', 'not found'))
    render(<SkillsPageClient />)

    await user.click(screen.getByRole('checkbox', { name: '选择所有行' }))
    await user.click(
      within(screen.getByTestId('skill-bulk-bar')).getByRole('button', { name: '删除' }),
    )
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '删除' }))

    expect(mockToastError).not.toHaveBeenCalled()
    expect(mockToastSuccess).toHaveBeenCalled()
  })

  it('filters skills from the shared tab row', async () => {
    const user = userEvent.setup()
    render(<SkillsPageClient />)

    await user.click(screen.getByRole('tab', { name: /套餐/ }))

    expect(mockUseSkills).toHaveBeenLastCalledWith({ kind: 'package' })
    expect(screen.getByRole('tab', { name: '套餐 1' })).toHaveAttribute('aria-selected', 'true')
  })

  it('filters skills from compact state chips', async () => {
    const user = userEvent.setup()
    mockUseSkills.mockReturnValue({
      data: [
        buildSkill({
          id: 'skill-needs-credentials',
          name: 'Credential Setup',
          health: {
            state: 'needs_credentials',
            label: '所需凭据',
            reason: '没有必需凭据。',
            severity: 'warning',
          },
          publication_summary: publishedSummary('item-credentials'),
        }),
        buildSkill({
          id: 'skill-needs-rerun',
          name: 'Rerun Needed',
          health: {
            state: 'needs_rerun',
            label: '需要重新运行',
            reason: '内容已更改。',
            severity: 'warning',
          },
          publication_summary: publishedSummary('item-rerun'),
        }),
        buildSkill({
          id: 'skill-failed',
          name: 'Failed Eval',
          health: {
            state: 'evaluation_failed',
            label: '评估失败',
            reason: '上次评估失败。',
            severity: 'error',
          },
          publication_summary: publishedSummary('item-failed'),
        }),
        buildSkill({
          id: 'skill-local',
          name: 'Local Draft',
          publication_summary: {
            state: 'not_published',
            is_listed: false,
            shared_user_count: 0,
          },
        }),
      ],
      isLoading: false,
    })

    render(<SkillsPageClient />)

    expect(screen.getByRole('button', { name: '所需凭据 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '需要重新运行 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '评估失败 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '已发表 3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '本地/草稿 1' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '所需凭据 1' }))

    expect(screen.getByText('Credential Setup')).toBeInTheDocument()
    expect(screen.queryByText('Rerun Needed')).not.toBeInTheDocument()
    expect(screen.queryByText('Failed Eval')).not.toBeInTheDocument()
    expect(screen.queryByText('Local Draft')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '本地/草稿 1' }))

    expect(screen.getByText('Local Draft')).toBeInTheDocument()
    expect(screen.queryByText('Credential Setup')).not.toBeInTheDocument()
  })

  it('opens the create dialog on the conversational tab from the primary CTA', async () => {
    const user = userEvent.setup()
    render(<SkillsPageClient />)

    await user.click(screen.getByRole('button', { name: '通过聊天构建' }))

    expect(screen.getByTestId('skill-create-dialog')).toHaveTextContent('chat')
    expect(mockCreateDialog).toHaveBeenLastCalledWith(
      expect.objectContaining({ open: true, initialTab: 'chat' }),
    )
  })
})
