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

  it('offers only conversational creation', () => {
    render(<AgentNewPage />)
    expect(screen.queryByText('手动构建')).not.toBeInTheDocument()
    expect(screen.queryByText('使用模板')).not.toBeInTheDocument()
  })
})
