import JSZip from 'jszip'
import { test, expect, loginApi, isRecord } from './fixtures'
import { ONBOARDING_DISMISSED_FLAG, SUPER_USER_WELCOMED_FLAG } from '../src/lib/auth/session-flags'

const api = `http://localhost:${process.env.E2E_BACKEND_PORT ?? '8101'}`

for (const category of ['写作', '客服', '知识问答', '纯对话']) {
  test(`simulation practice ${category}: authored decisions and actual scripted execution`, async ({
    page,
    request,
  }) => {
    const headers = await loginApi(request)
    const models = await (await request.get(`${api}/api/models`)).json()
    const model = models.find((m: unknown) => isRecord(m) && m.provider === 'e2e_scripted')
    expect(model).toBeTruthy()
    const response = await request.post(`${api}/api/agents`, {
      headers,
      data: {
        name: `${category}模拟实践`,
        system_prompt: `APM_PRACTICE_E2E: ${category}: Answer the supplied task.`,
        model_id: model.id,
      },
    })
    expect(response.ok()).toBeTruthy()
    const agent = await response.json()
    const path = `${api}/api/agents/${agent.id}/project`
    try {
      expect((await request.post(`${path}/create`, { headers })).ok()).toBeTruthy()
      const versions = await (await request.get(`${path}/versions`)).json()
      const setResponse = await request.post(`${path}/eval-sets`, {
        headers,
        data: {
          name: `${category}固定响应验收`,
          cases: [
            {
              name: 'Scripted response',
              input: `APM_PRACTICE_E2E: Perform the ${category} task using supplied facts.`,
              judgment_basis: 'Complete the task using supplied facts and business conditions.',
              expected: { answer: 'Complete task using supplied facts.' },
            },
          ],
        },
      })
      expect(setResponse.ok()).toBeTruthy()
      let dataset = await setResponse.json()
      expect(
        (await request.post(`${path}/eval-sets/${dataset.id}/quality`, { headers })).ok(),
      ).toBeTruthy()
      await page
        .context()
        .addCookies([{ name: 'moldy_locale', value: 'zh-CN', domain: 'localhost', path: '/' }])
      await page.addInitScript(
        ({ onboarding, welcome }) => {
          sessionStorage.setItem(onboarding, '1')
          sessionStorage.setItem(welcome, '1')
        },
        { onboarding: ONBOARDING_DISMISSED_FLAG, welcome: SUPER_USER_WELCOMED_FLAG },
      )
      await page.goto(`/agents/${agent.id}/project`)
      await expect(page.getByLabel('任务目标')).toBeVisible({ timeout: 20000 })
      for (const [label, value] of [
        ['任务目标', `${category}任务`],
        ['输入与边界', '固定输入'],
        ['预期产物', '明确答复'],
        ['业务规则（无特殊规则也请明确说明）', '本用例无外部操作'],
        ['成功条件', '匹配固定响应，验证执行链路'],
      ])
        await page.getByLabel(label, { exact: true }).fill(value)
      await page.getByRole('button', { name: /保存需求/ }).click()
      await expect(page.getByText('已保存', { exact: true })).toBeVisible({ timeout: 15000 })
      for (const stage of ['requirements', 'capabilities']) {
        await page.getByLabel('决策阶段').click()
        await page
          .getByRole('option', {
            name: {
              requirements: '需求确认',
              capabilities: '能力方案选择',
              case_review: '用例抽查',
            }[stage],
            exact: true,
          })
          .click()
        await page.getByLabel('你的选择或抽查结论').fill(`${category}：${stage}`)
        await page
          .getByLabel('为什么这样选择')
          .fill('固定响应检查执行与记录链路；内容能力需要真实模型实验验证。')
        const saved = page.waitForResponse(
          (r) => r.url() === `${path}/decisions` && r.request().method() === 'POST',
        )
        await page.getByRole('button', { name: '保存决策与理由' }).click()
        expect((await saved).ok()).toBeTruthy()
      }
      const planResponse = await request.post(`${path}/eval-spec/generate`, {
        headers,
        data: { version_id: versions[0].id },
      })
      expect(planResponse.status(), await planResponse.text()).toBe(200)
      const generatedCases = await request.post(`${path}/eval-sets/generate`, {
        headers,
        data: { version_id: versions[0].id },
      })
      expect(generatedCases.status(), await generatedCases.text()).toBe(201)
      dataset = await generatedCases.json()
      expect(dataset.cases_json).toHaveLength(20)
      expect(
        (await request.post(`${path}/eval-sets/${dataset.id}/quality`, { headers })).ok(),
      ).toBeTruthy()
      const runResponse = await request.post(`${path}/eval-runs`, {
        headers,
        data: {
          request_id: crypto.randomUUID(),
          version_id: versions[0].id,
          eval_set_id: dataset.id,
        },
      })
      expect(runResponse.status()).toBe(202)
      const run = await runResponse.json()
      await expect
        .poll(
          async () => (await (await request.get(`${path}/eval-runs/${run.id}`)).json()).status,
          { timeout: 30000 },
        )
        .toBe('completed')
      const completed = await (await request.get(`${path}/eval-runs/${run.id}`)).json()
      expect(completed.results_json[0].model_calls.length).toBeGreaterThan(0)
      expect(completed.results_json[0].termination_reason).toBe('completed')
      expect(completed.comparison_json.decisions.length).toBeGreaterThanOrEqual(2)
      expect(completed.pass_rate).toBe(0)
      expect(completed.comparison_json.eval_spec.rubric_version).toBe(2)
      expect(completed.comparison_json.rule_validation.source).toBe('model_C_requirement_review')
      expect(completed.metrics_json.metric_scores.task_completion.evaluated_cases).toBe(20)
      expect(completed.results_json[0].metric_scores.task_completion.criteria_results).toHaveLength(
        2,
      )
      expect(
        completed.results_json[0].metric_scores.task_completion.criteria_results[0].evidence[0]
          .quote,
      ).toBeTruthy()
      expect(completed.results_json[0].judge_calls.length).toBeGreaterThan(0)
      const status = await (
        await request.post(`${path}/completion`, {
          headers,
          data: { analysis: '仅完成基线，不能伪造 V2 或宣称智能体合格。' },
        })
      ).json()
      expect(status.status).toBe('incomplete')
      expect(status.reasons).toContain('project_comparable_experiment_required')
      const generated = await request.post(`${path}/eval-runs/${run.id}/proposals`, {
        headers,
        data: { request_id: crypto.randomUUID() },
      })
      expect(generated.ok()).toBeTruthy()
      await page.reload()
      await page.getByRole('button', { name: '优化 优化闭环' }).click()
      const proposal = page.locator('article').filter({ hasText: '固定响应方案 1' })
      await expect(proposal).toBeVisible({ timeout: 15000 })
      await proposal.getByText('查看 智能体指令 变更', { exact: true }).click()
      await expect(
        proposal.locator('pre').filter({ hasText: 'Check business expectations before answering' }),
      ).toBeVisible()
      await proposal
        .getByRole('textbox')
        .fill('优先补充遗漏的业务条件；固定响应结果不代表真实模型能力。')
      const accepted = page.waitForResponse(
        (r) => r.url().endsWith('/decision') && r.request().method() === 'POST',
      )
      await proposal.getByRole('button', { name: '接受建议并创建新版本' }).click()
      expect((await accepted).ok()).toBeTruthy()
      const acceptedBody = await (await accepted).json()
      const candidate = { id: acceptedBody.regression_run_id }
      expect(candidate.id).toBeTruthy()
      await expect
        .poll(
          async () =>
            (await (await request.get(`${path}/eval-runs/${candidate.id}`)).json()).status,
          { timeout: 30000 },
        )
        .toBe('completed')
      const v2 = await (await request.get(`${path}/eval-runs/${candidate.id}`)).json()
      expect(v2.pass_rate).toBe(1)
      expect(v2.dataset_hash).toBeTruthy()
      expect(v2.dataset_hash).toBe(completed.dataset_hash)
      expect(v2.results_json.map((c: { case_id: string }) => c.case_id)).toEqual(
        completed.results_json.map((c: { case_id: string }) => c.case_id),
      )
      expect(v2.comparison_json.resolved_examinee).toEqual(
        completed.comparison_json.resolved_examinee,
      )
      await page.reload()
      await expect(page.getByLabel('发送消息', { exact: true })).toBeVisible()
      const chatMessage = 'APM_PRACTICE_E2E: hello'
      await page.getByLabel('发送消息', { exact: true }).fill(chatMessage)
      const sent = page.waitForResponse(
        (r) => r.url().includes('/simulation-sessions/') && r.url().endsWith('/messages'),
      )
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const sentResponse = await sent
      expect(sentResponse.ok()).toBeTruthy()
      const chat = await sentResponse.json()
      expect(chat.turns_json[0].evidence.model_calls.length).toBeGreaterThan(0)
      await expect(page.locator('article').filter({ hasText: chatMessage })).toBeVisible()
      await page.reload()
      await expect(page.locator('article').filter({ hasText: chatMessage })).toBeVisible()
      await page.getByText('查看本次执行日志', { exact: true }).click()
      await expect(page.getByText(/^结束原因:/)).toBeVisible()
      await expect(page.locator('pre').filter({ hasText: 'termination_reason' })).not.toBeVisible()
      const reset = page.waitForResponse(
        (r) => r.url().includes('/simulation-sessions/') && r.url().endsWith('/reset'),
      )
      await page.getByRole('button', { name: '重置模拟会话', exact: true }).click()
      expect((await reset).ok()).toBeTruthy()
      await expect(page.locator('article').filter({ hasText: chatMessage })).toHaveCount(0)
      const secondProposal = await request.post(`${path}/eval-runs/${candidate.id}/proposals`, {
        headers,
        data: { request_id: crypto.randomUUID() },
      })
      expect(secondProposal.ok()).toBeTruthy()
      const second = await secondProposal.json()
      const secondDecision = await request.post(
        `${path}/eval-runs/${candidate.id}/proposals/${second.id}/decision`,
        {
          headers,
          data: {
            decision: 'accepted',
            decision_reason: '依据 V2 的薄弱指标补充证据说明，继续验证而非宣称已改进。',
          },
        },
      )
      expect(secondDecision.ok()).toBeTruthy()
      const v3Id = (await secondDecision.json()).regression_run_id
      await expect
        .poll(async () => (await (await request.get(`${path}/eval-runs/${v3Id}`)).json()).status, {
          timeout: 30000,
        })
        .toBe('completed')
      const v3 = await (await request.get(`${path}/eval-runs/${v3Id}`)).json()
      expect(v3.dataset_hash).toBe(completed.dataset_hash)
      expect(v3.results_json.map((c: { case_id: string }) => c.case_id)).toEqual(
        completed.results_json.map((c: { case_id: string }) => c.case_id),
      )
      expect(v3.comparison_json.regression.source_run_id).toBe(candidate.id)
      const done = await (
        await request.post(`${path}/completion`, {
          headers,
          data: {
            analysis:
              'V1 遗漏业务条件，V2 补充检查。固定响应仅验证流程，真实模型及测试边界仍需另行验收。',
          },
        })
      ).json()
      expect(done.status).toBe('completed')
      const report = await (await request.post(`${path}/report/generate`, { headers })).json()
      const resume = await (
        await request.post(`${path}/resume/generate`, { headers, data: { style: 'ai_product' } })
      ).json()
      const interview = await (await request.get(`${path}/interview`)).json()
      expect(report.markdown).toContain('评分口径与覆盖')
      expect(report.markdown).toContain('/100')
      expect(report.markdown).toContain('评分覆盖 20/20')
      expect(report.evidence_hash).toBe(resume.evidence_hash)
      expect(report.evidence_hash).toBe(interview.evidence_hash)
      expect(report.evidence.results.baseline.pass_rate).toBe(1)
      expect(report.evidence.results.candidate.pass_rate).toBe(category === '客服' ? 0.95 : 1)
      expect(report.evidence.results.comparisons).toHaveLength(3)
      const exported = await request.get(`${path}/export`)
      expect(exported.ok()).toBeTruthy()
      const archive = await exported.body()
      expect(archive.subarray(0, 2).toString()).toBe('PK')
      const zip = await JSZip.loadAsync(archive)
      const readArtifact = async (name: string) => {
        const file = zip.file(`agent-project/${name}`)
        if (!file) throw new Error(`Missing export artifact: ${name}`)
        return file.async('string')
      }
      expect(await readArtifact('README.md')).toBe(report.markdown)
      const exportedResume = JSON.parse(await readArtifact('resume.json'))
      const exportedInterview = JSON.parse(await readArtifact('interview.json'))
      expect(exportedResume.evidence_hash).toBe(resume.evidence_hash)
      expect(exportedInterview.evidence_hash).toBe(interview.evidence_hash)
      await test.info().attach(`${category}-fixed-response-evidence.json`, {
        body: JSON.stringify(
          {
            validation_type: 'fixed_response',
            category,
            dataset,
            runs: [completed, v2, v3],
            report,
            resume,
            interview,
            completion: done,
          },
          null,
          2,
        ),
        contentType: 'application/json',
      })
      await test.info().attach(`${category}-materials.zip`, {
        body: archive,
        contentType: 'application/zip',
      })
    } finally {
      await request.delete(`${api}/api/agents/${agent.id}`, { headers })
    }
  })
}
