import { render, screen } from '../test-utils'
import AgentNewPage from '@/app/agents/new/page'

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode
    href: string
    [key: string]: unknown
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

describe('AgentNewPage', () => {
  it('renders hero section with title', () => {
    render(<AgentNewPage />)
    expect(screen.getByText('你想建造什么？')).toBeInTheDocument()
  })

  it('renders chat input textarea', () => {
    render(<AgentNewPage />)
    const textarea = screen.getByRole('textbox')
    expect(textarea).toBeInTheDocument()
  })

  it('manual option links to correct path', () => {
    render(<AgentNewPage />)
    const manualLink = screen.getByText('手动构建').closest('a')
    expect(manualLink).toHaveAttribute('href', '/agents/new/manual')
  })

  it('template option links to correct path', () => {
    render(<AgentNewPage />)
    const templateLink = screen.getByText('使用模板').closest('a')
    expect(templateLink).toHaveAttribute('href', '/agents/new/template')
  })
})
