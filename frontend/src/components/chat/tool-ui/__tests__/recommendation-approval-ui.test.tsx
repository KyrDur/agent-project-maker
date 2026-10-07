import { expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor } from '../../../../../tests/test-utils'
import { HiTLContext } from '@/lib/chat/hitl-context'
import { RecommendationApprovalToolUI } from '../recommendation-approval-ui'

it('shows a persistent example but requires the user’s own capability confirmation reason', async () => {
  const resume = vi.fn().mockResolvedValue(undefined)
  render(
    <HiTLContext.Provider value={{ onResumeDecisions: resume }}>
      <RecommendationApprovalToolUI
        type="tool-call"
        args={{ phase: 3, title: '能力方案', items: [], item_kind: 'tool' }}
        status={{ type: 'requires-action', reason: 'interrupt' }}
        toolCallId="capability-confirmation"
        toolName="recommendation_approval"
        argsText="{}"
        addResult={vi.fn()}
        resume={vi.fn()}
        respondToApproval={vi.fn().mockResolvedValue(undefined)}
      />
    </HiTLContext.Provider>,
  )
  expect(screen.getByText(/示例（周报助手）/)).toBeVisible()
  const input = screen.getByRole('textbox', { name: /确认能力方案的理由/ })
  expect(input).toHaveValue('')
  expect(screen.getByRole('button', { name: '批准并继续' })).toBeDisabled()
  const reason = '我只需要文字归纳，这份写作指南符合需求。'
  await userEvent.type(input, reason)
  await userEvent.click(screen.getByRole('button', { name: '批准并继续' }))
  await waitFor(() => expect(resume).toHaveBeenCalledOnce())
  expect(JSON.stringify(resume.mock.calls[0])).toContain(reason)
  expect(JSON.stringify(resume.mock.calls[0])).not.toContain('示例（周报助手）')
})
