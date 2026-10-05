import type { APIRequestContext, Page } from '@playwright/test'
import { API_BASE, apiGetJson, apiPostJson, expect, isRecord, test, type CsrfHeaders } from '../fixtures'
import {
  approveExecuteInSkill,
  sendMessage,
  setupLangGraphV3Agent,
} from '../langgraph-v3-helpers'
import { capture, captureLocator, DESKTOP_VIEWPORT, settle, warmUpChatRoute } from './_capture-helpers'

/**
 * Wave 1 场景截图 — 以“Agent 团队的一天”的故事依次演示 Wave 1 功能：
 *
 *  第 1 幕 onboarding：OpenWiki template 一键 Agent → 空白界面 capability chip + usage_example starter
 *  第 2 幕 mission：E2E_LANGGRAPH_V3 run — mission control live → HITL approval →
 *               run 结束后仍保留的 checklist、subagent pill 结果摘要、
 *               artifact 代码高亮（wave1_demo.py）
 *  第 3 幕 cursor：E2E_SLOW_STREAM midstream 输入 caret
 *  第 4 幕 digest：schedule activity badge（overnight digest）— 通过 E2E activity helper 模拟
 *
 * Gated by E2E_CAPTURE_TOUR=1 (+ E2E_TEST_HELPERS_ENABLED, scripted model).
 */

const WAVE = 'wave1-scenario'
const OPENWIKI_TEMPLATE_NAME = 'OpenWiki 文档化 Agent'
const FINAL_TEXT = 'E2E LangGraph v3 validation complete'
const CODE_ARTIFACT = 'wave1_demo.py'

async function findOpenWikiTemplateId(request: APIRequestContext): Promise<string> {
  const templates = await apiGetJson(request, `${API_BASE}/api/templates`)
  if (!Array.isArray(templates)) throw new Error('templates list failed')
  const tpl = templates.find(
    (item) => isRecord(item) && item.name === OPENWIKI_TEMPLATE_NAME,
  )
  if (!isRecord(tpl) || typeof tpl.id !== 'string') throw new Error('OpenWiki template missing')
  return tpl.id
}

async function findScriptedModelId(request: APIRequestContext): Promise<string> {
  const models = await apiGetJson(request, `${API_BASE}/api/models`)
  if (!Array.isArray(models)) throw new Error('models list failed')
  const model = models.find((item) => isRecord(item) && item.provider === 'e2e_scripted')
  if (!isRecord(model) || typeof model.id !== 'string') throw new Error('scripted model missing')
  return model.id
}

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

