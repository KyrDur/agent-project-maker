import { render, screen } from '../../test-utils'
import { StatusChip } from '@/components/shared/status-chip'

describe('StatusChip', () => {
  it('uses Korean default labels', () => {
    render(
      <>
        <StatusChip variant="active" />
        <StatusChip variant="auth_needed" />
        <StatusChip variant="unreachable" />
      </>,
    )

    expect(screen.getByText('启用')).toBeInTheDocument()
    expect(screen.getByText('需要身份验证')).toBeInTheDocument()
    expect(screen.getByText('无法到达')).toBeInTheDocument()
  })
})
