import type { APIRequestContext, Page } from '@playwright/test'
import { API_BASE, apiPostJson, expect, isRecord, test, type CsrfHeaders } from '../fixtures'
import { sendMessage, setupLangGraphV3Agent } from '../langgraph-v3-helpers'
import { capture, DESKTOP_VIEWPORT, settle, warmUpChatRoute } from './_capture-helpers'

/**
 * Wave 2 follow-up ghost + 输入 history 截图：
 *
 *  第 1 幕 ghost：run 结束 → 1 条 LLM 后续建议以浅色显示在输入框中（像 placeholder）
 *  第 2 幕 → 接受：用 ArrowRight 将建议填入实际输入
 *  第 3 幕 typing：只要输入一个字符，ghost 就消失，仅保留输入
 *               （清空后再次出现，Esc 取消）
 *  第 4 幕 history：用 ↑ 按最新顺序浏览之前的输入，↓ 返回 + 恢复 draft
 *  第 5 幕 toggle：在 composer toolbar 中关闭后续建议（OFF） → run 结束后也不显示 ghost
 *
 * scripted 模型部署中，followup endpoint 返回确定性建议
 * ("把刚才的回答整理成表格")，因此整条链路是确定性的。
 * Gated by E2E_CAPTURE_TOUR=1.
 */

const WAVE = 'wave2-followup'
const SUGGESTION = '把刚才的回答整理成表格'
const SCRIPTED_READY = 'E2E scripted document model is ready.'
const FIRST_MESSAGE = '整理一下今天要做的事'
const SECOND_MESSAGE = '总结一下昨天的会议记录'

async function createConversation(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  agentId: string,
  title: string,
): Promise<string> {
  const convo = await apiPostJson(
    request,
    `${API_BASE}/api/agents/${agentId}/conversations`,
    csrfHeaders,
    { title },
  )
  if (!isRecord(convo) || typeof convo.id !== 'string') throw new Error('conversation create failed')
  return convo.id
}

async function gotoChat(page: Page, agentId: string, conversationId: string): Promise<void> {
  await page.goto(`/agents/${agentId}/conversations/${conversationId}`, {
    waitUntil: 'domcontentloaded',
    timeout: 280_000,
  })
  await page
    .locator('textarea[data-moldy-composer-input="true"]')
    .last()
    .waitFor({ state: 'visible', timeout: 120_000 })
}

test.describe('Wave 2 follow-up ghost + composer history captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('walks the ghost suggestion + input history story', async ({ page, request }) => {
    test.setTimeout(600_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const setup = await setupLangGraphV3Agent(request)
    const { csrfHeaders } = setup

    const conversationId = await createConversation(
      request,
      csrfHeaders,
      setup.parentAgentId,
      'Follow-up 演示',
    )
    await gotoChat(page, setup.parentAgentId, conversationId)
    const composer = page.locator('textarea[data-moldy-composer-input="true"]').last()
    const ghost = page.locator('[data-moldy-followup-ghost]')

    // ── 第 1 幕：run 结束 → ghost 建议以浅色出现在输入框中 ───────────
    await sendMessage(page, FIRST_MESSAGE)
    await expect(page.getByText(SCRIPTED_READY).first()).toBeVisible({ timeout: 120_000 })
    await expect(ghost).toBeVisible({ timeout: 30_000 })
    await expect(ghost.getByText(SUGGESTION)).toBeVisible()
    await settle(page)
    await capture(page, WAVE, '00-ghost-suggestion.png')

    // ── 第 2 幕：用 → 键将建议填入实际输入（ghost 被消耗）────────────
    await composer.click()
    await page.keyboard.press('ArrowRight')
    await expect(composer).toHaveValue(SUGGESTION, { timeout: 10_000 })
    await expect(ghost).toBeHidden()
    await settle(page)
    await capture(page, WAVE, '01-ghost-accepted-arrow-right.png')

    // ── 第 3 幕：输入后消失，清空后回来，Esc 取消 ───────────────────
    await composer.fill('')
    await sendMessage(page, SECOND_MESSAGE)
    await expect(page.getByText(SCRIPTED_READY).nth(1)).toBeVisible({ timeout: 120_000 })
    await expect(ghost).toBeVisible({ timeout: 30_000 })
    await composer.pressSequentially('直')
    await expect(ghost).toBeHidden()
    await settle(page)
    await capture(page, WAVE, '02-ghost-dismissed-by-typing.png')
    // 清空输入后，（尚未消耗的）建议会再次出现。
    await composer.fill('')
    await expect(ghost).toBeVisible({ timeout: 10_000 })
    // Esc → 取消本次建议。
    await composer.press('Escape')
    await expect(ghost).toBeHidden()

    // ── 第 4 幕：↑/↓ 输入 history — 按最新顺序浏览 + 恢复 draft ───────
    await composer.pressSequentially('正在编写的 draft')
    await composer.press('ArrowUp')
    await expect(composer).toHaveValue(SECOND_MESSAGE, { timeout: 10_000 })
    await composer.press('ArrowUp')
    await expect(composer).toHaveValue(FIRST_MESSAGE, { timeout: 10_000 })
    await settle(page)
    await capture(page, WAVE, '03-history-arrow-up.png')
    await composer.press('ArrowDown')
    await expect(composer).toHaveValue(SECOND_MESSAGE, { timeout: 10_000 })
    await composer.press('ArrowDown')
    // 越过最新项向下时，会恢复正在编写的 draft（readline contract）。
    await expect(composer).toHaveValue('正在编写的 draft', { timeout: 10_000 })
    await settle(page)
    await capture(page, WAVE, '04-history-draft-restored.png')

    // ── 第 5 幕：toggle OFF — run 结束后也不会显示 ghost ─────────────
    await composer.fill('')
    const toggle = page.locator('[data-moldy-followup-toggle]').last()
    await expect(toggle).toHaveAttribute('data-moldy-followup-toggle', 'on')
    await toggle.click()
    await expect(toggle).toHaveAttribute('data-moldy-followup-toggle', 'off')
    await sendMessage(page, '确认 toggle 关闭状态')
    await expect(page.getByText(SCRIPTED_READY).nth(2)).toBeVisible({ timeout: 120_000 })
    await expect(ghost).toBeHidden()
    await settle(page)
    await capture(page, WAVE, '05-followup-toggle-off.png')

    // 清理 — 为下一个 spec 恢复 toggle。
    await toggle.click()
    await expect(toggle).toHaveAttribute('data-moldy-followup-toggle', 'on')
  })
})
