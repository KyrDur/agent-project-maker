import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MissionControlBar } from '../mission-control-bar'
import type { DeepAgentTodo } from '@/lib/chat/langgraph-runtime/deepagents-state'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

const TODOS: readonly DeepAgentTodo[] = [
  { id: 't1', content: '调查仓库结构', status: 'completed' },
  { id: 't2', content: '编写 quickstart.md', status: 'in_progress' },
  { id: 't3', content: '发布 wiki', status: 'pending' },
]

describe('MissionControlBar', () => {
  it('没有 todos 时不渲染', () => {
    const { container } = render(<MissionControlBar todos={[]} />)
    expect(container.querySelector('[data-moldy-mission-control]')).toBeNull()
  })

  it('折叠状态下显示进度摘要(done/total)', () => {
    render(<MissionControlBar todos={TODOS} />)
    expect(screen.getByText(/tasks\.progress\(1\/3\).*tasks\.current/)).toBeInTheDocument()
    expect(screen.getByText('tasks.title')).toHaveClass('shrink-0')
    // 默认折叠状态 —— 不显示单个 todo 行。
    expect(screen.queryByText('编写 quickstart.md')).not.toBeInTheDocument()
  })

  it('展开后按模型原计划顺序显示 todo 行', async () => {
    const user = userEvent.setup()
    render(<MissionControlBar todos={TODOS} />)
    await user.click(screen.getByText('tasks.title'))
    const items = screen.getAllByRole('listitem').map((li) => li.textContent ?? '')
    expect(items[0]).toContain('调查仓库结构')
    expect(items[1]).toContain('编写 quickstart.md')
    expect(items[2]).toContain('发布 wiki')
  })

  it('所有 todo 完成后仍保留摘要', () => {
    render(
      <MissionControlBar
        todos={TODOS.map((todo) => ({ ...todo, status: 'completed' as const }))}
      />,
    )
    expect(screen.getByText('tasks.progress(3/3)')).toBeInTheDocument()
  })
})
