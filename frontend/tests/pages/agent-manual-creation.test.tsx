import ManualCreationPage from '@/app/agents/new/manual/page'

const redirect = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ redirect }))

describe('retired manual creation route', () => {
  it('directs old bookmarks to conversational creation', () => {
    ManualCreationPage()
    expect(redirect).toHaveBeenCalledExactlyOnceWith('/agents/new/conversational')
  })
})
