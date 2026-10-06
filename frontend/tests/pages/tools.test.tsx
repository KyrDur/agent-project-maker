import { render, screen } from '../test-utils'
import ToolsPage from '@/app/tools/page'

it('shows the simulation scope without external tool installation', () => {
  render(<ToolsPage />)
  expect(screen.getByText('已移除内置外部工具')).toBeInTheDocument()
  expect(screen.queryByText('需要凭据')).not.toBeInTheDocument()
  expect(screen.queryByTestId('tool-catalog-card')).not.toBeInTheDocument()
})
