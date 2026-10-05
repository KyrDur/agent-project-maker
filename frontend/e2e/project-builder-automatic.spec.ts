import { test, expect, loginApi } from './fixtures'

const api = `http://localhost:${process.env.E2E_BACKEND_PORT ?? '8101'}`

for (const category of ['写作', '客服', '知识问答', '纯对话']) {
  test(`confirmed ${category} creation starts an automatic frozen V1 benchmark`, async ({
    request,
  }) => {
    const headers = await loginApi(request)
    const created = await request.post(`${api}/api/builder`, {
      headers,
      data: { user_request: `APM_PRACTICE_E2E: ${category}模拟助手` },
    })
    expect(created.status()).toBe(201)
    const session = await created.json()
    const path = `${api}/api/builder/${session.id}`
    const started = await request.post(`${path}/messages`, {
      headers,
      data: { content: `APM_PRACTICE_E2E: ${category}模拟助手`, locale: 'zh-CN' },
    })
    expect(started.ok()).toBeTruthy()
    expect(await started.text()).toContain('question_flow')
    const resume = async (value: unknown, approve = false) => {
      const response = await request.post(`${path}/messages/resume`, {
        headers,
        data: {
          locale: 'zh-CN',
          decisions: [
            approve ? { type: 'approve' } : { type: 'respond', message: JSON.stringify(value) },
          ],
        },
      })
      expect(response.ok()).toBeTruthy()
      return response.text()
    }
    const requirements = {
      goal: 'APM_PRACTICE_E2E：完成给定任务',
      inputs: '用户提供的事实',
      deliverables: '可核查答复',
      business_rules: '不执行外部操作，不虚构事实',
      success_conditions: '依据事实满足任务条件',
      requirements_reason: '固定响应验证需求传递与自动评测，不代表真实模型质量。',
      agent_name: `${category}模拟助手`,
      response_tone: 'professional',
      output_style: 'summary',
    }
    await resume({ mode: 'question_flow', answers: requirements })
    await resume({ approved: true, reason: '纯文本任务只需要指令，不添加无业务必要的工具。' })
    await resume({}, true)
    await resume({}, true)
    await resume({}, true)
    const built = await (await request.get(path)).json()
    expect(built.status, JSON.stringify(built)).toBe('completed')
    expect(built.intent.project_requirements.goal).toBe(requirements.goal)
    try {
      const projectPath = `${api}/api/agents/${built.agent_id}/project`
      await expect
        .poll(
          async () => {
            const project = await (await request.get(projectPath)).json()
            return project.requirements_json?.bootstrap
          },
          { timeout: 30000 },
        )
        .toMatchObject({ stage: 'results', error: null })
      const runs = await (await request.get(`${projectPath}/eval-runs`)).json()
      expect(runs).toHaveLength(1)
      expect(runs[0].status).toBe('completed')
      const fullRun = await (await request.get(`${projectPath}/eval-runs/${runs[0].id}`)).json()
      expect(fullRun.results_json).toHaveLength(20)
      await test.info().attach(`${category}-automatic-builder-v1.json`, {
        body: JSON.stringify(
          { validation_type: 'fixed_response', builder: built, runs: [fullRun] },
          null,
          2,
        ),
        contentType: 'application/json',
      })
    } finally {
      await test.info().attach(`${category}-automatic-builder-final-state.json`, {
        body: JSON.stringify(
          await (await request.get(`${api}/api/agents/${built.agent_id}/project`)).json(),
          null,
          2,
        ),
        contentType: 'application/json',
      })
      await request.delete(`${api}/api/agents/${built.agent_id}`, { headers })
    }
  })
}
