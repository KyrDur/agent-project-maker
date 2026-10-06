import { render, screen } from '../../test-utils'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'

describe('SettingsSectionCard', () => {
  it('renders title, description, actions, and body', () => {
    render(
      <SettingsSectionCard
        title="配置模型"
        description="管理默认模型和凭证。"
        actions={<button type="button">保存</button>}
      >
        <div>section body</div>
      </SettingsSectionCard>,
    )

    expect(screen.getByRole('heading', { name: '配置模型' })).toBeInTheDocument()
    expect(screen.getByText('管理默认模型和凭证。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument()
    expect(screen.getByText('section body')).toBeInTheDocument()
  })

  it('keeps actions optional', () => {
    render(
      <SettingsSectionCard title="安全性">
        <div>body</div>
      </SettingsSectionCard>,
    )

    expect(screen.getByRole('heading', { name: '安全性' })).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
