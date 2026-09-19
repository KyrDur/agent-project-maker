import { render, screen, userEvent } from '../../test-utils'
import { SearchFilterBar } from '@/components/shared/search-filter-bar'

describe('SearchFilterBar', () => {
  it('emits text changes and renders filters and actions', async () => {
    const user = userEvent.setup()
    const changes: string[] = []

    render(
      <SearchFilterBar
        value=""
        onValueChange={(value) => changes.push(value)}
        searchLabel="리소스 검색"
        placeholder="搜索"
        filters={<span>filter</span>}
        actions={<button type="button">새로 만들기</button>}
      />,
    )

    await user.type(screen.getByRole('textbox', { name: '리소스 검색' }), 'abc')

    expect(changes).toEqual(['a', 'b', 'c'])
    expect(screen.getByText('filter')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建' })).toBeInTheDocument()
  })

  it('renders reset action when reset props are provided', async () => {
    const user = userEvent.setup()
    let resetCount = 0

    render(
      <SearchFilterBar
        value="query"
        onValueChange={() => undefined}
        searchLabel="搜索"
        resetLabel="重置"
        onReset={() => {
          resetCount += 1
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '重置' }))
    expect(resetCount).toBe(1)
  })
})
