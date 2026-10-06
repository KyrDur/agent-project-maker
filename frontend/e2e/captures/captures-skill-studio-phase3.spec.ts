import { API_BASE, apiDeleteOk, apiGetJson, apiPostJson, isRecord, loginApi, test } from '../fixtures'
import { capture, DESKTOP_VIEWPORT, settle } from './_capture-helpers'
import { expect, type APIRequestContext, type Page } from '@playwright/test'
import type { CsrfHeaders } from '../fixtures'

/**
 * Phase 3 — 实测评估指标 **按功能验证巡检**（8 张）。
 *
 * 在真实 backend 上跨两个版本实际运行评估 run（llm-2 scripted arm），并
 * 逐项操作、断言并截图 A/B benchmark 实测 badge、run 实际成本、各版本通过率、history badge、case/skill
 * human feedback、基于真实单价的 estimate。
 *
 * gate：E2E_CAPTURE_TOUR=1 + **E2E_SKILL_EVALUATION_ENABLED=true**
 *（playwright webServer 传递给 backend SKILL_EVALUATION_ENABLED）。
 * 前提：scripted system LLM（E2E_LLM_* 置空 + fresh throwaway DB）。
 */

const WAVE = 'skill-studio-phase3'

const SKILL_SLUG = 'phase3-meeting-actions'
const SKILL_BODY_V1 =
  '---\nname: phase3-meeting-actions\ndescription: "Use when extracting action items from meeting notes."\n---\n\n从会议记录中提取 action item 并整理成表格。\n'
const SKILL_BODY_V2 = `${SKILL_BODY_V1}如果没有截止日期，则标记为 "待定"。\n`

async function shot(page: Page, file: string): Promise<void> {
  await settle(page)
  await capture(page, WAVE, file)
}

async function createEvaluationRunAndWait(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  skillId: string,
  setId: string,
): Promise<void> {
  const run = await apiPostJson(
    request,
    `${API_BASE}/api/skills/${skillId}/evaluations/${setId}/runs`,
    csrfHeaders,
    {},
  )
  if (!isRecord(run) || typeof run.id !== 'string') {
    throw new Error('evaluation run create failed')
  }
  await expect
    .poll(
      async () => {
        const runs = (await apiGetJson(
          request,
          `${API_BASE}/api/skills/${skillId}/evaluations/${setId}/runs`,
        )) as Array<Record<string, unknown>>
        const row = runs.find((item) => item.id === run.id)
        return typeof row?.status === 'string' ? row.status : 'missing'
      },
      { timeout: 120_000, intervals: [1_000] },
    )
    .toBe('completed')
}

