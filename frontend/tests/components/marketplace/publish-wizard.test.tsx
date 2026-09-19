import { render, screen, userEvent, waitFor } from '../../test-utils'
import { PublishWizard, type PublishWizardResource } from '@/components/marketplace/publish-wizard'

const mockPublishSkill = vi.hoisted(() => vi.fn())
const mockPush = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/lib/hooks/use-marketplace', () => ({
  usePublishSkill: () => ({ mutateAsync: mockPublishSkill, isPending: false }),
  usePublishMcpServer: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePublishAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

function skillResource(): PublishWizardResource {
  return {
    id: 'skill-1',
    resourceType: 'skill',
    name: 'My Skill',
    description: 'A skill',
  }
}

async function goToVisibilityStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '下一步' })) // review → metadata
  await user.click(screen.getByRole('button', { name: '下一步' })) // metadata → visibility
}

describe('PublishWizard ACL validation', () => {
  beforeEach(() => {
    mockPublishSkill.mockReset()
    mockPush.mockReset()
    mockPublishSkill.mockResolvedValue({ id: 'item-1' })
  })

  it('restricted에서 입력한 stale ACL은 public 전환 후 제출을 막지 않는다', async () => {
    const user = userEvent.setup()
    render(<PublishWizard resource={skillResource()} open onOpenChange={vi.fn()} />)

    await goToVisibilityStep(user)

    await user.click(screen.getByRole('combobox', { name: '能见度' }))
    await user.click(await screen.findByRole('option', { name: '受限' }))
    await user.type(screen.getByLabelText('共享用户 ID（以逗号分隔）'), 'abc')

    await user.click(screen.getByRole('combobox', { name: '能见度' }))
    await user.click(await screen.findByRole('option', { name: '公共' }))

    await user.click(screen.getByRole('button', { name: '下一步' })) // visibility → confirm
    await user.click(screen.getByRole('button', { name: '发布' }))

    await waitFor(() => expect(mockPublishSkill).toHaveBeenCalledTimes(1))
    expect(mockPublishSkill).toHaveBeenCalledWith({
      skillId: 'skill-1',
      body: expect.objectContaining({ visibility: 'public', acl_user_ids: [] }),
    })
    expect(
      screen.queryByText(/유효하지 않은 사용자 ID/),
    ).not.toBeInTheDocument()
    expect(mockPush).toHaveBeenCalledWith('/marketplace/item-1')
  })

  it('restricted 제출 시 잘못된 UUID는 전용 에러로 차단된다', async () => {
    const user = userEvent.setup()
    render(<PublishWizard resource={skillResource()} open onOpenChange={vi.fn()} />)

    await goToVisibilityStep(user)

    await user.click(screen.getByRole('combobox', { name: '能见度' }))
    await user.click(await screen.findByRole('option', { name: '受限' }))
    await user.type(screen.getByLabelText('共享用户 ID（以逗号分隔）'), 'abc')

    await user.click(screen.getByRole('button', { name: '下一步' })) // visibility → confirm
    await user.click(screen.getByRole('button', { name: '发布' }))

    expect(await screen.findByText(/유효하지 않은 사용자 ID/)).toBeInTheDocument()
    expect(mockPublishSkill).not.toHaveBeenCalled()
  })
})
