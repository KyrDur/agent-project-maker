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
const badCase = {
  case_id: 'c1',
  category: 'instruction_issue',
  root_cause: 'Retrieval is optional.',
  evidence: ['/actual_output'],
  recommended_target: 'instructions',
  suggested_fix: 'Require source retrieval.',
  observations: [{ reference: '/actual_output', value: 'Unsupported claim' }],
}
const group = {
  category: 'instruction_issue',
  case_ids: ['c1'],
  root_cause: 'Retrieval is optional.',
  target: 'instructions',
  proposed_change: 'Retrieve before answering.',
}
const run = {
  id: 'r1',
  version_id: 'v1',
  status: 'completed',
  created_at: '2026-09-12T01:00:00',
  metrics_json: { total: 20, passed: 15, failed: 5, errored: 0, pass_rate: 0.75 },
  comparison_json: { eval_spec: {} },
  results_json: [
    {
      case_id: 'c1',
      name: 'Source evidence case',
      input: 'Summarize',
      output: 'Unsupported claim',
      status: 'failed',
      tool_calls: [],
      assertions: [],
      latency_ms: 1,
      error: null,
    },
  ],
}
const comparison = {
  fixed_cases: ['c1', 'c2', 'c3', 'c4'],
  regressed_cases: ['c5'],
  still_failing_cases: ['c6'],
  still_passing_cases: [],
  pass_rate: { before: 0.75, after: 0.9, delta: 0.15 },
  metrics: { task_completion: { before: 0.7, after: 0.8, delta: 0.1 } },
  decision: 'accepted',
  reasons: ['pass_rate_improved'],
}
const state = {
  state: 'completed',
  root_run_id: 'r1',
  best_version_id: 'v2',
  stop_reason: 'candidate_not_improved',
  rounds: [
    { version_id: 'v2', parent_version_id: 'v1', run_id: 'r2', decision: 'accepted', comparison },
    { version_id: 'v3', parent_version_id: 'v2', run_id: 'r3', decision: 'rejected' },
  ],
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
    http.get(`${path}/eval-runs`, () => HttpResponse.json([run])),
    http.get(`${path}/compare`, () =>
      HttpResponse.json({ changes: [], evaluations: [null, null], same_dataset: true }),
    ),
  ),
)

async function openEvaluationTab() {
  await userEvent.click(await screen.findByRole('button', { name: /Evaluation/ }))
}

it('reads retained optimization outcomes and patch evidence after analysis', async () => {
  server.use(
    http.post(`${path}/eval-runs/r1/analyze`, () => {
      server.use(
        http.get(path, () =>
          HttpResponse.json({ id: 'p1', title: 'Example', report_json: { optimization: state } }),
        ),
        http.get(`${path}/versions`, () =>
          HttpResponse.json([
            { ...version, id: 'v3', version_number: 3, status: 'rejected' },
            { ...version, id: 'v2', version_number: 2, status: 'accepted' },
            version,
          ]),
        ),
        http.get(`${path}/eval-runs`, () =>
          HttpResponse.json([
            {
              ...run,
              bad_cases_json: [badCase],
              comparison_json: {
                ...run.comparison_json,
                analysis: { groups: [group] },
                optimization: state,
              },
            },
          ]),
        ),
      )
      return HttpResponse.json(state)
    }),
    http.get(`${path}/versions/v2`, () =>
      HttpResponse.json({
        ...version,
        id: 'v2',
        snapshot_json: {
          optimization: {
            patches: [
              {
                target: 'instructions',
                before: 'Old instructions',
                after: 'Old instructions\nRetrieve first.',
              },
            ],
          },
        },
      }),
    ),
  )
  const { container } = render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  await screen.findByText('Source evidence case · 失败')
  const summary = container.querySelector('summary')
  if (!summary) throw new Error('Run summary missing')
  await userEvent.click(summary)
  await userEvent.click(screen.getByRole('button', { name: '分析失败用例' }))
  expect(await screen.findByText(/Retrieve before answering/)).toBeInTheDocument()
  expect(await screen.findByText('最佳版本: V2')).toBeInTheDocument()
  expect(await screen.findByText('75% → 90%')).toBeInTheDocument()
  expect(await screen.findByText('已修复：4')).toBeInTheDocument()
  expect(await screen.findByText('退化用例：1')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: '查看更改' })[0])
  expect(await screen.findByText(/Retrieve first/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '生成 AI 优化建议' })).toBeEnabled()
  expect(
    screen.getAllByText('最佳版本是项目评测的结果，不会改变在线智能体的配置。').length,
  ).toBeGreaterThan(0)
})

it('keeps infrastructure-only analysis visible and disables optimization', async () => {
  server.use(
    http.get(`${path}/eval-runs`, () =>
      HttpResponse.json([
        {
          ...run,
          bad_cases_json: [
            { ...badCase, category: 'external_unfixable', root_cause: 'Judge unavailable' },
          ],
          comparison_json: { ...run.comparison_json, analysis: { groups: [] } },
        },
      ]),
    ),
  )
  const { container } = render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  await screen.findByText('Judge unavailable')
  const summary = container.querySelector('summary')
  if (!summary) throw new Error('Run summary missing')
  await userEvent.click(summary)
  expect(screen.getByRole('button', { name: '生成 AI 优化建议' })).toBeDisabled()
  expect(await screen.findByText('没有可以修复的失败用例。')).toBeInTheDocument()
})

it('retains request identity on failure and shows a safe error', async () => {
  const requests: unknown[] = []
  server.use(
    http.post(`${path}/eval-runs/r1/proposals`, async ({ request }) => {
      requests.push(await request.json())
      return HttpResponse.json({}, { status: 422 })
    }),
  )
  const { container } = render(<ProjectWorkbench agentId="agent-id" />)
  await openEvaluationTab()
  await screen.findByText('Source evidence case · 失败')
  const summary = container.querySelector('summary')
  if (!summary) throw new Error('Run summary missing')
  await userEvent.click(summary)
  await userEvent.click(screen.getByRole('button', { name: '生成 AI 优化建议' }))
  expect(
    await screen.findByText('操作未完成，请检查运行证据或模型状态后重试。'),
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '生成 AI 优化建议' }))
  await waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[0]).toEqual(requests[1])
})
