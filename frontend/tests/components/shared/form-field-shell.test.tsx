import { render, screen } from '../../test-utils'
import { Input } from '@/components/ui/input'
import { FormFieldShell } from '@/components/shared/form-field-shell'

describe('FormFieldShell', () => {
  it('associates the label with the field id', () => {
    render(
      <FormFieldShell id="agent-name" label="智能体名称">
        <Input id="agent-name" />
      </FormFieldShell>,
    )

    expect(screen.getByLabelText('智能体名称')).toBeInTheDocument()
  })

  it('renders description, required mark, and error text', () => {
    render(
      <FormFieldShell
        id="model"
        label="模型"
        description="用于生成响应的模型。"
        required
        error="请选择模型。"
      >
        <Input id="model" aria-invalid />
      </FormFieldShell>,
    )

    expect(screen.getByText('*')).toBeInTheDocument()
    expect(screen.getByText('用于生成响应的模型。')).toHaveAttribute(
      'id',
      'model-description',
    )
    expect(screen.getByText('请选择模型。')).toHaveAttribute('id', 'model-error')
  })

  it('supports inline control layout and field actions', () => {
    render(
      <>
        <FormFieldShell
          id="memory-enabled"
          label="启用内存"
          description="关闭后，智能体将不会读取记忆。"
          layout="inline"
        >
          <Input id="memory-enabled" type="checkbox" />
        </FormFieldShell>
        <FormFieldShell id="model" label="模型" actions={<button type="button">应用</button>}>
          <Input id="model" />
        </FormFieldShell>
      </>,
    )

    expect(screen.getByLabelText('启用内存')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '应用' })).toBeInTheDocument()
  })
})
