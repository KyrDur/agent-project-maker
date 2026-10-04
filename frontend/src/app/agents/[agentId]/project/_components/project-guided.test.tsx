import { beforeEach, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { GuidedEvaluation } from './guided-evaluation'
import { ProjectProposals } from './project-proposals'
import { ProjectReliability } from './project-reliability'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import type {
  EvaluationRun,
  EvaluationSet,
  AgentProjectVersionSummary,
  OptimizationProposal,
} from '../_lib/agent-project-types'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const versions = [
  { id: 'v2', version_number: 2 },
  { id: 'v1', version_number: 1 },
] as AgentProjectVersionSummary[]
const cases = [0, 1, 2, 3].map((i) => ({
  id: `c${i}`,
  name: `Task ${i}`,
  input: `Course question ${i}`,
  context: [],
  expected: { answer: 'Cite course evidence', required_tools: [], forbidden_tools: [] },
  tags: [],
  enabled: true,
}))
const dataset = {
  id: 'set1',
  name: 'Course tests',
  cases_json: cases,
  frozen: false,
  created_at: '2026-09-20',
  rubric_json: { version_id: 'v1', purpose: 'development' },
  quality_report_json: null,
} as unknown as EvaluationSet
const proposal = {
  id: 'p1',
  source_version_id: 'v1',
  source_run_id: 'r1',
  status: 'pending',
  can_accept: true,
  created_at: '2026-09-20',
  affected_capabilities: ['conversation'],
  failure_patterns: [],
  diffs: [],
  deferred_changes: [],
  title: 'Cite first',
  what_changes: 'Require citations',
  why_it_may_work: 'Missing citations caused failures',
  benefits: [],
  risks: [],
} as unknown as OptimizationProposal
const baseline: EvaluationRun = {
  dataset_hash: 'dataset-hash',
  started_at: null,
  completed_at: null,
  error: null,
  id: 'r1',
  version_id: 'v1',
  eval_set_id: 'set1',
  created_at: '2026-09-20',
  status: 'completed',
  results_json: [
    {
      case_id: 'c0',
      name: 'Task 0',
      input: 'Question',
      expected: cases[0].expected,
      output: 'Unsupported',
      status: 'failed',
      assertions: [],
      tool_calls: [],
      latency_ms: 1,
      error: null,
    },
  ],
  metrics_json: { total: 1, passed: 0, quality_complete: true },
  comparison_json: { purpose: 'development', proposals: [proposal] },
}
let runs: EvaluationRun[]
let sets: EvaluationSet[]
function ProposalsFlow() {
  const data = useProjectEvaluation('agent-id').runs.data
  const run = data?.find((r) => r.id === 'r1')
  return run ? (
    <ProjectProposals agentId="agent-id" run={run} versions={versions} runs={data} guided />
  ) : null
}
beforeEach(() => {
  runs = []
  sets = [structuredClone(dataset)]
  server.use(
    http.get(path, () => HttpResponse.json({ id: 'p1', eval_spec_json: null })),
    http.get(`${path}/eval-sets`, () => HttpResponse.json(sets)),
    http.get(`${path}/eval-runs`, () => HttpResponse.json(runs)),
    http.get(`${path}/reliability/v2`, () =>
      HttpResponse.json({
        trials: [],
        calibration: { reviewed: 0, disagreements: 0, reviews: [] },
        limitations: [],
      }),
    ),
  )
})

it('shows three typical cases, checks structure then starts one full evaluation', async () => {
  const calls: string[] = []
  server.use(
    http.post(`${path}/eval-sets/set1/quality`, () => {
      calls.push('quality')
      sets[0] = { ...sets[0], quality_report_json: { status: 'approved' } } as EvaluationSet
      return HttpResponse.json(sets[0])
    }),
    http.post(`${path}/eval-runs`, async ({ request }) => {
      calls.push('run')
      expect(await request.json()).toMatchObject({ version_id: 'v1', eval_set_id: 'set1' })
      return HttpResponse.json({ ...baseline, status: 'pending' })
    }),
  )
  render(<GuidedEvaluation agentId="agent-id" versionId="v1" onImprove={() => {}} />)
  expect(await screen.findByText('Task 2')).toBeInTheDocument()
  expect(screen.queryByText('Task 3')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '案例方向符合需求，开始测试' }))
  await waitFor(() => expect(calls).toEqual(['quality', 'run']))
})
it('does not start a run when structural checks reject cases', async () => {
  let calls = 0
  server.use(
    http.post(`${path}/eval-sets/set1/quality`, () =>
      HttpResponse.json({ ...dataset, quality_report_json: { status: 'rejected' } }),
    ),
    http.post(`${path}/eval-runs`, () => {
      calls++
      return HttpResponse.json({})
    }),
  )
  render(<GuidedEvaluation agentId="agent-id" versionId="v1" onImprove={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: '案例方向符合需求，开始测试' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('案例结构检查未通过')
  expect(calls).toBe(0)
})
it('retains run request identity after a lost response', async () => {
  sets[0] = { ...dataset, quality_report_json: { status: 'approved' } } as EvaluationSet
  const ids: string[] = []
  server.use(
    http.post(`${path}/eval-runs`, async ({ request }) => {
      const body = (await request.json()) as { request_id: string }
      ids.push(body.request_id)
      return ids.length === 1
        ? HttpResponse.json({}, { status: 500 })
        : HttpResponse.json({ ...baseline, status: 'pending' })
    }),
  )
  render(<GuidedEvaluation agentId="agent-id" versionId="v1" onImprove={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: '案例方向符合需求，开始测试' }))
  await screen.findByRole('alert')
  await userEvent.click(screen.getByRole('button', { name: '案例方向符合需求，开始测试' }))
  await waitFor(() => expect(ids).toHaveLength(2))
  expect(ids[0]).toBe(ids[1])
})
it('does not show another version’s failures in the guided test', async () => {
  runs = [baseline]
  sets = [{ ...dataset, rubric_json: { version_id: 'v2' } }]
  render(<GuidedEvaluation agentId="agent-id" versionId="v2" onImprove={() => {}} />)
  await screen.findByText('Course tests')
  expect(screen.queryByText('Unsupported')).not.toBeInTheDocument()
})
it('accepts an AI reason and auto-tests, retaining a recoverable accepted version if regression fails', async () => {
  runs = [structuredClone(baseline)]
  const events: string[] = []
  const ids: string[] = []
  server.use(
    http.post(`${path}/eval-runs/r1/proposals/p1/decision`, async ({ request }) => {
      events.push('accept')
      expect(await request.json()).toMatchObject({ reason_source: 'ai_confirmed' })
      const accepted = {
        ...proposal,
        status: 'accepted' as const,
        version_id: 'v2',
        decision_reason: proposal.why_it_may_work,
        decision_reason_source: 'ai_confirmed' as const,
      }
      runs[0] = { ...runs[0], comparison_json: { proposals: [accepted] } }
      return HttpResponse.json(accepted)
    }),
    http.post(`${path}/eval-runs/r1/proposals/p1/regression`, async ({ request }) => {
      events.push('regression')
      ids.push(((await request.json()) as { request_id: string }).request_id)
      return ids.length === 1
        ? HttpResponse.json({}, { status: 500 })
        : HttpResponse.json({ ...baseline, id: 'r2', version_id: 'v2', status: 'pending' })
    }),
  )
  render(<ProposalsFlow />)
  await userEvent.click(await screen.findByRole('button', { name: '采纳这个建议并验证' }))
  await screen.findByRole('alert')
  expect(events).toEqual(['accept', 'regression'])
  expect(await screen.findByText(/已从 V1 创建 V2/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '运行同一评测集回归' }))
  await waitFor(() => expect(ids).toHaveLength(2))
  expect(ids[0]).toBe(ids[1])
  expect(events.filter((e) => e === 'accept')).toHaveLength(1)
})
it('requires reading reserved cases and sends a paired three-run validation request', async () => {
  runs = [
    {
      ...baseline,
      comparison_json: {
        ...baseline.comparison_json,
        proposals: [{ ...proposal, status: 'accepted', version_id: 'v2' }],
      },
    },
    {
      ...baseline,
      id: 'r2',
      version_id: 'v2',
      created_at: '2026-09-21',
      comparison_json: { regression: { source_run_id: 'r1', proposal_id: 'p1' } },
    },
  ]
  sets = [
    dataset,
    {
      ...dataset,
      id: 'holdout',
      name: 'Reserved course tests',
      frozen: true,
      rubric_json: { purpose: 'holdout', development_set_id: 'set1', source_version_id: 'v1' },
      quality_report_json: { status: 'approved' },
    } as EvaluationSet,
  ]
  let calls = 0
  server.use(
    http.post(`${path}/reliability/validate`, async ({ request }) => {
      calls++
      expect(await request.json()).toMatchObject({
        baseline_run_id: 'r1',
        candidate_version_id: 'v2',
        holdout_set_id: 'holdout',
        repetitions: 3,
      })
      return HttpResponse.json([])
    }),
  )
  render(<ProjectReliability agentId="agent-id" versionId="v2" versions={versions} />)
  const start = await screen.findByRole('button', { name: '确认案例，比较两个版本' })
  expect(start).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '阅读典型验证案例' }))
  await userEvent.click(start)
  await waitFor(() => expect(calls).toBe(1))
  expect(screen.getByText(/将新增 6 次评测/)).toBeInTheDocument()
})

