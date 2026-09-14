import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '../../../messages/en.json'
import zh from '../../../messages/zh-CN.json'
import ko from '../../../messages/ko.json'
import { DEFAULT_LOCALE, LOCALE_COOKIE_NAME } from '@/i18n/locales'
import { formatLongDate, formatRelativeKo } from '@/lib/utils/format-relative-time'
import { formatDisplayDateTime } from '@/lib/utils/display-format'

const state = vi.hoisted(() => ({ locale: undefined as string | undefined }))
vi.mock('next/headers', () => ({
  cookies: async () => ({ get: (name: string) => name === 'moldy_locale' ? { value: state.locale } : undefined }),
}))
vi.mock('next-intl/server', () => ({ getRequestConfig: (callback: unknown) => callback }))
import requestConfig from '@/i18n/request'

function leaves(value: unknown, prefix = ''): Record<string, string> {
  if (typeof value === 'string') return { [prefix]: value }
  if (!value || typeof value !== 'object') return {}
  return Object.fromEntries(Object.entries(value).flatMap(([key, child]) =>
    Object.entries(leaves(child, `${prefix}.${key}`)),
  ))
}

describe('product branding and locale defaults', () => {
  beforeEach(() => { state.locale = undefined })

  it('uses complete Chinese messages for new visitors and invalid locale cookies', async () => {
    expect(DEFAULT_LOCALE).toBe('zh-CN')
    expect(LOCALE_COOKIE_NAME).toBe('moldy_locale')
    for (const locale of [undefined, 'invalid', 'zh-CN']) {
      state.locale = locale
      const config = await requestConfig({ requestLocale: Promise.resolve(undefined) })
      expect(config.locale).toBe('zh-CN')
      expect(config.messages).toEqual(zh)
    }
    expect(Object.keys(leaves(zh)).sort()).toEqual(Object.keys(leaves(en)).sort())
    expect(Object.keys(leaves(zh)).sort()).toEqual(Object.keys(leaves(ko)).sort())
  })

  it('preserves explicitly selected English locale support', async () => {
    state.locale = 'en'
    const config = await requestConfig({ requestLocale: Promise.resolve(undefined) })
    expect(config.locale).toBe('en')
    expect(config.messages).toEqual(en)
  })

  it('preserves explicitly selected Korean locale support', async () => {
    state.locale = 'ko'
    const config = await requestConfig({ requestLocale: Promise.resolve(undefined) })
    expect(config.locale).toBe('ko')
    expect(config.messages).toEqual(ko)
  })

  it('has no Korean or legacy branding in default UI copy, retaining copyright', () => {
    expect(zh.metadata.title).toBe('Agent Project Maker')
    expect(zh.auth.hero.copyright).toBe('© 2026 Moldy contributors')
    for (const [key, text] of Object.entries(leaves(zh))) {
      expect(text, key).not.toMatch(/[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]/)
      if (!key.endsWith('.copyright')) expect(text, key).not.toMatch(/moldy/i)
    }
  })

  it('preserves dynamic arguments and rich-text tags in every Chinese message', () => {
    const chinese = leaves(zh)
    const tokens = (text: string) => [...new Set([
      ...Array.from(text.matchAll(/\{(\w+)(?:,|\})/g), (match) => match[1]),
      ...Array.from(text.matchAll(/<\/?(\w+)>/g), (match) => match[1]),
    ])].sort()
    for (const [key, text] of Object.entries(leaves(en))) {
      expect(tokens(chinese[key]), key).toEqual(tokens(text))
    }
  })

  it('formats default date and relative-time UI in Chinese', () => {
    const date = '2026-06-17T00:00:00Z'
    expect(formatLongDate(date)).toBe('2026年6月17日')
    expect(formatRelativeKo(date, new Date('2026-06-17T00:05:00Z'))).toBe('5分钟前')
    expect(formatDisplayDateTime(date)).toContain('2026年')
  })
})
