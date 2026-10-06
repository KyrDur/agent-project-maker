import { render, screen, waitFor, userEvent } from '../../test-utils'
import { act, fireEvent } from '@testing-library/react'
import { Provider, createStore } from 'jotai'
import { ChatNavigator } from '@/components/layout/chat-navigator'
import {
  ChatNavigatorAgentGroup,
  agentSessionScope,
} from '@/components/layout/chat-navigator-agent-group'
import { ChatNavigatorSessionRow } from '@/components/layout/chat-navigator-session-row'
import { formatShortcutLabel } from '@/components/layout/use-chat-navigator-shortcuts'
import type { ConversationRowActions } from '@/components/chat/use-conversation-row-actions'
import { replaceChatRouteWithoutRemount } from '@/lib/chat/chat-route-replacement'
import { shortcutPreviewActiveAtom } from '@/lib/stores/chat-navigator-store'
import {
  mockAgentSummaryList,
  mockConversation,
  mockConversationPage,
  mockGlobalConversationPage,
} from '../../mocks/fixtures'

const conversationHookMocks = vi.hoisted(() => ({
  invalidateConversationNavigators: vi.fn(),
  useConversationPages: vi.fn(),
  useGlobalConversationPages: vi.fn(),
}))

const routerMocks = vi.hoisted(() => ({
  pathname: '/agents/agent-1/conversations/new',
  push: vi.fn(),
}))

const sidebarMocks = vi.hoisted(() => {
  const setOpen = vi.fn()
  const toggleSidebar = vi.fn()
  const useSidebar = vi.fn(() => ({
    isMobile: false,
    open: true,
    openMobile: false,
    setOpen,
    setOpenMobile: vi.fn(),
    setSidebarWidth: vi.fn(),
    sidebarWidth: 256,
    state: 'expanded',
    toggleSidebar,
  }))

  return { setOpen, toggleSidebar, useSidebar }
})

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

vi.mock('next/navigation', () => ({
  usePathname: () => routerMocks.pathname,
  useRouter: () => ({ push: routerMocks.push }),
}))

vi.mock('@/lib/hooks/use-agents', () => ({
  useAgentSummaries: () => ({ data: mockAgentSummaryList, isLoading: false }),
}))

vi.mock('@/lib/hooks/use-conversations', () => ({
  invalidateConversationNavigators: conversationHookMocks.invalidateConversationNavigators,
  useConversationPages: conversationHookMocks.useConversationPages,
  useGlobalConversationPages: conversationHookMocks.useGlobalConversationPages,
}))

vi.mock('@/components/chat/use-conversation-row-actions', () => ({
  useConversationRowActions: () => ({
    isDeleting: false,
    dialogs: null,
    openRenameDialog: vi.fn(),
    openShareDialog: vi.fn(),
    requestDelete: vi.fn(),
    togglePin: vi.fn(),
  }),
}))

vi.mock('@/components/ui/sidebar', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/ui/sidebar')>()
  return {
    ...actual,
    useSidebar: () => sidebarMocks.useSidebar(),
  }
})

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

