import { API_BASE, apiPostJson, expect, isRecord, test } from './fixtures'
import { sendMessage, setupLangGraphV3Agent } from './langgraph-v3-helpers'

/**
 * G5 (conversation export) + G6 (in-conversation search) contract. Sends a
 * message, then verifies the navigator menu export triggers a file download and
 * the Ctrl+F search overlay finds a match. Requires the scripted model
 * (E2E_SCRIPTED_MODEL_ENABLED=true).
 */
test.describe('Chat export + in-conversation search (G5/G6)', () => {
  test('export downloads a markdown file and search finds a match', async ({ page, request }) => {
    test.setTimeout(180_000)
    const setup = await setupLangGraphV3Agent(request)
    const { parentAgentId: agentId, csrfHeaders } = setup

    const convo = await apiPostJson(
      request,
      `${API_BASE}/api/agents/${agentId}/conversations`,
      csrfHeaders,
      { title: 'export-search' },
    )
    if (!isRecord(convo) || typeof convo.id !== 'string') throw new Error('conversation create failed')
    const conversationId = convo.id

    await page.goto(`/agents/${agentId}/conversations/${conversationId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 180_000,
    })
    await page
      .locator('textarea[data-moldy-composer-input="true"]')
      .last()
      .waitFor({ state: 'visible', timeout: 90_000 })

    // Send multiple turns. "E2E" appears in both the user messages and the
    // scripted assistant reply, so search matches user + LLM answers alike.
    for (const text of ['整理一下 E2E 会议内容', '也告诉我 E2E 会议议题']) {
      await sendMessage(page, text)
      const stop = page.locator('[data-moldy-stop-button="true"]:visible').last()
      await stop.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {})
      await stop.waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => {})
    }

    // G5 — navigator session menu → 导出 → Markdown triggers a download.
    await page.getByRole('button', { name: '对话菜单' }).first().click()
    await page.getByRole('menuitem', { name: '导出' }).click()
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Markdown (.md)' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/^conversation-.*\.md$/)

    // G6 — Ctrl/Cmd+F overlay finds the sent message ("会议").
    await page.locator('textarea[data-moldy-composer-input="true"]').last().click()
    await page.keyboard.press('ControlOrMeta+f')
    const overlay = page.getByRole('search')
    await expect(overlay).toBeVisible({ timeout: 10_000 })
    await overlay.getByRole('textbox').fill('E2E')
    // user 消息 + assistant 响应都包含 "E2E"，所以 total 足够大于等于 2。
    await expect(overlay.getByText(/^\d+\/[2-9]\d*$/)).toBeVisible({ timeout: 10_000 })
  })
})