test.describe('Wave 1 scenario captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('walks the Wave 1 story and captures every surface', async ({ page, request }) => {
    test.setTimeout(600_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const setup = await setupLangGraphV3Agent(request)
    const { csrfHeaders } = setup

    // ── 第 1 幕：onboarding — template 一键 Agent 的空白界面（capability chip + starter）──
    const templateId = await findOpenWikiTemplateId(request)
    const modelId = await findScriptedModelId(request)
    const onboardAgent = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
      name: OPENWIKI_TEMPLATE_NAME,
      system_prompt: 'wave1 onboarding demo',
      model_id: modelId,
      template_id: templateId,
      identity_mode: 'per_user',
    })
    if (!isRecord(onboardAgent) || typeof onboardAgent.id !== 'string') {
      throw new Error('template agent create failed')
    }
    await gotoChat(page, onboardAgent.id, 'new')
    const capabilities = page.locator('[data-moldy-empty-capabilities]')
    await expect(capabilities).toBeVisible({ timeout: 60_000 })
    await expect(capabilities.getByText('openwiki')).toBeVisible()
    const starter = page.locator('[data-moldy-empty-starters] button').first()
    await expect(starter).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '00-empty-state-capabilities-starter.png')

    await starter.click()
    await expect(page.locator('textarea[data-moldy-composer-input="true"]').last()).toHaveValue(
      /저장소의 위키를 만들어줘/,
      { timeout: 10_000 },
    )
    await settle(page)
    await capture(page, WAVE, '01-starter-filled-composer.png')

    // ── 第 2 幕：mission — 包含计划·委派·artifact 的完整 run ───────────
    const missionConversationId = await createConversation(
      request,
      csrfHeaders,
      setup.parentAgentId,
      'Wave1 mission run',
    )
    await gotoChat(page, setup.parentAgentId, missionConversationId)
    await sendMessage(
      page,
      `准备 viral report E2E_LANGGRAPH_V3 code_artifact=true subagent=${setup.childRuntimeName}`,
    )

    // mission control bar — streaming 时显示 live checklist。
    const missionControl = page.locator('[data-moldy-mission-control]')
    await expect(missionControl).toBeVisible({ timeout: 60_000 })
    await expect(missionControl.getByText('1/3 完成')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '02-mission-control-live.png')

    // HITL approval 2 次 — code_artifact 流程按 write_file → execute_in_skill 顺序
    // 依次 interrupt，frontend 将连续 approval card 分组显示。
    await expect(page.getByText(/승인이 필요합니다|Approval Required/).last()).toBeVisible({
      timeout: 90_000,
    })
    await approveExecuteInSkill(page)
    // 截取第二次 approval（skill 执行）加入 group card 的瞬间。group(compact)
    // 模式下没有单独的“需要批准”headline，因此不用 helper，而是直接点击剩余的
    // approval button。
    await expect(page.getByText(/승인 대기 2건/)).toBeVisible({ timeout: 90_000 })
    const pendingApprove = page.getByTestId('approval-approve-button')
    await expect
      .poll(async () => pendingApprove.count(), { timeout: 30_000, intervals: [500, 1_000] })
      .toBeGreaterThan(0)
    await settle(page)
    await capture(page, WAVE, '03-grouped-approvals.png')
    await pendingApprove.last().click()
    await expect(page.getByText(FINAL_TEXT).first()).toBeVisible({ timeout: 120_000 })

    // run 结束后 mission control 仍保留 — 展开后截图 checklist。
    await expect(missionControl).toBeVisible()
    await missionControl.getByText(/작업 계획|Task plan/).click()
    await expect(missionControl.getByText('Collect LangGraph v3 runtime evidence')).toBeVisible({
      timeout: 10_000,
    })
    await settle(page)
    await capture(page, WAVE, '04-mission-control-after-run.png')
    await missionControl.getByText(/작업 계획|Task plan/).click()

    // 已完成的 subagent pill — 折叠状态下也能看到结果第一行摘要。
    const subagentSummary = page.locator('[data-moldy-subagent-summary]').first()
    await expect(subagentSummary).toBeVisible({ timeout: 30_000 })
    await expect(subagentSummary).toContainText('E2E subagent')
    await settle(page)
    await capture(page, WAVE, '05-subagent-pill-summary.png')

    // artifact rail — 由 write_file 创建的 Python 文件会高亮显示。
    await page.getByRole('button', { name: /파일 패널|Artifacts/ }).click()
    const rail = page.getByRole('complementary')
    const codeArtifactButton = rail.getByRole('button', { name: new RegExp(CODE_ARTIFACT) }).last()
    await expect(codeArtifactButton).toBeVisible({ timeout: 30_000 })
    await codeArtifactButton.click()
    // highlighter 按 token 单位 span 渲染代码 — 通过 dataclass token 可见性验证。
    await expect(rail.getByText('dataclass').first()).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '06-artifact-code-highlight.png')

    // ── 第 3 幕：streaming 输入 caret（midstream）──────────────────────
    const caretConversationId = await createConversation(
      request,
      csrfHeaders,
      setup.parentAgentId,
      'Wave1 caret 演示',
    )
    await gotoChat(page, setup.parentAgentId, caretConversationId)
    await sendMessage(page, '用慢速回答展示 streaming E2E_SLOW_STREAM')
    const stopButton = page.locator('[data-moldy-stop-button="true"]:visible').last()
    await stopButton.waitFor({ state: 'visible', timeout: 30_000 })
    // slow stream 每个 chunk 0.75 秒 — 在流过约两个 chunk 时截取 caret。
    await page.waitForTimeout(1_800)
    await capture(page, WAVE, '07-streaming-caret.png')
    await stopButton.waitFor({ state: 'hidden', timeout: 90_000 })

    // ── 第 4 幕：overnight digest — schedule activity badge ──────────
    const activityResponse = await request.patch(
      `${API_BASE}/api/e2e/conversations/${missionConversationId}/activity`,
      {
        headers: csrfHeaders,
        data: { last_activity_source: 'schedule', unread_count: 3 },
      },
    )
    expect(activityResponse.ok()).toBe(true)
    await page.reload({ waitUntil: 'domcontentloaded' })
    const scheduleBadge = page.locator(
      `[data-moldy-schedule-activity="${missionConversationId}"]`,
    )
    await expect(scheduleBadge).toBeVisible({ timeout: 60_000 })
    await settle(page)
    await capture(page, WAVE, '08-schedule-digest-badge.png')
    const sessionRow = page.locator(
      `[data-chat-session-href*="${missionConversationId}"]`,
    )
    await captureLocator(sessionRow, WAVE, '09-schedule-digest-row.png')

    // ── 尾声：reload 恢复 — mission control 通过 thread state hydrate 恢复 ──
    await gotoChat(page, setup.parentAgentId, missionConversationId)
    await expect(missionControl).toBeVisible({ timeout: 60_000 })
    await expect(missionControl.getByText('1/3 完成')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '10-mission-control-after-reload.png')
  })
})