it('requires a new test set when confirmed business requirements change', async () => {
  runs = [baseline]
  sets = [
    {
      ...dataset,
      rubric_json: {
        version_id: 'v1',
        purpose: 'development',
        business_contract: { content_hash: 'old-contract' },
      },
    },
  ]
  server.use(
    http.get(path, () =>
      HttpResponse.json({
        id: 'p1',
        eval_spec_json: null,
        requirements_json: { learning_brief: { content_hash: 'new-contract' } },
      }),
    ),
  )
  render(<GuidedEvaluation agentId="agent-id" versionId="v1" onImprove={() => {}} />)
  expect(await screen.findByRole('button', { name: '生成评测计划' })).toBeEnabled()
  await waitFor(() => expect(screen.queryByText('Course tests')).not.toBeInTheDocument())
  expect(screen.queryByText('Unsupported')).not.toBeInTheDocument()
})

it('compares a later iteration against the original dataset baseline', async () => {
  server.use(
    http.get(`${path}/reliability/v3`, () =>
      HttpResponse.json({
        trials: [],
        calibration: { reviewed: 0, disagreements: 0, reviews: [] },
        limitations: [],
      }),
    ),
  )
  const candidateVersions = [
    { id: 'v3', version_number: 3 },
    ...versions,
  ] as AgentProjectVersionSummary[]
  runs = [
    {
      ...baseline,
      comparison_json: {
        ...baseline.comparison_json,
        proposals: [{ ...proposal, status: 'accepted', version_id: 'v2' }],
      },
    },
    {
      ...baseline,
      id: 'r2',
      version_id: 'v2',
      created_at: '2026-09-21',
      comparison_json: {
        proposals: [
          {
            ...proposal,
            id: 'p2',
            source_version_id: 'v2',
            source_run_id: 'r2',
            status: 'accepted',
            version_id: 'v3',
          },
        ],
      },
    },
    {
      ...baseline,
      id: 'r3',
      version_id: 'v3',
      created_at: '2026-09-22',
      comparison_json: { regression: { source_run_id: 'r2', proposal_id: 'p2' } },
    },
  ]
  sets = [
    dataset,
    {
      ...dataset,
      id: 'holdout',
      frozen: true,
      rubric_json: { purpose: 'holdout', development_set_id: 'set1', source_version_id: 'v1' },
      quality_report_json: { status: 'approved' },
    } as EvaluationSet,
  ]
  let called = false
  server.use(
    http.post(`${path}/reliability/validate`, async ({ request }) => {
      expect(await request.json()).toMatchObject({
        baseline_run_id: 'r1',
        candidate_version_id: 'v3',
      })
      called = true
      return HttpResponse.json([])
    }),
  )
  render(<ProjectReliability agentId="agent-id" versionId="v3" versions={candidateVersions} />)
  await userEvent.click(await screen.findByRole('button', { name: '阅读典型验证案例' }))
  await userEvent.click(screen.getByRole('button', { name: '确认案例，比较两个版本' }))
  await waitFor(() => expect(called).toBe(true))
})
