import { useState } from 'react'
import { render, screen, userEvent } from '../test-utils'
import {
  RuntimePolicySettings,
  type RuntimePolicySettingsProps,
} from '@/components/agent/runtime-policy-settings'
import type { RuntimePolicyV1 } from '@/lib/types/runtime-policy'

const DEFAULT_PROPS: RuntimePolicySettingsProps = {
  value: null,
  onValueChange: vi.fn(),
  contextWindow: 128_000,
  surface: 'existing-agent',
}

function ControlledRuntimePolicySettings(
  props: Omit<RuntimePolicySettingsProps, 'value' | 'onValueChange'> & {
    readonly initialValue?: RuntimePolicyV1 | null
  },
) {
  const [value, setValue] = useState<RuntimePolicyV1 | null>(props.initialValue ?? null)

  return <RuntimePolicySettings {...props} value={value} onValueChange={setValue} />
}

describe('RuntimePolicySettings', () => {
  it('creates the exact v1 custom policy from the recommended state', async () => {
    const user = userEvent.setup()
    const onValueChange = vi.fn()

    render(<RuntimePolicySettings {...DEFAULT_PROPS} onValueChange={onValueChange} />)

    await user.click(screen.getByRole('button', { name: '自定义设置' }))

    expect(onValueChange).toHaveBeenCalledWith({
      version: 1,
      filesystem: { mode: 'artifact_write' },
      todo: { enabled: true },
      summarization: { mode: 'auto' },
    })
  })

  it('resets a custom policy to the recommended state', async () => {
    const user = userEvent.setup()
    const onValueChange = vi.fn()

    render(
      <RuntimePolicySettings
        {...DEFAULT_PROPS}
        onValueChange={onValueChange}
        value={{
          version: 1,
          filesystem: { mode: 'inspect' },
          todo: { enabled: false },
          summarization: { mode: 'auto' },
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '使用推荐设置' }))

    expect(onValueChange).toHaveBeenCalledWith(null)
  })

  it('keeps an existing custom policy when custom is already selected', async () => {
    const user = userEvent.setup()
    const onValueChange = vi.fn()

    render(
      <RuntimePolicySettings
        {...DEFAULT_PROPS}
        onValueChange={onValueChange}
        value={{
          version: 1,
          filesystem: { mode: 'inspect' },
          todo: { enabled: false },
          summarization: { mode: 'preset', preset: 'balanced_context_v1' },
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '自定义设置' }))

    expect(onValueChange).not.toHaveBeenCalled()
  })

  it('updates custom filesystem, todo, and summarization controls', async () => {
    const user = userEvent.setup()

    render(<ControlledRuntimePolicySettings {...DEFAULT_PROPS} />)

    await user.click(screen.getByRole('button', { name: '自定义设置' }))
    await user.click(screen.getByRole('button', { name: '仅供审核' }))
    await user.click(screen.getByRole('switch', { name: '使用任务列表' }))
    await user.click(screen.getByRole('button', { name: '平衡' }))

    expect(screen.getByRole('button', { name: '仅供审核' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('switch', { name: '使用任务列表' })).toHaveAttribute(
      'aria-checked',
      'false',
    )
    expect(screen.getByRole('button', { name: '平衡' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('groups each mutually exclusive runtime choice under its visible purpose', async () => {
    const user = userEvent.setup()

    render(<ControlledRuntimePolicySettings {...DEFAULT_PROPS} />)

    expect(screen.getByRole('group', { name: '运行时行为模式' })).toContainElement(
      screen.getByRole('button', { name: '使用推荐设置' }),
    )

    await user.click(screen.getByRole('button', { name: '自定义设置' }))

    expect(screen.getByRole('group', { name: '档案工作' })).toContainElement(
      screen.getByRole('button', { name: '仅供审核' }),
    )
    expect(screen.getByRole('group', { name: '长对话上下文' })).toContainElement(
      screen.getByRole('button', { name: '汽车' }),
    )
  })

  it('disables balanced summarization without a positive context window', async () => {
    const user = userEvent.setup()

    render(<ControlledRuntimePolicySettings {...DEFAULT_PROPS} contextWindow={null} />)

    await user.click(screen.getByRole('button', { name: '自定义设置' }))

    expect(screen.getByRole('button', { name: '平衡' })).toBeDisabled()
    expect(
      screen.getByText('平衡模式需要所选模型的上下文长度信息。'),
    ).toBeInTheDocument()
  })

  it('warns about an already invalid balanced policy without replacing it', () => {
    const onValueChange = vi.fn()

    render(
      <RuntimePolicySettings
        {...DEFAULT_PROPS}
        contextWindow={0}
        onValueChange={onValueChange}
        value={{
          version: 1,
          filesystem: { mode: 'artifact_write' },
          todo: { enabled: true },
          summarization: { mode: 'preset', preset: 'balanced_context_v1' },
        }}
      />,
    )

    expect(screen.getByRole('button', { name: '平衡' })).toBeDisabled()
    expect(
      screen.getByText(
        '当前的选择不适用于该模型。更改模型或切换为自动。',
      ),
    ).toBeInTheDocument()
    expect(onValueChange).not.toHaveBeenCalled()
  })

  it('uses a closed advanced presentation only for manual creation', async () => {
    const user = userEvent.setup()

    render(<RuntimePolicySettings {...DEFAULT_PROPS} surface="new-agent" collapsible />)

    expect(screen.getByRole('button', { name: '自定义设置' })).not.toBeVisible()
    await user.click(screen.getByText('高级运行时设置'))
    expect(screen.getByRole('button', { name: '自定义设置' })).toBeInTheDocument()
    expect(screen.getByText('该设置适用于新对话。')).toBeInTheDocument()
  })

  it('labels the source without exposing internal runtime provenance', () => {
    render(<RuntimePolicySettings {...DEFAULT_PROPS} />)

    expect(screen.getByText('推荐设置')).toBeInTheDocument()
    expect(
      screen.getByText(
        '这不会影响已经运行的对话。更新的设置适用于尚未运行的对话和新对话。',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/legacy_compat|stored/i)).not.toBeInTheDocument()
  })
})
