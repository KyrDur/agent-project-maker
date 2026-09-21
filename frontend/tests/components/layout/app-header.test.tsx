import { render, screen } from '../../test-utils'
import { AppHeader } from '@/components/layout/app-header'

vi.mock('@/components/ui/sidebar', () => ({
  SidebarTrigger: (props: Record<string, unknown>) => (
    <button
      data-testid="sidebar-trigger"
      aria-label="打开或关闭侧边栏"
      className={props.className as string}
    />
  ),
}))

vi.mock('@/components/ui/separator', () => ({
  Separator: () => <hr />,
}))

vi.mock('@/components/layout/breadcrumb-nav', () => ({
  BreadcrumbNav: () => <nav data-testid="breadcrumb-nav" />,
}))

vi.mock('@/components/agent/assistant-side-chat-trigger', () => ({
  AssistantSideChatTrigger: () => <button data-testid="assistant-side-chat-trigger" />,
}))

describe('AppHeader', () => {
  it('renders header element', () => {
    const { container } = render(<AppHeader />)
    const header = container.querySelector('header')
    expect(header).toBeInTheDocument()
  })

  it('renders sidebar trigger with correct aria label', () => {
    const { container } = render(<AppHeader />)
    const trigger = container.querySelector('[aria-label="打开或关闭侧边栏"]')
    expect(trigger).toBeInTheDocument()
  })

  it('renders the assistant side chat trigger in the authenticated header', () => {
    render(<AppHeader />)
    expect(screen.getByTestId('assistant-side-chat-trigger')).toBeInTheDocument()
  })
})
