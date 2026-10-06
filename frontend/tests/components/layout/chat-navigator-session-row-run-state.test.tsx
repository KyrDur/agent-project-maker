import { render, screen } from '../../test-utils'
import { Provider, createStore } from 'jotai'
import { ChatNavigatorSessionRow } from '@/components/layout/chat-navigator-session-row'
import type { ConversationRowActions } from '@/components/chat/use-conversation-row-actions'
import { conversationRuntimeStatusAtom } from '@/lib/stores/chat-navigator-store'
import type { Conversation, ConversationRun } from '@/lib/types'
import { mockConversation } from '../../mocks/fixtures'

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode
    href: string
    [key: string]: unknown
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

function createRowActions(): ConversationRowActions {
  return {
    isDeleting: false,
    dialogs: null,
    openRenameDialog: vi.fn(),
    openShareDialog: vi.fn(),
    requestDelete: vi.fn(),
    togglePin: vi.fn(),
  }
}

function run(conversationId: string, status: ConversationRun['status']): ConversationRun {
  return {
    id: `run-${status}`,
    conversation_id: conversationId,
    agent_id: 'agent-1',
    parent_run_id: null,
    status,
    source: 'chat',
    worker_instance_id: null,
    interrupt_id: null,
    last_event_id: null,
    input_preview: null,
    error_code: null,
    error_message: null,
    cancel_requested_at: null,
    started_at: null,
    heartbeat_at: null,
    completed_at: null,
    created_at: '2026-06-11T00:00:00.000Z',
    updated_at: '2026-06-11T00:00:00.000Z',
  }
}

function conversation(
  id: string,
  title: string,
  status: ConversationRun['status'] | null,
): Conversation {
  return {
    ...mockConversation,
    id,
    title,
    active_run: status ? run(id, status) : null,
  }
}

describe('ChatNavigatorSessionRow run 状态显示', () => {
  it('仅 active run 显示 spinner，interrupted run 显示需要确认标记', () => {
    render(
      <>
        <ChatNavigatorSessionRow
          conversation={conversation('conversation-running', 'Running session', 'running')}
          active={false}
          actions={createRowActions()}
        />
        <ChatNavigatorSessionRow
          conversation={conversation('conversation-interrupted', 'Needs action', 'interrupted')}
          active={false}
          actions={createRowActions()}
        />
        <ChatNavigatorSessionRow
          conversation={conversation('conversation-completed', 'Done session', 'completed')}
          active={false}
          actions={createRowActions()}
        />
      </>,
    )

    expect(screen.getByText('Running session')).toBeInTheDocument()
    expect(screen.getByLabelText('生成答案')).toHaveAttribute(
      'data-moldy-run-spinner',
      'conversation-running',
    )

    expect(screen.getByText('Needs action')).toBeInTheDocument()
    expect(screen.getByLabelText('需要用户操作')).toHaveAttribute(
      'data-moldy-run-attention',
      'conversation-interrupted',
    )

    expect(screen.getByText('Done session')).toBeInTheDocument()
    expect(screen.queryAllByLabelText('生成答案')).toHaveLength(1)
    expect(screen.queryAllByLabelText('需要用户操作')).toHaveLength(1)
  })

  it('即使没有 active_run，只要同一标签页的流式覆盖层(atom)为 running，也显示 spinner', () => {
    const store = createStore()
    store.set(conversationRuntimeStatusAtom, { 'conversation-local': 'running' })

    render(
      <Provider store={store}>
        <ChatNavigatorSessionRow
          conversation={conversation('conversation-local', 'Local stream', null)}
          active={false}
          actions={createRowActions()}
        />
      </Provider>,
    )

    expect(screen.getByLabelText('生成答案')).toHaveAttribute(
      'data-moldy-run-spinner',
      'conversation-local',
    )
  })
})
