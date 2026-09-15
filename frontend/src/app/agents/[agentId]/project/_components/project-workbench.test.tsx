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

it('waits for explicit creation and then shows V1 with evaluation requiring cases', async () => {
  render(<ProjectWorkbench agentId="agent-id" />)
  const button = await screen.findByRole('button', { name: '프로젝트 만들기' })
  expect(create).not.toHaveBeenCalled()
  await userEvent.click(button)
  expect(await screen.findByText('Example Agent')).toBeInTheDocument()
  expect(await screen.findByText('최초 스냅샷')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '평가 실행' })).toBeDisabled()
  expect(create).toHaveBeenCalledOnce()
})

it('loads an existing project without creating another one', async () => {
  server.use(http.get(path, () => HttpResponse.json(project)))
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(await screen.findByText('최초 스냅샷')).toBeInTheDocument()
  expect(create).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '프로젝트 만들기' })).not.toBeInTheDocument()
})

it('keeps creation available after an API failure', async () => {
  server.use(http.post(`${path}/create`, () => HttpResponse.json({}, { status: 500 })))
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '프로젝트 만들기' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('프로젝트를 만들지 못했습니다')
  expect(screen.getByRole('button', { name: '프로젝트 만들기' })).toBeEnabled()
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
  expect(await screen.findByText('构建与基线评估')).toBeInTheDocument()
  expect(await screen.findByText('当前步骤：生成 20 个评估用例')).toBeInTheDocument()
  expect(bootstrap).toHaveBeenCalledOnce()
  expect(create).not.toHaveBeenCalled()
  expect(container.textContent).not.toMatch(/[\uac00-\ud7af]|agentProject\./)
  const t = createTranslator({ locale: 'zh-CN', messages: zhMessages })
  expect(t('agentProject.openProject')).toBe('打开项目')
  expect(t('agent.settings.toolsSkills.empty')).toBe('尚未添加工具或技能。')
})
