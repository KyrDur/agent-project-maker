import { beforeEach, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectPractice } from './project-practice'
import type { AgentProject, AgentProjectVersionSummary } from '../_lib/agent-project-types'

const path = 'http://localhost:8001/api/agents/a/project'
const project: AgentProject = {
  id: 'p',
  user_id: 'u',
  agent_id: 'a',
  builder_session_id: null,
  title: 'Writing',
  requirements_json: {
    task: {
      goal: 'Write a summary',
      inputs: 'User notes',
      deliverables: 'Summary',
      business_rules: 'Use supplied facts',
      success_conditions: 'Complete and accurate',
    },
  },
  eval_spec_json: null,
  report_json: null,
  created_at: '',
  updated_at: '',
}
const versions: AgentProjectVersionSummary[] = [
  {
    id: 'v1',
    project_id: 'p',
    version_number: 1,
    parent_version_id: null,
    status: 'original',
    change_summary: null,
    config_hash: 'hash',
    created_at: '',
  },
]

beforeEach(() =>
  server.use(
    http.get(`${path}/versions/v1`, () =>
      HttpResponse.json({
        snapshot_json: {
          agent: { system_prompt: 'Use supplied facts', planned_tools: [], skill_links: [] },
        },
      }),
    ),
    http.get(`${path}/eval-sets`, () =>
      HttpResponse.json([
        {
          id: 's1',
          name: 'Writing cases',
          cases_json: [
            {
              id: 'c1',
              name: 'Summary case',
              enabled: true,
              expected: { answer: 'Use supplied facts' },
            },
          ],
        },
      ]),
    ),
  ),
)

it('saves authored requirements and reasoned capability approval', async () => {
  const save = vi.fn()
  server.use(
    http.put(`${path}/requirements`, async ({ request }) => {
      save(await request.json())
      return HttpResponse.json(project)
    }),
    http.post(`${path}/decisions`, async ({ request }) => {
      save(await request.json())
      return HttpResponse.json(project)
    }),
  )
  render(<ProjectPractice agentId="a" project={project} versions={versions} />)
  await userEvent.clear(screen.getByLabelText('任务目标'))
  await userEvent.type(screen.getByLabelText('任务目标'), 'Polish supplied notes')
  await userEvent.click(screen.getByRole('button', { name: /保存需求/ }))
  expect(await screen.findByText('已保存')).toBeInTheDocument()
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ goal: 'Polish supplied notes' }))
  await userEvent.click(screen.getByLabelText('决策阶段'))
  await userEvent.click(await screen.findByRole('option', { name: '能力方案选择' }))
  expect(screen.queryByRole('option', {name: '用例抽查'})).not.toBeInTheDocument()
  await userEvent.type(
    screen.getByLabelText('你的选择或抽查结论'),
    'Reviewed the summary criterion',
  )
  expect(screen.getByRole('button', { name: '保存决策与理由' })).toBeDisabled()
  await userEvent.type(
    screen.getByLabelText('为什么这样选择'),
    'The criterion checks supplied facts',
  )
  await userEvent.click(screen.getByRole('button', { name: '保存决策与理由' }))
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        stage: 'capabilities',
        version_id: 'v1',
        reason: 'The criterion checks supplied facts',
      }),
    ),
  )
})

it('shows completion separately from quality and displays interview evidence', async () => {
  server.use(
    http.post(`${path}/completion`, () =>
      HttpResponse.json({
        status: 'completed',
        reasons: [],
        analysis: 'V2 regressed, but evidence is valid.',
      }),
    ),
    http.get(`${path}/interview`, () =>
      HttpResponse.json({
        evidence_hash: 'h',
        questions: [
          {
            question: 'Why did V2 regress?',
            references: ['experiment-2/case-1'],
            answer_points: ['Explain the observed failure.'],
          },
        ],
      }),
    ),
  )
  render(<ProjectPractice agentId="a" project={project} versions={versions} />)
  await userEvent.type(screen.getByLabelText(/个人复盘/), 'V2 regressed, but evidence is valid.')
  await userEvent.click(screen.getByRole('button', { name: '检查并记录项目完成状态' }))
  expect(await screen.findByText('项目已完成（不代表智能体合格）')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /生成 AI 产品经理面试题/ }))
  expect(await screen.findByText('Why did V2 regress?')).toBeInTheDocument()
  expect(screen.getByText(/experiment-2\/case-1/)).toBeInTheDocument()
})
