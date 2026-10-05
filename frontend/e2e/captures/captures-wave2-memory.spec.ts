import type { APIRequestContext, Page } from '@playwright/test'
import {
  API_BASE,
  apiGetJson,
  apiPostJson,
  expect,
  isRecord,
  test,
  type CsrfHeaders,
} from '../fixtures'
import { sendMessage, setupLangGraphV3Agent } from '../langgraph-v3-helpers'
import { capture, DESKTOP_VIEWPORT, settle, warmUpChatRoute } from './_capture-helpers'

/**
 * Wave 2 memory lifecycle 截图 — chat 中所有 memory 相关界面：
 *
 *  第 1 幕自动保存：write_policy=auto + E2E_MEMORY_SAVE → "已保存" pill（立即记录）
 *  第 2 幕保存建议：write_policy=ask + E2E_MEMORY_PROPOSE → 建议 card
 *                 （保存/修改/拒绝 button，默认展开）
 *  第 3 幕保存批准：在建议 card 中点击保存 → 状态变为 "已保存"
 *  第 4 幕保存拒绝：新建议 → 点击拒绝 → 状态变为 "不保存"
 *  第 5 幕修改后保存：新建议 → 修改 → textarea 编辑 → 修改后保存
 *  第 6 幕回忆闭环：已保存 memory 在下一次 run 中以 "记忆回忆" chip 返回
 *
 * Gated by E2E_CAPTURE_TOUR=1 (+ E2E_TEST_HELPERS_ENABLED, scripted model).
 */

const WAVE = 'wave2-memory'
const MEMORY_FINAL = 'E2E memory tool run complete.'
const SAVE_CONTENT = '用户偏好结论优先、以表格为主的报告。'
const PROPOSE_CONTENT = '希望每周一早上收到周计划 briefing。'

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

async function setWritePolicy(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  policy: 'auto' | 'ask',
): Promise<void> {
  const response = await request.patch(`${API_BASE}/api/me/memory-settings`, {
    headers: csrfHeaders,
    data: { memory_write_policy: policy },
  })
  expect(response.ok()).toBe(true)
}

