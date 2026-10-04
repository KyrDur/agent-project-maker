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
    http.get('http://localhost:8001/api/user-llm-settings/readiness', () => HttpResponse.json([])),
    http.get('http://localhost:8001/api/agents/agent-id/runtime-readiness', () =>
      HttpResponse.json({ ready: false, model: null, credential: null }),
    ),
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
  expect(await screen.findByText('先说清楚：这个 Agent 要解决什么问题')).toBeInTheDocument()
  expect(screen.getByText('正在查看的版本')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /2. 测试表现/ }))
  expect(screen.getByRole('button', { name: '生成评测计划' })).toBeEnabled()
  expect(create).toHaveBeenCalledOnce()
})

it('loads an existing project without creating another one', async () => {
  server.use(http.get(path, () => HttpResponse.json(project)))
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(await screen.findByText('先说清楚：这个 Agent 要解决什么问题')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /1. 创建项目/ })).toHaveAttribute(
    'aria-current',
    'page',
  )
  expect(create).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '创建项目' })).not.toBeInTheDocument()
})

it('offers four stages and keeps material generation accessible without a quiz', async () => {
  server.use(
    http.get(path, () => HttpResponse.json(project)),
    http.get(`${path}/reliability/version-id`, () =>
      HttpResponse.json({
        trials: [],
        calibration: { reviewed: 0, disagreements: 0, reviews: [] },
        limitations: [],
      }),
    ),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: /4. 项目材料/ }))
  expect(await screen.findByRole('button', { name: '生成我的项目讲解' })).toBeEnabled()
  expect(screen.getByText('我的迭代记录')).toBeInTheDocument()
  expect(screen.getByText('再验证：改进是否稳定、能否迁移')).toBeInTheDocument()
  expect(screen.getByText('简历、报告与下载')).toBeInTheDocument()
  expect(create).not.toHaveBeenCalled()
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
