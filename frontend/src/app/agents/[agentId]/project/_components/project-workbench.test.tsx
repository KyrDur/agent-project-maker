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