/** 为确保 rerun/retry 具有确定性，删除所有现有 memory。 */
async function clearMemories(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
): Promise<void> {
  const existing = await apiGetJson(request, `${API_BASE}/api/memories?scope=all`)
  if (!Array.isArray(existing)) return
  for (const row of existing) {
    if (!isRecord(row) || typeof row.id !== 'string') continue
    const response = await request.delete(`${API_BASE}/api/memories/${row.id}`, {
      headers: csrfHeaders,
    })
    expect(response.ok()).toBe(true)
  }
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

test.describe('Wave 2 memory lifecycle captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('walks the memory save/propose/approve/reject/edit/recall lifecycle', async ({
    page,
    request,
  }) => {
    test.setTimeout(600_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const setup = await setupLangGraphV3Agent(request)
    const { csrfHeaders } = setup
    await clearMemories(request, csrfHeaders)

    try {
      // ── 第 1 幕：自动保存（write_policy=auto）— 不询问，直接记录 ───────
      await setWritePolicy(request, csrfHeaders, 'auto')
      const autoConversationId = await createConversation(
        request,
        csrfHeaders,
        setup.parentAgentId,
        'memory 自动保存',
      )
      await gotoChat(page, setup.parentAgentId, autoConversationId)
      await sendMessage(page, '一定要记住我的报告偏好 E2E_MEMORY_SAVE')
      await expect(page.getByText(MEMORY_FINAL).first()).toBeVisible({ timeout: 120_000 })

      const memoryCard = page.getByTestId('memory-tool-card').last()
      await expect(memoryCard.getByText('已保存')).toBeVisible({ timeout: 30_000 })
      // 折叠 pill 中也会显示内容 preview(meta) — 展开查看全文。
      await memoryCard.getByText('已保存').click()
      // 内容会同时出现在折叠 meta(truncate span) 和展开正文(p) 两处 — 固定用 first。
      await expect(memoryCard.getByText(SAVE_CONTENT).first()).toBeVisible({ timeout: 10_000 })
      await settle(page)
      await capture(page, WAVE, '00-memory-auto-saved-pill.png')

      // ── 第 2 幕：保存建议（write_policy=ask）— 批准前不记录 ─────────
      await setWritePolicy(request, csrfHeaders, 'ask')
      const proposeConversationId = await createConversation(
        request,
        csrfHeaders,
        setup.parentAgentId,
        'memory 保存建议',
      )
      await gotoChat(page, setup.parentAgentId, proposeConversationId)
      await sendMessage(page, '如果能记住周一 briefing 的事就好了 E2E_MEMORY_PROPOSE')
      await expect(page.getByText(MEMORY_FINAL).first()).toBeVisible({ timeout: 120_000 })

      const proposalCard = page.getByTestId('memory-tool-card').last()
      await expect(proposalCard.getByText('保存建议')).toBeVisible({ timeout: 30_000 })
      // 建议 card 默认展开 — 内容 + 保存/修改/拒绝 button 直接可见。
      await expect(proposalCard.getByText(PROPOSE_CONTENT).first()).toBeVisible({ timeout: 10_000 })
      await expect(proposalCard.getByTestId('memory-proposal-approve')).toBeVisible()
      await expect(proposalCard.getByTestId('memory-proposal-reject')).toBeVisible()
      await expect(proposalCard.getByTestId('memory-proposal-edit')).toBeVisible()
      await settle(page)
      await capture(page, WAVE, '01-memory-proposal-card.png')

      // ── 第 3 幕：保存批准 — card 转为 "已保存" ─────────────────────
      await proposalCard.getByTestId('memory-proposal-approve').click()
      await expect(proposalCard.getByText('已保存')).toBeVisible({ timeout: 30_000 })
      await settle(page)
      await capture(page, WAVE, '02-memory-proposal-approved.png')

      // ── 第 4 幕：保存拒绝 — card 转为 "不保存" ─────────────────────
      const rejectConversationId = await createConversation(
        request,
        csrfHeaders,
        setup.parentAgentId,
        'memory 保存拒绝',
      )
      await gotoChat(page, setup.parentAgentId, rejectConversationId)
      await sendMessage(page, '这个别保存 E2E_MEMORY_PROPOSE')
      await expect(page.getByText(MEMORY_FINAL).first()).toBeVisible({ timeout: 120_000 })
      const rejectCard = page.getByTestId('memory-tool-card').last()
      await expect(rejectCard.getByTestId('memory-proposal-reject')).toBeVisible({
        timeout: 30_000,
      })
      await rejectCard.getByTestId('memory-proposal-reject').click()
      await expect(rejectCard.getByText('不保存')).toBeVisible({ timeout: 30_000 })
      await settle(page)
      await capture(page, WAVE, '03-memory-proposal-rejected.png')

      // ── 第 5 幕：修改后保存 — 修改建议内容后批准 ────────────────────
      const editConversationId = await createConversation(
        request,
        csrfHeaders,
        setup.parentAgentId,
        'memory 修改后保存',
      )
      await gotoChat(page, setup.parentAgentId, editConversationId)
      await sendMessage(page, '记住 briefing 时间 E2E_MEMORY_PROPOSE')
      await expect(page.getByText(MEMORY_FINAL).first()).toBeVisible({ timeout: 120_000 })
      const editCard = page.getByTestId('memory-tool-card').last()
      await expect(editCard.getByTestId('memory-proposal-edit')).toBeVisible({ timeout: 30_000 })
      await editCard.getByTestId('memory-proposal-edit').click()
      const editor = editCard.getByRole('textbox')
      await expect(editor).toBeVisible({ timeout: 10_000 })
      await editor.fill('希望每周一上午 9 点收到周计划 briefing。')
      await settle(page)
      await capture(page, WAVE, '04-memory-proposal-editing.png')
      await editCard.getByTestId('memory-proposal-edit-approve').click()
      await expect(editCard.getByText('已保存')).toBeVisible({ timeout: 30_000 })
      await expect(
        editCard.getByText('希望每周一上午 9 点收到周计划 briefing。').first(),
      ).toBeVisible()
      await settle(page)
      await capture(page, WAVE, '05-memory-proposal-edit-approved.png')

      // ── 第 6 幕：回忆闭环 — 保存的 memory 在下一次 run 以 recall chip 返回 ──
      // 已保存：自动保存 1 + 批准 1 + 修改后保存 1 = 3 个。
      const recallConversationId = await createConversation(
        request,
        csrfHeaders,
        setup.parentAgentId,
        '确认 memory recall',
      )
      await gotoChat(page, setup.parentAgentId, recallConversationId)
      await sendMessage(page, '按上次说的偏好整理一下')
      const recallChip = page.locator('[data-moldy-memory-recall]')
      await expect(recallChip).toBeVisible({ timeout: 60_000 })
      await expect(recallChip.getByText('3 个')).toBeVisible({ timeout: 15_000 })
      await recallChip.getByText('记忆回忆').click()
      await expect(recallChip.getByText(SAVE_CONTENT).first()).toBeVisible({ timeout: 10_000 })
      await settle(page)
      await capture(page, WAVE, '06-memory-recall-full-circle.png')

      // reload — 持久化 event 中 memory 内容会被 <redacted> 掩码（共享安全
      // contract），owner 界面需通过 memory API join 恢复内容。
      await gotoChat(page, setup.parentAgentId, recallConversationId)
      await expect(recallChip).toBeVisible({ timeout: 60_000 })
      await recallChip.getByText('记忆回忆').click()
      await expect(recallChip.getByText(SAVE_CONTENT).first()).toBeVisible({ timeout: 15_000 })
      await expect(recallChip.getByText('<redacted>')).toHaveCount(0)
    } finally {
      // 清理 — 恢复 policy 默认值(ask) + 删除 memory/建议残留，切断 spec 间耦合。
      await setWritePolicy(request, csrfHeaders, 'ask')
      await clearMemories(request, csrfHeaders)
    }
  })
})
