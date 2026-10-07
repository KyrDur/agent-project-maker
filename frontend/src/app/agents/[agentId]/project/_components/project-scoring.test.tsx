import { expect, it } from 'vitest'
import { render, screen, userEvent } from '../../../../../../tests/test-utils'
import { ProjectMetricScores, ProjectCaseScores } from './project-scoring'
import { ProjectMetrics } from './project-evaluation'
import type { EvaluationResult, EvaluationSpec } from '../_lib/agent-project-types'

const spec: EvaluationSpec = {
  rubric_version: 2,
  version_id: 'v1',
  categories: [],
  case_count: 20,
  pass_threshold: 0.75,
  metrics: [
    {
      name: 'compliance_escalation',
      type: 'llm_judge',
      weight: 1,
      display_name: '业务规则遵守与转人工处理',
      description: '按确认的模拟规则转交人工。',
      criteria: '按明确档位计分',
      scoring_mode: 'criterion_mean',
      requirement_refs: [{ field: 'business_rules', quote: '用户要求人工时转交。' }],
      scoring_criteria: [
        {
          id: 'handoff',
          description: '实际完成模拟转人工。',
          requirement_refs: [{ field: 'business_rules', quote: '用户要求人工时转交。' }],
          fail: '未转交',
          partial: '摘要不完整',
          full: '完成转交并说明工单',
          critical: true,
        },
      ],
    },
  ],
}

it('distinguishes 19-case metric averages from all-case task pass rates and errors', () => {
  render(
    <ProjectMetrics
      spec={spec}
      metrics={{
        total: 20,
        passed: 10,
        failed: 9,
        errored: 1,
        execution_errors: 1,
        judge_errors: 0,
        pass_rate: 0.5,
        complete: true,
        metric_scores: { compliance_escalation: { score: 0.913157, evaluated_cases: 19 } },
      }}
    />,
  )
  expect(screen.getByText('全部用例通过率：10/20（50.0%）')).toBeInTheDocument()
  expect(screen.getByText('平均得分：91.3/100')).toBeInTheDocument()
  expect(screen.getByText('评分覆盖：19/20 条用例')).toBeInTheDocument()
  expect(screen.getByText('执行错误')).toBeInTheDocument()
  expect(screen.getByText('裁判错误')).toBeInTheDocument()
  expect(screen.queryByText('compliance_escalation')).not.toBeVisible()
})

it('shows frozen rules, anchors and actual requirement sources', async () => {
  render(<ProjectMetricScores spec={spec} summaries={{}} total={20} />)
  expect(screen.getByText('不可用')).toBeInTheDocument()
  await userEvent.click(screen.getByText('查看评分规则与需求出处'))
  expect(screen.getByText('0.5 分：摘要不完整')).toBeVisible()
  expect(screen.getByText('关键条件：不满足时，本指标计 0 分。')).toBeVisible()
  expect(screen.getAllByText(/用户要求人工时转交/)[0]).toBeVisible()
})

it('does not fabricate missing historical coverage or a frozen rubric', () => {
  render(<ProjectMetricScores total={20} summaries={{ task_completion: { score: 0.8 } }} />)
  expect(screen.getByText('评分覆盖数：历史记录缺失')).toBeInTheDocument()
  expect(screen.getByText(/该运行没有保存此指标的规则/)).toBeInTheDocument()
})

it('renders criterion reasons and cited execution evidence', () => {
  const result: EvaluationResult = {
    case_id: 'c1',
    name: '转交失败',
    input: '转人工',
    output: '已转交',
    expected: { required_tools: [], forbidden_tools: [] },
    status: 'failed',
    assertions: [],
    tool_calls: [],
    error: null,
    latency_ms: 0,
    metric_scores: {
      compliance_escalation: {
        score: 0,
        passed: false,
        reason: '转交接口失败却宣称成功。',
        method: 'llm_judge',
        criteria_results: [
          {
            criterion_id: 'handoff',
            level: 0,
            reason: '实际操作失败',
            evidence: [{ reference: 'tool_trace/0/error', quote: 'timeout' }],
          },
        ],
      },
    },
    metric_unavailable: { groundedness: '没有事实性陈述' },
  }
  render(<ProjectCaseScores result={result} spec={spec} />)
  expect(screen.getByText('实际操作失败')).toBeInTheDocument()
  expect(screen.getByText(/tool_trace\/0\/error/)).toBeInTheDocument()
  expect(screen.getByText(/timeout/)).toBeInTheDocument()
  expect(screen.getByText(/没有事实性陈述/)).toBeInTheDocument()
})

it('withholds pending scores instead of inventing zeros', () => {
  render(<ProjectMetrics metrics={{ total: 20 }} />)
  expect(screen.getByRole('status')).toHaveTextContent('评测尚未完成')
  expect(screen.queryByText('平均得分：0.0/100')).not.toBeInTheDocument()
})
