import { useState, type ReactNode } from 'react'
import { createStore, Provider } from 'jotai'

import {
  AssistantSideChatProvider,
  useAssistantSideChat,
} from '@/components/agent/assistant-side-chat-provider'
import type { AssistantPanelSession } from '@/components/agent/assistant-panel'
import type { Message } from '@/lib/types'
import { reconnectStateAtom, sessionTokenUsageAtom } from '@/lib/stores/chat-store'
import { render, screen, userEvent, waitFor } from '../../test-utils'

const testState = vi.hoisted(() => ({
  isMobile: false,
  pathname: '/agents/agent-1/settings',
  userId: 'user-1',
}))

vi.mock('next/navigation', () => ({
  usePathname: () => testState.pathname,
}))

vi.mock('@/lib/auth/session', () => ({
  useSession: () => ({ data: { id: testState.userId } }),
}))

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => testState.isMobile,
}))

vi.mock('@/components/agent/assistant-panel', async () => {
  const { useSetAtom } = await import('jotai')
  const { reconnectStateAtom, sessionTokenUsageAtom } = await import('@/lib/stores/chat-store')

  return {
    AssistantPanel: ({
      agentId,
      onClose,
      session,
    }: {
      agentId: string
      onClose?: () => void
      session: AssistantPanelSession
    }) => {
      const setReconnectState = useSetAtom(reconnectStateAtom)
      const setSessionTokenUsage = useSetAtom(sessionTokenUsageAtom)
      const simulateSideRuntimeEffect = () => {
        setReconnectState('reconnecting')
        setSessionTokenUsage({ inputTokens: 1, outputTokens: 2, cost: 3 })
      }

      return (
        <div
          data-testid="retained-assistant-panel"
          data-agent-id={agentId}
          data-message-count={session.messages.length}
          data-session-id={session.sessionId}
        >
          <button
            type="button"
            autoFocus
            onClick={() =>
              session.onMessagesCommit([
                {
                  id: `message-${session.messages.length + 1}`,
                  role: 'assistant',
                  content: 'side message',
                } as Message,
              ])
            }
          >
            commit side message
          </button>
          <button type="button" onClick={simulateSideRuntimeEffect}>
            simulate side success
          </button>
          <button type="button" onClick={simulateSideRuntimeEffect}>
            simulate side error
          </button>
          <button type="button" onClick={simulateSideRuntimeEffect}>
            simulate side cancel
          </button>
          <button type="button" onClick={onClose}>
            close side chat
          </button>
        </div>
      )
    },
  }
})

vi.mock('@/components/shared/dialog-shell', () => {
  function Root({ open, children }: { open: boolean; children: ReactNode }) {
    return open ? <div role="dialog">{children}</div> : null
  }
  const Header = ({ title }: { title: ReactNode }) => <header>{title}</header>
  const Body = ({ children }: { children: ReactNode }) => <div>{children}</div>
  return { DialogShell: Object.assign(Root, { Header, Body }) }
})

function SideChatControls() {
  const sideChat = useAssistantSideChat()
  const [mainMessages] = useState(['main message'])
  return (
    <>
      <p data-testid="main-transcript">{mainMessages.join(',')}</p>
      <button
        type="button"
        onClick={(event) =>
          sideChat.openForAgent({ agentId: 'agent-1', agentName: 'Agent One' }, event.currentTarget)
        }
      >
        open agent one
      </button>
      <button
        type="button"
        onClick={() => sideChat.openForAgent({ agentId: 'agent-2', agentName: 'Agent Two' })}
      >
        open agent two
      </button>
    </>
  )
}

function renderSideChat(mainStore = createStore()) {
  return render(
    <Provider store={mainStore}>
      <AssistantSideChatProvider>
        <SideChatControls />
      </AssistantSideChatProvider>
    </Provider>,
  )
}