describe('ChatNavigator', () => {
  beforeEach(() => {
    routerMocks.pathname = '/agents/agent-1/conversations/new'
    routerMocks.push.mockClear()
    sidebarMocks.setOpen.mockClear()
    sidebarMocks.toggleSidebar.mockClear()
    sidebarMocks.useSidebar.mockReset()
    sidebarMocks.useSidebar.mockReturnValue({
      isMobile: false,
      open: true,
      openMobile: false,
      setOpen: sidebarMocks.setOpen,
      setOpenMobile: vi.fn(),
      setSidebarWidth: vi.fn(),
      sidebarWidth: 256,
      state: 'expanded',
      toggleSidebar: sidebarMocks.toggleSidebar,
    })
    // 防止 atomWithStorage(collapsedAgentIdsAtom) 在测试之间泄漏状态
    window.localStorage.clear()
    window.history.replaceState(null, '', '/')
    conversationHookMocks.useConversationPages.mockReturnValue({
      data: { pages: [mockConversationPage] },
      isLoading: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    })
    conversationHookMocks.useGlobalConversationPages.mockReturnValue({
      data: { pages: [mockGlobalConversationPage] },
      isLoading: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    })
  })

  it('renders agent-grouped navigation and the local draft row', async () => {
    render(<ChatNavigator />)

    expect(screen.getByText('智能体')).toBeInTheDocument()
    expect(screen.getByText('智能体').closest('[data-sidebar="group-label"]')).toHaveClass(
      'group-data-[collapsible=icon]:hidden',
    )
    expect(screen.getByText('Test Agent')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('link', { name: /新对话/ })).toBeInTheDocument())
    expect(screen.getByText('Test Conversation')).toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: '搜索智能体或对话' }),
    ).not.toBeInTheDocument()

    const activeAgentNewChat = screen.getByRole('button', { name: '与 Test Agent 的新聊天' })
    const activeAgentControls = activeAgentNewChat.closest('div')
    if (!activeAgentControls) {
      throw new TypeError('active agent controls container was missing')
    }
    expect(activeAgentControls).toHaveClass('opacity-100')
    expect(screen.queryByRole('button', { name: 'Test Agent 会话搜索' })).not.toBeInTheDocument()
  })

  it('promotes a remountless draft route replacement to the real active session', async () => {
    render(<ChatNavigator />)

    await waitFor(() => expect(screen.getByRole('link', { name: /新对话/ })).toBeInTheDocument())

    act(() => {
      replaceChatRouteWithoutRemount('/agents/agent-1/conversations/conv-1')
    })

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: /新对话/ })).not.toBeInTheDocument()
      expect(screen.getByText('Test Conversation').closest('[data-chat-session-href]')).toHaveClass(
        'bg-primary',
      )
    })
  })

  it('shows global search results above agent groups', async () => {
    const user = userEvent.setup()
    render(<ChatNavigator />)

    await user.click(screen.getByRole('button', { name: '搜索智能体' }))
    await user.type(screen.getByRole('textbox', { name: '搜索智能体或对话' }), 'Second')

    expect(screen.getByText('搜索结果')).toBeInTheDocument()
    expect(screen.getAllByText('Second Conversation').length).toBeGreaterThan(0)
    expect(screen.queryByText('没有搜索结果')).not.toBeInTheDocument()
  })

  it('expands collapsed agent sessions before fetching another page', async () => {
    const user = userEvent.setup()
    const fetchNextPage = vi.fn()
    const onToggleListExpanded = vi.fn()
    const agent = mockAgentSummaryList[0]
    if (!agent) {
      throw new TypeError('agent fixture was missing')
    }
    const conversations = Array.from({ length: 6 }, (_, index) => ({
      ...mockConversation,
      id: `conv-${index + 1}`,
      title: `Session ${index + 1}`,
    }))
    conversationHookMocks.useConversationPages.mockReturnValue({
      data: { pages: [{ ...mockConversationPage, items: conversations }] },
      isLoading: false,
      hasNextPage: true,
      fetchNextPage,
      isFetchingNextPage: false,
    })

    render(
      <ChatNavigatorAgentGroup
        agent={agent}
        activeAgentId="agent-1"
        activeConversationId="conv-1"
        searchQuery=""
        sessionSort="updated"
        expanded
        listExpanded={false}
        shortcutHintsEnabled
        onToggleExpanded={vi.fn()}
        onToggleListExpanded={onToggleListExpanded}
        actions={createRowActions()}
      />,
    )

    await user.click(screen.getByRole('button', { name: '加载更多' }))

    expect(onToggleListExpanded).toHaveBeenCalledWith(agentSessionScope('agent-1'))
    expect(fetchNextPage).not.toHaveBeenCalled()
  })

  it('uses the agent avatar as the collapsed rail target and expands the sidebar from it', async () => {
    const user = userEvent.setup()
    const onExpandSidebar = vi.fn()
    const agent = mockAgentSummaryList[0]
    if (!agent) {
      throw new TypeError('agent fixture was missing')
    }
    sidebarMocks.useSidebar.mockReturnValue({
      isMobile: false,
      open: false,
      openMobile: false,
      setOpen: sidebarMocks.setOpen,
      setOpenMobile: vi.fn(),
      setSidebarWidth: vi.fn(),
      sidebarWidth: 48,
      state: 'collapsed',
      toggleSidebar: sidebarMocks.toggleSidebar,
    })

    render(
      <ChatNavigatorAgentGroup
        agent={agent}
        activeAgentId="agent-1"
        activeConversationId="conv-1"
        searchQuery=""
        sessionSort="updated"
        expanded
        listExpanded={false}
        shortcutHintsEnabled
        isSidebarCollapsed
        onExpandSidebar={onExpandSidebar}
        onToggleExpanded={vi.fn()}
        onToggleListExpanded={vi.fn()}
        actions={createRowActions()}
      />,
    )

    const collapseToggle = screen.getByRole('button', { name: '展开智能体' })
    expect(collapseToggle).toHaveClass('group-data-[collapsible=icon]:hidden')

    const agentLink = screen.getByRole('link', { name: 'Test Agent' })
    expect(agentLink).toHaveClass('group-data-[collapsible=icon]:size-8')
    expect(screen.queryByText('Test Conversation')).not.toBeInTheDocument()

    await user.click(agentLink)

    expect(onExpandSidebar).toHaveBeenCalledTimes(1)
    expect(sidebarMocks.setOpen).not.toHaveBeenCalled()
  })

  it('navigates with Cmd+Shift+digit even when event.key is a layout character', () => {
    render(<ChatNavigator />)

    const firstHref = document
      .querySelector('[data-chat-session-href]')
      ?.getAttribute('data-chat-session-href')
    expect(firstHref).toBeTruthy()

    // IME 组合过程中快捷键不应生效
    fireEvent.keyDown(window, {
      key: '!',
      code: 'Digit1',
      metaKey: true,
      shiftKey: true,
      isComposing: true,
    })
    expect(routerMocks.push).not.toHaveBeenCalled()

    // 在 macOS 上 Cmd+Shift+1 的 event.key 会是 '!' — 必须按物理键代码匹配
    fireEvent.keyDown(window, { key: '!', code: 'Digit1', metaKey: true, shiftKey: true })

    expect(routerMocks.push).toHaveBeenCalledWith(firstHref)
  })

  it('does not navigate with Cmd+Shift+digit while an editable element is focused', () => {
    render(<ChatNavigator />)

    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()

    // 输入元素聚焦时进行导航会丢失正在编辑的 draft，因此应忽略
    fireEvent.keyDown(textarea, { key: '!', code: 'Digit1', metaKey: true, shiftKey: true })

    expect(routerMocks.push).not.toHaveBeenCalled()
    textarea.remove()
  })

  it('collapses and re-expands the active agent group via the toggle', async () => {
    const user = userEvent.setup()
    render(
      <Provider store={createStore()}>
        <ChatNavigator />
      </Provider>,
    )

    // active 智能体(agent-1)只要没有 collapse override，默认就是展开状态
    expect(screen.getByText('Test Conversation')).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: '折叠智能体' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Test Conversation')).not.toBeInTheDocument()

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Test Conversation')).toBeInTheDocument()
  })

  it('renders shortcut hints from the global session row order', async () => {
    const store = createStore()
    const actions = createRowActions()

    render(
      <Provider store={store}>
        <ChatNavigatorSessionRow
          conversation={{ ...mockConversation, id: 'conv-a', title: 'First session' }}
          active={false}
          shortcutIndex={1}
          actions={actions}
        />
        <ChatNavigatorSessionRow
          conversation={{ ...mockConversation, id: 'conv-b', title: 'Second session' }}
          active={false}
          shortcutIndex={2}
          actions={actions}
        />
        <ChatNavigatorSessionRow
          conversation={{ ...mockConversation, id: 'conv-c', title: 'Tenth session' }}
          active={false}
          shortcutIndex={10}
          actions={actions}
        />
      </Provider>,
    )
    act(() => store.set(shortcutPreviewActiveAtom, true))

    await waitFor(() => expect(screen.getByText(formatShortcutLabel(1))).toBeInTheDocument())
    expect(screen.getByText(formatShortcutLabel(2))).toBeInTheDocument()
    // 快捷键只映射到 Digit1~9，因此第 10 行及之后不显示提示
    expect(screen.queryByText(formatShortcutLabel(10))).not.toBeInTheDocument()
  })

  it('requests sidebar expansion from a collapsed standalone session row', async () => {
    const user = userEvent.setup()
    const onExpandSidebar = vi.fn()

    render(
      <ChatNavigatorSessionRow
        conversation={{ ...mockConversation, title: 'Collapsed session' }}
        active={false}
        actions={createRowActions()}
        isSidebarCollapsed
        onExpandSidebar={onExpandSidebar}
      />,
    )

    await user.click(screen.getByRole('link', { name: 'Collapsed session' }))

    expect(onExpandSidebar).toHaveBeenCalledTimes(1)
  })
})
