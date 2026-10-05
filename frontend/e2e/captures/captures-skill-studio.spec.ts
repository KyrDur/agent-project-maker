import { API_BASE, apiDeleteOk, apiGetJson, apiPostJson, isRecord, loginApi, test } from '../fixtures'
import { capture, DESKTOP_VIEWPORT, scriptedModelId, settle } from './_capture-helpers'
import { expect, type APIRequestContext, type Page } from '@playwright/test'
import type { CsrfHeaders } from '../fixtures'

/**
 * Phase 2 — Skill Studio **按功能全量验证巡检**（20 张）。
 *
 * 不是罗列页面，而是在真实 backend 中逐一
 * 操作、断言并截图本次 release 的用户流程：列表表格/搜索/行操作/bulk 删除执行、连接真实计数、
 * source 编辑→生成 revision、version diff、read-only viewer、评估/设置 tab、发布 guard、
 * skill switcher 保持 tab、legacy deeplink redirect、builder scope/进入改进/index。
 * E2E_CAPTURE_TOUR=1 gate，前提为 scripted system LLM（E2E_LLM_* 置空）。
 */

const WAVE = 'skill-studio'

const SKILL_BODY_V1 =
  '---\nname: meeting-actions\ndescription: "Use when extracting action items from meeting notes."\n---\n\n从会议记录中提取 action item。\n'
const SKILL_BODY_V2 =
  '---\nname: meeting-actions\ndescription: "Use when extracting action items from meeting notes."\n---\n\n从会议记录中提取 action item。\n如果没有截止日期，则标记为 "待定"。\n'
const SKILL_BODY_V3_LINE = '负责人候选人仅限于参会人员列表。'

async function seedSkill(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  payload: { name: string; slug: string; description: string; content: string },
): Promise<string> {
  const created = await apiPostJson(request, `${API_BASE}/api/skills`, csrfHeaders, payload)
  if (!isRecord(created) || typeof created.id !== 'string') {
    throw new Error('skill seed failed')
  }
  return created.id
}

async function shot(page: Page, file: string): Promise<void> {
  await settle(page)
  await capture(page, WAVE, file)
}

