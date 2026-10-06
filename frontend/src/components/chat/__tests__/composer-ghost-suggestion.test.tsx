import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ComposerGhostSuggestion } from '../composer-ghost-suggestion'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

describe('ComposerGhostSuggestion', () => {
  it('以浅色显示建议文本和 → 键帽提示', () => {
    render(<ComposerGhostSuggestion text="把刚才的回答整理成表格" onAccept={() => {}} />)
    expect(screen.getByText('把刚才的回答整理成表格')).toBeInTheDocument()
    expect(screen.getByText('hint')).toBeInTheDocument()
    expect(document.querySelector('[data-moldy-followup-ghost]')).not.toBeNull()
  })

  it('点击文本时调用接受回调（触屏 fallback）', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn()
    render(<ComposerGhostSuggestion text="帮我整理成表格" onAccept={onAccept} />)
    await user.click(screen.getByText('帮我整理成表格'))
    expect(onAccept).toHaveBeenCalledTimes(1)
  })
})
