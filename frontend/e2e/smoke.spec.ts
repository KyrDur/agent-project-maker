import { expect, isRecord, loginApi, test } from './fixtures'
import type { APIRequestContext } from '@playwright/test'
import { ONBOARDING_DISMISSED_FLAG, SUPER_USER_WELCOMED_FLAG } from '../src/lib/auth/session-flags'

const BACKEND_PORT = process.env.E2E_BACKEND_PORT ?? '8001'
const API_BASE = process.env.E2E_API_BASE_URL ?? `http://localhost:${BACKEND_PORT}`
const SCRIPTED_PROVIDER = 'e2e_scripted'
const SCRIPTED_MODEL_NAME = 'document-artifact-scripted'

async function getScriptedModelId(request: APIRequestContext): Promise<string> {
  const modelsRes = await request.get(`${API_BASE}/api/models`)
  expect(modelsRes.ok(), `GET ${API_BASE}/api/models → ${modelsRes.status()}`).toBeTruthy()

  const body: unknown = await modelsRes.json()
  if (!Array.isArray(body)) {
    throw new Error('E2E model seed response must be an array')
  }

  const scriptedModel = body.find((item: unknown) => {
    if (!isRecord(item)) return false
    return (
      item.provider === SCRIPTED_PROVIDER &&
      item.model_name === SCRIPTED_MODEL_NAME &&
      typeof item.id === 'string'
    )
  })
  if (!isRecord(scriptedModel) || typeof scriptedModel.id !== 'string') {
    throw new Error(
      `Required E2E seed model is missing: ${SCRIPTED_PROVIDER}/${SCRIPTED_MODEL_NAME}`,
    )
  }
  return scriptedModel.id
}

async function getEntityId(responseBody: unknown, resource: string): Promise<string> {
  if (!isRecord(responseBody) || typeof responseBody.id !== 'string') {
    throw new Error(`E2E ${resource} response did not include an id`)
  }
  return responseBody.id
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ({ onboardingDismissedFlag, superUserWelcomedFlag }) => {
      window.sessionStorage.setItem(onboardingDismissedFlag, '1')
      window.sessionStorage.setItem(superUserWelcomedFlag, '1')
    },
    {
      onboardingDismissedFlag: ONBOARDING_DISMISSED_FLAG,
      superUserWelcomedFlag: SUPER_USER_WELCOMED_FLAG,
    },
  )
})

// ---------------------------------------------------------------------------
// Smoke Test - Static Pages
// ---------------------------------------------------------------------------

test.describe('Smoke Test - Static Pages', () => {
  test('/ - dashboard loads without errors', async ({ page, errors }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')

    const main = page.getByRole('main')

    // Verify personalized dashboard hero rendered
    await expect(page.getByRole('heading', { name: /E2E User/ })).toBeVisible()
    // Verify quick action cards
    await expect(main.getByText('通过聊天构建')).toBeVisible()
    await expect(main.getByText('手动构建')).toHaveCount(0)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/agents/new - creation chooser loads', async ({ page, errors }) => {
    await page.goto('/agents/new')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByRole('heading', { name: '你想建造什么？' })).toBeVisible()
    const main = page.getByRole('main')
    await expect(main.getByRole('textbox')).toBeVisible()
    await expect(main.getByRole('button', { name: '开始创建智能体' })).toBeDisabled()
    await expect(main.getByText('手动构建')).toHaveCount(0)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/agents/new/template - template selection loads', async ({ page, errors }) => {
    await page.goto('/agents/new/template')
    await page.waitForLoadState('domcontentloaded')

    await expect(
      page.getByRole('main').getByRole('heading', { name: '从模板开始' }),
    ).toBeVisible()
    // Category tabs (custom pill-group with role="tab")
    await expect(page.getByRole('tab', { name: '全部' })).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/tools - tools page loads', async ({ page, errors }) => {
    await page.goto('/tools')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByRole('heading', { name: '工具' })).toBeVisible()
    await expect(page.getByText('已移除内置外部工具')).toBeVisible()
    await expect(page.getByText('项目使用模拟工具验证 Agent 的行为，无需配置外部服务授权。')).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/models - models page loads', async ({ page, errors }) => {
    await page.goto('/models')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByRole('heading', { name: '模型' })).toBeVisible()
    await expect(page.getByTestId('show-hidden')).toBeVisible()
    await expect(page.getByRole('button', { name: /新模型|添加模型/ }).first()).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/usage - usage page loads', async ({ page, errors }) => {
    await page.goto('/usage')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByRole('heading', { name: '用量' })).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Smoke Test - Dynamic Pages (require agent + conversation via API)
