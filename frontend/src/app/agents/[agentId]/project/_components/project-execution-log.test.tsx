import { expect, it } from 'vitest'
import { render, screen, userEvent } from '../../../../../../tests/test-utils'
import { ProjectExecutionLog, ProjectEvidenceValue } from './project-execution-log'
import { executionLog } from '../_lib/execution-log'

const evidence = {
  output: 'Your order is on its way.',
  termination_reason: 'completed',
  model_calls: [
    {
      model: { model_name: 'configured-model', parameters: { temperature: 0.2 } },
      status: 'completed',
      input_messages: [[{ type: 'human', content: 'Where is order 123?' }]],
      returns: [
        {
          content: 'Checking your order.',
          tool_calls: [{ name: 'query_order', args: { order_id: '123' } }],
        },
      ],
    },
    {
      model: { model_name: 'configured-model' },
      status: 'completed',
      input_messages: [[{ type: 'tool', content: '{"status":"shipped"}' }]],
      returns: [{ content: 'Your order is on its way.', tool_calls: [] }],
    },
  ],
  tool_trace: [
    {
      name: 'query_order',
      order: 1,
      arguments: { order_id: '123' },
      output: '{"status":"shipped","message":"Delivery tomorrow\\nTracking available"}',
      latency_ms: 20,
      state_before: { orders: [] },
      state_after: { orders: ['123'] },
    },
  ],
  judge_calls: [
    {
      model: { model_name: 'configured-judge' },
      status: 'completed',
      instruction: 'Use recorded facts.',
      input: { output: 'Your order is on its way.' },
      output:
        '{"scores":{"groundedness":{"score":0.9,"reason":"Matches the order record.","evidence":["/tool_trace/0/output"]}}}',
    },
  ],
}

it('shows model, tool and judge records as readable prose and fields; keeps raw JSON collapsed', async () => {
  render(<ProjectExecutionLog evidence={evidence} graded />)
  expect(screen.getByText('第 1 次模型调用 · configured-model')).toBeInTheDocument()
  expect(screen.getByText('第 2 次模型调用 · configured-model')).toBeInTheDocument()
  expect(screen.getByText('调用工具 · query_order')).toBeInTheDocument()
  expect(screen.getByText('订单号')).toBeInTheDocument()
  expect(screen.getByText('123', { selector: 'dd > span' })).toBeInTheDocument()
  expect(screen.getByText('shipped', { selector: 'article dd > span' })).toBeInTheDocument()
  expect(screen.getByText(/Delivery tomorrow/, { selector: 'span' })).toHaveTextContent(
    'Delivery tomorrow Tracking available',
  )
  expect(screen.getByText('Matches the order record.')).toBeInTheDocument()
  expect(screen.getByText('/tool_trace/0/output')).toBeInTheDocument()
  expect(screen.getByText('正常结束')).toBeInTheDocument()
  const technical = screen.getByText('原始记录（技术详情 / JSON）').closest('details')
  expect(technical).not.toHaveAttribute('open')
  await userEvent.click(screen.getByText('原始记录（技术详情 / JSON）'))
  expect(technical).toHaveAttribute('open')
  expect(technical?.querySelector('pre')?.textContent).toBe(JSON.stringify(evidence, null, 2))
})

it('retains failed tool retries and missing results instead of presenting them as successful', () => {
  const calls = [
    {
      status: 'completed',
      returns: [
        {
          tool_calls: [
            { name: 'query_order', args: { order_id: '123' } },
            { name: 'query_order', args: { order_id: '123' } },
            { name: 'query_logistics', args: {} },
          ],
        },
      ],
    },
  ]
  const events = [
    { name: 'query_order', order: 1, error: 'temporary_failure' },
    { name: 'query_order', order: 2, output: 'Retry succeeded' },
  ]
  const log = executionLog({ model_calls: calls, tool_trace: events })
  expect(log.calls[0].tools.map((tool) => tool.event?.order)).toEqual([1, 2, undefined])
  render(
    <ProjectExecutionLog
      evidence={{ model_calls: calls, tool_trace: events, termination_reason: 'timeout' }}
    />,
  )
  expect(screen.getByText(/temporary_failure/, { selector: 'p' })).toBeInTheDocument()
  expect(screen.getByText('Retry succeeded')).toBeInTheDocument()
  expect(screen.getByText('模型请求了这个工具，但未记录对应执行结果。')).toBeInTheDocument()
  expect(screen.getByText('执行超时')).toBeInTheDocument()
  expect(screen.queryByText('裁判评测日志')).not.toBeInTheDocument()
})

it('labels legacy missing evidence and separately retained tool executions without inventing a model call', () => {
  render(
    <ProjectExecutionLog
      evidence={{
        output: 'Legacy answer',
        tool_trace: [{ name: 'legacy_tool', output: { result: 'Actual retained result' } }],
      }}
      graded
    />,
  )
  expect(screen.getByText('没有保存模型调用明细，无法还原这一部分执行过程。')).toBeInTheDocument()
  expect(screen.getByText('单独保存的工具执行记录')).toBeInTheDocument()
  expect(screen.getByText('Actual retained result')).toBeInTheDocument()
  expect(screen.queryByText(/第 1 次模型调用/)).not.toBeInTheDocument()
  expect(screen.getByText(/未记录裁判调用明细/)).toBeInTheDocument()
})

it('distinguishes null from missing data and preserves multiline text and unknown field names', () => {
  render(
    <ProjectEvidenceValue
      value={{ custom_field: 'Line one\nLine two', result: null, output: undefined }}
    />,
  )
  expect(screen.getByText('custom_field')).toBeInTheDocument()
  expect(screen.getByText(/Line one/).textContent).toBe('Line one\nLine two')
  expect(screen.getByText('空值')).toBeInTheDocument()
  expect(screen.getByText('未记录')).toBeInTheDocument()
})

it('explains a tool-only response and localizes missing simulated data from the actual trial', () => {
  render(
    <ProjectExecutionLog
      evidence={{
        model_calls: [
          {
            model: { model_name: 'trial-model' },
            status: 'completed',
            returns: [
              {
                content: '',
                tool_calls: [{ name: 'search_faq', args: { query: 'Return policy' } }],
              },
            ],
          },
        ],
        tool_trace: [
          {
            name: 'search_faq',
            arguments: { query: 'Return policy' },
            error: 'evaluation_mock_missing',
            output: null,
          },
        ],
        output: 'Please provide an order number.',
        termination_reason: 'completed',
      }}
    />,
  )
  expect(screen.getByText('模型请求调用下面的工具，本次没有返回答复文本。')).toBeInTheDocument()
  expect(screen.getByText(/所需或调用的工具没有模拟数据/, { selector: 'p' })).toBeInTheDocument()
  expect(screen.queryByText('没有文本内容')).not.toBeInTheDocument()
})