test.describe('Skill studio captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT)
  })

  test('feature-by-feature studio verification tour', async ({ page, request }) => {
    test.setTimeout(480_000)
    const csrfHeaders = await loginApi(request)
    const skillIds: string[] = []
    let agentId: string | null = null
    // 幂等性 — 上一次 timeout run 的 finally 不会执行，因此（避免 slug unique 冲突
    // ）先清理相同 seed 的残留物。
    const TOUR_SLUGS = new Set([
      'meeting-actions',
      'weekly-report',
      'bulk-target-a',
      'bulk-target-b',
    ])
    const existingAgents = (await apiGetJson(request, `${API_BASE}/api/agents`)) as Array<
      Record<string, unknown>
    >
    for (const stale of existingAgents.filter((a) => a.name === '会议助手')) {
      await request
        .delete(`${API_BASE}/api/agents/${stale.id}`, { headers: csrfHeaders })
        .catch(() => {})
    }
    const existingSkills = (await apiGetJson(request, `${API_BASE}/api/skills`)) as Array<
      Record<string, unknown>
    >
    for (const stale of existingSkills.filter((s) => TOUR_SLUGS.has(String(s.slug)))) {
      await apiDeleteOk(request, `${API_BASE}/api/skills/${stale.id}`, csrfHeaders)
    }
    try {
      // ── seed：4 个 skill（主 skill A 有 2 个 revision）+ 1 个连接到 A 的 Agent ──
      const primary = await seedSkill(request, csrfHeaders, {
        name: '会议记录 action item',
        slug: 'meeting-actions',
        description: '整理会议记录中的负责人和截止日期。',
        content: SKILL_BODY_V1,
      })
      skillIds.push(primary)
      const updated = await request.put(`${API_BASE}/api/skills/${primary}/content`, {
        headers: csrfHeaders,
        data: { content: SKILL_BODY_V2 },
      })
      expect(updated.ok()).toBeTruthy()
      const secondary = await seedSkill(request, csrfHeaders, {
        name: '周报摘要',
        slug: 'weekly-report',
        description: '将周报总结为一页。',
        content: SKILL_BODY_V1.replace('meeting-actions', 'weekly-report'),
      })
      skillIds.push(secondary)
      for (const [name, slug] of [
        ['bulk 删除目标 A', 'bulk-target-a'],
        ['bulk 删除目标 B', 'bulk-target-b'],
      ] as const) {
        skillIds.push(
          await seedSkill(request, csrfHeaders, {
            name,
            slug,
            description: '用于验证批量删除的 skill。',
            content: SKILL_BODY_V1.replace('meeting-actions', slug),
          }),
        )
      }
      // 用于验证 used_by_count 真实汇总 — 使用 A 的 Agent。
      const modelId = await scriptedModelId(request)
      const agent = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
        name: '会议助手',
        description: '整理会议记录的 Agent',
        system_prompt: '整理会议记录中的 action item。',
        model_id: modelId,
        skill_ids: [primary],
      })
      if (isRecord(agent) && typeof agent.id === 'string') agentId = agent.id

      // ── 01. 列表表格 — 连接真实计数（M1 反向汇总）───────────────────
      await page.goto('/skills', { waitUntil: 'domcontentloaded', timeout: 90_000 })
      await expect(page.getByText('会议记录 action item')).toBeVisible({ timeout: 30_000 })
      const primaryRow = page.getByRole('row').filter({ hasText: '会议记录 action item' })
      await expect(primaryRow.getByText('1 个 Agent')).toBeVisible({ timeout: 15_000 })
      await shot(page, '01-list-table.png')

      // ── 02. 保持搜索筛选 ─────────────────────────────────────────
      await page.getByPlaceholder('搜索技巧').fill('会议记录')
      await expect(page.getByText('周报摘要')).toBeHidden({ timeout: 15_000 })
      await expect(page.getByText('会议记录 action item')).toBeVisible()
      await shot(page, '02-list-search.png')
      await page.getByPlaceholder('搜索技巧').fill('')
      await expect(page.getByText('周报摘要')).toBeVisible({ timeout: 15_000 })

      // ── 03. 行菜单（source/发布/无导出(text)/删除）──────────────────
      await primaryRow.getByRole('button', { name: '会议记录 action item 附加任务' }).click()
      await expect(page.getByRole('menuitem', { name: '查看源码' })).toBeVisible()
      await expect(page.getByRole('menuitem', { name: '发布' })).toBeVisible()
      await shot(page, '03-row-menu.png')
      await page.keyboard.press('Escape')

      // ── 04~06. bulk 选择 → 确认（列出名称）→ 执行删除/重置 ──────────
      for (const name of ['bulk 删除目标 A', 'bulk 删除目标 B']) {
        await page
          .getByRole('row')
          .filter({ hasText: name })
          .getByRole('checkbox', { name: '选择行' })
          .check()
      }
      await expect(page.getByTestId('skill-bulk-bar')).toContainText('已选择 2 个')
      await shot(page, '04-bulk-bar.png')

      await page.getByTestId('skill-bulk-bar').getByRole('button', { name: '删除' }).click()
      const bulkDialog = page.getByRole('alertdialog')
      await expect(bulkDialog).toContainText('删除 2 个 skill')
      await expect(bulkDialog).toContainText('bulk 删除目标 A')
      await expect(bulkDialog).toContainText('bulk 删除目标 B')
      await shot(page, '05-bulk-confirm.png')

      await bulkDialog.getByRole('button', { name: '删除' }).click()
      await expect(page.getByText('已删除 2 个 skill')).toBeVisible({ timeout: 20_000 })
      await expect(page.getByText('bulk 删除目标 A')).toBeHidden({ timeout: 15_000 })
      await expect(page.getByTestId('skill-bulk-bar')).toBeHidden()
      await shot(page, '06-bulk-deleted.png')

      // ── 07. 点击行 → source tab + context bar（连接 1）──────────────
      await page.getByText('会议记录 action item').click()
      await page.waitForURL(new RegExp(`/skills/${primary}/source`), { timeout: 30_000 })
      const contextBar = page.getByTestId('studio-context-bar')
      await expect(contextBar).toContainText('会议记录 action item')
      await expect(contextBar).toContainText('已连接 智能体')
      await expect(contextBar).toContainText('1')
      await shot(page, '07-source-tab.png')

      // ── 08. 直接编辑 source → 保存（=生成 revision，D2）─────────────
      const editor = page.getByRole('textbox')
      await expect(editor).toHaveValue(/미정/, { timeout: 15_000 })
      await editor.fill(`${SKILL_BODY_V2}${SKILL_BODY_V3_LINE}\n`)
      await page.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('已保存')).toBeVisible({ timeout: 20_000 })
      await shot(page, '08-source-saved.png')

      // ── 09. version tab — 3 个 revision + 刚保存内容的 diff ──────────
      await page.getByTestId('studio-tab-versions').click()
      await page.waitForURL(new RegExp(`/skills/${primary}/versions`))
      await expect(page.getByRole('heading', { name: 'revision 3', exact: true })).toBeVisible({
        timeout: 20_000,
      })
      const diffCard = page.getByTestId('revision-diff-card')
      await expect(diffCard).toContainText(`+ ${SKILL_BODY_V3_LINE}`, { timeout: 20_000 })
      await shot(page, '09-versions-diff.png')

      // ── 10. 查看此版本 source → read-only viewer ───────────────────
      await diffCard.getByRole('link', { name: '查看此版本的源代码' }).click()
      await page.waitForURL(/\/source\?revision=/)
      await expect(page.getByText('只读')).toBeVisible({ timeout: 20_000 })
      await expect(page.getByText(SKILL_BODY_V3_LINE)).toBeVisible()
      await expect(page.getByRole('button', { name: '保存文件' })).toBeHidden()
      await shot(page, '10-revision-source.png')
      await page.getByRole('link', { name: '查看当前版本' }).click()
      await page.waitForURL(new RegExp(`/skills/${primary}/source$`))

      // ── 11. 评估 tab（空 set 状态）────────────────────────────────
      await page.getByTestId('studio-tab-evaluation').click()
      await page.waitForURL(new RegExp(`/skills/${primary}/evaluation`))
      await expect(page.getByText('尚未设置评估')).toBeVisible({ timeout: 20_000 })
      await shot(page, '11-evaluation-tab.png')

      // ── 12~13. 设置 tab + 删除确认（连接警告，D1）──────────────────
      await page.getByTestId('studio-tab-settings').click()
      await page.waitForURL(new RegExp(`/skills/${primary}/settings`))
      await expect(page.getByText('元数据')).toBeVisible({ timeout: 20_000 })
      await expect(page.getByText('已连接 1 个 Agent')).toBeVisible()
      await shot(page, '12-settings-tab.png')

      await page.getByRole('button', { name: '删除技能' }).click()
      const deleteDialog = page.getByRole('alertdialog')
      await expect(deleteDialog).toContainText('已连接 1 个 Agent')
      await shot(page, '13-settings-delete-confirm.png')
      await deleteDialog.getByRole('button', { name: '取消' }).click()

      // ── 14. 进入发布（未发布 skill → 打开 wizard，canPublish guard）──
      await page.getByRole('button', { name: '发布' }).click()
      await expect(page.getByRole('dialog')).toBeVisible({ timeout: 20_000 })
      await shot(page, '14-publish-wizard.png')
      await page.keyboard.press('Escape')

      // ── 15~16. skill switcher — dropdown + 切换时保持 tab ───────────
      await page.getByTestId('studio-skill-switcher').click()
      await expect(page.getByRole('menuitem', { name: /주간 리포트 요약/ })).toBeVisible()
      await shot(page, '15-switcher-open.png')
      await page.getByRole('menuitem', { name: /주간 리포트 요약/ }).click()
      await page.waitForURL(new RegExp(`/skills/${secondary}/settings`), { timeout: 30_000 })
      await expect(contextBar).toContainText('周报摘要')
      await shot(page, '16-switched-keeps-tab.png')

      // ── 17. legacy deeplink redirect（M2b safety net）────────────────
      await page.goto(`/skills?detailId=${primary}&tab=history`, {
        waitUntil: 'domcontentloaded',
      })
      await page.waitForURL(new RegExp(`/skills/${primary}/versions`), { timeout: 30_000 })
      await expect(page.getByRole('heading', { name: 'revision 3', exact: true })).toBeVisible({
        timeout: 20_000,
      })
      await shot(page, '17-legacy-redirect.png')

      // ── 18. builder tab — 在 ?skillId= scope 中保持 context（review R）──
      await page.getByTestId('studio-tab-builder').click()
      await page.waitForURL(new RegExp(`/skills/builder\\?skillId=${primary}`))
      await expect(contextBar).toContainText('会议记录 action item')
      await expect(page.getByTestId('studio-tab-source')).toBeEnabled()
      await shot(page, '18-builder-scoped-index.png')

      // ── 19. 开始改进 → builder chat（seed workspace + 自动发送）──────
      await page.getByRole('button', { name: /회의록 액션 아이템 개선 시작/ }).click()
      await page.waitForURL(/\/skills\/builder\/[0-9a-f-]{36}/, { timeout: 60_000 })
      const improveSessionId = page.url().match(/builder\/([0-9a-f-]{36})/)?.[1] ?? ''
      expect(improveSessionId).not.toBe('')
      await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
      // improve seed — 原始 SKILL.md 会出现在 draft 文件列表中。
      await expect(page.getByTestId('skill-builder-rail')).toContainText('SKILL.md', {
        timeout: 30_000,
      })
      // 同时确认自动首条消息的 scripted 响应（处于可对话状态）。
      await expect(page.locator('[data-moldy-message-id]').first()).toBeVisible({
        timeout: 60_000,
      })
      await shot(page, '19-improve-builder-chat.png')

      // ── 20. builder index — **刚创建的 session** 已反映在 history 中（list invalidate）。
      // 为避免仅凭重新运行残留 session 也能通过的 tautology，按 session id 做 scope。
      await page.goto('/skills/builder', { waitUntil: 'domcontentloaded' })
      await expect(
        page
          .getByTestId('builder-session-list')
          .locator(`a[href="/skills/builder/${improveSessionId}"]`),
      ).toBeVisible({ timeout: 30_000 })
      await shot(page, '20-builder-index-history.png')
    } finally {
      if (agentId) {
        await request
          .delete(`${API_BASE}/api/agents/${agentId}`, { headers: csrfHeaders })
          .catch(() => {})
      }
      for (const id of skillIds) {
        await apiDeleteOk(request, `${API_BASE}/api/skills/${id}`, csrfHeaders)
      }
    }
  })
})