describe('AssistantSideChatProvider', () => {
  beforeEach(() => {
    testState.isMobile = false
    testState.pathname = '/agents/agent-1/settings'
    testState.userId = 'user-1'
    window.requestAnimationFrame = (callback) => {
      callback(0)
      return 1
    }
  })

  it('关闭后重新打开同一智能体时，保留其独立消息和会话', async () => {
    const user = userEvent.setup()
    renderSideChat()

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    const initialPanel = screen.getByTestId('retained-assistant-panel')
    const initialSessionId = initialPanel.getAttribute('data-session-id')
    await user.click(screen.getByRole('button', { name: 'commit side message' }))
    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-message-count',
      '1',
    )

    await user.click(screen.getByRole('button', { name: 'close side chat' }))
    expect(screen.queryByTestId('assistant-side-chat')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'open agent one' }))

    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-session-id',
      initialSessionId,
    )
    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-message-count',
      '1',
    )
  })

  it('按智能体分离侧边 transcript', async () => {
    const user = userEvent.setup()
    renderSideChat()

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    await user.click(screen.getByRole('button', { name: 'commit side message' }))
    await user.click(screen.getByRole('button', { name: 'open agent two' }))
    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-agent-id',
      'agent-2',
    )
    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-message-count',
      '0',
    )

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-message-count',
      '1',
    )
  })

  it('侧边消息变更和关闭不会修改主 transcript', async () => {
    const user = userEvent.setup()
    renderSideChat()

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    await user.click(screen.getByRole('button', { name: 'commit side message' }))
    await user.click(screen.getByRole('button', { name: 'close side chat' }))

    expect(screen.getByTestId('main-transcript')).toHaveTextContent('main message')
  })

  it('侧边 runtime 的成功、错误、取消及关闭不会修改主显示 atom', async () => {
    const user = userEvent.setup()
    const mainStore = createStore()
    const mainUsage = { inputTokens: 101, outputTokens: 202, cost: 3.03 }
    mainStore.set(sessionTokenUsageAtom, mainUsage)
    mainStore.set(reconnectStateAtom, 'reconnecting')
    renderSideChat(mainStore)

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    for (const action of ['simulate side success', 'simulate side error', 'simulate side cancel']) {
      await user.click(screen.getByRole('button', { name: action }))
      expect(mainStore.get(sessionTokenUsageAtom)).toEqual(mainUsage)
      expect(mainStore.get(reconnectStateAtom)).toBe('reconnecting')
    }
    await user.click(screen.getByRole('button', { name: 'close side chat' }))

    expect(mainStore.get(sessionTokenUsageAtom)).toEqual(mainUsage)
    expect(mainStore.get(reconnectStateAtom)).toBe('reconnecting')
  })

  it('移动到其他智能体路径时关闭已打开的面板', async () => {
    const user = userEvent.setup()
    const mainStore = createStore()
    const view = renderSideChat(mainStore)

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    expect(screen.getByTestId('assistant-side-chat')).toBeInTheDocument()
    testState.pathname = '/agents/agent-2/settings'
    view.rerender(
      <Provider store={mainStore}>
        <AssistantSideChatProvider>
          <SideChatControls />
        </AssistantSideChatProvider>
      </Provider>,
    )

    await waitFor(() => expect(screen.queryByTestId('assistant-side-chat')).not.toBeInTheDocument())
  })

  it('用户变化时清空保存的侧边会话', async () => {
    const user = userEvent.setup()
    const mainStore = createStore()
    const view = renderSideChat(mainStore)

    await user.click(screen.getByRole('button', { name: 'open agent one' }))
    const firstSessionId = screen
      .getByTestId('retained-assistant-panel')
      .getAttribute('data-session-id')
    await user.click(screen.getByRole('button', { name: 'commit side message' }))

    testState.userId = 'user-2'
    view.rerender(
      <Provider store={mainStore}>
        <AssistantSideChatProvider>
          <SideChatControls />
        </AssistantSideChatProvider>
      </Provider>,
    )
    await user.click(screen.getByRole('button', { name: 'open agent one' }))

    expect(screen.getByTestId('retained-assistant-panel')).toHaveAttribute(
      'data-message-count',
      '0',
    )
    expect(screen.getByTestId('retained-assistant-panel')).not.toHaveAttribute(
      'data-session-id',
      firstSessionId,
    )
  })

  it('在移动端 dialog 中聚焦 composer 后关闭时，将焦点返回 trigger', async () => {
    testState.isMobile = true
    const user = userEvent.setup()
    renderSideChat()
    const trigger = screen.getByRole('button', { name: 'open agent one' })

    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'commit side message' })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'close side chat' }))

    expect(trigger).toHaveFocus()
  })
})
