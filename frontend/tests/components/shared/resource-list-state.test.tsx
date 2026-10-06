import { render, screen, userEvent } from '../../test-utils'
import { ResourceListState } from '@/components/shared/resource-list-state'

describe('ResourceListState', () => {
  it('renders loading skeleton first', () => {
    render(
      <ResourceListState
        loading
        skeleton={<div data-testid="skeleton">loading</div>}
        emptyTitle="为空"
        filteredEmptyTitle="搜索空"
      />,
    )

    expect(screen.getByTestId('skeleton')).toBeInTheDocument()
    expect(screen.queryByText('为空')).not.toBeInTheDocument()
  })

  it('renders the base empty state', () => {
    render(
      <ResourceListState
        skeleton={<div />}
        emptyTitle="暂无项目"
        emptyDescription="创建第一个项目吧。"
        filteredEmptyTitle="搜索空"
      />,
    )

    expect(screen.getByText('暂无项目')).toBeInTheDocument()
    expect(screen.getByText('创建第一个项目吧。')).toBeInTheDocument()
  })

  it('renders filtered empty state with retry action', async () => {
    const user = userEvent.setup()
    let retryCount = 0

    render(
      <ResourceListState
        isFiltered
        skeleton={<div />}
        emptyTitle="为空"
        filteredEmptyTitle="没有符合条件的项目"
        filteredEmptyDescription="请调整筛选条件。"
        retryLabel="重置过滤器"
        onRetry={() => {
          retryCount += 1
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '重置过滤器' }))

    expect(screen.getByText('没有符合条件的项目')).toBeInTheDocument()
    expect(screen.getByText('请调整筛选条件。')).toBeInTheDocument()
    expect(retryCount).toBe(1)
  })

  it('renders error state with retry action', async () => {
    const user = userEvent.setup()
    let retryCount = 0

    render(
      <ResourceListState
        error
        skeleton={<div />}
        emptyTitle="为空"
        filteredEmptyTitle="搜索空"
        errorTitle="加载失败"
        errorDescription="请重试。"
        onRetry={() => {
          retryCount += 1
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '重试' }))

    expect(screen.getByRole('alert')).toHaveTextContent('加载失败')
    expect(screen.getByText('请重试。')).toBeInTheDocument()
    expect(retryCount).toBe(1)
  })
})
