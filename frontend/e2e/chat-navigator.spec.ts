import { test, expect } from './fixtures'
import type { Page, Route } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

const now = '2026-06-10T12:00:00Z'
const captureDir = join(process.cwd(), '..', 'output', 'e2e-captures', '20260611-chat-navigator')

const agents = [
  {
    id: 'agent-1',
    name: 'Alpha Agent',
    description: 'Research and planning assistant',
    status: 'active',
    is_favorite: false,
    image_url: null,
    model_display_name: 'GPT-4o',
    tool_count: 2,
    fallback_count: 0,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    last_used_at: '2026-06-10T12:00:00Z',
    unread_count: 0,
  },
  {
    id: 'agent-2',
    name: 'Beta Agent',
    description: 'Writing assistant',
    status: 'active',
    is_favorite: false,
    image_url: null,
    model_display_name: 'GPT-4o',
    tool_count: 1,
    fallback_count: 0,
    created_at: '2026-06-02T00:00:00Z',
    updated_at: '2026-06-02T00:00:00Z',
    last_used_at: '2026-06-09T12:00:00Z',
    unread_count: 3,
  },
]

const agentDetails = agents.map((agent) => ({
  ...agent,
  runtime_name: `${agent.name.toLowerCase().replaceAll(' ', '-')}`,
  identity_mode: 'fixed',
  system_prompt: 'You are helpful.',
  model: { id: 'model-1', display_name: 'GPT-4o' },
  tools: [{ id: 'tool-1', name: 'Web Search' }],
  mcp_tools: [],
  skills: [],
  sub_agents: [],
  model_params: null,
  middleware_configs: [],
  template_id: null,
  opener_questions: null,
  llm_credential_id: null,
  model_fallback_ids: [],
}))

const conversations = [
  {
    id: 'conv-1',
    agent_id: 'agent-1',
    title: 'Alpha kickoff',
    is_pinned: false,
    unread_count: 0,
    last_read_at: null,
    last_unread_at: null,
    last_activity_source: 'user',
    created_at: '2026-06-08T10:00:00Z',
    updated_at: now,
    active_run: null,
  },
  {
    id: 'conv-2',
    agent_id: 'agent-1',
    title: 'Second hidden session',
    is_pinned: true,
    unread_count: 0,
    last_read_at: null,
    last_unread_at: null,
    last_activity_source: 'user',
    created_at: '2026-06-07T10:00:00Z',
    updated_at: '2026-06-09T10:00:00Z',
    active_run: null,
  },
  {
    id: 'conv-3',
    agent_id: 'agent-2',
    title: 'Beta recent session',
    is_pinned: false,
    unread_count: 2,
    last_read_at: null,
    last_unread_at: '2026-06-09T12:00:00Z',
    last_activity_source: 'schedule',
    created_at: '2026-06-06T10:00:00Z',
    updated_at: '2026-06-09T12:00:00Z',
    active_run: null,
  },
]

function withAgent(conversation: (typeof conversations)[number]) {
  const agent = agents.find((item) => item.id === conversation.agent_id) ?? agents[0]
  return {
    ...conversation,
    agent: {
      id: agent.id,
      name: agent.name,
      image_url: agent.image_url,
    },
  }
}

function filteredConversations(url: URL, agentId?: string) {
  const query = (url.searchParams.get('q') ?? '').toLowerCase()
  return conversations.filter((conversation) => {
    if (agentId && conversation.agent_id !== agentId) return false
    return query ? (conversation.title ?? '').toLowerCase().includes(query) : true
  })
}

async function mockApi(route: Route) {
  const url = new URL(route.request().url())
  const pathname = url.pathname
  if (pathname === '/api/auth/me') {
    await route.fulfill({
      json: {
        id: 'user-1',
        email: 'e2e@moldy.dev',
        name: 'E2E User',
        is_super_user: true,
      },
    })
    return
  }
  if (pathname === '/api/agents/summary') {
    await route.fulfill({ json: agents })
    return
  }
  if (pathname.startsWith('/api/agents/') && pathname.endsWith('/conversations/page')) {
    const agentId = pathname.split('/')[3]
    await route.fulfill({
      json: {
        items: filteredConversations(url, agentId),
        next_cursor: null,
        has_more: false,
      },
    })
    return
  }
  if (pathname === '/api/conversations/page') {
    await route.fulfill({
      json: {
        items: filteredConversations(url).map(withAgent),
        next_cursor: null,
        has_more: false,
      },
    })
    return
  }
  if (/^\/api\/agents\/[^/]+$/.test(pathname)) {
    const agentId = pathname.split('/')[3]
    await route.fulfill({
      json: agentDetails.find((agent) => agent.id === agentId) ?? agentDetails[0],
    })
    return
  }
  if (/^\/api\/conversations\/[^/]+$/.test(pathname)) {
    const conversationId = pathname.split('/')[3]
    const conversation = conversations.find((item) => item.id === conversationId)
    await route.fulfill({
      json: conversation ? withAgent(conversation) : withAgent(conversations[0]),
    })
    return
  }
  if (pathname.endsWith('/messages')) {
    await route.fulfill({
      json: {
        messages: [],
        active_tip_message_id: null,
        active_checkpoint_id: null,
        total_estimated_cost: 0,
      },
    })
    return
  }
  if (pathname.endsWith('/files')) {
    await route.fulfill({ json: [] })
    return
  }
  await route.fulfill({ json: { items: [], total: 0 } })
}

