import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatEmptyState } from '../chat-empty-state'
import type { Agent, Template } from '@/lib/types'

const setText = vi.fn()

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

vi.mock('@assistant-ui/react', () => ({
  useAui: () => ({ optional: { composer: { setText } } }),
}))

vi.mock('@/components/agent/agent-avatar', () => ({
  AgentAvatar: ({ name }: { name: string }) => <span data-testid="avatar">{name}</span>,
}))

const useTemplatesMock = vi.fn()
vi.mock('@/lib/hooks/use-templates', () => ({
  useTemplates: (...args: unknown[]) => useTemplatesMock(...args),
}))

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    name: '文档化智能体',
    description: null,
    system_prompt: 'p',
    status: 'active',
    is_favorite: false,
    image_url: null,
    opener_questions: null,
    template_id: null,
    tools: [],
    mcp_tools: [],
    skills: [],
    sub_agents: [],
    created_at: '2026-07-04T00:00:00Z',
    updated_at: '2026-07-04T00:00:00Z',
    ...overrides,
  } as unknown as Agent
}

const OPENWIKI_TEMPLATE = {
  id: 'tpl-1',
  usage_example: '帮我为 openwiki 仓库创建 wiki',
} as unknown as Template

beforeEach(() => {
  setText.mockClear()
  useTemplatesMock.mockReset()
  useTemplatesMock.mockReturnValue({ data: undefined })
})

describe('ChatEmptyState', () => {
  it('始终显示技能/工具/MCP 能力 chip', () => {
    const agent = makeAgent({
      skills: [{ id: 's1', name: 'openwiki' }],
      tools: [{ id: 't1', name: 'Web Search' }],
      mcp_tools: [{ id: 'm1', name: 'notion_search', server_id: 'sv', server_name: 'Notion' }],
    } as Partial<Agent>)
    render(<ChatEmptyState agent={agent} fallback="开始对话吧" />)
    const chips = screen.getByText('openwiki').closest('[data-moldy-empty-capabilities]')
    expect(chips).not.toBeNull()
    expect(screen.getByText('emptyState.canDo')).toBeInTheDocument()
    expect(screen.getByText('Web Search')).toBeInTheDocument()
    expect(screen.getByText('notion_search')).toBeInTheDocument()
  })

  it('能力超过 6 个时折叠为 +N chip', () => {
    const agent = makeAgent({
      tools: Array.from({ length: 8 }, (_, i) => ({ id: `t${i}`, name: `工具 ${i}` })),
    } as Partial<Agent>)
    render(<ChatEmptyState agent={agent} fallback="来自" />)
    expect(screen.getByText('emptyState.moreCapabilities(2)')).toBeInTheDocument()
    expect(screen.queryByText('工具 7')).not.toBeInTheDocument()
  })

  it('有 opener 时不查询模板，使用 opener starter', () => {
    const agent = makeAgent({
      opener_questions: ['告诉我今天的日程'],
      template_id: 'tpl-1',
    } as Partial<Agent>)
    render(<ChatEmptyState agent={agent} fallback="来自" />)
    expect(screen.getByText('告诉我今天的日程')).toBeInTheDocument()
    expect(useTemplatesMock).toHaveBeenCalledWith(undefined, { enabled: false })
  })

  it('没有 opener 时回退到模板 usage_example 作为 starter，点击后填入 composer', async () => {
    const user = userEvent.setup()
    useTemplatesMock.mockReturnValue({ data: [OPENWIKI_TEMPLATE] })
    const agent = makeAgent({ template_id: 'tpl-1' } as Partial<Agent>)
    render(<ChatEmptyState agent={agent} fallback="来自" />)
    const starter = screen.getByText('帮我为 openwiki 仓库创建 wiki')
    expect(useTemplatesMock).toHaveBeenCalledWith(undefined, { enabled: true })
    await user.click(starter)
    expect(setText).toHaveBeenCalledWith('帮我为 openwiki 仓库创建 wiki')
  })

  it('opener 和模板都没有时，不显示 starter', () => {
    render(<ChatEmptyState agent={makeAgent()} fallback="来自" />)
    expect(document.querySelector('[data-moldy-empty-starters]')).toBeNull()
  })
})
