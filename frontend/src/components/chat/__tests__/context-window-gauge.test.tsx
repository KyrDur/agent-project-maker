import { describe, expect, it } from 'vitest'
import type { TokenUsageBreakdown } from '@/lib/types'
import { render, screen } from '../../../../tests/test-utils'
import { ContextWindowGauge } from '../context-window-gauge'

function usage(over: Partial<TokenUsageBreakdown>): TokenUsageBreakdown {
  return {
    prompt_tokens: 0,
    completion_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    ...over,
  }
}

describe('ContextWindowGauge', () => {
  it('占用量仅使用 prompt_tokens —— 不叠加 cache_*', () => {
    // prompt 700k + cache 300k。若叠加 cache 会变成 100%，但只算 prompt，因此是 70%。
    render(
      <ContextWindowGauge
        usage={usage({
          prompt_tokens: 700000,
          cache_creation_tokens: 200000,
          cache_read_tokens: 100000,
        })}
        contextWindow={1000000}
        modelName="claude-sonnet-4-6"
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger.textContent).toContain('70%')
    expect(trigger.textContent).not.toContain('100%')
    expect(trigger.textContent).toContain('claude-sonnet-4-6')
  })

  it('< 80%: 中性色（非警告色）', () => {
    const { container } = render(
      <ContextWindowGauge usage={usage({ prompt_tokens: 500000 })} contextWindow={1000000} />,
    )
    expect(container.querySelector('.text-status-warn')).toBeNull()
    expect(container.querySelector('.text-status-danger')).toBeNull()
  })

  it('≥ 80%: 警告色(--status-warn)', () => {
    const { container } = render(
      <ContextWindowGauge usage={usage({ prompt_tokens: 850000 })} contextWindow={1000000} />,
    )
    expect(container.querySelector('.text-status-warn')).not.toBeNull()
    expect(container.querySelector('.text-status-danger')).toBeNull()
  })

  it('≥ 95%: 危险色(--status-danger)', () => {
    const { container } = render(
      <ContextWindowGauge usage={usage({ prompt_tokens: 980000 })} contextWindow={1000000} />,
    )
    expect(container.querySelector('.text-status-danger')).not.toBeNull()
  })

  it('context_window null: 不隐藏，显示为禁用 + "没有限制"', () => {
    render(
      <ContextWindowGauge
        usage={usage({ prompt_tokens: 500000 })}
        contextWindow={null}
        modelName="scripted"
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger).toBeInTheDocument() // 不隐藏
    expect(trigger.textContent).toContain('没有限制')
    expect(trigger).toHaveAttribute('aria-label', '上下文限制未知')
    // 不显示占用率(%)文本。
    expect(trigger.textContent).not.toContain('%')
  })

  it('usage null（首轮之前）: 以 0% 空状态显示', () => {
    render(<ContextWindowGauge usage={null} contextWindow={1000000} />)
    expect(screen.getByRole('button').textContent).toContain('0%')
  })
})
