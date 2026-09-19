import { fireEvent } from '@testing-library/react'
import { render, screen, userEvent, waitFor } from '../../test-utils'
import { ScheduleForm } from '@/features/schedules/components/schedule-form'

vi.mock('@/lib/hooks/use-conversations', () => ({
  useConversations: () => ({
    data: [
      {
        id: 'conv-1',
        title: '주말 여행 상담',
        updated_at: '2026-05-30T03:00:00Z',
        unread_count: 0,
      },
      {
        id: 'conv-2',
        title: null,
        updated_at: '2026-05-29T03:00:00Z',
        unread_count: 2,
      },
    ],
  }),
}))

describe('ScheduleForm', () => {
  it('creates a one-time schedule request', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ScheduleForm onSubmit={onSubmit} onCancel={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '一次' }))
    await user.type(screen.getByPlaceholderText('名称'), '한 번만 실행')
    await user.type(
      screen.getByPlaceholderText('提示'),
      '테스트 메시지',
    )
    fireEvent.change(screen.getByLabelText('预定于'), {
      target: { value: '2030-01-02T09:30' },
    })
    await user.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: '한 번만 실행',
        trigger_type: 'one_time',
        schedule_config: {
          scheduled_at: new Date('2030-01-02T09:30').toISOString(),
        },
        input_message: '테스트 메시지',
        timezone: 'Asia/Seoul',
        conversation_policy: 'schedule_thread',
      }),
    )
  })

  it('selects an existing conversation by title instead of requiring a raw id', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ScheduleForm agentId="agent-1" onSubmit={onSubmit} onCancel={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '保存到现有对话' }))

    expect(screen.queryByPlaceholderText('对话ID')).not.toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: '对话' }))
    await user.click(screen.getByRole('option', { name: /주말 여행 상담/ }))
    await user.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        conversation_policy: 'selected_conversation',
        target_conversation_id: 'conv-1',
      }),
    )
  })

  it('can return max run and auto-pause limits back to unlimited', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ScheduleForm onSubmit={onSubmit} onCancel={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '麦克斯跑有限公司' }))
    await user.clear(screen.getByLabelText('最大运行值'))
    await user.type(screen.getByLabelText('最大运行值'), '3')
    await user.click(screen.getByRole('button', { name: '最大运行次数无限制' }))

    await user.click(screen.getByRole('button', { name: '自动暂停已启用' }))
    await user.clear(screen.getByLabelText('自动暂停值'))
    await user.type(screen.getByLabelText('自动暂停值'), '2')
    await user.click(screen.getByRole('button', { name: '自动暂停已禁用' }))

    await user.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        max_runs: null,
        auto_pause_after_failures: null,
      }),
    )
  })
})
