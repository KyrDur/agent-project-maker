import { render as renderDirect } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NextIntlClientProvider, createTranslator } from 'next-intl'
import zhMessages from '../../../../../../messages/zh-CN.json'
import { beforeEach, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectWorkbench } from './project-workbench'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const project = { id: 'project-id', title: 'Example Agent', agent_id: 'agent-id' }
const versions = [
  {
    id: 'version-id',
    project_id: 'project-id',
    version_number: 1,
    status: 'original',
    created_at: '2026-09-12T09:00:00',
  },
]
const create = vi.fn()

beforeEach(() => {
  create.mockReset()
  server.use(
    http.get(`${path}/report`, () => HttpResponse.json({ evidence: null, sections: [] })),
    http.get(`${path}/evaluation-reports`, () =>
      HttpResponse.json({ reports: [], best_run_ids: {}, active: false }),
    ),
    http.get(path, () => HttpResponse.json(null)),
    http.post(`${path}/create`, () => {
      create()
      return HttpResponse.json(project)
    }),
    http.get(`${path}/versions`, () => HttpResponse.json(versions)),
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([])),
  )
})

it('waits for explicit creation and then opens the lifecycle overview', async () => {
  render(<ProjectWorkbench agentId="agent-id" />)
  const button = await screen.findByRole('button', { name: '创建项目' })
  expect(create).not.toHaveBeenCalled()
  await userEvent.click(button)
  expect(await screen.findByText('Example Agent')).toBeInTheDocument()
  expect(await screen.findByText('生命周期进度')).toBeInTheDocument()
  expect(screen.getByText('当前版本')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Evaluation/ }))
  expect(screen.getByRole('button', { name: '运行评测' })).toBeDisabled()
  expect(create).toHaveBeenCalledOnce()
})

it('loads an existing project without creating another one', async () => {
  server.use(http.get(path, () => HttpResponse.json(project)))
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(await screen.findByText('生命周期进度')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Overview/ })).toHaveAttribute('aria-current', 'page')
  expect(create).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '创建项目' })).not.toBeInTheDocument()
})

it('uses real lifecycle data for best version, latest evaluation and optimization entry', async () => {
  const proposal = {
    id: 'proposal-id',
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
        root_cause: '需要先检索资料。',
        target: 'instructions',
        proposed_change: '回答前先检索资料。',
      },
    ],
    diffs: [],
    deferred_changes: [],
    can_accept: true,
  }
  server.use(
    http.get(path, () => HttpResponse.json(project)),
    http.get(`${path}/versions`, () =>
      HttpResponse.json([
        { ...versions[0], id: 'v2', version_number: 2, status: 'accepted' },
        versions[0],
      ]),
    ),
    http.get(`${path}/eval-sets`, () =>
      HttpResponse.json([
        {
          id: 'set1',
          name: '客服评测集',
          frozen: true,
          cases_json: [{ id: 'c1', enabled: true }],
          quality_report_json: { status: 'approved', overall_score: 1, issues: [] },
        },
      ]),
    ),
    http.get(`${path}/eval-runs`, () =>
      HttpResponse.json([
        {
          id: 'r2',
          version_id: 'v2',
          eval_set_id: 'set1',
          status: 'completed',
          created_at: '2026-09-16T01:00:00Z',
          completed_at: '2026-09-16T01:02:00Z',
          metrics_json: { total: 2, passed: 2, failed: 0, errored: 0, pass_rate: 0.9 },
          results_json: [],
          comparison_json: { proposals: [proposal] },
        },
      ]),
    ),
    http.get(`${path}/evaluation-reports`, () =>
      HttpResponse.json({
        reports: [
          {
            version_id: 'v2',
            eval_set_id: 'set1',
            evaluation_run_id: 'r2',
            status: 'completed',
            score: 0.9,
            metrics: {},
            total: 2,
            passed: 2,
            bad_case_count: 0,
            bad_cases: [],
            optimization_suggestions: [],
            comparison_key: 'set1',
            created_at: '2026-09-16T01:02:00Z',
          },
        ],
        best_run_ids: { set1: 'r2' },
        active: false,
      }),
    ),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  expect((await screen.findAllByText('最佳版本')).length).toBeGreaterThan(0)
  expect(screen.getAllByText('V2').length).toBeGreaterThan(0)
  expect((await screen.findAllByText('90%')).length).toBeGreaterThan(0)
  expect(screen.getByText('需要先检索资料。')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Optimization/ }))
  expect(await screen.findByText('优化')).toBeInTheDocument()
})

it('keeps creation available after an API failure', async () => {
  server.use(http.post(`${path}/create`, () => HttpResponse.json({}, { status: 500 })))
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '创建项目' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('无法创建项目。请再试一次。')
  expect(screen.getByRole('button', { name: '创建项目' })).toBeEnabled()
})

it('automatically resumes a Builder project and shows Chinese lifecycle progress', async () => {
  const bootstrap = vi.fn()
  server.use(
    http.get(path, () =>
      HttpResponse.json({
        ...project,
        builder_session_id: 'builder-id',
        requirements_json: { bootstrap: { stage: 'cases', error: null, run_id: null } },
      }),
    ),
    http.post(`${path}/bootstrap`, () => {
      bootstrap()
      return HttpResponse.json({ accepted: true })
    }),
  )
  const { container } = renderDirect(
    <NextIntlClientProvider locale="zh-CN" messages={zhMessages}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProjectWorkbench agentId="agent-id" />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /Settings/ }))
  expect(await screen.findByText('构建与基线评估')).toBeInTheDocument()
  expect(await screen.findByText('当前步骤：生成 20 个评估用例')).toBeInTheDocument()
  expect(bootstrap).toHaveBeenCalledOnce()
  expect(create).not.toHaveBeenCalled()
  expect(container.textContent).not.toMatch(/[\uac00-\ud7af]|agentProject\./)
  const t = createTranslator({ locale: 'zh-CN', messages: zhMessages })
  expect(t('agentProject.openProject')).toBe('打开项目')
  expect(t('agent.settings.toolsSkills.empty')).toBe('尚未添加工具或技能。')
})
