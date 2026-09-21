import { describe, expect, it } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'
import { CompactionSummary } from '../compaction-summary'

describe('CompactionSummary', () => {
  it('요약 문구만 보이고 원본 보기나 복사 동작은 제공하지 않는다', () => {
    render(<CompactionSummary />)

    expect(screen.getByText('对较旧的消息进行了总结以释放上下文')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '원본 보기' })).not.toBeInTheDocument()
  })
})
