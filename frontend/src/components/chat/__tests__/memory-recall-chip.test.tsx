import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider as JotaiProvider, createStore } from 'jotai'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRecallChip } from '../memory-recall-chip'
import { ChatConversationContext } from '../conversation-context'
import { chatMemoryRecallAtom } from '@/lib/stores/chat-memory-recall'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

const memoriesQueryMock = vi.hoisted(() => ({ current: { data: undefined as unknown } }))

vi.mock('@/lib/hooks/use-memory', () => ({
  useMemories: () => memoriesQueryMock.current,
}))

function renderChip(store = createStore(), conversationId: string | null = 'conv-1') {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <JotaiProvider store={store}>
        <ChatConversationContext.Provider value={conversationId}>
          {children}
        </ChatConversationContext.Provider>
      </JotaiProvider>
    )
  }
  return render(<MemoryRecallChip />, { wrapper: Wrapper })
}

describe('MemoryRecallChip', () => {
  it('没有回忆时不渲染', () => {
    const { container } = renderChip()
    expect(container.querySelector('[data-moldy-memory-recall]')).toBeNull()
  })

  it('不渲染其他对话的回忆（对话 scope）', () => {
    const store = createStore()
    store.set(chatMemoryRecallAtom, {
      'conv-OTHER': [{ id: 'm1', scope: 'user', content: '其他对话的记忆' }],
    })
    const { container } = renderChip(store)
    expect(container.querySelector('[data-moldy-memory-recall]')).toBeNull()
  })

  it('reload(redacted) brief 会通过 Memory API join 恢复内容', async () => {
    const user = userEvent.setup()
    memoriesQueryMock.current = {
      data: [{ id: 'm1', scope: 'user', content: '偏好使用中文回答' }],
    }
    const store = createStore()
    store.set(chatMemoryRecallAtom, {
      'conv-1': [
        { id: 'm1', scope: 'user', content: '<redacted>' },
        { id: 'm-deleted', scope: 'agent', content: '<redacted>' },
      ],
    })
    renderChip(store)
    await user.click(screen.getByText('title'))
    // join 成功 → 恢复原文。已删除的记忆 fallback 到 hiddenContent。
    expect(screen.getByText('偏好使用中文回答')).toBeInTheDocument()
    expect(screen.getByText('hiddenContent')).toBeInTheDocument()
    expect(screen.queryByText('<redacted>')).not.toBeInTheDocument()
  })

  it('显示回忆数量 meta，展开后显示 scope badge + 内容', async () => {
    const user = userEvent.setup()
    const store = createStore()
    store.set(chatMemoryRecallAtom, {
      'conv-1': [
        { id: 'm1', scope: 'user', content: '偏好使用中文回答' },
        { id: 'm2', scope: 'agent', content: '报告整理成表格' },
      ],
    })
    renderChip(store)
    expect(screen.getByText('count(2)')).toBeInTheDocument()
    // 默认折叠状态。
    expect(screen.queryByText('偏好使用中文回答')).not.toBeInTheDocument()
    await user.click(screen.getByText('title'))
    expect(screen.getByText('偏好使用中文回答')).toBeInTheDocument()
    expect(screen.getByText('scopeUser')).toBeInTheDocument()
    expect(screen.getByText('scopeAgent')).toBeInTheDocument()
  })
})