// ---------------------------------------------------------------------------

test.describe('Smoke Test - Dynamic Pages', () => {
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  let agentId: string
  let conversationId: string
  let csrfHeaders: Record<string, string>

  test.beforeAll(async ({ request }) => {
    csrfHeaders = await loginApi(request)

    const modelId = await getScriptedModelId(request)

    // Create test agent
    const agentRes = await request.post(`${API_BASE}/api/agents`, {
      headers: csrfHeaders,
      data: {
        name: 'E2E Smoke Agent',
        system_prompt: 'You are a test agent for E2E smoke tests.',
        model_id: modelId,
      },
    })
    expect(agentRes.ok()).toBeTruthy()
    agentId = await getEntityId(await agentRes.json(), 'agent')

    // Create conversation
    const convRes = await request.post(`${API_BASE}/api/agents/${agentId}/conversations`, {
      headers: csrfHeaders,
      data: {},
    })
    expect(convRes.ok()).toBeTruthy()
    conversationId = await getEntityId(await convRes.json(), 'conversation')
  })

  test.afterAll(async ({ request }) => {
    if (agentId) {
      const cleanupHeaders = await loginApi(request)
      const deleteRes = await request.delete(`${API_BASE}/api/agents/${agentId}`, {
        headers: cleanupHeaders,
      })
      expect(deleteRes.ok(), `DELETE agent ${agentId} → ${deleteRes.status()}`).toBeTruthy()
    }
  })

  test('/agents/[id]/conversations/[cid] - chat page loads', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/conversations/${conversationId}`)
    await page.waitForLoadState('domcontentloaded')

    const main = page.getByRole('main')

    // Agent name appears in multiple headings (sidebar h2, chat header h1, empty state h2).
    // smoke 验证至少能看到一个即可 OK。
    await expect(main.getByRole('heading', { name: 'E2E Smoke Agent' }).first()).toBeVisible()
    // New Conversation and Settings are available from the chat header menu.
    // The menu is rendered in a portal, so locate its items at page level.
    await main.getByRole('button', { name: '菜单' }).click()
    await expect(page.getByRole('menuitem', { name: '新的对话' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '设置' })).toBeVisible()
    await page.keyboard.press('Escape')
    // The starter stays editable and only fills the composer; it does not send.
    const example = '请说明你能帮我完成什么，并给出一个可以直接试用的输入示例。'
    await expect(main.getByText('试用示例（虚构输入，可编辑后发送）')).toBeVisible()
    await main.getByRole('button', { name: example, exact: true }).click()
    await expect(main.locator('textarea').first()).toHaveValue(example)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/agents/[id]/settings - settings page loads', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/settings`)
    await page.waitForLoadState('domcontentloaded')

    const main = page.getByRole('main')

    await expect(page.locator('header input').first()).toHaveValue('E2E Smoke Agent')
    // Form labels
    await expect(main.locator('textarea').first()).toHaveValue('You are a test agent for E2E smoke tests.')
    // "保存" button
    await expect(main.getByRole('button', { name: '保存' })).toBeVisible()
    // "删除智能体" button
    await expect(main.getByRole('button', { name: '删除智能体' })).toBeVisible()
    // AssistantPanel 已集成到右侧面板 — 没有单独的 trigger 按钮

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('/agents/[id] - redirects to conversation', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}`)
    // Should redirect to a conversation URL
    await page.waitForURL(`**/agents/${agentId}/conversations/**`, { timeout: 10_000 })
    await page.waitForLoadState('domcontentloaded')

    // Verify we landed on the chat page (heading 有多处 — first 匹配即可)
    await expect(
      page.getByRole('main').getByRole('heading', { name: 'E2E Smoke Agent' }).first(),
    ).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Smoke Test - Chat Navigator（集成侧边栏）
// ---------------------------------------------------------------------------

test.describe('Smoke Test - Chat Navigator', () => {
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  let agentId: string
  let conversationId: string
  let csrfHeaders: Record<string, string>

  test.beforeAll(async ({ request }) => {
    csrfHeaders = await loginApi(request)

    const modelId = await getScriptedModelId(request)
    const agentRes = await request.post(`${API_BASE}/api/agents`, {
      headers: csrfHeaders,
      data: {
        name: 'E2E Navigator Smoke Agent',
        system_prompt: 'Test agent for chat navigator smoke tests.',
        model_id: modelId,
      },
    })
    expect(agentRes.ok()).toBeTruthy()
    agentId = await getEntityId(await agentRes.json(), 'agent')

    const convRes = await request.post(`${API_BASE}/api/agents/${agentId}/conversations`, {
      headers: csrfHeaders,
      data: { title: 'Navigator smoke session' },
    })
    expect(convRes.ok()).toBeTruthy()
    conversationId = await getEntityId(await convRes.json(), 'conversation')
  })

  test.afterAll(async ({ request }) => {
    if (agentId) {
      const cleanupHeaders = await loginApi(request)
      const deleteRes = await request.delete(`${API_BASE}/api/agents/${agentId}`, {
        headers: cleanupHeaders,
      })
      expect(deleteRes.ok(), `DELETE agent ${agentId} → ${deleteRes.status()}`).toBeTruthy()
    }
  })

  test('sidebar renders the agent group with a session row and row menu', async ({
    page,
    errors,
  }) => {
    await page.goto(`/agents/${agentId}/conversations/${conversationId}`)
    await page.waitForLoadState('domcontentloaded')

    // 集成 navigator：Agent group 和 session row 会渲染到侧边栏
    await expect(page.getByText('E2E Navigator Smoke Agent').first()).toBeVisible()
    const sessionRow = page.locator(
      `[data-chat-session-href="/agents/${agentId}/conversations/${conversationId}"]`,
    )
    await expect(sessionRow).toBeVisible()
    await expect(sessionRow.getByText('Navigator smoke session')).toBeVisible()

    // row menu 在 hover 时显示，menu item 通过 portal 渲染
    await sessionRow.hover()
    await sessionRow.getByRole('button', { name: '对话菜单' }).click()
    await expect(page.getByRole('menuitem', { name: /重命名/ })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /分享/ })).toBeVisible()
    await page.keyboard.press('Escape')

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('quick switcher opens with Cmd/Ctrl+K and closes with Escape', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/conversations/${conversationId}`)
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('E2E Navigator Smoke Agent').first()).toBeVisible()

    const modifier = process.platform === 'darwin' ? 'Meta' : 'Control'
    await page.keyboard.press(`${modifier}+K`)
    await expect(page.getByRole('heading', { name: '快速开关' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: '快速开关' })).not.toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('agent search finds the seeded conversation', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/conversations/${conversationId}`)
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('E2E Navigator Smoke Agent').first()).toBeVisible()

    await page.getByRole('button', { name: '搜索智能体' }).click()
    await page
      .getByRole('textbox', { name: '搜索智能体或对话' })
      .fill('Navigator smoke session')
    await expect(page.getByText('搜索结果')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Navigator smoke session').first()).toBeVisible()
    await expect(page.getByText('没有搜索结果')).toHaveCount(0)

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Smoke Test - Dialogs
// ---------------------------------------------------------------------------

test.describe('Smoke Test - Dialogs', () => {
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  let agentId: string
  let csrfHeaders: Record<string, string>

  test.beforeAll(async ({ request }) => {
    csrfHeaders = await loginApi(request)

    const modelId = await getScriptedModelId(request)
    const agentRes = await request.post(`${API_BASE}/api/agents`, {
      headers: csrfHeaders,
      data: {
        name: 'E2E Dialog Agent',
        system_prompt: 'Test agent for dialog smoke tests.',
        model_id: modelId,
      },
    })
    expect(agentRes.ok()).toBeTruthy()
    agentId = await getEntityId(await agentRes.json(), 'agent')
  })

  test.afterAll(async ({ request }) => {
    if (agentId) {
      const cleanupHeaders = await loginApi(request)
      const deleteRes = await request.delete(`${API_BASE}/api/agents/${agentId}`, {
        headers: cleanupHeaders,
      })
      expect(deleteRes.ok(), `DELETE agent ${agentId} → ${deleteRes.status()}`).toBeTruthy()
    }
  })

  test('models page - "添加对话框" dialog opens', async ({ page, errors }) => {
    await page.goto('/models')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByTestId('show-hidden')).toBeVisible()

    await page.getByRole('button', { name: '新' }).click()
    // Verify dialog content
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: '添加对话框' })).toBeVisible()
    await expect(
      dialog.getByText(
        '注册模型并配置定价和功能。',
      ),
    ).toBeVisible()
    // Close by pressing Escape
    await page.keyboard.press('Escape')

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('tools page exposes simulation guidance without external connections', async ({ page, errors }) => {
    await page.goto('/tools')
    await expect(page.getByText('已移除内置外部工具')).toBeVisible()
    await expect(page.getByRole('button', { name: /HTTP 请求|HTTP Request|设置密钥/ })).toHaveCount(0)
    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('settings page - Fix right rail renders', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/settings`)
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByRole('tab', { name: '修复智能体' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '修复E2E Dialog Agent' })).toBeVisible()
    await expect(page.getByText('修复英雄字幕')).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })

  test('settings page - "删除智能体" confirmation dialog opens', async ({ page, errors }) => {
    await page.goto(`/agents/${agentId}/settings`)
    await page.waitForLoadState('domcontentloaded')

    await page.getByRole('button', { name: '删除智能体' }).click()
    // Verify alert dialog content
    const dialog = page.getByRole('alertdialog')
    await expect(dialog.getByText('删除对话框')).toBeVisible()
    await expect(
      dialog.getByText('此智能体 及其对话将被删除。此操作无法撤消。'),
    ).toBeVisible()
    // Cancel and confirm buttons inside dialog
    await expect(dialog.getByRole('button', { name: '取消' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '删除' })).toBeVisible()
    // Close by clicking Cancel
    await dialog.getByRole('button', { name: '取消' }).click()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Smoke Test - Conversational Creation Page (mocked API)
// ---------------------------------------------------------------------------

test.describe('Smoke Test - Conversational Creation', () => {
  test('/agents/new/conversational - page loads with mocked session', async ({ page, errors }) => {
    // Mock the creation session start API
    await page.route('**/api/agents/create-session', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'mock-session-id',
            status: 'in_progress',
            conversation_history: [],
            draft_config: null,
          }),
        })
      }
      return route.continue()
    })

    await page.goto('/agents/new/conversational')
    await page.waitForLoadState('domcontentloaded')

    // Header
    await expect(page.getByRole('heading', { name: '使用自然语言创建 智能体' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '使用自然语言创建 智能体' })).toBeVisible()
    await expect(page.getByPlaceholder('示例：请说明你能帮我完成什么，并给出一个输入示例')).toBeVisible()
    await expect(page.getByRole('button', { name: '发送按钮' })).toBeVisible()

    expect(errors.console).toEqual([])
    expect(errors.network).toEqual([])
  })
})
