import { beforeEach, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectResults } from './project-results'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const evidence = {
  project: { name: 'Controlled project', goal: 'Source-grounded reports' },
  results: {
    best_version: 2,
    baseline: { pass_rate: 0.75, passed: 15, total: 20, metrics: {} },
    best: {
      pass_rate: 0.9,
      passed: 18,
      total: 20,
      metrics: { task_completion: { score: 0.83, evaluated_cases: 20 } },
    },
    metric_deltas: { task_completion: 0.105 },
  },
  versions: [
    { version: 1, best: false, decision: 'original', evaluation: { pass_rate: 0.75 } },
    { version: 2, best: true, decision: 'accepted', evaluation: { pass_rate: 0.9 } },
    { version: 3, best: false, decision: 'rejected', evaluation: { pass_rate: 0.85 } },
  ],
  limitations: ['Mock evaluation; production impact unvalidated.'],
}
const report = {
  evidence,
  evidence_hash: 'hash',
  markdown: 'Controlled report',
  sections: [
    { title: 'Final Results', body: 'Best Version: 2. Controlled evaluation: 75.0% → 90.0%' },
  ],
}

beforeEach(() => server.use(http.get(`${path}/report`, () => HttpResponse.json(report))))

it('shows the measured best, rejected latest, report, live chat and ZIP links', async () => {
  render(<ProjectResults agentId="agent-id" />)
  expect(await screen.findByText('最佳版本：2')).toBeInTheDocument()
  expect(screen.getByText(/V3.*rejected/)).toBeInTheDocument()
  expect(screen.getByText(/Mock evaluation/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '试用在线智能体' })).toHaveAttribute(
    'href',
    '/agents/agent-id',
  )
  expect(screen.getByRole('link', { name: '下载项目' })).toHaveAttribute('href', `${path}/export`)
  await userEvent.click(screen.getByRole('button', { name: '查看/隐藏报告' }))
  expect(screen.getByText(report.sections[0].body)).toBeInTheDocument()
})

it.each(['ai_product', 'product', 'engineering'])(
  'generates and copies %s resume using the selected style',
  async (style) => {
    const copy = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: copy },
    })
    server.use(
      http.post(`${path}/resume/generate`, async ({ request }) => {
        expect(await request.json()).toEqual({ style })
        return HttpResponse.json({
          style,
          bullets: ['Controlled evaluation: 75% to 90%.'],
          evidence_hash: 'hash',
        })
      }),
    )
    render(<ProjectResults agentId="agent-id" />)
    await userEvent.selectOptions(await screen.findByLabelText('简历风格'), style)
    await userEvent.click(screen.getByRole('button', { name: '生成/重新生成简历' }))
    expect(await screen.findByText('Controlled evaluation: 75% to 90%.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '复制项目要点' }))
    expect(copy).toHaveBeenCalledWith('Controlled evaluation: 75% to 90%.')
  },
)

it('creates and revokes a fixed public link', async () => {
  server.use(
    http.post(`${path}/share`, () => HttpResponse.json({ path: '/shared/projects/p/t' })),
    http.delete(`${path}/share`, () => HttpResponse.json({ path: null })),
  )
  render(<ProjectResults agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '创建/获取分享链接' }))
  expect(await screen.findByRole('link', { name: '打开公开案例' })).toHaveAttribute(
    'href',
    '/shared/projects/p/t',
  )
  await userEvent.click(screen.getByRole('button', { name: '撤销分享' }))
  expect(await screen.findByText('分享已撤销。')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '打开公开案例' })).not.toBeInTheDocument()
})
