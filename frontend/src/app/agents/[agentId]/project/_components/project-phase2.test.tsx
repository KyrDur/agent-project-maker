import { beforeEach, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { render, screen, userEvent, waitFor } from '../../../../../../tests/test-utils'
import { server } from '../../../../../../tests/setup'
import { ProjectWorkbench } from './project-workbench'

const path = 'http://localhost:8001/api/agents/agent-id/project'
const v1 = {
  id: 'v1',
  project_id: 'p1',
  version_number: 1,
  status: 'original',
  created_at: '2026-09-12T00:00:00',
  config_hash: 'hash1',
}
const v2 = { ...v1, id: 'v2', version_number: 2, status: 'candidate', config_hash: 'hash2' }
const caseOne = {
  id: 'c1',
  name: 'Greeting case',
  input: 'Hello',
  context: [],
  expected: { required_tools: [], forbidden_tools: [] },
  tags: [],
  enabled: true,
}
const dataset = { id: 'set1', name: 'Manual', frozen: false, cases_json: [caseOne] }
const run = {
  id: 'r1',
  version_id: 'v1',
  eval_set_id: 'set1',
  status: 'completed',
  created_at: '2026-09-12T01:00:00',
  metrics_json: { total: 1, passed: 1, failed: 0, errored: 0 },
  results_json: [
    {
      case_id: 'c1',
      name: 'Greeting case',
      input: 'Hello',
      output: 'Hello back',
      status: 'passed',
      tool_calls: [],
      assertions: [{ kind: 'answer_exists', passed: true }],
      latency_ms: 12,
      error: null,
    },
  ],
}

beforeEach(() => {
  server.use(
    http.get(`${path}/report`, () => HttpResponse.json({ evidence: null, sections: [] })),
    http.get(path, () => HttpResponse.json({ id: 'p1', title: 'Example Agent' })),
    http.get(`${path}/versions`, () => HttpResponse.json([v1])),
    http.get(`${path}/eval-sets`, () => HttpResponse.json([])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json([])),
    http.get(`${path}/compare`, () =>
      HttpResponse.json({
        changes: [{ field: 'system_prompt', before: 'Old instruction', after: 'New instruction' }],
        evaluations: [null, null],
        same_dataset: false,
      }),
    ),
    http.get(`${path}/versions/v1`, () =>
      HttpResponse.json({
        ...v1,
        snapshot_json: { agent: { system_prompt: 'Original instruction' } },
      }),
    ),
  )
})

it('creates a version and refreshes the history', async () => {
  server.use(
    http.post(`${path}/versions`, async ({ request }) => {
      expect(await request.json()).toHaveProperty('request_id')
      server.use(http.get(`${path}/versions`, () => HttpResponse.json([v2, v1])))
      return HttpResponse.json({ outcome: 'created', version: v2 })
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '버전 만들기' }))
  expect(await screen.findByText('버전을 만들었습니다.')).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: 'V2' })).toBeInTheDocument()
})

it('explains unchanged configuration and exposes version detail', async () => {
  server.use(
    http.post(`${path}/versions`, () => HttpResponse.json({ outcome: 'unchanged', version: v1 })),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '버전 만들기' }))
  expect(
    await screen.findByText('설정이 변경되지 않아 최신 버전을 유지했습니다.'),
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'V1' }))
  await userEvent.click(await screen.findByText('스냅샷 보기'))
  expect(screen.getByText(/Original instruction/)).toBeInTheDocument()
})

