import { describe, expect, it } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'
import { SubagentProgress } from '../subagent-progress'

describe('SubagentProgress', () => {
  it('renders nothing when no subagents are discovered', () => {
    const { container } = render(
      <SubagentProgress summary={{ total: 0, running: 0, completed: 0, failed: 0 }} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('shows completed, running, and failed counts', () => {
    render(<SubagentProgress summary={{ total: 4, running: 1, completed: 2, failed: 1 }} />)

    expect(screen.getByText('3/4 个子智能体已完成')).toBeInTheDocument()
    expect(screen.getByText('1 运行中')).toBeInTheDocument()
    expect(screen.getByText('1 失败')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: '子智能体进度' })).toHaveAttribute('value', '3')
  })
})
