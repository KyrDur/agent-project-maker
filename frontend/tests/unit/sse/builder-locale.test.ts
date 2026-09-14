import { afterEach, describe, expect, it, vi } from 'vitest'
import { getActiveClientLocale } from '@/i18n/client-locale'
import { streamBuilderMessage } from '@/lib/sse/stream-builder-message'
import { streamBuilderResume } from '@/lib/sse/stream-builder-resume'
import { streamAssistant, streamAssistantResume } from '@/lib/sse/stream-assistant'

const mocks = vi.hoisted(() => ({ post: vi.fn(async function* () {}) }))
vi.mock('@/lib/sse/parse-sse', () => ({ streamSSEPost: mocks.post }))

async function consume(stream: AsyncIterable<unknown>) {
  for await (const item of stream) void item
}

afterEach(() => {
  document.cookie = 'moldy_locale=; max-age=0; path=/'
  document.documentElement.lang = ''
  vi.clearAllMocks()
})

describe('Builder runtime locale propagation', () => {
  it.each(['zh-CN', 'en', 'ko'])(
    'sends %s on Builder and Assistant message/resume',
    async (locale) => {
      document.cookie = `moldy_locale=${locale}; path=/`
      const decisions = [{ type: 'approve' as const }]
      await consume(streamBuilderMessage('builder', 'Goal'))
      await consume(streamBuilderResume('builder', decisions))
      await consume(streamAssistant('agent', 'Help'))
      await consume(streamAssistantResume('agent', decisions))
      expect(mocks.post).toHaveBeenCalledTimes(4)
      for (const call of mocks.post.mock.calls) {
        expect((call as unknown[])[1]).toMatchObject({ locale })
      }
    },
  )

  it('reads the locale again after switching in an existing session', async () => {
    document.cookie = 'moldy_locale=zh-CN; path=/'
    await consume(streamBuilderMessage('same-session', 'Goal'))
    document.cookie = 'moldy_locale=en; path=/'
    await consume(streamBuilderResume('same-session', [{ type: 'approve' }]))
    expect(mocks.post).toHaveBeenNthCalledWith(
      1,
      '/api/builder/same-session/messages',
      { content: 'Goal', locale: 'zh-CN' },
      undefined,
      'content_delta',
    )
    expect(mocks.post).toHaveBeenNthCalledWith(
      2,
      '/api/builder/same-session/messages/resume',
      expect.objectContaining({ locale: 'en' }),
      undefined,
      'content_delta',
    )
  })

  it('uses the rendered locale without a cookie, and safely defaults invalid values', () => {
    document.documentElement.lang = 'en'
    expect(getActiveClientLocale()).toBe('en')
    document.cookie = 'moldy_locale=invalid; path=/'
    expect(getActiveClientLocale()).toBe('zh-CN')
    document.cookie = 'moldy_locale=%ZZ; path=/'
    expect(getActiveClientLocale()).toBe('zh-CN')
  })
})
