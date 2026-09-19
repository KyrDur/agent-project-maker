import { beforeEach, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectWorkbench } from './project-workbench'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const version = {
  id: 'v1',
  version_number: 1,
  status: 'original',
  created_at: '2026-09-12T00:00:00',
}
const spec = {
  version_id: 'v1',
  case_count: 20,
  pass_threshold: 0.7,
  categories: [
    'normal',
    'missing_information',
    'ambiguous',
    'tool_failure',
    'edge_case',
    'hallucination',
  ],
  metrics: [
    { name: 'task_completion', weight: 0.4, criteria: 'Complete the task' },
    { name: 'tool_correctness', weight: 0.3, criteria: 'Use source tools' },
    { name: 'groundedness', weight: 0.3, criteria: 'Use supported facts' },
  ],
  focus_options: [
    { id: 'tool_correctness', label: '工具调用正确性', description: 'Use source tools' },
    { id: 'groundedness', label: '事实依据与证据', description: 'Use supported facts' },
    { id: 'ambiguous', label: '模糊需求处理', description: 'Handle unclear requests' },
  ],
}
const item = {
  id: 'c1',
  name: 'Generated example',
  input: 'Summarize',
  context: [],
  expected: { answer: 'Use source facts', required_tools: ['search'], forbidden_tools: [] },
  tags: ['normal'],
  enabled: true,
  mock_tool_data: { search: { result: ['Login reviewed'] } },
}

beforeEach(() =>
  server.use(
    http.get(`${path}/report`, () => HttpResponse.json({ evidence: null, sections: [] })),
    http.get(`${path}/evaluation-reports`, () =>
      HttpResponse.json({ reports: [], best_run_ids: {}, active: false }),
    ),
    http.get(path, () => HttpResponse.json({ id: 'p1', title: 'Example', eval_spec_json: null })),
    http.get(`${path}/versions`, () => HttpResponse.json([version])),
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([])),
  ),
)

async function openEvaluationTab() {
  await userEvent.click(await screen.findByRole('button', { name: /Evaluation/ }))
}

it('generates a plan then cases and edits mocks using the existing editor', async () => {
  const dataset = { id: 's1', name: 'Generated', frozen: false, cases_json: [item] }
  server.use(
    http.post(`${path}/eval-spec/generate`, async ({ request }) => {
      expect(await request.json()).toEqual({ version_id: 'v1' })
      server.use(
        http.get(path, () =>
          HttpResponse.json({ id: 'p1', title: 'Example', eval_spec_json: spec }),
        ),
      )
      return HttpResponse.json(spec)
    }),
    http.post(`${path}/eval-sets/generate`, async ({ request }) => {
      expect(await request.json()).toEqual({
        version_id: 'v1',
        evaluation_focus: ['tool_correctness', 'groundedness'],
        evaluation_focus_reason: '重点确认工具和依据',
      })
      server.use(http.get(`${path}/eval-sets`, () => HttpResponse.json([dataset])))
      return HttpResponse.json(dataset)
    }),
    http.put(`${path}/eval-sets/s1`, async ({ request }) => {
      const body = (await request.json()) as { cases: (typeof item)[] }
      expect(body.cases[0].mock_tool_data.search.result).toEqual(['Edited source'])
      return HttpResponse.json({ ...dataset, cases_json: body.cases })
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  await userEvent.click(await screen.findByRole('button', { name: '生成评测计划' }))
  expect(await screen.findByText('Complete the task')).toBeInTheDocument()
  expect(await screen.findByText('20 个测试用例')).toBeInTheDocument()
  const generate = await screen.findByRole('button', { name: '生成 20 个测试用例' })
  expect(generate).toBeDisabled()
  await userEvent.click(screen.getByLabelText(/工具调用正确性/))
  await userEvent.click(screen.getByLabelText(/事实依据与证据/))
  await userEvent.type(
    screen.getByPlaceholderText(/正式使用前必须确认/),
    '重点确认工具和依据',
  )
  await userEvent.click(generate)
  await userEvent.click(
    await screen.findByRole('button', { name: /Generated example.*编辑|编辑.*Generated example/ }),
  )
  const mocks = screen.getByLabelText('模拟工具数据（JSON）')
  await userEvent.clear(mocks)
  await userEvent.paste('{"search":{"result":["Edited source"]}}')
  await userEvent.click(screen.getByRole('button', { name: '保存用例' }))
  await waitFor(() =>
    expect(screen.queryByLabelText('模拟工具数据（JSON）')).not.toBeInTheDocument(),
  )
})

it('shows pass rate, individual scores and failed-case evidence', async () => {
  server.use(
    http.get(`${path}/eval-runs`, () =>
      HttpResponse.json([
        {
          id: 'r1',
          version_id: 'v1',
          status: 'completed',
          created_at: '2026-09-12T01:00:00',
          metrics_json: {
            total: 20,
            passed: 17,
            failed: 3,
            errored: 0,
            pass_rate: 0.85,
            metric_scores: { groundedness: { score: 0.84, evaluated_cases: 20 } },
          },
          results_json: [
            {
              case_id: 'c1',
              name: 'Unsupported revenue',
              input: 'Summarize',
              output: 'Revenue doubled',
              expected: { answer: 'Only login review' },
              status: 'failed',
              tool_calls: [{ name: 'search' }],
              assertions: [],
              latency_ms: 20,
              error: null,
              metric_scores: {
                groundedness: {
                  score: 0.2,
                  passed: false,
                  method: 'llm_judge',
                  reason: 'Revenue is absent from the sources.',
                },
              },
            },
          ],
        },
      ]),
    ),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  expect(await screen.findByText('通过率85%')).toBeInTheDocument()
  expect(await screen.findByText(/Revenue is absent from the sources/)).toBeInTheDocument()
  expect(await screen.findByText(/Revenue doubled/)).toBeInTheDocument()
})

it('reports generation failure without inserting sample scores or cases', async () => {
  server.use(http.post(`${path}/eval-spec/generate`, () => HttpResponse.json({}, { status: 422 })))
  render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  await userEvent.click(await screen.findByRole('button', { name: '生成评测计划' }))
  expect(await screen.findByText('生成失败，请检查模型凭据后重试。')).toBeInTheDocument()
  expect(screen.queryByText('20 个测试用例')).not.toBeInTheDocument()
})
