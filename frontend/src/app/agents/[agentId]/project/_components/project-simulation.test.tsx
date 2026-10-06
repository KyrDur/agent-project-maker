import { beforeEach, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { saveSimulationSession } from '@/lib/project-simulation/session-storage'
import { ProjectSimulation } from './project-simulation'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const versions = [1, 2].map((number) => ({
  id: `v${number}`,
  version_number: number,
})) as AgentProjectVersionSummary[]
const dataset = {
  id: 'regression',
  frozen: true,
  rubric_json: { purpose: 'regression' },
  cases_json: [
    {
      id: 'normal',
      name: '普通查询',
      input: '查询订单',
      enabled: true,
      tags: ['normal'],
      mock_tool_data: {},
    },
    {
      id: 'other',
      name: '异常查询',
      input: '处理未知订单',
      enabled: true,
      tags: ['edge_case'],
      mock_tool_data: {},
    },
  ],
}
beforeEach(() => {
  for (const key of [
    'project-simulation-version:agent-id',
    'project-simulation-scenario:agent-id',
    'project-simulation:agent-id:v2:other',
  ])
    saveSimulationSession(key, '')
  server.use(
    http.get(`${path}/eval-sets`, () =>
      HttpResponse.json([
        {
          ...dataset,
          id: 'validation',
          rubric_json: { purpose: 'validation' },
          cases_json: [
            {
              ...dataset.cases_json[0],
              id: 'hidden',
              name: '未见验证',
              input: 'hidden validation input',
            },
          ],
        },
        dataset,
      ]),
    ),
  )
})

it('restores version, scenario and its saved conversation after remount and omits held-out data', async () => {
  saveSimulationSession('project-simulation-version:agent-id', 'v2')
  saveSimulationSession('project-simulation-scenario:agent-id', 'other')
  saveSimulationSession('project-simulation:agent-id:v2:other', 'saved')
  server.use(
    http.get(`${path}/simulation-sessions/saved`, () =>
      HttpResponse.json({
        id: 'saved',
        state_json: {},
        turns_json: [
          { request_id: 'one', input: '已保存输入', output: '**已保存答复**', evidence: {} },
        ],
      }),
    ),
  )
  const view = render(<ProjectSimulation agentId="agent-id" versions={versions} />)
  expect(await screen.findByText('已保存答复')).toBeInTheDocument()
  expect(screen.getByText('V2')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '模拟场景' })).toHaveTextContent('异常查询')
  expect(screen.queryByText(/hidden validation input/)).not.toBeInTheDocument()
  view.unmount()
  render(<ProjectSimulation agentId="agent-id" versions={versions} />)
  expect(await screen.findByText('已保存答复')).toBeInTheDocument()
})