it('shows the evaluation empty state and creates an accessible manual case', async () => {
  server.use(
    http.post(`${path}/eval-sets`, async ({ request }) => {
      const body = (await request.json()) as { cases: (typeof caseOne)[] }
      expect(body.cases[0].input).toBe('A test message')
      server.use(
        http.get(`${path}/eval-sets`, () =>
          HttpResponse.json([{ ...dataset, cases_json: body.cases }]),
        ),
      )
      return HttpResponse.json({ ...dataset, cases_json: body.cases })
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(
    await screen.findByText('평가 케이스가 없습니다. 케이스를 추가해 시작하세요.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '평가 실행' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '케이스 추가' }))
  await userEvent.type(screen.getByLabelText('케이스 이름'), 'New case')
  await userEvent.type(screen.getByLabelText('입력'), 'A test message')
  await userEvent.click(screen.getByRole('button', { name: '케이스 저장' }))
  expect(await screen.findByText('New case')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: '평가 실행' })).toBeEnabled())
})

it('edits, disables and removes a case', async () => {
  let cases = [caseOne]
  server.use(
    http.get(`${path}/eval-sets`, () => HttpResponse.json([{ ...dataset, cases_json: cases }])),
    http.put(`${path}/eval-sets/set1`, async ({ request }) => {
      cases = ((await request.json()) as { cases: (typeof caseOne)[] }).cases
      return HttpResponse.json({ ...dataset, cases_json: cases })
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Greeting case 수정' }))
  await userEvent.clear(screen.getByLabelText('케이스 이름'))
  await userEvent.type(screen.getByLabelText('케이스 이름'), 'Edited')
  await userEvent.click(screen.getByRole('button', { name: '케이스 저장' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Edited 활성화 또는 비활성화' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '평가 실행' })).toBeDisabled())
  await userEvent.click(screen.getByRole('button', { name: 'Edited 삭제' }))
  expect(
    await screen.findByText('평가 케이스가 없습니다. 케이스를 추가해 시작하세요.'),
  ).toBeInTheDocument()
})

it('submits evaluation against the chosen version and shows persisted results', async () => {
  let submitted = false
  server.use(
    http.get(`${path}/eval-sets`, () => HttpResponse.json([dataset])),
    http.get(`${path}/eval-runs`, () => HttpResponse.json(submitted ? [run] : [])),
    http.post(`${path}/eval-runs`, async ({ request }) => {
      const body = await request.json()
      expect(body).toMatchObject({ version_id: 'v1', eval_set_id: 'set1' })
      submitted = true
      return HttpResponse.json({ ...run, status: 'pending' }, { status: 202 })
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  await waitFor(() => expect(screen.getByRole('button', { name: '평가 실행' })).toBeEnabled())
  await userEvent.click(screen.getByRole('button', { name: '평가 실행' }))
  await userEvent.click(await screen.findByText(/V1 · 완료/))
  expect(screen.getByText('출력: Hello back')).toBeInTheDocument()
  expect(screen.getByText('전체 1 · 통과 1 · 실패 0 · 오류 0')).toBeInTheDocument()
})

it.each(['pending', 'running', 'completed', 'failed'] as const)(
  'shows the %s lifecycle state',
  async (status) => {
    const labels = { pending: '대기 중', running: '실행 중', completed: '완료', failed: '실패' }
    server.use(
      http.get(`${path}/eval-runs`, () =>
        HttpResponse.json([
          { ...run, status, error: status === 'failed' ? 'evaluation_case_errors' : null },
        ]),
      ),
    )
    render(<ProjectWorkbench agentId="agent-id" />)
    await userEvent.click(await screen.findByText(new RegExp(`V1 · ${labels[status]}`)))
    expect(screen.getByText(labels[status], { selector: 'p' })).toBeInTheDocument()
    if (status === 'failed')
      expect(screen.getByRole('alert')).toHaveTextContent('실행하지 못한 케이스가 있습니다.')
  },
)

it('shows loading while data is in flight', async () => {
  server.use(
    http.get(path, async () => {
      await delay(100)
      return HttpResponse.json(null)
    }),
  )
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(screen.getByRole('status')).toHaveTextContent('불러오는 중')
  expect(await screen.findByRole('button', { name: '프로젝트 만들기' })).toBeInTheDocument()
})

it('compares two versions without treating different datasets as comparable', async () => {
  server.use(http.get(`${path}/versions`, () => HttpResponse.json([v2, v1])))
  render(<ProjectWorkbench agentId="agent-id" />)
  expect(await screen.findByText('Old instruction')).toBeInTheDocument()
  expect(screen.getByText('New instruction')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '왼쪽 버전' })).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '오른쪽 버전' })).toBeInTheDocument()
  expect(screen.getByText(/결과를 직접 비교할 수 없습니다/)).toBeInTheDocument()
})

it('shows retry controls for a rejected version creation', async () => {
  server.use(http.post(`${path}/versions`, () => HttpResponse.json({}, { status: 500 })))
  render(<ProjectWorkbench agentId="agent-id" />)
  await userEvent.click(await screen.findByRole('button', { name: '버전 만들기' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
})
