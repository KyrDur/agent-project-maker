import { expect, it } from 'vitest'
import { render, screen } from '../../../../../../tests/test-utils'
import { ProjectMetrics } from './project-evaluation'

it('keeps uncompleted trial scores unavailable', () => {
  render(
    <ProjectMetrics
      metrics={{
        total: 60,
        passed: 10,
        failed: 0,
        repetitions: 3,
        trial_pass_rates: [0.5, null, null],
      }}
    />,
  )
  expect(screen.getByText(/50.0.*未完成.*未完成/)).toBeInTheDocument()
  expect(screen.queryByText(/50.0.*0.0.*0.0/)).not.toBeInTheDocument()
})

it('uses valid scored trials instead of completed executions for the effective rate', () => {
  render(
    <ProjectMetrics
      metrics={{
        total: 20,
        passed: 10,
        failed: 5,
        errored: 5,
        executed_cases: 20,
        executed_pass_rate: 0.5,
        valid_scored_cases: 15,
        valid_scored_pass_rate: 10 / 15,
      }}
    />,
  )
  expect(screen.getByText(/有效评分任务通过率：10\/15.*66.7.*5 个错误/)).toBeInTheDocument()
})
