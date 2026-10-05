import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider as JotaiProvider, createStore } from 'jotai'
import { describe, expect, it, vi } from 'vitest'
import type { SubagentDiscoverySnapshot } from '@langchain/react'
import type { ReactNode } from 'react'
import { SubagentTeamStrip } from '../subagent-team-strip'
import { ChatConversationContext } from '../conversation-context'
import { chatRightRailAtom } from '@/lib/stores/chat-right-rail'
import { chatSubagentNamesAtom } from '@/lib/stores/chat-subagent-names'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

const snapshotsMock = vi.hoisted(() => ({ current: [] as readonly SubagentDiscoverySnapshot[] }))

vi.mock('@/lib/chat/langgraph-runtime/subagent-runtime', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/lib/chat/langgraph-runtime/subagent-runtime')>()
  return {
    ...actual,
    useSubagentSnapshots: () => snapshotsMock.current,
  }
})

function snapshot(overrides: Partial<SubagentDiscoverySnapshot>): SubagentDiscoverySnapshot {
  return {
    id: 'call-1',
    name: 'agent_ab12cd34',
    namespace: ['task:1'],
    parentId: null,
    depth: 0,
    status: 'running',
    taskInput: '帮我调研',
    output: undefined,
    error: undefined,
    startedAt: new Date('2026-07-04T00:00:00Z'),
    completedAt: null,
    ...overrides,
  } as SubagentDiscoverySnapshot
}

function renderStrip(store = createStore(), conversationId: string | null = 'conv-1') {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <JotaiProvider store={store}>
        <ChatConversationContext.Provider value={conversationId}>
          {children}
        </ChatConversationContext.Provider>
      </JotaiProvider>
    )
  }
  return render(<SubagentTeamStrip />, { wrapper: Wrapper })
}

describe('SubagentTeamStrip', () => {
  it('没有快照时不渲染', () => {
    snapshotsMock.current = []
    const { container } = renderStrip()
    expect(container.querySelector('[data-moldy-team-strip]')).toBeNull()
  })

  it('将子 Agent chip 与状态 dot 一起渲染，并显示进度 meta', () => {
    snapshotsMock.current = [
      snapshot({ id: 'c1', name: 'agent_a', status: 'running' }),
      snapshot({ id: 'c2', name: 'agent_b', status: 'complete', completedAt: new Date() }),
    ]
    renderStrip()
    expect(screen.getByText('agent_a')).toBeInTheDocument()
    expect(screen.getByText('agent_b')).toBeInTheDocument()
    // 有进行中项时优先 runningMeta。
    expect(screen.getByText('runningMeta(1)')).toBeInTheDocument()
    expect(document.querySelector('[data-moldy-team-chip="running"]')).not.toBeNull()
    expect(document.querySelector('[data-moldy-team-chip="complete"]')).not.toBeNull()
  })

  it('全部结束后显示 done/total meta', () => {
    snapshotsMock.current = [
      snapshot({ id: 'c1', status: 'complete' }),
      snapshot({ id: 'c2', status: 'error', error: 'boom' }),
    ]
    renderStrip()
    expect(screen.getByText('doneMeta(2/2)')).toBeInTheDocument()
  })

  it('有显示名 map 时，将 runtime_name 替换为 display_name', () => {
    snapshotsMock.current = [snapshot({ id: 'c1', name: 'agent_ab12cd34' })]
    const store = createStore()
    store.set(chatSubagentNamesAtom, { 'conv-1': { agent_ab12cd34: '调研员' } })
    renderStrip(store)
    expect(screen.getByText('调研员')).toBeInTheDocument()
    expect(screen.queryByText('agent_ab12cd34')).not.toBeInTheDocument()
  })

  it('点击 chip 时打开右侧 rail 的 subagent 面板', async () => {
    const user = userEvent.setup()
    snapshotsMock.current = [snapshot({ id: 'call-9', name: 'agent_x', taskInput: '任务输入' })]
    const store = createStore()
    renderStrip(store)
    await user.click(screen.getByText('agent_x'))
    expect(store.get(chatRightRailAtom)).toEqual({
      mode: 'subagent',
      subagent: {
        conversationId: 'conv-1',
        toolCallId: 'call-9',
        agentName: 'agent_x',
        input: '任务输入',
      },
    })
  })

  it('只有子级的子级(depth≥2)才加 ↳ 标记 —— 直接委派(depth 1)不加标记', () => {
    snapshotsMock.current = [
      snapshot({ id: 'c1', name: 'agent_parent', depth: 1 }),
      snapshot({ id: 'c2', name: 'agent_child', parentId: 'c1', depth: 2 }),
    ]
    renderStrip()
    expect(screen.getAllByText('↳')).toHaveLength(1)
  })
})
