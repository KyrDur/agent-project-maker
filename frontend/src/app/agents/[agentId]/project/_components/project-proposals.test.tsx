import { beforeEach, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import { ProjectProposals } from './project-proposals'
import { ProjectEvaluation } from './project-evaluation'
import type {
  AgentProjectVersionSummary,
  EvaluationRun,
  OptimizationProposal,
} from '../_lib/agent-project-types'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const versions = [1, 2].map((n) => ({
  id: `v${n}`,
  version_number: n,
})) as AgentProjectVersionSummary[]
const proposal: OptimizationProposal = {
  id: 'proposal1',
  source_version_id: 'v1',
  source_run_id: 'r1',
  eval_set_id: 'set1',
  status: 'pending',
  created_at: '2026-09-16T00:00:00Z',
  decided_at: null,
  version_id: null,
  affected_capabilities: ['workflow'],
  failure_patterns: [
    {
      category: 'instruction_issue',
      case_ids: ['c1'],
      root_cause: 'Missing refund verification',
      target: 'instructions',
      proposed_change: 'Verify identity first',
    },
  ],
  diffs: [
    {
      target: 'instructions',
      before: 'Help customers',
      after: 'Help customers. Verify identity.',
      reason: 'Fix refund workflow',
    },
  ],
  deferred_changes: [],
  can_accept: true,
}
const baseline = {
  id: 'r1',
  version_id: 'v1',
  status: 'completed',
  results_json: [{ case_id: 'c1', status: 'failed' }],
  comparison_json: { proposals: [] },
} as unknown as EvaluationRun
let runs: EvaluationRun[]
function Flow() {
  const query = useProjectEvaluation('agent-id').runs
  const run = query.data?.find((r) => r.id === 'r1')
  return run ? (
    <ProjectProposals agentId="agent-id" run={run} versions={versions} runs={query.data} />
  ) : null
}
beforeEach(() => {
  runs = [structuredClone(baseline)]
  server.use(
    http.get(path, () => HttpResponse.json({ id: 'p1', eval_spec_json: null })),
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json(runs)),
    http.post(`${path}/eval-runs/r1/proposals`, () => {
      runs[0].comparison_json = { proposals: [proposal] }
      return HttpResponse.json(proposal)
    }),
  )
})

it('reviews a preview, accepts a version, and runs the frozen regression', async () => {
  let accepted = false
  server.use(
    http.post(`${path}/eval-runs/r1/proposals/proposal1/decision`, async ({ request }) => {
      expect(await request.json()).toEqual({
        decision: 'accepted',
        decision_reason: '先修复身份校验',
      })
      accepted = true
      const result = {
        ...proposal,
        status: 'accepted' as const,
        version_id: 'v2',
        decision_reason: '先修复身份校验',
      }
      runs[0].comparison_json = { proposals: [result] }
      return HttpResponse.json(result)
    }),
    http.post(`${path}/eval-runs/r1/proposals/proposal1/regression`, async ({ request }) => {
      expect(await request.json()).toHaveProperty('request_id')
      const result = {
        ...baseline,
        id: 'r2',
        version_id: 'v2',
        status: 'completed' as const,
        comparison_json: { regression: { proposal_id: 'proposal1', source_run_id: 'r1' } },
      }
      runs = [result, runs[0]]
      return HttpResponse.json(result, { status: 202 })
    }),
  )
  render(<Flow />)
  await userEvent.click(await screen.findByRole('button', { name: '生成 AI 优化建议' }))
  expect(
    await screen.findByText((_, element) => {
      const text = element?.textContent ?? ''
      return (
        element?.tagName === 'P' &&
        text.includes('证据驱动优化方案') &&
        text.includes('待审核') &&
        text.includes('V1')
      )
    }),
  ).toBeInTheDocument()
  expect(accepted).toBe(false)
  await userEvent.click(screen.getByText('查看 instructions 变更'))
  expect(screen.getByText('Help customers. Verify identity.')).toBeVisible()
  await userEvent.type(
    screen.getByPlaceholderText(/优先修复工具调用/),
    '先修复身份校验',
  )
  await userEvent.click(screen.getByRole('button', { name: '接受建议并创建新版本' }))
  expect(await screen.findByText('已从 V1 创建 V2，原版本保持不变。')).toBeInTheDocument()
  expect(screen.getByText('选择理由：先修复身份校验')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '运行同一评测集回归' }))
  expect(await screen.findByRole('link', { name: '查看报告和版本比较' })).toHaveAttribute(
    'href',
    '#evaluation-report',
  )
  expect(screen.getByRole('button', { name: '新建一次回归评估' })).toBeEnabled()
})

it('retains rejected proposals and offers a new proposal', async () => {
  server.use(
    http.post(`${path}/eval-runs/r1/proposals/proposal1/decision`, async ({ request }) => {
      expect(await request.json()).toEqual({ decision: 'rejected', decision_reason: null })
      const result = { ...proposal, status: 'rejected' as const }
      runs[0].comparison_json = { proposals: [result] }
      return HttpResponse.json(result)
    }),
  )
  render(<Flow />)
  await userEvent.click(await screen.findByRole('button', { name: '生成 AI 优化建议' }))
  await userEvent.click(await screen.findByRole('button', { name: '拒绝建议' }))
  expect(await screen.findByText('已拒绝，建议和变更预览保留在历史中。')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '运行同一评测集回归' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '生成 AI 优化建议' })).toBeEnabled()
})

it('reuses the request ID after uncertain generation failure', async () => {
  const requests: unknown[] = []
  server.use(
    http.post(`${path}/eval-runs/r1/proposals`, async ({ request }) => {
      requests.push(await request.json())
      return HttpResponse.json({}, { status: 500 })
    }),
  )
  render(<Flow />)
  await userEvent.click(await screen.findByRole('button', { name: '生成 AI 优化建议' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '生成 AI 优化建议' }))
  await waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[0]).toEqual(requests[1])
})

it('requires quality approval before allowing an evaluation', async () => {
  let approved = false
  let submitted = false
  const dataset = () => ({
    id: 'set1',
    name: 'Refund cases',
    frozen: false,
    cases_json: [
      {
        id: 'c1',
        name: 'Refund',
        input: 'Refund order',
        expected: {},
        context: [],
        enabled: true,
        tags: [],
      },
    ],
    quality_report_json: approved ? { status: 'approved', overall_score: 1, issues: [] } : null,
  })
  server.use(
    http.get(`${path}/eval-sets`, () => HttpResponse.json([dataset()])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([])),
    http.post(`${path}/eval-sets/set1/quality`, () => {
      approved = true
      return HttpResponse.json(dataset())
    }),
    http.post(`${path}/eval-runs`, async ({ request }) => {
      expect(await request.json()).toMatchObject({ version_id: 'v2', eval_set_id: 'set1' })
      submitted = true
      return HttpResponse.json(baseline, { status: 202 })
    }),
  )
  render(<ProjectEvaluation agentId="agent-id" versions={[versions[1], versions[0]]} />)
  expect(await screen.findByRole('button', { name: '运行评测' })).toBeDisabled()
  await userEvent.click(await screen.findByRole('button', { name: '执行质量检查' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '运行评测' })).toBeEnabled())
  await userEvent.click(screen.getByRole('button', { name: '运行评测' }))
  await waitFor(() => expect(submitted).toBe(true))
})
