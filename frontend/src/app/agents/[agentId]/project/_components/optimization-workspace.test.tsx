import { beforeEach, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'
import { OptimizationWorkspace } from './optimization-workspace'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const versions = [1, 2].map((n) => ({
  id: `v${n}`,
  version_number: n,
})) as AgentProjectVersionSummary[]
const completed = {
  id: 'abb6332f-old',
  version_id: 'v1',
  status: 'completed',
  created_at: '2026-10-06T12:00:00Z',
  metrics_json: { total: 1, complete: true },
  comparison_json: { eval_spec: {} },
  results_json: [{ case_id: 'c1', name: '订单查询', status: 'failed', metric_scores: {} }],
}
const running = {
  ...completed,
  id: '07bf291c-new',
  version_id: 'v2',
  status: 'running',
  created_at: '2026-10-06T13:00:00Z',
  metrics_json: { total: 20 },
}
beforeEach(() =>
  server.use(
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([running, completed])),
  ),
)

it('names runs by version and status and prevents optimizing partial regression results', async () => {
  let submitted = 0
  server.use(
    http.post(`${path}/eval-runs/:id/analyze`, () => {
      submitted++
      return HttpResponse.json({})
    }),
  )
  render(<OptimizationWorkspace agentId="agent-id" versions={versions} />)
  expect(await screen.findByRole('button', { name: /V2 · 运行中/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.queryByRole('button', { name: '07bf291c' })).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('已完成 1/20 条用例')
  expect(screen.getByRole('button', { name: '分析失败用例' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '生成 AI 优化建议' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '分析失败用例' }))
  expect(submitted).toBe(0)
  await userEvent.click(screen.getByRole('button', { name: /V1 · 已完成/ }))
  expect(screen.getByRole('button', { name: '分析失败用例' })).toBeEnabled()
  expect(screen.getByRole('button', { name: '生成 AI 优化建议' })).toBeEnabled()
})

it('explains backend readiness errors and clears mutation errors when switching runs', async () => {
  server.use(
    http.post(`${path}/eval-runs/abb6332f-old/analyze`, () =>
      HttpResponse.json(
        { error: { code: 'optimization_run_incomplete', message: 'optimization_run_incomplete' } },
        { status: 422 },
      ),
    ),
  )
  render(<OptimizationWorkspace agentId="agent-id" versions={versions} />)
  await userEvent.click(await screen.findByRole('button', { name: /V1 · 已完成/ }))
  await userEvent.click(screen.getByRole('button', { name: '分析失败用例' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('这次评测结果不完整')
  await userEvent.click(screen.getByRole('button', { name: /V2 · 运行中/ }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(screen.getByRole('status')).toHaveTextContent('结果完整后才能分析失败')
})
