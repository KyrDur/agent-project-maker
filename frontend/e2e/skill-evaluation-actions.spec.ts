import { mkdir } from 'node:fs/promises'
import path from 'node:path'

import { test, expect } from './fixtures'

const now = '2026-06-01T00:00:00.000Z'

const skill = {
  id: 'skill-visual',
  name: 'Korea Weather',
  slug: 'korea-weather',
  description: '稳定整理韩国天气响应。',
  kind: 'package',
  version: '0.1.0',
  storage_path: null,
  content_hash: 'hash-current',
  size_bytes: 2048,
  used_by_count: 1,
  package_metadata: null,
  health: {
    state: 'evaluation_running',
    label: '评估运行',
    reason: 'Latest evaluation is still running.',
    severity: 'info',
  },
  latest_evaluation_summary: {
    status: 'running',
    latest_run_id: 'run-active',
    evaluation_set_id: 'set-active',
    pass_rate: 0.5,
    skill_content_hash: 'hash-current',
    created_at: now,
    completed_at: null,
  },
  last_modified_at: now,
  created_at: now,
  updated_at: now,
  origin_summary: null,
  publication_summary: null,
  installation: null,
}

const activeEvaluationSet = {
  id: 'set-active',
  skill_id: 'skill-visual',
  name: '核心评估',
  description: '这是当前正在运行的响应质量评估。',
  source_kind: 'generated',
  evals: [{ input: '首尔天气摘要', expected: '简洁的韩语摘要' }],
  expectations_schema_version: 1,
  latest_run: {
    id: 'run-active',
    skill_id: 'skill-visual',
    evaluation_set_id: 'set-active',
    status: 'running',
    summary: { pass_rate: 0.5 },
    benchmark: null,
    case_results: null,
    error_message: null,
    cancellation_requested_at: null,
    cancellation_reason: null,
    skill_version: '0.1.0',
    skill_content_hash: 'hash-current',
    runner_model: 'gpt-5-mini',
    started_at: now,
    completed_at: null,
    created_at: now,
    updated_at: now,
  },
}

const completedEvaluationSet = {
  id: 'set-complete',
  skill_id: 'skill-visual',
  name: '回归评估',
  description: '应能够重新运行已完成的评估。',
  source_kind: 'generated',
  evals: [{ input: '釜山天气摘要', expected: '简洁的韩语摘要' }],
  expectations_schema_version: 1,
  latest_run: {
    id: 'run-complete',
    skill_id: 'skill-visual',
    evaluation_set_id: 'set-complete',
    status: 'completed',
    summary: { pass_rate: 0.92 },
    benchmark: null,
    case_results: null,
    error_message: null,
    cancellation_requested_at: null,
    cancellation_reason: null,
    skill_version: '0.1.0',
    skill_content_hash: 'hash-current',
    runner_model: 'gpt-5-mini',
    started_at: now,
    completed_at: '2026-06-01T00:01:00.000Z',
    created_at: now,
    updated_at: '2026-06-01T00:01:00.000Z',
  },
}

const credentialRequiredSkill = {
  ...skill,
  id: 'skill-needs-credentials',
  health: {
    state: 'needs_credentials',
    label: '所需凭据',
    reason: '必需凭据尚未连接。',
    severity: 'warning',
  },
  latest_evaluation_summary: {
    status: 'failed',
    latest_run_id: 'run-missing-credentials',
    evaluation_set_id: 'set-complete',
    pass_rate: 0.2,
    skill_content_hash: 'hash-current',
    created_at: now,
    completed_at: '2026-06-01T00:01:00.000Z',
  },
  credential_requirements: [
    {
      key: 'weather_key',
      definition_key: 'weather_api',
      required: true,
      label: 'Weather API',
      description: '这是天气 API key。',
      fields: ['api_key'],
      injection: 'env',
      scope: 'user',
    },
  ],
}

