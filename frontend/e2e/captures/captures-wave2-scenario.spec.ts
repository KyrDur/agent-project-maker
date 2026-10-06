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
import {
  approveExecuteInSkill,
  sendMessage,
  setupLangGraphV3Agent,
} from '../langgraph-v3-helpers'
import { capture, DESKTOP_VIEWPORT, settle, warmUpChatRoute } from './_capture-helpers'

/**
 * Wave 2 场景截图 — “会记忆、会搜索、会团队协作的 Agent”故事：
 *
 *  第 1 幕 memory：植入 2 条 long-term memory → run 开始时 memory recall chip(moldy.memory_recalled)
 *  第 2 幕 search：E2E_SEARCH_RICH — answer 摘要 box + rich result card，
 *               E2E_SEARCH_SHOP — Simulated shopping data thumbnail + 最低价 card
 *  第 3 幕 team：E2E_LANGGRAPH_V3 mission run — subagent team strip（live/完成），
 *               execute_in_skill approval → terminal ui_data card（genui 首个真实工具 producer）
 *  第 4 幕 reload：skill 执行 pill（command+file chip）+ team strip 恢复
 *
 * Gated by E2E_CAPTURE_TOUR=1 (+ E2E_TEST_HELPERS_ENABLED, scripted model).
 */

const WAVE = 'wave2-scenario'
const FINAL_TEXT = 'E2E LangGraph v3 validation complete'
const RICH_FINAL = 'E2E rich search rendering complete.'
const SHOP_FINAL = 'E2E shop search rendering complete.'

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

/** 删除所有现有 memory，只保留准确需要的 set — 防止 retry/rerun 时
 * memory 累积导致“参考 2 条 memory”断言失效的 rerun-safe helper。 */
