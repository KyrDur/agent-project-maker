import { test, expect, API_BASE, isRecord } from './fixtures'
import { ONBOARDING_DISMISSED_FLAG, SUPER_USER_WELCOMED_FLAG } from '../src/lib/auth/session-flags'

test('regular users save personal API keys and model roles', async ({ page, request }) => {
  const registration = await request.post(`${API_BASE}/api/auth/register`, {
    data: {
      email: `personal-ai-${Date.now()}@example.com`,
      password: 'disposable test password 42',
      name: 'Personal AI test user',
    },
  })
  expect(registration.status()).toBe(201)
  const auth: unknown = await registration.json()
  if (!isRecord(auth) || typeof auth.csrf_token !== 'string' || !isRecord(auth.user))
    throw new Error('Registration did not return user and CSRF token')
  expect(auth.user.is_super_user).toBe(false)
  const state = await request.storageState()
  await page.context().clearCookies()
  await page.context().addCookies(state.cookies)
  await page.addInitScript(({ onboarding, welcome }) => {
    localStorage.setItem(onboarding, '1')
    localStorage.setItem(welcome, '1')
  }, { onboarding: ONBOARDING_DISMISSED_FLAG, welcome: SUPER_USER_WELCOMED_FLAG })
  // Only discovery is stubbed: credentials and settings persist through the real API.
  await page.route('**/api/credentials/*/discover-models', (route) => route.fulfill({
    json: [{ model_name: 'personal-test-model', display_name: 'personal-test-model', provider: 'openai' }],
  }))
  await page.goto('/settings/system-llm')
  await expect(page.getByRole('heading', { name: '我的 AI 配置' })).toBeVisible({ timeout: 20000 })
  await page.locator('#quick-provider').click()
  await page.getByRole('option', { name: 'OpenAI', exact: true }).click()
  await page.getByRole('button', { name: '添加我的 API Key', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: '新的 OpenAI 凭据', exact: true })
  await dialog.getByRole('textbox', { name: /^API Key/ }).fill('sk-disposable-personal-ui-test')
  const created = page.waitForResponse(r => r.url() === `${API_BASE}/api/credentials` && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  const response = await created
  expect(response.ok()).toBeTruthy()
  const credential: unknown = await response.json()
  if (!isRecord(credential)) throw new Error('Credential response is invalid')
  expect(credential.is_system).toBe(false)
  expect(credential.user_id).toBe(auth.user.id)
  await page.locator('#quick-system-model').click()
  await page.getByRole('option', { name: 'personal-test-model', exact: true }).click()
  await page.getByRole('button', { name: '应用到创建、评测和优化', exact: true }).click()
  await expect.poll(async () => {
    const result = await request.get(`${API_BASE}/api/system-llm-settings/readiness`)
    const rows: unknown = await result.json()
    return Array.isArray(rows) && rows.length === 3 && rows.every(row =>
      isRecord(row) && row.configured === true && row.model_name === 'personal-test-model')
  }, { timeout: 15000 }).toBe(true)
  await page.reload()
  await expect(page.getByText('personal-test-model', { exact: true }).first()).toBeVisible({ timeout: 15000 })
  const rendered = await page.locator('body').innerText()
  expect(rendered).not.toContain('sk-disposable-personal-ui-test')
})
