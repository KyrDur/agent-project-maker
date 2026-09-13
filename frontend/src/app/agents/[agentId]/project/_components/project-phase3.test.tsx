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
    http.get(path, () => HttpResponse.json({ id: 'p1', title: 'Example', eval_spec_json: null })),
    http.get(`${path}/versions`, () => HttpResponse.json([version])),
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([])),
  ),
)

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
    http.post(`${path}/eval-sets/generate`, () => {
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
  await userEvent.click(await screen.findByRole('button', { name: '평가 계획 생성' }))
  expect(await screen.findByText('Complete the task')).toBeInTheDocument()
  expect(await screen.findByText('테스트 케이스 20개')).toBeInTheDocument()
  await userEvent.click(await screen.findByRole('button', { name: '테스트 케이스 20개 생성' }))
  await userEvent.click(
    await screen.findByRole('button', { name: /Generated example.*수정|수정.*Generated example/ }),
  )
  const mocks = screen.getByLabelText('모의 도구 데이터 (JSON)')
  await userEvent.clear(mocks)
  await userEvent.paste('{"search":{"result":["Edited source"]}}')
  await userEvent.click(screen.getByRole('button', { name: '케이스 저장' }))
  await waitFor(() =>
    expect(screen.queryByLabelText('모의 도구 데이터 (JSON)')).not.toBeInTheDocument(),
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
  expect(await screen.findByText('통과율 85%')).toBeInTheDocument()
  expect(await screen.findByText(/Revenue is absent from the sources/)).toBeInTheDocument()
  expect(await screen.findByText(/Revenue doubled/)).toBeInTheDocument()
})

it('reports generation failure without inserting sample scores or cases', async () => {
  server.use(http.post(`${path}/eval-spec/generate`, () => HttpResponse.json({}, { status: 422 })))
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '평가 계획 생성' }))
  expect(
    await screen.findByText('생성에 실패했습니다. 모델 자격증명을 확인하고 다시 시도하세요.'),
  ).toBeInTheDocument()
  expect(screen.queryByText('테스트 케이스 20개')).not.toBeInTheDocument()
})