test.describe('Skill studio phase 3 captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT)
  })

  test('measured evaluation metrics verification tour', async ({ page, request }) => {
    test.setTimeout(480_000)
    const csrfHeaders = await loginApi(request)
    const skillIds: string[] = []

    // 幂等性 — 清理上一次 timeout run 残留的 seed。
    const existingSkills = (await apiGetJson(request, `${API_BASE}/api/skills`)) as Array<
      Record<string, unknown>
    >
    for (const stale of existingSkills.filter((s) => s.slug === SKILL_SLUG)) {
      await apiDeleteOk(request, `${API_BASE}/api/skills/${stale.id}`, csrfHeaders)
    }

    try {
      // ── seed：skill v1 → eval set → 实测 run 1 ───────────────────────
      const created = await apiPostJson(request, `${API_BASE}/api/skills`, csrfHeaders, {
        name: 'Phase3 会议记录 action',
        slug: SKILL_SLUG,
        description: '整理会议记录中的负责人和截止日期。',
        content: SKILL_BODY_V1,
        version: '1.0.0',
      })
      if (!isRecord(created) || typeof created.id !== 'string') throw new Error('seed failed')
      const skillId = created.id
      skillIds.push(skillId)

      const evalSet = await apiPostJson(
        request,
        `${API_BASE}/api/skills/${skillId}/evaluations`,
        csrfHeaders,
        {
          name: '实测 A/B smoke',
          description: '有/无 skill 实测对比',
          evals: [
            { input: '从会议记录中提取负责人和截止日期', expected: '负责人/截止日期表格' },
            { input: '整理本周的 action item', expected: 'action item 表格' },
          ],
        },
      )
      if (!isRecord(evalSet) || typeof evalSet.id !== 'string') throw new Error('set seed failed')
      const setId = evalSet.id

      await createEvaluationRunAndWait(request, csrfHeaders, skillId, setId)

      // ── 升级版本（1.1.0 + 正文 v2）后运行 run 2 — 生成按版本通过率轴 ──
      const contentUpdated = await request.put(`${API_BASE}/api/skills/${skillId}/content`, {
        headers: csrfHeaders,
        data: { content: SKILL_BODY_V2 },
      })
      expect(contentUpdated.ok()).toBeTruthy()
      const versionBumped = await request.patch(`${API_BASE}/api/skills/${skillId}`, {
        headers: csrfHeaders,
        data: { version: '1.1.0' },
      })
      expect(versionBumped.ok()).toBeTruthy()
      await createEvaluationRunAndWait(request, csrfHeaders, skillId, setId)

      // ── 01. 评估 tab 全景 — usage card + feedback card + version panel ──
      await page.goto(`/skills/${skillId}/evaluation`, {
        waitUntil: 'domcontentloaded',
        timeout: 90_000,
      })
      const usageCard = page.getByTestId('skill-usage-summary-card')
      await expect(usageCard).toBeVisible({ timeout: 30_000 })
      // 实测 usage — 2 次评估 run 已写入 skill 维度账本。
      await expect(usageCard).toContainText('评估运行', { timeout: 15_000 })
      await expect(usageCard).toContainText('2')
      await expect(page.getByTestId('skill-feedback-card')).toBeVisible()
      await shot(page, '01-evaluation-overview.png')

      // ── 02. 各版本通过率 — 1.0.0/1.1.0 两个轴 ─────────────────────
      const versionPanel = page.getByTestId('skill-version-pass-rate-panel')
      await expect(versionPanel).toContainText('1.0.0', { timeout: 15_000 })
      await expect(versionPanel).toContainText('1.1.0')
      await expect(versionPanel.getByTestId('skill-metric-bar')).toHaveCount(2)
      await shot(page, '02-version-pass-rates.png')

      // ── 03. A/B benchmark — 实测 badge + with/without bar + delta ───
      const benchmark = page.getByTestId('skill-benchmark-panel')
      await expect(benchmark.getByTestId('benchmark-measured')).toBeVisible({ timeout: 15_000 })
      await expect(benchmark).toContainText('有技巧')
      await expect(benchmark).toContainText('没有技巧')
      // scripted grader: with=pass(0.95), without=fail(0.3) — 实测为正 delta。
      await expect(benchmark).toContainText('通过率差值')
      await shot(page, '03-ab-benchmark.png')

      // ── 04. run 实测用量行 — model call/token/cost ───────────────────
      const usageLine = page.getByTestId('run-usage-line')
      await expect(usageLine).toContainText('model call', { timeout: 15_000 })
      await expect(usageLine).toContainText('Token 数')
      await shot(page, '04-run-measured-usage.png')

      // ── 05. case feedback — 不同意判定 + 保存 comment ────────────────
      const disagree = page.getByTestId('case-feedback-disagree-0')
      await disagree.scrollIntoViewIfNeeded()
      await disagree.click()
      await expect
        .poll(
          async () => {
            const runs = (await apiGetJson(
              request,
              `${API_BASE}/api/skills/${skillId}/evaluations/${setId}/runs`,
            )) as Array<Record<string, unknown>>
            const latest = runs.find((row) => row.status === 'completed')
            if (!latest) return []
            const rows = (await apiGetJson(
              request,
              `${API_BASE}/api/skills/${skillId}/evaluations/${setId}/runs/${latest.id}/case-feedback`,
            )) as Array<Record<string, unknown>>
            return rows.map((row) => `${row.case_index}:${row.verdict}`)
          },
          { timeout: 20_000 },
        )
        .toContain('0:disagree')
      await shot(page, '05-case-feedback.png')

      // ── 06. skill feedback — 有帮助 + 计数更新 ───────────────────────
      const upButton = page.getByTestId('skill-feedback-up')
      await upButton.scrollIntoViewIfNeeded()
      await upButton.click()
      await expect(upButton).toContainText('1', { timeout: 15_000 })
      await shot(page, '06-skill-feedback.png')

      // ── 07. estimate dialog — 基于真实单价的预估成本 + 执行模型 ───────
      await page
        .getByRole('button', { name: /重新运行/ })
        .first()
        .click()
      await expect(page.getByTestId('estimate-cost')).toBeVisible({ timeout: 20_000 })
      await shot(page, '07-estimate-dialog.png')
      await page.keyboard.press('Escape')

      // ── 08. history（version）tab — revision 行通过率 badge ───────────
      await page.getByTestId('studio-tab-versions').click()
      await page.waitForURL(new RegExp(`/skills/${skillId}/versions`), { timeout: 30_000 })
      await expect(page.getByTestId('revision-pass-rate').first()).toBeVisible({
        timeout: 20_000,
      })
      await shot(page, '08-history-pass-rate-badges.png')
    } finally {
      for (const id of skillIds) {
        await apiDeleteOk(request, `${API_BASE}/api/skills/${id}`, csrfHeaders)
      }
    }
  })
})