async function setupNavigatorPage(page: Page) {
  await page.route('**/threads/**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/**', mockApi)
  await page.goto('/agents/agent-1/conversations/conv-1')
  await page.waitForLoadState('domcontentloaded')
}

async function capturePage(page: Page, name: string) {
  mkdirSync(captureDir, { recursive: true })
  await page.screenshot({ path: join(captureDir, name), fullPage: true })
}

async function locatorWidth(locator: ReturnType<Page['locator']>): Promise<number> {
  const box = await locator.boundingBox()
  if (!box) throw new Error('Expected locator to have a bounding box')
  return box.width
}

async function dragHorizontally(page: Page, locator: ReturnType<Page['locator']>, deltaX: number) {
  const box = await locator.boundingBox()
  if (!box) throw new Error('Expected drag handle to have a bounding box')
  const startX = box.x + box.width / 2
  const startY = box.y + Math.min(40, box.height / 2)
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.mouse.move(startX + deltaX, startY, { steps: 8 })
  await page.mouse.up()
}

test.describe('Chat navigator consolidation', () => {
  test('shows one consolidated navigator with search, menus, and shortcuts', async ({
    page,
    errors,
  }) => {
    await setupNavigatorPage(page)

    await expect(page.getByText('智能体').first()).toBeVisible()
    await expect(page.getByText('Alpha Agent').first()).toBeVisible()
    await expect(page.getByText('Alpha kickoff').first()).toBeVisible()
    await expect(page.getByRole('textbox', { name: '搜索智能体或对话' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Alpha Agent 对话搜索' })).toHaveCount(0)
    await capturePage(page, 'chat-navigator-default.png')

    const kickoffRow = page.locator(
      '[data-chat-session-href="/agents/agent-1/conversations/conv-1"]',
    )
    await kickoffRow.hover()
    await kickoffRow.getByRole('button', { name: '对话菜单' }).click()
    await expect(page.getByRole('menuitem', { name: /重命名/ })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /分享/ })).toBeVisible()
    await capturePage(page, 'chat-navigator-row-menu.png')
    await page.keyboard.press('Escape')

    const modifier = process.platform === 'darwin' ? 'Meta' : 'Control'
    await page.keyboard.down(modifier)
    await expect(
      page.getByText(process.platform === 'darwin' ? '⌘⇧1' : 'Ctrl+Shift+1'),
    ).toBeVisible()
    await capturePage(page, 'chat-navigator-shortcuts.png')
    await page.keyboard.up(modifier)

    await page.keyboard.press(`${modifier}+K`)
    await expect(page.getByRole('heading', { name: '快速开关' })).toBeVisible()
    await capturePage(page, 'chat-navigator-quick-switcher.png')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: '快速开关' })).not.toBeVisible()

    await page.getByRole('button', { name: '搜索智能体' }).click()
    await page.getByRole('textbox', { name: '搜索智能体或对话' }).fill('Second')
    await expect(page.getByText('搜索结果')).toBeVisible()
    await expect(page.getByText('Second hidden session').first()).toBeVisible()
    await expect(page.getByText('没有搜索结果')).toHaveCount(0)
    await capturePage(page, 'chat-navigator-search.png')

    await page.getByRole('button', { name: '新聊天' }).click()
    await expect(page).toHaveURL(/\/agents\/agent-1\/conversations\/new$/)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('resizes, collapses, and re-expands the app sidebar rail', async ({ page, errors }) => {
    await setupNavigatorPage(page)

    const sidebar = page.locator('[data-slot="sidebar-container"]')
    const handle = page.getByRole('separator', { name: '调整侧边栏大小' })
    await expect(handle).toBeVisible()
    await handle.hover()
    await expect(handle).toHaveCSS('cursor', 'col-resize')

    const initialWidth = await locatorWidth(sidebar)
    await dragHorizontally(page, handle, 80)
    await expect
      .poll(() => locatorWidth(sidebar), { timeout: 15_000, intervals: [250, 500, 1000] })
      .toBeGreaterThan(initialWidth + 60)

    await dragHorizontally(page, handle, -260)
    await expect
      .poll(() => locatorWidth(sidebar), { timeout: 15_000, intervals: [250, 500, 1000] })
      .toBeLessThan(80)

    await dragHorizontally(page, handle, 260)
    await expect
      .poll(() => locatorWidth(sidebar), { timeout: 15_000, intervals: [250, 500, 1000] })
      .toBeGreaterThanOrEqual(224)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('drives view mode and agent sort from the navigator options menu', async ({
    page,
    errors,
  }) => {
    await setupNavigatorPage(page)

    // Agent group header link 的 DOM 顺序（用于 sort assertion）
    // 主 chat header breadcrumb 中也有 /agents/<id> link，因此将 scope 缩小到 sidebar
    const sidebar = page.locator('[data-sidebar="sidebar"]')
    const agentHeaderOrder = () =>
      sidebar
        .locator('a[href="/agents/agent-1"], a[href="/agents/agent-2"]')
        .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')))

    // 默认状态：按 Agent 查看 + 最近使用排序（Alpha 在上），inactive Agent session 折叠
    await expect(page.getByText('Alpha kickoff').first()).toBeVisible()
    await expect(page.getByText('Beta recent session')).toHaveCount(0)
    await expect.poll(agentHeaderOrder).toEqual(['/agents/agent-1', '/agents/agent-2'])

    // trigger 是 opacity-0，因此先 hover heading 让其显示再打开（Playwright 虽可点击 opacity-0，但为了截图）
    // Base UI radio item 的 closeOnClick=false，因此 menu 会保持打开，可一次打开后连续操作
    const menuTrigger = page.getByRole('button', { name: '导航器选项' })
    await menuTrigger.hover()
    await menuTrigger.click()
    await expect(page.getByRole('menuitem', { name: '分组方式' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '智能体 排序' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '对话排序' })).toBeVisible()
    await expect(
      page.getByRole('menuitemcheckbox', { name: '一次展开一个智能体' }),
    ).toBeVisible()
    await capturePage(page, 'chat-navigator-options-menu.png')

    // 将 Agent 排序改为按创建顺序后，Beta（06-02 创建）会排到 Alpha（06-01 创建）上方
    await page.getByRole('menuitem', { name: '智能体 排序' }).hover()
    await expect(page.getByRole('menuitemradio', { name: '最后使用' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await page.getByRole('menuitemradio', { name: '创建时间' }).click()
    await expect.poll(agentHeaderOrder).toEqual(['/agents/agent-2', '/agents/agent-1'])
    await capturePage(page, 'chat-navigator-agent-sort-created.png')

    // 查看方式 submenu：确认三种 mode radio 和当前选择（按 Agent）
    await page.getByRole('menuitem', { name: '分组方式' }).hover()
    await expect(page.getByRole('menuitemradio', { name: '通过 智能体' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await expect(page.getByRole('menuitemradio', { name: '最近智能体' })).toBeVisible()
    await expect(page.getByRole('menuitemradio', { name: '最近的对话' })).toBeVisible()
    await capturePage(page, 'chat-navigator-view-modes.png')

    // 切换到最近对话 mode：group header 消失，所有 session 与 Agent avatar 一起扁平化
    await page.getByRole('menuitemradio', { name: '最近的对话' }).click()
    // Escape 每次关闭一级（submenu → root menu）
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('menuitem', { name: '分组方式' })).toHaveCount(0)
    const betaRow = page.locator('[data-chat-session-href="/agents/agent-2/conversations/conv-3"]')
    await expect(betaRow).toBeVisible()
    // Agent 名称通过 avatar hover tooltip 显示
    const betaAgentTrigger = betaRow
      .locator('[data-slot="tooltip-trigger"]')
      .filter({ hasText: 'Beta Agent' })
    await expect(betaAgentTrigger).toHaveCount(1)
    await betaAgentTrigger.hover()
    await expect(
      page.locator('[data-slot="tooltip-content"]').getByText('Beta Agent'),
    ).toBeVisible()
    await expect(page.getByText('Alpha kickoff').first()).toBeVisible()
    await expect(sidebar.locator('a[href="/agents/agent-1"]')).toHaveCount(0)
    await capturePage(page, 'chat-navigator-recent-sessions.png')

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})
