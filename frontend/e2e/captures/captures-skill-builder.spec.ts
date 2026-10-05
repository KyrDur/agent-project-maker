import { test, expect, loginApi } from '../fixtures'
import { capture, DESKTOP_VIEWPORT, settle, warmUpChatRoute } from './_capture-helpers'

/**
 * Skill Builder chat 截图巡检 (skill-studio phase 1, spec §2 视觉证据)。
 *
 * 从 UI 入口开始，把完整流程以真实界面记录下来：
 * 进入（skill 列表 → 通过对话创建）→ builder route → 渐进编辑 → 验证 rail →
 * 测试 approval card + session consent → consent 后无卡片再次运行 → finalize card → 完成
 * banner/deeplink → reload replay → 已生成 skill 详情 → 通过对话改进（improve seed）→
 * session unavailable 状态。E2E_CAPTURE_TOUR=1 gate（普通运行时 skip）。
 *
 * 前提：throwaway stack + scripted system LLM (E2E_LLM_* 置空 — 参见 CHECKPOINT M6)。
 */

const WAVE = 'skill-builder-chat'

test.describe('Skill Builder chat — 全界面截图巡检', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('进入 → 编辑 → 验证 → consent → finalize → 改进完整巡检', async ({ page, request }) => {
    test.setTimeout(600_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await loginApi(request)

    const composer = page.locator('textarea[data-moldy-composer-input="true"]').last()

    // M8-1 之后，Enter 发送在 run 刚结束后也会立即生效（skill-builder-chat.spec contract）。
    const sendMessage = async (text: string) => {
      await composer.fill(text)
      await composer.press('Enter')
      await expect(composer).toHaveValue('', { timeout: 10_000 })
    }
    // M8-2 之后，approval 无需 retry，一次即可接受（skill-builder-chat.spec contract）。
    const approve = async () => {
      await page.getByTestId('approval-approve-button').last().click()
      await expect(
        page.getByText('无法发送批准响应。再试一次。'),
      ).toHaveCount(0)
    }

    // ── 1. 入口：skill 列表 ───────────────────────────────────────────
    await page.goto('/skills', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await expect(page.getByRole('button', { name: '通过聊天构建' }).first()).toBeVisible({
      timeout: 60_000,
    })
    await settle(page)
    await capture(page, WAVE, '01-skills-entry.png')

    // ── 2. 通过对话创建 dialog（chat tab）────────────────────────────
    await page.getByRole('button', { name: '通过聊天构建' }).first().click()
    const requestBox = page.locator('#skill-chat-request')
    await expect(requestBox).toBeVisible({ timeout: 15_000 })
    await requestBox.fill('帮我创建一个把会议记录中的负责人、待办事项和截止日期整理成表格的 skill')
    await settle(page, 300)
    await capture(page, WAVE, '02-create-dialog-chat.png')

    // ── 3. 开始对话 → builder route redirect ──────────────────────────
    await page.getByRole('button', { name: '开始聊天' }).click()
    await page.waitForURL(/\/skills\/builder\/[0-9a-f-]{36}/, { timeout: 120_000 })
    const sessionId = new URL(page.url()).pathname.split('/').pop() as string
    await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
    await expect(composer).toBeVisible({ timeout: 60_000 })
    // Phase 1.5 — dialog 请求会作为自动首条消息发出。响应完成后截图。
    await expect(page.getByText('E2E scripted document model is ready.').last()).toBeVisible({
      timeout: 60_000,
    })
    await settle(page)
    await capture(page, WAVE, '03-builder-entry.png')

    // ── 3b. 点击 try-hint → composer prefill（沿用 M7 mockup）──────────
    await page.getByTestId('builder-try-hint').click()
    await expect(composer).not.toHaveValue('')
    await settle(page, 300)
    await capture(page, WAVE, '03b-try-hint-prefill.png')

    // ── 4. 渐进编辑（write_file — 无 approval card，AD-3）─────────────
    await sendMessage(`E2E_SKILL_BUILDER_WRITE /skill-drafts/${sessionId}`)
    await expect(page.getByText('已写入 draft 文件').last()).toBeVisible({
      timeout: 45_000,
    })
    await settle(page)
    await capture(page, WAVE, '04-draft-written.png')

    // ── 5. 验证 + rail（moldy.skill_draft/skill_validation）────────────
    await sendMessage('E2E_SKILL_BUILDER_VALIDATE')
    await expect(page.getByText('已执行 draft 验证').last()).toBeVisible({
      timeout: 45_000,
    })
    const rail = page.getByTestId('skill-builder-rail')
    await expect(rail.getByTestId('builder-draft-files')).toBeVisible({ timeout: 30_000 })
    // M7 状态卡 — 验证行 + runtime compatibility chip 会由真实数据填充。
    await expect(rail.getByTestId('builder-status-rows')).toBeVisible({ timeout: 15_000 })
    await expect(rail.getByTestId('builder-runtime-chips')).toBeVisible({ timeout: 15_000 })
    await settle(page)
    await capture(page, WAVE, '05-validate-rail.png')

    // ── 5b. 查看 source — rail 切换为文件树 + read-only viewer（M7）──
    await page.getByTestId('builder-open-source').click()
    await expect(rail.getByTestId('builder-source-pane')).toBeVisible({ timeout: 15_000 })
    await expect(rail.getByTestId('builder-source-viewer')).toContainText('e2e-notes', {
      timeout: 30_000,
    })
    await settle(page)
    await capture(page, WAVE, '05b-source-pane.png')
    await page.getByTestId('builder-open-source').click()
    await expect(rail.getByTestId('builder-status-rows')).toBeVisible({ timeout: 15_000 })

    // ── 6. 测试 approval card + "留出本次会议的剩余时间" ───────────────
    await sendMessage('E2E_SKILL_BUILDER_TEST run=1')
    await expect(page.getByText('需要批准').last()).toBeVisible({ timeout: 45_000 })
    const consent = page.getByTestId('approval-session-consent').last()
    await expect(consent).toBeVisible()
    await consent.check()
    await settle(page, 300)
    await capture(page, WAVE, '06-test-approval-consent.png')

    // ── 7. 批准 → sandbox 执行完成 ──────────────────────────────────
    await approve()
    await expect(page.getByText('draft 测试执行已完成').last()).toBeVisible({
      timeout: 60_000,
    })
    await settle(page)
    await capture(page, WAVE, '07-test-executed.png')

    // ── 8. consent 后重新执行 — 无卡片 ───────────────────────────────
    await sendMessage('E2E_SKILL_BUILDER_RETEST run=2')
    await expect(page.getByText('draft 测试执行已完成').nth(1)).toBeVisible({
      timeout: 60_000,
    })
    await expect(page.getByText('需要批准')).toHaveCount(0)
    await settle(page)
    await capture(page, WAVE, '08-retest-no-card.png')

    // ── 9. finalize — 始终显示 approval card（无 consent 选项）──────
    await sendMessage('E2E_SKILL_BUILDER_FINALIZE')
    await expect(page.getByText('finalize_skill').last()).toBeVisible({ timeout: 45_000 })
    await expect(page.getByTestId('approval-session-consent')).toHaveCount(0)
    await settle(page, 300)
    await capture(page, WAVE, '09-finalize-card.png')

    // ── 10. 批准 → 完成 banner + deeplink ───────────────────────────
    await approve()
    await expect(page.getByText('已保存 skill').last()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('builder-completed-banner')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '10-finalized-completed.png')

    // ── 11. reload replay — 恢复 rail ───────────────────────────────
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('builder-draft-files')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('builder-completed-banner')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '11-reload-replay.png')

    // ── 12. deeplink → 已生成 skill source tab（Phase 2 studio）──────
    await page.getByRole('link', { name: '开放技能' }).click()
    await page.waitForURL(/\/skills\/[^/]+\/source/, { timeout: 60_000 })
    await expect(page.getByRole('button', { name: '通过聊天改进' })).toBeVisible({
      timeout: 30_000,
    })
    await settle(page)
    await capture(page, WAVE, '12-created-skill-detail.png')

    // ── 13. 通过对话改进 → improve session（原始 seed）──────────────
    await page.getByRole('button', { name: '通过聊天改进' }).click()
    await page.waitForURL(/\/skills\/builder\/[0-9a-f-]{36}/, { timeout: 120_000 })
    await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('改善', { exact: true }).first()).toBeVisible({ timeout: 15_000 })
    // Phase 1.5 — improve 默认请求("我想提高这项现有的技能。")也会自动发送。
    await expect(page.getByText('E2E scripted document model is ready.').last()).toBeVisible({
      timeout: 60_000,
    })
    await settle(page)
    await capture(page, WAVE, '13-improve-entry.png')

    // ── 14. 确认 improve seed — 验证 run 的 brief 显示原始文件 ───────
    await sendMessage('E2E_SKILL_BUILDER_VALIDATE')
    await expect(page.getByText('已执行 draft 验证').last()).toBeVisible({
      timeout: 45_000,
    })
    await expect(
      page.getByTestId('skill-builder-rail').getByTestId('builder-draft-files'),
    ).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '14-improve-seeded-rail.png')

    // ── 15. session unavailable 状态 ────────────────────────────────
    await page.goto('/skills/builder/00000000-0000-4000-8000-000000000000', {
      waitUntil: 'domcontentloaded',
    })
    await expect(page.getByText('构建器会话不可用')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '15-session-unavailable.png')
  })
})
