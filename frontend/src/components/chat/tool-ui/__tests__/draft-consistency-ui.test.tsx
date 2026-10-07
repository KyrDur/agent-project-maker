import { expect, it } from 'vitest'
import { render, screen, userEvent } from '../../../../../tests/test-utils'
import { DraftConfigCardToolUI } from '../draft-config-ui'

it('shows the reviewed quotes and limits without turning a review into task success', async () => {
  const props = {
    args: {
      phase: 7,
      draft: {
        name: '周报助手',
        consistency_review: {
          status: 'approved',
          requirement_reviews: [
            {
              field: 'deliverables',
              supported: true,
              reason: '输出结构与确认需求一致',
              evidence: [
                {
                  reference: 'requirements/deliverables',
                  quote: '本周完成、风险、下周计划、待确认四段',
                },
              ],
            },
          ],
        },
      },
    },
  } as Parameters<typeof DraftConfigCardToolUI>[0]
  render(<DraftConfigCardToolUI {...props} />)
  await userEvent.click(screen.getByText(/需求与实现一致性审查/))
  expect(screen.getByText('本周完成、风险、下周计划、待确认四段')).toBeVisible()
  expect(screen.getByText(/模型判断仍可能出错/)).toBeVisible()
})
