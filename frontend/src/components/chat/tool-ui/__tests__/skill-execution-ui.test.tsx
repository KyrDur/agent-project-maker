import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { ChatConversationContext } from '../../conversation-context'
import { outputFilesFromResult, skillNameFromDirectory } from '../skill-execution-ui'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

describe('skillNameFromDirectory', () => {
  it('从虚拟路径最后一个 segment 提取技能名', () => {
    expect(skillNameFromDirectory('/runtime/thread-1/agents/a1/skills/openwiki')).toBe('openwiki')
    expect(skillNameFromDirectory('skills/data-report/')).toBe('data-report')
  })

  it('没有路径或就是 skills 目录本身时为 null', () => {
    expect(skillNameFromDirectory(undefined)).toBeNull()
    expect(skillNameFromDirectory('/skills/')).toBeNull()
    expect(skillNameFromDirectory('')).toBeNull()
  })
})

describe('outputFilesFromResult', () => {
  it('从 OUTPUT_FILES 约定行中提取文件名', () => {
    expect(outputFilesFromResult('stdout...\n\nOUTPUT_FILES: report.md, chart.png')).toEqual([
      'report.md',
      'chart.png',
    ])
  })

  it('没有 OUTPUT_FILES 时为空数组', () => {
    expect(outputFilesFromResult('普通输出')).toEqual([])
    expect(outputFilesFromResult(undefined)).toEqual([])
    expect(outputFilesFromResult({ not: 'a string' })).toEqual([])
  })
})

describe('SkillExecutionToolUI render', () => {
  async function renderCard(props: {
    args: Record<string, unknown>
    result?: unknown
    statusType?: string
  }) {
    // 直接调用当前 Toolkit 中注册的实际 renderer。
    const { SkillExecutionToolUI } = await import('../skill-execution-ui')
    const renderFn = SkillExecutionToolUI as unknown as (props: unknown) => ReactNode
    // 必须在 Provider "下方" 的组件 render 过程中调用 renderFn，
    // 这样 useChatConversationId 才能读取 provider 值（如果在 Wrapper 正文中直接
    // 调用，hook 会在 provider 外部 fiber 中执行）。
    function CardUnderTest() {
      return (
        <>
          {renderFn({
            toolName: 'execute_in_skill',
            toolCallId: 'call-1',
            args: props.args,
            argsText: JSON.stringify(props.args),
            result: props.result,
            status: { type: props.statusType ?? 'complete' },
          })}
        </>
      )
    }
    return render(
      <ChatConversationContext.Provider value="conv-77">
        <CardUnderTest />
      </ChatConversationContext.Provider>,
    )
  }

  it('以技能名为标题，以文件数量为 meta 显示', async () => {
    await renderCard({
      args: {
        skill_directory: '/runtime/t/skills/data-report',
        command: 'python scripts/aggregate.py',
      },
      result: 'ok\n\nOUTPUT_FILES: out.csv',
    })
    expect(screen.getByText('data-report')).toBeInTheDocument()
    expect(screen.getByText('files(1)')).toBeInTheDocument()
  })

  it('展开后显示 command 和文件链接（API 路径）', async () => {
    const user = userEvent.setup()
    await renderCard({
      args: {
        skill_directory: '/runtime/t/skills/data-report',
        command: 'python scripts/aggregate.py',
      },
      result: 'ok\n\nOUTPUT_FILES: out.csv, chart.png',
    })
    // 有文件时默认展开 —— 链接直接可见。
    const link = screen.getByText('out.csv').closest('a')
    expect(link).not.toBeNull()
    expect(link?.getAttribute('href')).toContain('/api/conversations/conv-77/files/out.csv')
    expect(screen.getByText('python scripts/aggregate.py')).toBeInTheDocument()
    // 折叠再展开后仍保持。
    await user.click(screen.getByText('data-report'))
    expect(screen.queryByText('python scripts/aggregate.py')).not.toBeInTheDocument()
  })

  it('执行中显示 running meta，不解析文件', async () => {
    await renderCard({
      args: { skill_directory: '/runtime/t/skills/openwiki', command: 'python x.py' },
      statusType: 'running',
    })
    expect(screen.getByText('running')).toBeInTheDocument()
  })
})