test.describe('Skill evaluation actions', () => {
  test('shows rerun and cancel controls in the installed skill evaluation tab', async ({
    page,
  }) => {
    let rerunRequested = false
    let cancelRequested = false

    await page.route('**/api/skills**', (route) => {
      const url = new URL(route.request().url())
      const method = route.request().method()
      const pathName = url.pathname

      if (method === 'GET' && pathName === '/api/skills') {
        return route.fulfill({ json: [skill] })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-visual') {
        return route.fulfill({ json: skill })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-visual/evaluations') {
        return route.fulfill({ json: [activeEvaluationSet, completedEvaluationSet] })
      }
      if (
        method === 'POST' &&
        pathName === '/api/skills/skill-visual/evaluations/set-complete/estimate'
      ) {
        return route.fulfill({
          json: {
            case_count: 1,
            model_call_count: 2,
            estimated_seconds: 8,
            timeout_seconds: 60,
            estimated_cost_usd: 0.0042,
            uses_baseline_comparison: true,
          },
        })
      }
      if (
        method === 'POST' &&
        pathName === '/api/skills/skill-visual/evaluations/set-complete/runs'
      ) {
        rerunRequested = true
        return route.fulfill({
          status: 201,
          json: {
            ...completedEvaluationSet.latest_run,
            id: 'run-rerun',
            status: 'queued',
            completed_at: null,
          },
        })
      }
      if (
        method === 'POST' &&
        pathName === '/api/skills/skill-visual/evaluations/set-active/runs/run-active/cancel'
      ) {
        cancelRequested = true
        return route.fulfill({
          json: {
            ...activeEvaluationSet.latest_run,
            status: 'cancelled',
            cancellation_requested_at: now,
            cancellation_reason: 'user_requested',
          },
        })
      }

      return route.fulfill({ status: 404, json: { detail: pathName } })
    })

    // Phase 2 studio — 验证 legacy deeplink 也会 redirect 到 evaluation tab route。
    await page.goto('/skills?detailId=skill-visual&tab=evaluation')
    await page.waitForURL(/\/skills\/skill-visual\/evaluation/)
    await expect(page.getByTestId('studio-context-bar')).toContainText('Korea Weather')
    await expect(page.getByRole('button', { name: '核心评估 取消评估' })).toBeVisible()
    await expect(page.getByRole('button', { name: '回归评估 重新运行评估' })).toBeVisible()

    const captureDir = path.resolve(
      process.cwd(),
      '../output/e2e-captures/20260615-skill-eval-actions',
    )
    await mkdir(captureDir, { recursive: true })
    await page.screenshot({
      path: path.join(captureDir, 'evaluation-tab-actions.png'),
      fullPage: false,
    })

    await page.getByRole('button', { name: '回归评估 重新运行评估' }).click()
    await expect(page.getByRole('alertdialog', { name: '确认评估运行' })).toBeVisible()
    await page.screenshot({
      path: path.join(captureDir, 'evaluation-estimate-confirmation.png'),
      fullPage: false,
    })
    await page.getByRole('button', { name: '评估运行' }).click()
    await expect(page.getByRole('alertdialog', { name: '确认评估运行' })).toBeHidden()
    await expect.poll(() => rerunRequested).toBe(true)

    await page.getByRole('button', { name: '核心评估 取消评估' }).click()

    await expect.poll(() => cancelRequested).toBe(true)
  })

  test('opens the credentials tab instead of rerunning when required credentials are missing', async ({
    page,
  }) => {
    let estimateRequested = false

    await page.route('**/api/skills**', (route) => {
      const url = new URL(route.request().url())
      const method = route.request().method()
      const pathName = url.pathname

      if (method === 'GET' && pathName === '/api/skills') {
        return route.fulfill({ json: [credentialRequiredSkill] })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-needs-credentials') {
        return route.fulfill({ json: credentialRequiredSkill })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-needs-credentials/evaluations') {
        return route.fulfill({ json: [completedEvaluationSet] })
      }
      if (
        method === 'POST' &&
        pathName === '/api/skills/skill-needs-credentials/evaluations/set-complete/estimate'
      ) {
        estimateRequested = true
        return route.fulfill({ status: 409, json: { detail: 'credentials required' } })
      }
      if (
        method === 'GET' &&
        pathName === '/api/skills/skill-needs-credentials/credential-requirements'
      ) {
        return route.fulfill({ json: credentialRequiredSkill.credential_requirements })
      }
      if (
        method === 'GET' &&
        pathName === '/api/skills/skill-needs-credentials/credential-bindings'
      ) {
        return route.fulfill({ json: [] })
      }

      return route.fulfill({ status: 404, json: { detail: pathName } })
    })

    await page.goto('/skills?detailId=skill-needs-credentials&tab=evaluation')
    await page.waitForURL(/\/skills\/skill-needs-credentials\/evaluation/)
    await expect(page.getByRole('button', { name: '回归评估 连接凭据' })).toBeVisible()

    await page.getByRole('button', { name: '回归评估 连接凭据' }).click()

    // 在 studio 中连接凭据会跳转到 settings tab（D1）。
    await page.waitForURL(/\/skills\/skill-needs-credentials\/settings/)
    await expect(page.getByTestId('studio-tab-settings')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByText('1 个必需凭据未连接')).toBeVisible()
    await expect(page.getByText('weather_api')).toBeVisible()
    await expect.poll(() => estimateRequested).toBe(false)

    const captureDir = path.resolve(
      process.cwd(),
      '../output/e2e-captures/20260615-skill-eval-actions',
    )
    await mkdir(captureDir, { recursive: true })
    await page.screenshot({
      path: path.join(captureDir, 'evaluation-missing-credentials.png'),
      fullPage: false,
    })
  })
})