async function resetMemories(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  records: readonly Record<string, unknown>[],
): Promise<void> {
  const existing = await apiGetJson(request, `${API_BASE}/api/memories?scope=all`)
  if (Array.isArray(existing)) {
    for (const row of existing) {
      if (!isRecord(row) || typeof row.id !== 'string') continue
      const response = await request.delete(`${API_BASE}/api/memories/${row.id}`, {
        headers: csrfHeaders,
      })
      expect(response.ok()).toBe(true)
    }
  }
  for (const data of records) {
    const record = await apiPostJson(request, `${API_BASE}/api/memories`, csrfHeaders, data)
    if (!isRecord(record) || typeof record.id !== 'string') throw new Error('memory create failed')
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

test.describe('Wave 2 scenario captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('walks the Wave 2 story and captures every surface', async ({ page, request }) => {
    test.setTimeout(600_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const setup = await setupLangGraphV3Agent(request)
    const { csrfHeaders } = setup

    // ── 第 1 幕：植入 long-term memory — 从下一次 run 起显示 recall chip ──
    await resetMemories(request, csrfHeaders, [
      {
        scope: 'user',
        content: '偏好用韩语回答，并先给结论。',
      },
      {
        scope: 'agent',
        agent_id: setup.parentAgentId,
        content: '报告以表格和 3 行摘要为主。',
      },
    ])

    // ── 第 2 幕：search rich card — 同时确认 answer 摘要 box + recall chip ──
    const searchConversationId = await createConversation(
      request,
      csrfHeaders,
      setup.parentAgentId,
      'Wave2 搜索调研',
    )
    await gotoChat(page, setup.parentAgentId, searchConversationId)
    await sendMessage(page, '调研 agentic os E2E_SEARCH_RICH')
    await expect(page.getByText(RICH_FINAL).first()).toBeVisible({ timeout: 120_000 })

    // memory recall chip — 作为 stream head event 到达，run 结束后也始终显示。
    const memoryChip = page.locator('[data-moldy-memory-recall]')
    await expect(memoryChip).toBeVisible({ timeout: 30_000 })
    await expect(memoryChip.getByText('2 个')).toBeVisible({ timeout: 10_000 })

    // search pill — Tavily answer 摘要 box + 3 张 result card（单独调用所以展开）。
    const answerBox = page.locator('[data-moldy-search-answer]')
    await expect(answerBox).toBeVisible({ timeout: 30_000 })
    await expect(answerBox.getByText(/智能体 OS 是/)).toBeVisible()
    await expect(page.getByText('Agentic OS 架构概览')).toBeVisible()
    await settle(page)
    await capture(page, WAVE, '00-search-rich-answer-and-memory-chip.png')

    // 展开 recall chip — scope badge + memory preview。
    await memoryChip.getByText('记忆回忆').click()
    await expect(memoryChip.getByText('偏好用韩语回答，并先给结论。')).toBeVisible(
      { timeout: 10_000 },
    )
    await settle(page)
    await capture(page, WAVE, '01-memory-recall-expanded.png')
    await memoryChip.getByText('记忆回忆').click()

    // shopping search — Simulated shopping data: thumbnail + 最低价 + seller。
    await sendMessage(page, '告诉我无线键盘最低价 E2E_SEARCH_SHOP')
    await expect(page.getByText(SHOP_FINAL).first()).toBeVisible({ timeout: 120_000 })
    const priceRow = page.locator('[data-moldy-search-price]').first()
    await expect(priceRow).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('[data-moldy-search-thumbnail]').first()).toBeVisible()
    await expect(page.getByText('最低 42,900 韩元')).toBeVisible()
    await settle(page)
    await capture(page, WAVE, '02-search-shop-thumbnail-price.png')

    // ── 第 3 幕：team mission run — team strip + skill approval + terminal card ──
    const missionConversationId = await createConversation(
      request,
      csrfHeaders,
      setup.parentAgentId,
      'Wave2 team mission',
    )
    await gotoChat(page, setup.parentAgentId, missionConversationId)
    await sendMessage(
      page,
      `准备 wiki report E2E_LANGGRAPH_V3 subagent=${setup.childRuntimeName}`,
    )

    // team strip — 委派后立即显示 subagent chip，并替换为 display name。
    const teamStrip = page.locator('[data-moldy-team-strip]')
    await expect(teamStrip).toBeVisible({ timeout: 90_000 })
    await expect(teamStrip.getByText(setup.childName)).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '03-team-strip-live.png')

    // execute_in_skill approval → docx skill 实际执行。
    await approveExecuteInSkill(page)
    await expect(page.getByText(FINAL_TEXT).first()).toBeVisible({ timeout: 180_000 })

    // team strip 完成状态 — done/total meta。
    await expect(teamStrip.getByText('1/1 完成')).toBeVisible({ timeout: 30_000 })

    // terminal ui_data card — 第一个真实工具 genui producer（execute_in_skill stdout）。
    const terminalCard = page.getByTestId('data-ui-terminal').last()
    await expect(terminalCard).toBeVisible({ timeout: 60_000 })
    await terminalCard.scrollIntoViewIfNeeded()
    await settle(page)
    await capture(page, WAVE, '04-team-strip-done-terminal-card.png')

    // 点击 team strip chip → 右侧 rail 显示 subagent 详情。
    await teamStrip.getByText(setup.childName).click()
    const rail = page.getByRole('complementary')
    await expect(rail.getByText(setup.childName).first()).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '05-team-chip-opens-rail.png')

    // ── 第 4 幕：reload — skill 执行 pill（command+file chip）+ team strip 恢复 ──
    await gotoChat(page, setup.parentAgentId, missionConversationId)
    await expect(teamStrip).toBeVisible({ timeout: 90_000 })
    const skillPill = page.locator('[data-moldy-skill-execution="docx-document"]').last()
    await expect(skillPill).toBeVisible({ timeout: 60_000 })
    // 有文件时默认展开 — OUTPUT_FILES chip 链接到 file API。
    const fileChip = skillPill.locator('[data-moldy-skill-file]').first()
    await expect(fileChip).toBeVisible({ timeout: 30_000 })
    await skillPill.scrollIntoViewIfNeeded()
    await settle(page)
    await capture(page, WAVE, '06-skill-pill-files-after-reload.png')

    // ── 清理：user-scope memory 是账号全局的，会泄漏到其他 spec 界面的 "记忆回忆"
    // chip — 删除本次 tour 创建的 memory，切断 spec 间耦合。
    await resetMemories(request, csrfHeaders, [])
  })
})
