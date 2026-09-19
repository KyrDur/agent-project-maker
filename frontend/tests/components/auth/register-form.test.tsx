import { render, screen, userEvent, waitFor } from '../../test-utils'
import { RegisterForm } from '@/components/auth/RegisterForm'

describe('RegisterForm', () => {
  it('submits display_name instead of asking for a legal name', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<RegisterForm onSubmit={onSubmit} isLoading={false} error={null} />)

    await userEvent.type(screen.getByLabelText('显示名称'), '用户')
    await userEvent.type(screen.getByLabelText('电子邮件'), 'chester@example.com')
    await userEvent.type(screen.getByLabelText('密码'), 'correct horse')
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: '创建帐户' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        display_name: '用户',
        email: 'chester@example.com',
        password: 'correct horse',
      })
    })
    expect(screen.getByText('您无需输入您的法定姓名。')).toBeInTheDocument()
  })
})
