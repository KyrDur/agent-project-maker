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

it('disables duplicate preparation while displaying the actual generation stage', async () => {
  server.use(http.get(`${path}/eval-sets`, () => HttpResponse.json([])))
  render(
    <ProjectSimulation
      agentId="agent-id"
      versions={versions}
      bootstrap={{ stage: 'plan', error: null, run_id: null }}
    />,
  )
  expect(await screen.findByRole('status')).toHaveTextContent('当前步骤：生成评估计划')
  expect(screen.getByRole('button', { name: '重试准备场景' })).toBeDisabled()
})

it('uses the frozen scenario as an editable example without sending or overwriting input', async () => {
  const { userEvent } = await import('../../../../../../tests/test-utils')
  render(<ProjectSimulation agentId="agent-id" versions={versions} />)
  const button = await screen.findByRole('button', { name: '填入当前场景示例' })
  await userEvent.click(button)
  expect(screen.getByRole('textbox', { name: '发送消息' })).toHaveValue('查询订单')
  expect(button).toBeDisabled()
})

it('distinguishes a recovered plan from its preserved previous preparation failure', async () => {
  server.use(http.get(`${path}/eval-sets`, () => HttpResponse.json([])))
  render(
    <ProjectSimulation
      agentId="agent-id"
      versions={versions}
      planReady
      bootstrap={{ stage: 'plan', error: 'evaluation_rubric_unsupported', run_id: null }}
    />,
  )
  expect(await screen.findByRole('status')).toHaveTextContent('评测方案已修正并通过审核')
  expect(screen.getByRole('button', { name: '继续准备场景与评测' })).toBeEnabled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText('查看上次失败记录（已保留）')).toBeInTheDocument()
})

it('opens a reviewed scene before the formal benchmark has begun', async () => {
  server.use(
    http.get(`${path}/eval-sets`, () =>
      HttpResponse.json([
        { ...dataset, frozen: false, quality_report_json: { status: 'approved' } },
      ]),
    ),
  )
  render(<ProjectSimulation agentId="agent-id" versions={versions} />)
  expect(await screen.findByRole('button', { name: '填入当前场景示例' })).toBeEnabled()
  expect(screen.queryByText(/模拟场景尚未准备好/)).not.toBeInTheDocument()
})
