import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { HiTLContext } from '@/lib/chat/hitl-context'
import { PlanToolUI } from '../plan-tool-ui'
import { UserInputUI } from '../user-input-ui'

// M8-4 regression：流式中 tool-call args 会以部分 JSON 到达 —— 数组字段
// 即使处于字符串/对象片段状态也会触发 render；若无 guard，真实 LLM 路径中会发生
// render crash（触发 error boundary，整个聊天挂掉）。scripted 模型只输出完整
// args，因此无法复现该 crash（在真实 LLM tour 中发现）。

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

type ToolUiRender = {
  render: (props: {
    args: Record<string, unknown>
    result?: unknown
    status: { type: string }
  }) => ReactNode
}

const renderPlan = PlanToolUI as unknown as ToolUiRender['render']
const renderUserInput = UserInputUI as unknown as ToolUiRender['render']

describe('部分流式 args 防护 (M8-4)', () => {
  it('write_todos: 即使 todos 是字符串片段，也能无 crash 渲染', () => {
    expect(() =>
      render(
        <>{renderPlan({ args: { todos: '从会议记录中提取' }, status: { type: 'running' } })}</>,
      ),
    ).not.toThrow()
  })

  it('write_todos: item.status 为部分字符串时 fallback 到 pending', () => {
    expect(() =>
      render(
        <>
          {renderPlan({
            args: { todos: [{ content: '编写草稿', status: 'in_prog' }] },
            status: { type: 'running' },
          })}
        </>,
      ),
    ).not.toThrow()
  })

  it('write_todos: 过滤掉没有 content 的片段 item', () => {
    expect(() =>
      render(
        <>
          {renderPlan({
            args: { todos: [{}, { content: '执行验证' }] },
            status: { type: 'running' },
          })}
        </>,
      ),
    ).not.toThrow()
  })

  it('write_todos: historical plan details start collapsed', () => {
    render(
      <>
        {renderPlan({
          args: { todos: [{ content: '编写草稿', status: 'in_progress' }] },
          status: { type: 'complete' },
        })}
      </>,
    )

    expect(screen.queryByText('编写草稿')).toBeNull()
    expect(screen.getByRole('button', { name: 'Expand' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('ask_user: 即使 questions/options 是字符串片段，也能无 crash 渲染', () => {
    const hitl = { onResumeDecisions: vi.fn(), registerDecision: vi.fn() }
    // render fn 会直接调用 hook，因此包成组件，在 React render 阶段执行。
    function AskUserUnderTest() {
      return (
        <>
          {renderUserInput({
            args: { questions: '什么格式', options: '表格' },
            status: { type: 'running' },
          })}
        </>
      )
    }
    expect(() =>
      render(
        <HiTLContext.Provider value={hitl}>
          <AskUserUnderTest />
        </HiTLContext.Provider>,
      ),
    ).not.toThrow()
  })
})
