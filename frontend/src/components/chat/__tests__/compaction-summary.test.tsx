import { describe, expect, it } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'
import { CompactionSummary } from '../compaction-summary'

describe('CompactionSummary', () => {
  it('只显示摘要文案，不提供查看原文或复制操作', () => {
    render(<CompactionSummary />)

    expect(screen.getByText('对较旧的消息进行了总结以释放上下文')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '查看原文' })).not.toBeInTheDocument()
  })
})
