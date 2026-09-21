import { expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectEvaluationReport } from './project-evaluation-report'
import type { AgentProjectVersionSummary, EvaluationReport } from '../_lib/agent-project-types'

const path = 'http://localhost:8001/api/agents/agent-id/project/evaluation-reports'
const versions = [1, 2].map((n) => ({
  id: `v${n}`,
  version_number: n,
})) as AgentProjectVersionSummary[]
const first: EvaluationReport = {
  version_id: 'v1',
  eval_set_id: 'set1',
  evaluation_run_id: 'run1',
  status: 'completed',
  score: 0.5,
  metrics: { task_completion: 0.6 },
  total: 2,
  passed: 1,
  bad_case_count: 1,
  bad_cases: [{ case_id: 'c1', name: 'Missing answer', reasons: ['Required answer absent'] }],
  optimization_suggestions: ['Clarify instructions'],
  comparison_key: 'same',
  created_at: '2026-09-15T00:00:00Z',
}
const second: EvaluationReport = {
  ...first,
  version_id: 'v2',
  evaluation_run_id: 'run2',
  score: 1,
  metrics: { task_completion: 0.9 },
  passed: 2,
  bad_case_count: 0,
  bad_cases: [],
  optimization_suggestions: [],
  created_at: '2026-09-15T01:00:00Z',
}
function respond(reports: EvaluationReport[], active = false) {
  server.use(
    http.get(path, () => HttpResponse.json({ reports, best_run_ids: { same: 'run2' }, active })),
  )
}

it('shows scores, best version and percentage point differences', async () => {
  respond([second, first])
  render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  expect(await screen.findByText('+50 个百分点')).toBeInTheDocument()
  expect(screen.getByText('V2 · 100%')).toBeInTheDocument()
  expect(screen.getByText('60% → 90% · +30 个百分点')).toBeInTheDocument()
  expect(screen.getByText('共 2 条用例，通过 2 条')).toBeInTheDocument()
})

it('selects historical runs and keeps failures and suggestions tied to that run', async () => {
  respond([second, first])
  render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  await userEvent.click(await screen.findByRole('combobox', { name: '选择历史评估（版本 B）' }))
  await userEvent.click(await screen.findByRole('option', { name: /V1/ }))
  expect(await screen.findByText('Clarify instructions')).toBeInTheDocument()
  expect(screen.getByText('Bad Cases · 失败案例（1）')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Missing answer'))
  expect(screen.getByText('Required answer absent')).toBeVisible()
  expect(screen.getByText('-50 个百分点')).toBeInTheDocument()
})

it('withholds improvement for different datasets or failed runs', async () => {
  respond([{ ...second, comparison_key: 'other', score: null, status: 'failed' }, first])
  render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  expect(
    await screen.findByText('需要相同冻结数据、评分口径且有效的评估，才能计算提升幅度。'),
  ).toBeInTheDocument()
  expect(screen.queryByText('+50 个百分点')).not.toBeInTheDocument()
})

it('explains empty state and exposes retry on API errors', async () => {
  respond([])
  const view = render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  expect(await screen.findByText(/暂无评估报告，请选择版本/)).toBeInTheDocument()
  view.unmount()
  server.use(http.get(path, () => HttpResponse.json({}, { status: 500 })))
  render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  expect(await screen.findByRole('button', { name: /重试/ })).toBeInTheDocument()
})

it('automatically refreshes after an active evaluation finishes', async () => {
  let requests = 0
  server.use(
    http.get(path, () => {
      requests += 1
      return HttpResponse.json({
        reports: requests === 1 ? [] : [second, first],
        best_run_ids: { same: 'run2' },
        active: requests === 1,
      })
    }),
  )
  render(<ProjectEvaluationReport agentId="agent-id" versions={versions} />)
  expect(await screen.findByText(/评估或优化正在运行/)).toBeInTheDocument()
  expect(await screen.findByText('+50 个百分点', {}, { timeout: 4000 })).toBeInTheDocument()
})
